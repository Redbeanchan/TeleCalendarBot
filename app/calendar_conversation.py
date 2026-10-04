from __future__ import annotations

import re

from app.models import IntentType, ParsedIntent


MONTH = r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
DAY = re.compile(
    rf"\b(?:today|tomorrow|tonight|this evening|(?:this|next)\s+(?:mon(?:day)?|tue(?:sday)?|wed(?:nesday)?|thu(?:rsday)?|fri(?:day)?|sat(?:urday)?|sun(?:day)?)|\d{{1,2}}(?:st|nd|rd|th)?\s+{MONTH}(?:\s+\d{{4}})?|\d{{4}}-\d{{2}}-\d{{2}})\b",
    re.IGNORECASE,
)
CLOCK = re.compile(r"\b(?:(1[0-2]|0?[1-9])(?::([0-5]\d))?\s*(am|pm)|([01]?\d|2[0-3]):([0-5]\d))\b", re.IGNORECASE)
INVITATION = re.compile(r"^(?:let'?s\s+)?(?:meet|meet up|schedule a meeting|create an event|schedule an event)$", re.IGNORECASE)


def calendar_followup(message: str, draft=None) -> ParsedIntent | None:
    """Handle explicit invitation slots and draft-only answers without a model guess."""
    text = message.strip().replace("\u2019", "'")
    day = DAY.search(text)
    clock = CLOCK.search(text)
    if len(DAY.findall(text)) > 1 or len(CLOCK.findall(text)) > 1:
        return None
    remainder = CLOCK.sub("", DAY.sub("", text))
    remainder = re.sub(r"\b(?:at|on|for|please)\b", "", remainder, flags=re.IGNORECASE)
    remainder = " ".join(remainder.strip(" ,.!?").split())
    generic = bool(INVITATION.fullmatch(remainder))
    slot_answer = draft is not None and not remainder and bool(day or clock)
    title_answer = draft is not None and not draft["title"] and not day and not clock
    if title_answer and re.match(r"^(?:remind\b|what\b|show\b|cancel\b)", text, re.IGNORECASE):
        return None
    if not (generic or slot_answer or title_answer):
        return None
    event_time = None
    if clock:
        if clock.group(3):
            hour = int(clock.group(1)) % 12 + (12 if clock.group(3).lower() == "pm" else 0)
            event_time = f"{hour:02d}:{int(clock.group(2) or 0):02d}"
        else:
            event_time = f"{int(clock.group(4)):02d}:{clock.group(5)}"
    return ParsedIntent(
        intent=IntentType.PROPOSE_CALENDAR_EVENT,
        title=message.strip() if title_answer else None,
        date_expression=day.group() if day else None,
        time=event_time,
        confidence=1,
    )
