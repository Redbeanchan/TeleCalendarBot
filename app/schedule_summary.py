from __future__ import annotations

import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from app.calendar_service import CalendarError
from app.date_resolver import DateResolutionError
from app.scheduling import reminder_occurrences


def summary_range(text: str, now: datetime):
    if re.match(r"^(?:remind|create|add|let'?s|schedule (?:a|an|dinner|lunch|meeting))\b", text, re.I):
        return None
    if not re.search(r"\b(my schedule|schedule for|summary|upcoming|what'?s on|what is on|(?:show|list|what).*?(?:reminders|events|schedule))\b", text, re.I):
        return None
    count = re.search(r"next\s+(\d+|few)\s+days?", text, re.I)
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    if count:
        days = 3 if count.group(1).lower() == "few" else int(count.group(1))
        if not 1 <= days <= 31:
            raise DateResolutionError("Please choose between 1 and 31 days.")
        return now, midnight + timedelta(days=days)
    if re.search(r"\btomorrow\b", text, re.I):
        return midnight + timedelta(days=1), midnight + timedelta(days=2)
    if re.search(r"\b(today|day)\b", text, re.I) or not re.search(r"\b(next|on|week|month)\b", text, re.I):
        return now, midnight + timedelta(days=1)
    return None


async def send_summary(message, services, user_id, chat_id, start, end, reminders_only=False):
    tz = ZoneInfo(services["settings"].timezone)
    entries = []
    for row in services["database"].list_reminders(user_id, chat_id):
        for when in reminder_occurrences(row, start, end):
            repeat = " (recurring)" if row["recurrence_rule"] else ""
            entries.append((when, f"Reminder: {row['title']}{repeat} [ID: {row['id']}]"))
        due = datetime.fromisoformat(row["scheduled_at_utc"]).astimezone(tz)
        if due < start and start.date() == datetime.now(tz).date():
            entries.append((start, f"Overdue reminder: {row['title']} [ID: {row['id']}]"))
    warning = ""
    if not reminders_only:
        try:
            for event in await services["calendar"].list_events(start, end):
                when = event.start.astimezone(tz)
                label = "All-day event" if event.all_day else "Event"
                entries.append((max(when, start), f"{label}: {event.title}"))
        except CalendarError:
            warning = "\nCalendar is unavailable; only reminders are shown."
    heading = f"Upcoming schedule: {start.strftime('%d %b')} to {(end - timedelta(seconds=1)).strftime('%d %b %Y')}"
    lines = [heading + warning]
    for when, label in sorted(entries, key=lambda item: item[0]):
        lines.append(f"{when.strftime('%a %d %b, %I:%M %p')} - {label}")
    if not entries:
        lines.append("No upcoming reminders." if warning or reminders_only else "Nothing scheduled.")
    # Telegram text messages have a fixed size limit; split only between entries.
    chunk = ""
    for line in lines:
        if len(chunk) + len(line) + 1 > 3900:
            await message.reply_text(chunk)
            chunk = ""
        chunk += ("\n" if chunk else "") + line
    if chunk:
        await message.reply_text(chunk)
