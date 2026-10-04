from __future__ import annotations

import re
from datetime import datetime, timedelta

from dateutil.rrule import rrulestr

from app.calendar_conversation import CLOCK
from app.date_resolver import DateResolutionError
from app.models import IntentType, ParsedIntent


def format_title(text: str) -> str:
    text = re.sub(r"\s+", " ", text).strip().strip('"\'')
    small = {"a", "an", "and", "at", "for", "in", "of", "on", "the", "to", "with"}
    return " ".join(word if word.isupper() else word.lower() if i and word.lower() in small
                    else word[0].upper() + word[1:] for i, word in enumerate(text.split()))


def recurring_intent(text: str, now: datetime) -> ParsedIntent | None:
    if not re.match(r"^remind me\b", text, re.I) or not re.search(r"\b(every|daily|weekdays|weekly)\b", text, re.I):
        return None
    match = re.fullmatch(
        r"remind me\s+(every day|daily|every weekday|every weekdays|weekdays|every week|weekly|every monday|every tuesday|every wednesday|every thursday|every friday|every saturday|every sunday)\s+(?:at\s+)?(.+?)\s+to\s+(.+)",
        text.strip(), re.I,
    )
    if not match:
        raise DateResolutionError("Try: remind me every day at 10am to take my weight. I support daily, weekdays, weekly, and a named weekday.")
    frequency, clock_text, title = match.groups()
    clock = CLOCK.fullmatch(clock_text.strip())
    if not clock:
        raise DateResolutionError("Please give the recurring reminder a time, such as 10am or 22:00.")
    if clock.group(3):
        hour = int(clock.group(1)) % 12 + (12 if clock.group(3).lower() == "pm" else 0)
        minute = int(clock.group(2) or 0)
    else:
        hour, minute = int(clock.group(4)), int(clock.group(5))
    frequency = frequency.lower()
    rule = "FREQ=DAILY"
    if "weekday" in frequency:
        rule += ";BYDAY=MO,TU,WE,TH,FR"
    elif frequency in {"weekly", "every week"}:
        rule = "FREQ=WEEKLY"
    elif frequency.startswith("every ") and frequency != "every day":
        rule = "FREQ=WEEKLY;BYDAY=" + frequency.split()[1][:2].upper()
    anchor = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    start = rrulestr(rule, dtstart=anchor).after(now)
    return ParsedIntent(intent=IntentType.CREATE_REMINDER, title=format_title(title),
                        date_expression=start.date().isoformat(), time=start.strftime("%H:%M"),
                        recurrence_rule=rule, confidence=1)


def reminder_occurrences(row, start: datetime, end: datetime):
    anchor = datetime.fromisoformat(row["scheduled_at_utc"]).astimezone(start.tzinfo)
    if not row["recurrence_rule"]:
        return [anchor] if start <= anchor < end else []
    rule = rrulestr(row["recurrence_rule"], dtstart=anchor)
    return rule.between(start, end - timedelta(microseconds=1), inc=True)


def recurrence_description(rule: str) -> str:
    if rule == "FREQ=DAILY":
        return "Every day"
    if rule == "FREQ=DAILY;BYDAY=MO,TU,WE,TH,FR":
        return "Every weekday"
    names = dict(zip(["MO", "TU", "WE", "TH", "FR", "SA", "SU"],
                     ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]))
    if ";BYDAY=" in rule:
        return "Every " + ", ".join(names[day] for day in rule.split(";BYDAY=", 1)[1].split(","))
    return "Every week"
