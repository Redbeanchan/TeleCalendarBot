from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field, field_validator


class IntentType(StrEnum):
    CREATE_REMINDER = "create_reminder"
    PROPOSE_CALENDAR_EVENT = "propose_calendar_event"
    QUERY_CALENDAR = "query_calendar"
    UNKNOWN = "unknown"


class ParsedIntent(BaseModel):
    intent: IntentType
    title: str | None = None
    date_expression: str | None = None
    time: str | None = None
    end_time: str | None = None
    location: str | None = None
    confidence: float = Field(default=0, ge=0, le=1)
    missing_fields: list[str] = Field(default_factory=list)
    needs_clarification: bool = False

    @field_validator("title", "date_expression", "time", "end_time", "location")
    @classmethod
    def trim_strings(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value[:500] or None


class ResolvedRange(BaseModel):
    start: datetime
    end: datetime | None = None


class CalendarEvent(BaseModel):
    event_id: str
    title: str
    start: datetime
    end: datetime
    location: str | None = None
    all_day: bool = False
