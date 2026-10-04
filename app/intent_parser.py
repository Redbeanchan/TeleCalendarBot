from __future__ import annotations

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
                raw = await self.client.generate_json(
                    SYSTEM_PROMPT,
                    prompt + ("\nYour previous response was invalid. Return valid schema JSON." if attempt else ""),
                    ParsedIntent.model_json_schema(),
                )
                return ParsedIntent.model_validate_json(raw)
            except OllamaError as exc:
                raise IntentParseError(str(exc)) from exc
            except ValidationError as exc:
                last_error = exc
        raise IntentParseError("I couldn't safely understand that message. Please rephrase it with a day and time.") from last_error

    async def update(self, draft: ParsedIntent, message: str, now: datetime | None = None) -> ParsedIntent:
        """Apply a natural-language correction while preserving omitted draft fields."""
        local_now = (now or datetime.now(ZoneInfo(self.timezone))).astimezone(ZoneInfo(self.timezone))
        prompt = (
            f"Current local datetime: {local_now.isoformat()} ({local_now:%A}); timezone: {self.timezone}\n"
            f"Existing calendar draft: {draft.model_dump_json()}\n"
            f"User update: {message[:4000]}\n"
            "Return the complete updated calendar intent. Preserve every existing value the user did not change. "
            "Location is optional and must not cause clarification. Preserve relative date wording; Python resolves it."
        )
        try:
            raw = await self.client.generate_json(SYSTEM_PROMPT, prompt, ParsedIntent.model_json_schema())
            updated = ParsedIntent.model_validate_json(raw)
        except OllamaError as exc:
            raise IntentParseError(str(exc)) from exc
        except ValidationError as exc:
            raise IntentParseError("I couldn't understand that change. Try something like “6 October” or “8:30 pm”.") from exc
        values = draft.model_dump()
        for field in ("title", "date_expression", "time", "end_time", "location"):
            value = getattr(updated, field)
            if value is not None:
                values[field] = value
        values.update(intent=draft.intent, confidence=max(draft.confidence, updated.confidence))
        return ParsedIntent.model_validate(values)
