from app.handlers.messages import _calendar_draft_prompt, _merge_calendar_draft
from app.models import IntentType, ParsedIntent

import pytest
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

from app.calendar_conversation import calendar_followup
from app.database import Database
from app.date_resolver import DateResolver
from app.handlers.callbacks import callback_handler
from app.handlers.messages import message_handler


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


@pytest.mark.parametrize("text", ["Let's meet tomorrow 7pm", "lets meet tomorrow 7pm", "Let\u2019s meet tomorrow at 7pm"])
def test_generic_invitation_does_not_invent_title(text):
    intent = calendar_followup(text)
    assert intent.title is None
    assert intent.date_expression == "tomorrow"
    assert intent.time == "19:00"


@pytest.mark.parametrize("text", ["remind me tomorrow at 7pm to call", "what's on tomorrow?", "Dinner tomorrow 7pm"])
def test_other_requests_use_normal_parser(text):
    assert calendar_followup(text) is None


NOW = datetime(2026, 10, 4, 16, 8, tzinfo=ZoneInfo("Asia/Singapore"))


class FixedResolver(DateResolver):
    def resolve(self, intent, now=None):
        return super().resolve(intent, now or NOW)

    def resolve_date(self, expression, now=None):
        return super().resolve_date(expression, now or NOW)


def finish_mocked_coroutine(coroutine):
    # All async boundaries in these handlers are immediate mocks; no network or loop is needed.
    try:
        with pytest.raises(StopIteration):
            coroutine.send(None)
    finally:
        coroutine.close()


def test_conversation_through_real_handlers_requires_yes(tmp_path):
    db = Database(tmp_path / "drafts.db")
    db.initialize()
    parser = SimpleNamespace(parse=AsyncMock(side_effect=AssertionError("This flow must not guess with the LLM")))
    calendar = SimpleNamespace(create_event=AsyncMock(return_value="google-event-id"))
    services = {
        "database": db,
        "intent_parser": parser,
        "calendar": calendar,
        "date_resolver": FixedResolver("Asia/Singapore"),
        "settings": SimpleNamespace(timezone="Asia/Singapore", pending_action_ttl_minutes=30),
    }
    context = SimpleNamespace(application=SimpleNamespace(bot_data=services))
    user = SimpleNamespace(id=42)
    chat = SimpleNamespace(id=42)

    def message(text, update_id):
        msg = SimpleNamespace(text=text, reply_text=AsyncMock())
        update = SimpleNamespace(effective_message=msg, effective_user=user, effective_chat=chat,
                                 callback_query=None, update_id=update_id)
        finish_mocked_coroutine(message_handler(42)(update, context))
        return msg.reply_text.call_args

    def click(data, update_id):
        query = SimpleNamespace(data=data, answer=AsyncMock(), edit_message_text=AsyncMock())
        update = SimpleNamespace(callback_query=query, effective_user=user, effective_chat=chat, update_id=update_id)
        finish_mocked_coroutine(callback_handler(42)(update, context))
        return query

    reply = message("Let's meet tomorrow 7pm", 1)
    assert reply.args[0] == "What should I name this event?"
    draft = db.get_calendar_draft(42, 42)
    assert draft["title"] is None
    assert draft["date_expression"] == "2026-10-05"
    assert draft["event_time"] == "19:00"

    # The draft survives a database connection / process restart.
    services["database"] = Database(db.path)
    reply = message("dinner with boss", 2)
    assert reply.args[0] == 'Shall I create an event for 5 October 2026 called "dinner with boss", at 7:00 PM?'
    buttons = reply.kwargs["reply_markup"].inline_keyboard[0]
    assert [button.text for button in buttons] == ["Yes", "No", "Edit details"]
    old_yes = buttons[0].callback_data
    click(buttons[2].callback_data, 3)
    calendar.create_event.assert_not_awaited()

    reply = message("6th Oct", 4)
    assert reply.args[0] == 'Shall I create an event for 6 October 2026 called "dinner with boss", at 7:00 PM?'
    buttons = reply.kwargs["reply_markup"].inline_keyboard[0]
    action = db.get_action(buttons[0].callback_data.split(":", 2)[2])
    assert action["end_datetime"] == "2026-10-06T21:00:00+08:00"
    calendar.create_event.assert_not_awaited()
    click(old_yes, 5)
    calendar.create_event.assert_not_awaited()
    click(buttons[0].callback_data, 6)
    calendar.create_event.assert_awaited_once()
    click(buttons[0].callback_data, 7)
    calendar.create_event.assert_awaited_once()

    reply = message("Let's meet tomorrow 7pm", 8)
    assert reply.args[0] == "What should I name this event?"
    reply = message("Cancellation test", 9)
    buttons = reply.kwargs["reply_markup"].inline_keyboard[0]
    click(buttons[1].callback_data, 10)
    click(buttons[0].callback_data, 11)
    calendar.create_event.assert_awaited_once()
