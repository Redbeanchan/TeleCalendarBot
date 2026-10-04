from __future__ import annotations

from datetime import datetime


def time_12h(value: datetime, *, include_period: bool = True) -> str:
    """Return a portable 12-hour time without platform-specific strftime flags."""
    hour = value.strftime("%I").lstrip("0") or "0"
    suffix = f" {value:%p}" if include_period else ""
    return f"{hour}:{value:%M}{suffix}"


def short_datetime(value: datetime) -> str:
    return f"{value:%a}, {value.day} {value:%b} · {time_12h(value)}"


def long_date(value: datetime) -> str:
    return f"{value:%A}, {value.day} {value:%B %Y}"


def day_heading(value: datetime) -> str:
    return f"{value:%A}, {value.day} {value:%B}"


def event_range(start: datetime, end: datetime) -> str:
    return f"{time_12h(start)} – {time_12h(end)}"


def proposal_date(value: datetime) -> str:
    return f"{value.day} {value:%B}"


def compact_event_range(start: datetime, end: datetime) -> str:
    return f"{start:%a}, {start.day} {start:%b} · {time_12h(start, include_period=False)}–{time_12h(end)}"
