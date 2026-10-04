from app.handlers.messages import _calendar_draft_prompt, _merge_calendar_draft
from app.models import IntentType, ParsedIntent


class Draft:
    data = {
        "title": None,
        "date_expression": "tomorrow",
        "event_time": "19:00",
        "end_time": None,
        "location": None,
    }

    def __getitem__(self, key):
        return self.data[key]


class ExistingProposalDraft:
    data = {
        "title": "Dinner with Louis",
        "date_expression": "tomorrow",
        "event_time": "19:00",
        "end_time": "21:00",
        "location": None,
    }

    def __getitem__(self, key):
        return self.data[key]


def test_title_update_preserves_existing_calendar_day_and_time():
    incoming = ParsedIntent(
        intent=IntentType.PROPOSE_CALENDAR_EVENT,
        title="Dinner with Louis",
        confidence=0.9,
        needs_clarification=True,
        missing_fields=["date_expression", "time"],
    )

    merged = _merge_calendar_draft(incoming, Draft(), "Dinner with Louis")

    assert merged.title == "Dinner with Louis"
    assert merged.date_expression == "tomorrow"
    assert merged.time == "19:00"
    assert not merged.needs_clarification


def test_date_update_preserves_existing_calendar_title_and_time():
    incoming = ParsedIntent(
        intent=IntentType.PROPOSE_CALENDAR_EVENT,
        date_expression="6th Oct",
        confidence=0.9,
        needs_clarification=True,
        missing_fields=["title", "time"],
    )

    merged = _merge_calendar_draft(incoming, ExistingProposalDraft(), "6th Oct")

    assert merged.title == "Dinner with Louis"
    assert merged.date_expression == "6th Oct"
    assert merged.time == "19:00"
    assert merged.end_time == "21:00"
    assert not merged.needs_clarification


def test_draft_prompt_does_not_show_internal_field_names():
    intent = ParsedIntent(
        intent=IntentType.PROPOSE_CALENDAR_EVENT,
        title="Dinner with Louis",
        date_expression="6th Oct",
        confidence=0.9,
        needs_clarification=True,
        missing_fields=["time"],
    )

    prompt = _calendar_draft_prompt(intent)

    assert "missing_fields" not in prompt
    assert "date_expression" not in prompt
    assert prompt == "What time should I schedule Dinner with Louis?"
