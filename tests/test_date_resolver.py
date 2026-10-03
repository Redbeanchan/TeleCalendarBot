from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from app.date_resolver import DateResolutionError, DateResolver, default_duration
from app.models import IntentType, ParsedIntent

TZ = ZoneInfo("Asia/Singapore")
NOW = datetime(2026, 10, 3, 21, 0, tzinfo=TZ)  # Saturday


def intent(expression, time="20:00", kind=IntentType.CREATE_REMINDER):
    return ParsedIntent(intent=kind, title="Test", date_expression=expression, time=time, confidence=1)


def test_tomorrow():
    assert DateResolver("Asia/Singapore").resolve(intent("tomorrow"), NOW).start == datetime(2026, 10, 4, 20, tzinfo=TZ)


def test_next_weekday_means_following_calendar_week():
    assert DateResolver("Asia/Singapore").resolve(intent("next Wednesday"), NOW).start.date().isoformat() == "2026-10-07"


def test_relative_hours_uses_supplied_clock():
    result = DateResolver("Asia/Singapore").resolve(intent("in 2 hours", time=None), NOW)
    assert result.start == datetime(2026, 10, 3, 23, 0, tzinfo=TZ)


def test_past_today_rejected():
    with pytest.raises(DateResolutionError, match="past"):
        DateResolver("Asia/Singapore").resolve(intent("today"), NOW)


def test_ambiguous_next_week_rejected():
    with pytest.raises(DateResolutionError):
        DateResolver("Asia/Singapore").resolve(intent("next week"), NOW)


def test_default_durations():
    assert default_duration("Dinner with Ryan").total_seconds() == 7200
    assert default_duration("Dentist appointment").total_seconds() == 3600
