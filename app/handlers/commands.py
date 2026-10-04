from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from telegram import BotCommand, BotCommandScopeChat, MenuButtonCommands
from telegram.ext import CommandHandler

from app.handlers.auth import authorized
from app.handlers.messages import message_handler
from app.schedule_summary import send_summary


COMMANDS = [
    ("start", "Start the assistant"), ("help", "Commands and examples"),
    ("today", "Today's events and reminders"), ("tomorrow", "Tomorrow's events and reminders"),
    ("schedule", "Upcoming events and reminders: /schedule 3"),
    ("reminders", "List active reminders and cancellation IDs"),
    ("remind", "Set a reminder: /remind tomorrow 8pm to pay bills"),
    ("daily", "Daily reminder: /daily 10am take my weight"),
    ("event", "Propose an event: /event dinner tomorrow 7pm"),
    ("cancel", "Cancel a reminder: /cancel ID"),
    ("debug", "Live terminal debug output: /debug on or off"),
    ("health", "Check the assistant is running"),
]


async def register_menu(bot, chat_id):
    await bot.set_my_commands([BotCommand(name, description) for name, description in COMMANDS],
                              scope=BotCommandScopeChat(chat_id))
    await bot.set_chat_menu_button(chat_id=chat_id, menu_button=MenuButtonCommands())


def command_handlers(user_id):
    @authorized(user_id)
    async def commands(update, context):
        msg = update.effective_message
        name = msg.text.split()[0].split("@")[0].lstrip("/")
        services = context.application.bot_data
        args = context.args
        if name == "help":
            await msg.reply_text("\n".join(f"/{command} - {description}" for command, description in COMMANDS)
                                 + '\n\nYou can also write naturally: "what is my schedule for the next 2 days including reminders?"'
                                 + '\n"remind me every weekday at 10am to take my weight"'
                                 + '\nTo change a Calendar proposal, press Edit details. Google writes require Yes.')
        elif name == "debug":
            if args not in (["on"], ["off"]):
                await msg.reply_text("Use /debug on or /debug off. Output appears in the bot's terminal.")
                return
            enabled = args == ["on"]
            services["debug_enabled"] = enabled
            services["intent_parser"].client.debug_enabled = enabled
            await msg.reply_text(f"Terminal debug output {'enabled' if enabled else 'disabled'}. Model thinking is shown when available.")
        elif name == "cancel":
            if not args:
                await msg.reply_text("Use /cancel ID. Find the reminder ID with /reminders.")
                return
            cancelled = services["database"].cancel_reminder(args[0], update.effective_user.id, update.effective_chat.id)
            await msg.reply_text("Reminder cancelled." if cancelled else "No active reminder found with that ID.")
        else:
            now = datetime.now(ZoneInfo(services["settings"].timezone))
            if name == "reminders":
                rows = services["database"].list_reminders(update.effective_user.id, update.effective_chat.id)
                if not rows:
                    await msg.reply_text("No active reminders.")
                for row in rows:
                    when = datetime.fromisoformat(row["scheduled_at_utc"]).astimezone(now.tzinfo)
                    repeat = " (recurring)" if row["recurrence_rule"] else ""
                    await msg.reply_text(f"{row['title']}{repeat}\nNext: {when.strftime('%d %b %Y, %I:%M %p')}\nID: {row['id']}")
                return
            if args and (len(args) != 1 or not args[0].isdigit() or not 1 <= int(args[0]) <= 31):
                await msg.reply_text("Use /schedule followed by a number from 1 to 31, for example /schedule 3.")
                return
            days = int(args[0]) if args else (3 if name == "schedule" else 1)
            start = now
            midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
            if name == "tomorrow":
                start = midnight + timedelta(days=1)
                midnight = start
            await send_summary(msg, services, update.effective_user.id, update.effective_chat.id,
                               start, midnight + timedelta(days=days))

    return [CommandHandler(["help", "today", "tomorrow", "schedule", "reminders", "cancel", "debug"], commands),
            CommandHandler("remind", message_handler(user_id, lambda context: "remind me " + " ".join(context.args))),
            CommandHandler("daily", message_handler(user_id, lambda context: "remind me every day at " + " ".join(context.args[:1]) + " to " + " ".join(context.args[1:]))),
            CommandHandler("event", message_handler(user_id, lambda context: "create an event " + " ".join(context.args)))]
