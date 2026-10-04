from app.handlers.messages import _clarification, _required_missing
from app.models import IntentType, ParsedIntent


def test_location_is_never_required_for_calendar_proposal():
    intent = ParsedIntent(
        intent=IntentType.PROPOSE_CALENDAR_EVENT,
        title="Dinner with Louis",
        date_expression="tomorrow",
        time="19:00",
        location=None,
        missing_fields=["location"],
        needs_clarification=True,
    )
    assert _required_missing(intent) == []


def test_internal_schema_names_are_not_shown_to_user():
    intent = ParsedIntent(intent=IntentType.PROPOSE_CALENDAR_EVENT, title="Dinner with Louis")
    missing = _required_missing(intent)
    message = _clarification(intent, missing)
    assert missing == ["date", "time"]
    assert "date_expression" not in message
    assert "location" not in message
    assert message == "I can add “Dinner with Louis”. Just tell me which day and what time."


def test_relative_duration_does_not_require_separate_time():
    intent = ParsedIntent(
        intent=IntentType.CREATE_REMINDER,
        title="Eat",
        date_expression="in 5 minutes",
    )
    assert _required_missing(intent) == []
