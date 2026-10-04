import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

import httpx
import pytest

from app.calendar_conversation import calendar_followup
from app.calendar_service import CalendarError
from app.database import Database
from app.date_resolver import DateResolutionError
from app.handlers.commands import COMMANDS, command_handlers, register_menu
from app.handlers.messages import message_handler
from app.models import CalendarEvent, IntentType, ParsedIntent
from app.ollama_client import OllamaClient, OllamaError
from app.schedule_summary import send_summary, summary_range
from app.scheduling import format_title, recurring_intent, reminder_occurrences

TZ = ZoneInfo("Asia/Singapore")
NOW = datetime(2026, 10, 4, 17, 32, tzinfo=TZ)


def finish(coroutine):
    # Network boundaries are immediate mocks, so these coroutine tests need no live event loop.
    try:
        with pytest.raises(StopIteration):
            coroutine.send(None)
    finally:
        coroutine.close()


@pytest.mark.parametrize("text,expected", [
    ("dinner with kor", "Dinner with Kor"),
    ("  dinner   with   NASA ", "Dinner with NASA"),
    ("'dinner with kor'", "Dinner with Kor"),
])
def test_title_formatting(text, expected):
    assert format_title(text) == expected


def test_rename_extracts_title_only():
    intent = calendar_followup("rename the event 'dinner with kor'", {"title": "Old title"})
    assert format_title(intent.title) == "Dinner with Kor"
    assert intent.time is None and intent.date_expression is None


def test_screenshot_schedule_request_has_two_day_range():
    start, end = summary_range("whats my schedule for the next 2 days, including my upcoming reminders", NOW)
    assert start == NOW
    assert end == datetime(2026, 10, 6, tzinfo=TZ)


@pytest.mark.parametrize("text", ["schedule a meeting tomorrow 7pm", "remind me every day at 10am to check my schedule", "create an event tomorrow"])
def test_summary_does_not_intercept_writes(text):
    assert summary_range(text, NOW) is None


def test_summary_range_limits_and_tomorrow():
    with pytest.raises(DateResolutionError):
        summary_range("my schedule for the next 99 days", NOW)
    assert summary_range("show my events tomorrow", NOW) == (datetime(2026, 10, 5, tzinfo=TZ), datetime(2026, 10, 6, tzinfo=TZ))
    assert summary_range("summary for the next few days", NOW)[1] == datetime(2026, 10, 7, tzinfo=TZ)


@pytest.mark.parametrize("phrase,day,rule", [
    ("every day", 5, "FREQ=DAILY"),
    ("every weekday", 5, "FREQ=DAILY;BYDAY=MO,TU,WE,TH,FR"),
    ("every monday", 5, "FREQ=WEEKLY;BYDAY=MO"),
    ("every week", 11, "FREQ=WEEKLY"),
])
def test_recurring_reminder_first_occurrence(phrase, day, rule):
    intent = recurring_intent(f"remind me {phrase} at 10am to take my weight", NOW)
    assert intent.title == "Take My Weight"
    assert intent.date_expression == f"2026-10-{day:02d}"
    assert intent.time == "10:00"
    assert intent.recurrence_rule == rule


def test_unsupported_recurrence_does_not_become_one_off():
    with pytest.raises(DateResolutionError):
        recurring_intent("remind me every month at 10am to pay bills", NOW)


def test_recurring_delivery_advances_and_cancel_is_scoped(tmp_path, monkeypatch):
    db = Database(tmp_path / "db.sqlite")
    db.initialize()
    monkeypatch.setattr("app.database.utcnow", lambda: NOW.astimezone(timezone.utc))
    reminder_id = db.create_reminder(42, 42, "Weight", NOW.replace(hour=10, minute=0), "Asia/Singapore", "FREQ=DAILY")
    assert len(db.claim_due_reminders()) == 1
    db.finish_reminder(reminder_id, False)
    assert len(db.claim_due_reminders()) == 1
    db.finish_reminder(reminder_id, True)
    row = Database(db.path).list_reminders(42, 42)[0]
    assert datetime.fromisoformat(row["scheduled_at_utc"]).astimezone(TZ) == datetime(2026, 10, 5, 10, tzinfo=TZ)
    assert not db.claim_due_reminders()
    assert not db.cancel_reminder(reminder_id, 99, 42)
    assert db.cancel_reminder(reminder_id, 42, 42)
    assert not db.list_reminders(42, 42)


def test_recurrence_expansion_and_weekend_skip():
    row = {"scheduled_at_utc": datetime(2026, 10, 5, 10, tzinfo=TZ).isoformat(),
           "recurrence_rule": "FREQ=DAILY;BYDAY=MO,TU,WE,TH,FR"}
    dates = reminder_occurrences(row, NOW, datetime(2026, 10, 12, tzinfo=TZ))
    assert [when.day for when in dates] == [5, 6, 7, 8, 9]


def test_combined_summary_and_calendar_failure(tmp_path):
    db = Database(tmp_path / "db.sqlite")
    db.initialize()
    tomorrow = datetime(2026, 10, 5, 10, tzinfo=TZ)
    db.create_reminder(42, 42, "Take My Weight", tomorrow, "Asia/Singapore", "FREQ=DAILY")
    db.create_reminder(99, 99, "Private reminder", tomorrow, "Asia/Singapore")
    event = CalendarEvent(event_id="event", title="Dinner with Kor", start=tomorrow + timedelta(hours=9), end=tomorrow + timedelta(hours=11))
    calendar = SimpleNamespace(list_events=AsyncMock(return_value=[event]))
    services = {"database": db, "calendar": calendar, "settings": SimpleNamespace(timezone="Asia/Singapore")}
    message = SimpleNamespace(reply_text=AsyncMock())
    end = datetime(2026, 10, 7, tzinfo=TZ)
    finish(send_summary(message, services, 42, 42, NOW, end))
    output = message.reply_text.call_args.args[0]
    assert output.count("Take My Weight") == 2
    assert "Dinner with Kor" in output and "Private reminder" not in output
    calendar.list_events.side_effect = CalendarError("Unavailable")
    finish(send_summary(message, services, 42, 42, NOW, end))
    assert "only reminders" in message.reply_text.call_args.args[0]


def test_menu_and_debug_command():
    bot = SimpleNamespace(set_my_commands=AsyncMock(), set_chat_menu_button=AsyncMock())
    finish(register_menu(bot, 42))
    assert len(bot.set_my_commands.call_args.args[0]) == len(COMMANDS)
    bot.set_chat_menu_button.assert_awaited_once()
    client = SimpleNamespace(debug_enabled=False)
    services = {"intent_parser": SimpleNamespace(client=client)}
    context = SimpleNamespace(application=SimpleNamespace(bot_data=services), args=["on"])
    message = SimpleNamespace(text="/debug on", reply_text=AsyncMock())
    update = SimpleNamespace(effective_user=SimpleNamespace(id=42), effective_message=message, callback_query=None, update_id=None)
    finish(command_handlers(42)[0].callback(update, context))
    assert client.debug_enabled and services["debug_enabled"]
    update.effective_user.id = 99
    context.args = ["off"]
    finish(command_handlers(42)[0].callback(update, context))
    assert client.debug_enabled


def test_schedule_does_not_overwrite_calendar_draft(tmp_path, monkeypatch):
    db = Database(tmp_path / "db.sqlite")
    db.initialize()
    db.upsert_calendar_draft(42, 42, None, "2026-10-05", "19:00", None, None, "Asia/Singapore", 30)
    parser = SimpleNamespace(parse=AsyncMock(side_effect=AssertionError("No model needed")))
    context = SimpleNamespace(application=SimpleNamespace(bot_data={
        "database": db, "intent_parser": parser, "calendar": SimpleNamespace(list_events=AsyncMock(return_value=[])),
        "settings": SimpleNamespace(timezone="Asia/Singapore"),
    }))
    message = SimpleNamespace(text="whats my schedule for the next 2 days including upcoming reminders", reply_text=AsyncMock())
    update = SimpleNamespace(effective_user=SimpleNamespace(id=42), effective_chat=SimpleNamespace(id=42),
                             effective_message=message, callback_query=None, update_id=1)
    finish(message_handler(42)(update, context))
    assert db.get_calendar_draft(42, 42)["title"] is None
    assert "Upcoming schedule" in message.reply_text.call_args.args[0]


def test_streamed_thinking_and_final_json(monkeypatch, capsys):
    captured_payload = {}

    class Response:
        def raise_for_status(self):
            pass

        async def aiter_lines(self):
            yield json.dumps({"message": {"thinking": "Checking the supplied date. "}})
            yield json.dumps({"message": {"content": '{"intent":'}})
            yield json.dumps({"message": {"content": '"unknown"}'}, "done": True})

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

    class Client(Response):
        def __init__(self, **kwargs):
            pass

        def stream(self, method, url, json):
            captured_payload.update(json)
            return Response()

    monkeypatch.setattr(httpx, "AsyncClient", Client)
    client = OllamaClient("http://localhost:11434", "qwen3:8b")
    client.debug_enabled = True
    coroutine = client.generate_json("system", "test prompt")
    with pytest.raises(StopIteration) as result:
        coroutine.send(None)
    assert json.loads(result.value.value) == {"intent": "unknown"}
    assert "Checking the supplied date." in capsys.readouterr().err
    assert captured_payload["stream"] is True


def test_bad_recurrence_is_rejected():
    with pytest.raises(ValueError):
        ParsedIntent(intent=IntentType.CREATE_REMINDER, recurrence_rule="FREQ=SECONDLY")


@pytest.mark.parametrize("line", ['{"message":{"content":"{}"}}', '{"error":"failed"}', 'not json'])
def test_incomplete_or_invalid_stream_is_rejected(monkeypatch, line):
    class Client:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        def stream(self, *args, **kwargs):
            return self

        def raise_for_status(self):
            pass

        async def aiter_lines(self):
            yield line

    monkeypatch.setattr(httpx, "AsyncClient", Client)
    client = OllamaClient("http://localhost:11434", "qwen3:8b")
    client.debug_enabled = True
    coroutine = client.generate_json("system", "message")
    try:
        with pytest.raises(OllamaError):
            coroutine.send(None)
    finally:
        coroutine.close()


def test_daily_command_creates_persistent_recurring_reminder(tmp_path):
    from app.date_resolver import DateResolver

    db = Database(tmp_path / "db.sqlite")
    db.initialize()
    context = SimpleNamespace(args=["10am", "take", "my", "weight"], application=SimpleNamespace(bot_data={
        "database": db, "settings": SimpleNamespace(timezone="Asia/Singapore"),
        "date_resolver": DateResolver("Asia/Singapore"),
        "intent_parser": SimpleNamespace(parse=AsyncMock(side_effect=AssertionError("No model needed"))),
    }))
    message = SimpleNamespace(text="/daily 10am take my weight", reply_text=AsyncMock())
    update = SimpleNamespace(effective_user=SimpleNamespace(id=42), effective_chat=SimpleNamespace(id=42),
                             effective_message=message, callback_query=None, update_id=1)
    finish(command_handlers(42)[2].callback(update, context))
    row = db.list_reminders(42, 42)[0]
    assert row["recurrence_rule"] == "FREQ=DAILY"
    assert row["title"] == "Take My Weight"
    assert "Every day" in message.reply_text.call_args.args[0]
