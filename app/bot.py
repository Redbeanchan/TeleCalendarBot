from __future__ import annotations

import asyncio
import logging
import signal

from telegram import Update
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, MessageHandler, filters

from app.calendar_service import CalendarService
from app.config import get_settings
from app.database import Database
from app.date_resolver import DateResolver
from app.handlers.auth import authorized
from app.handlers.callbacks import callback_handler
from app.handlers.messages import message_handler
from app.intent_parser import IntentParser
from app.ollama_client import OllamaClient
from app.reminders import CalendarReminderWorker, ReminderWorker

logger = logging.getLogger(__name__)


async def main() -> None:
    settings = get_settings()
    logging.basicConfig(level=settings.log_level, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    database = Database(settings.database_path)
    database.initialize()
    calendar = CalendarService(settings.google_token_path, settings.google_calendar_id, settings.timezone)
    application = Application.builder().token(settings.telegram_bot_token.get_secret_value()).build()
    application.bot_data.update({
        "settings": settings, "database": database, "calendar": calendar,
        "date_resolver": DateResolver(settings.timezone),
        "intent_parser": IntentParser(OllamaClient(settings.ollama_base_url, settings.ollama_model, settings.ollama_timeout_seconds), settings.timezone),
    })

    @authorized(settings.telegram_allowed_user_id)
    async def start(update, context):
        await update.effective_message.reply_text("Ready. Ask me to set a reminder, check your schedule, or propose an event.")

    @authorized(settings.telegram_allowed_user_id)
    async def health(update, context):
        await update.effective_message.reply_text("✅ Assistant is running.")

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("health", health))
    application.add_handler(CallbackQueryHandler(callback_handler(settings.telegram_allowed_user_id), pattern=r"^calendar:"))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler(settings.telegram_allowed_user_id)))

    await application.initialize()
    await application.start()
    if application.updater is None:
        raise RuntimeError("Telegram updater was not initialized")
    await application.updater.start_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=False)
    reminder_worker = ReminderWorker(database, application.bot, settings.reminder_poll_seconds)
    tasks = [asyncio.create_task(reminder_worker.run(), name="reminder-worker")]
    calendar_worker = None
    if settings.calendar_reminders_enabled:
        calendar_worker = CalendarReminderWorker(
            database, calendar, application.bot, settings.telegram_allowed_user_id, settings.timezone,
            settings.calendar_reminder_minutes, settings.calendar_poll_seconds,
        )
        tasks.append(asyncio.create_task(calendar_worker.run(), name="calendar-reminder-worker"))
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)
    logger.info("Assistant started with long polling")
    await stop.wait()
    logger.info("Assistant shutting down")
    reminder_worker.stop()
    if calendar_worker:
        calendar_worker.stop()
    await asyncio.gather(*tasks, return_exceptions=True)
    await application.updater.stop()
    await application.stop()
    await application.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
