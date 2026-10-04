from __future__ import annotations

import re
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import dateparser

from app.models import ParsedIntent, ResolvedRange


class DateResolutionError(ValueError):
    pass


WEEKDAYS = {name: i for i, name in enumerate(("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"))}


class DateResolver:
    """Resolve language deterministically in the configured timezone.

    `next Wednesday` always means the Wednesday in the following Mon-Sun week;
    `this Wednesday` means the next occurrence in the current week and is rejected if past.
    """

    def __init__(self, timezone: str):
        self.timezone, self.tz = timezone, ZoneInfo(timezone)

    def resolve(self, intent: ParsedIntent, now: datetime | None = None) -> ResolvedRange:
        now = (now or datetime.now(self.tz)).astimezone(self.tz)
        expression = (intent.date_expression or "").strip().lower()
        if not expression:
            raise DateResolutionError("Please provide a day or date.")
        relative = re.fullmatch(r"in\s+(\d+)\s+(minute|hour)s?", expression)
        if relative:
            amount = int(relative.group(1))
            result = now + timedelta(**{f"{relative.group(2)}s": amount})
            return ResolvedRange(start=result.replace(second=0, microsecond=0))
        parsed_time = self._time(intent.time, expression)
        if parsed_time is None and intent.intent != "query_calendar":
            raise DateResolutionError("Please provide a time.")
        base_date = self._date(expression, now)
        start = datetime.combine(base_date, parsed_time or time.min, self.tz)
        if start <= now and intent.intent != "query_calendar":
            raise DateResolutionError("That time is in the past. What future time should I use?")
        end = None
        if intent.intent == "query_calendar":
            end = start + timedelta(days=1)
        elif intent.end_time:
            end = datetime.combine(base_date, self._time(intent.end_time, "") or time.min, self.tz)
            if end <= start:
                end += timedelta(days=1)
        return ResolvedRange(start=start, end=end)

    def _date(self, expression: str, now: datetime):
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", expression):
            try:
                return date.fromisoformat(expression)
            except ValueError as exc:
                raise DateResolutionError("That date is invalid. Please give an exact day.") from exc
        if expression in {"tonight", "this evening"}:
            return now.date()
        match = re.search(r"\b(this|next)\s+(mon(?:day)?|tue(?:sday)?|wed(?:nesday)?|thu(?:rsday)?|fri(?:day)?|sat(?:urday)?|sun(?:day)?)\b", expression)
        if match:
            full = next(name for name in WEEKDAYS if name.startswith(match.group(2)[:3]))
            target = WEEKDAYS[full]
            if match.group(1) == "next":
                return (now + timedelta(days=(7 - now.weekday()) + target)).date()
            return (now + timedelta(days=target - now.weekday())).date()
        if expression == "next week":
            raise DateResolutionError("Please specify a day and time next week.")
        parsed = dateparser.parse(expression, settings={
            "RELATIVE_BASE": now.replace(tzinfo=None), "PREFER_DATES_FROM": "future",
            "DATE_ORDER": "DMY", "STRICT_PARSING": False,
        })
        if not parsed:
            raise DateResolutionError("I couldn't resolve that date. Please give an exact day.")
        return parsed.date()

    def resolve_date(self, expression: str, now: datetime | None = None):
        local_now = (now or datetime.now(self.tz)).astimezone(self.tz)
        return self._date(expression.strip().lower(), local_now)

    @staticmethod
    def _time(value: str | None, expression: str) -> time | None:
        if value:
            match = re.fullmatch(r"(\d{1,2}):(\d{2})", value)
            if not match or int(match.group(1)) > 23 or int(match.group(2)) > 59:
                raise DateResolutionError("I couldn't resolve that time.")
            return time(int(match.group(1)), int(match.group(2)))
        if expression in {"tonight", "this evening"}:
            return time(19)
        return None


def default_duration(title: str) -> timedelta:
    social = ("dinner", "lunch", "brunch", "coffee", "drinks", "party")
    return timedelta(hours=2 if any(word in title.lower() for word in social) else 1)
