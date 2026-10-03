from __future__ import annotations

import json
from datetime import datetime
from zoneinfo import ZoneInfo

from pydantic import ValidationError

from app.models import ParsedIntent
from app.ollama_client import OllamaClient, OllamaError


SYSTEM_PROMPT = """You extract intent; you never perform actions. Return one JSON object only.
Allowed intent values: create_reminder, propose_calendar_event, query_calendar, unknown.
Fields: intent,title,date_expression,time,end_time,location,confidence,missing_fields,needs_clarification.
Preserve relative date language in date_expression; do not calculate dates. time/end_time use 24-hour HH:MM.
Reminder requests are create_reminder. Real-world plans are propose_calendar_event. Schedule questions are query_calendar.
If a required day or time is absent for a write, set needs_clarification true and list it. Never invent details."""


class IntentParseError(RuntimeError):
    pass


class IntentParser:
    def __init__(self, client: OllamaClient, timezone: str):
        self.client, self.timezone = client, timezone

    async def parse(self, message: str, now: datetime | None = None) -> ParsedIntent:
        local_now = (now or datetime.now(ZoneInfo(self.timezone))).astimezone(ZoneInfo(self.timezone))
        prompt = f"Current local datetime: {local_now.isoformat()} ({local_now.strftime('%A')}); timezone: {self.timezone}\nMessage: {message[:4000]}"
        last_error: Exception | None = None
        for attempt in range(2):
            try:
                raw = await self.client.generate_json(SYSTEM_PROMPT, prompt + ("\nYour previous response was invalid. Return valid schema JSON." if attempt else ""))
                return ParsedIntent.model_validate(json.loads(raw))
            except (json.JSONDecodeError, ValidationError, OllamaError) as exc:
                last_error = exc
        raise IntentParseError("I couldn't safely understand that message. Please rephrase it with a day and time.") from last_error
