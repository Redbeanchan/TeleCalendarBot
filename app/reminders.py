from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from app.calendar_service import CalendarError, CalendarService
from app.database import Database

logger = logging.getLogger(__name__)


class ReminderWorker:
    def __init__(self, database: Database, bot, poll_seconds: int):
        self.database, self.bot, self.poll_seconds = database, bot, poll_seconds
        self._stopping = asyncio.Event()

    async def run(self) -> None:
        self.database.recover_deliveries()
        while not self._stopping.is_set():
            for row in self.database.claim_due_reminders():
                scheduled = datetime.fromisoformat(row["scheduled_at_utc"])
                overdue = datetime.now(UTC) - scheduled
                suffix = "\n_(Due earlier while I was offline.)_" if overdue > timedelta(minutes=2) else ""
                try:
                    await self.bot.send_message(row["telegram_chat_id"], f"⏰ Reminder: {row['title']}{suffix}", parse_mode="Markdown")
                    self.database.finish_reminder(row["id"], True)
                    logger.info("Reminder delivered id=%s", row["id"])
                except Exception:
                    self.database.finish_reminder(row["id"], False)
                    logger.exception("Reminder delivery failed id=%s", row["id"])
            try:
                await asyncio.wait_for(self._stopping.wait(), self.poll_seconds)
            except TimeoutError:
                pass

    def stop(self) -> None:
        self._stopping.set()


class CalendarReminderWorker:
    def __init__(self, database: Database, calendar: CalendarService, bot, chat_id: int, timezone: str,
                 minutes: int, poll_seconds: int):
        self.database, self.calendar, self.bot, self.chat_id = database, calendar, bot, chat_id
        self.tz, self.minutes, self.poll_seconds = ZoneInfo(timezone), minutes, poll_seconds
        self._stopping = asyncio.Event()

    async def run(self) -> None:
        while not self._stopping.is_set():
            now = datetime.now(self.tz)
            try:
                events = await self.calendar.list_events(now, now + timedelta(minutes=self.minutes + 5))
                for event in events:
                    remaining = event.start - now
                    if not event.all_day and timedelta(0) <= remaining <= timedelta(minutes=self.minutes) and self.database.mark_calendar_notice(event.event_id, event.start, self.minutes):
                        location = f"\n{event.location}" if event.location else ""
                        await self.bot.send_message(self.chat_id, f"📅 {event.title} in {max(1, round(remaining.total_seconds()/60))} minutes\n\n{event.start.strftime('%-I:%M %p')}{location}")
            except CalendarError as exc:
                logger.warning("Calendar reminder poll failed: %s", exc)
            except Exception:
                logger.exception("Calendar reminder worker failed")
            try:
                await asyncio.wait_for(self._stopping.wait(), self.poll_seconds)
            except TimeoutError:
                pass

    def stop(self) -> None:
        self._stopping.set()
