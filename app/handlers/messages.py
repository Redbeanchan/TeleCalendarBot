from __future__ import annotations

import logging
from datetime import timedelta
from zoneinfo import ZoneInfo

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from app.calendar_service import CalendarError
from app.date_resolver import DateResolutionError, default_duration
from app.intent_parser import IntentParseError
from app.models import IntentType

logger = logging.getLogger(__name__)


def message_handler(allowed_user_id: int):
    from app.handlers.auth import authorized

    @authorized(allowed_user_id)
    async def handle(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        message = update.effective_message
        if not message or not message.text:
            return
        services = context.application.bot_data
        try:
            intent = await services["intent_parser"].parse(message.text)
            logger.info("Intent classified type=%s confidence=%.2f", intent.intent, intent.confidence)
            if intent.needs_clarification or intent.confidence < 0.55:
                await message.reply_text(_clarification(intent))
                return
            resolved = services["date_resolver"].resolve(intent)
            if intent.intent == IntentType.CREATE_REMINDER:
                if not intent.title:
                    await message.reply_text("What should I remind you about?")
                    return
                services["database"].create_reminder(update.effective_user.id, update.effective_chat.id, intent.title, resolved.start, services["settings"].timezone)
                await message.reply_text(f"🔔 Reminder set\n\n{intent.title}\n{resolved.start.strftime('%a, %#d %b · %#I:%M %p')}")
            elif intent.intent == IntentType.PROPOSE_CALENDAR_EVENT:
                if not intent.title:
                    await message.reply_text("What should I call this event?")
                    return
                end = resolved.end or resolved.start + default_duration(intent.title)
                action_id = services["database"].create_pending_action(
                    update.effective_user.id, intent.title, resolved.start, end, services["settings"].timezone,
                    intent.location, services["settings"].pending_action_ttl_minutes,
                )
                keyboard = InlineKeyboardMarkup([[
                    InlineKeyboardButton("✅ Create", callback_data=f"calendar:create:{action_id}"),
                    InlineKeyboardButton("❌ Cancel", callback_data=f"calendar:cancel:{action_id}"),
                ]])
                await message.reply_text(_proposal(intent.title, resolved.start, end, intent.location), reply_markup=keyboard)
            elif intent.intent == IntentType.QUERY_CALENDAR:
                events = await services["calendar"].list_events(resolved.start, resolved.end or resolved.start + timedelta(days=1))
                await message.reply_text(_event_list(resolved.start, events, ZoneInfo(services["settings"].timezone)))
            else:
                await message.reply_text("I can set reminders, propose calendar events, or check your schedule. What would you like?")
        except (IntentParseError, DateResolutionError, CalendarError) as exc:
            logger.info("Request could not be completed: %s", exc)
            await message.reply_text(str(exc))
        except Exception:
            logger.exception("Unexpected message handling failure")
            await message.reply_text("Something went wrong. Nothing was changed; please try again.")
    return handle


def _clarification(intent) -> str:
    missing = " and ".join(intent.missing_fields)
    subject = intent.title or "that"
    return f"🗓️ {subject} needs more detail.\n\nWhat {missing or 'day and time'} should I use?"


def _proposal(title, start, end, location) -> str:
    where = f"\n📍 {location}" if location else ""
    return f"📅 Create Google Calendar event?\n\n{title}\n{start.strftime('%A, %#d %B %Y')}\n{start.strftime('%#I:%M %p')} – {end.strftime('%#I:%M %p')}{where}"


def _event_list(day, events, timezone) -> str:
    heading = day.astimezone(timezone).strftime("%A, %#d %B")
    if not events:
        return f"📅 {heading}\n\nNothing scheduled."
    lines = []
    for event in events:
        when = "All day" if event.all_day else event.start.astimezone(timezone).strftime("%#I:%M %p")
        lines.append(f"• {when} — {event.title}")
    return f"📅 {heading}\n\n" + "\n".join(lines)
