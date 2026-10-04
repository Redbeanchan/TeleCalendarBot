from datetime import datetime, timedelta, timezone

from app.database import Database


def database(tmp_path):
    db = Database(tmp_path / "assistant.db")
    db.initialize()
    return db


def test_reminder_persists_across_instances(tmp_path):
    db = database(tmp_path)
    reminder_id = db.create_reminder(1, 1, "Persistent", datetime.now(timezone.utc) - timedelta(seconds=1), "UTC")
    reopened = Database(db.path)
    reopened.initialize()
    assert reopened.claim_due_reminders()[0]["id"] == reminder_id


def test_claim_prevents_duplicate_delivery(tmp_path):
    db = database(tmp_path)
    db.create_reminder(1, 1, "Once", datetime.now(timezone.utc) - timedelta(seconds=1), "UTC")
    assert len(db.claim_due_reminders()) == 1
    assert db.claim_due_reminders() == []


def test_update_deduplication(tmp_path):
    db = database(tmp_path)
    assert db.mark_update(123) is True
    assert db.mark_update(123) is False


def test_action_claim_is_atomic_and_callback_idempotent(tmp_path):
    db = database(tmp_path)
    now = datetime.now(timezone.utc) + timedelta(hours=1)
    action_id = db.create_pending_action(1, "Dinner", now, now + timedelta(hours=2), "UTC", None, 30)
    assert db.claim_action(action_id, 1) is not None
    assert db.claim_action(action_id, 1) is None
    db.complete_action(action_id, "google-id")
    assert db.get_action(action_id)["status"] == "executed"


def test_expired_action_cannot_be_claimed(tmp_path):
    db = database(tmp_path)
    now = datetime.now(timezone.utc) + timedelta(hours=1)
    action_id = db.create_pending_action(1, "Dinner", now, now + timedelta(hours=1), "UTC", None, -1)
    assert db.claim_action(action_id, 1) is None
    assert db.get_action(action_id)["status"] == "expired"


def test_wrong_user_cannot_cancel_or_claim(tmp_path):
    db = database(tmp_path)
    now = datetime.now(timezone.utc) + timedelta(hours=1)
    action_id = db.create_pending_action(1, "Private", now, now + timedelta(hours=1), "UTC", None, 30)
    assert db.claim_action(action_id, 2) is None
    assert db.cancel_action(action_id, 2) is False


def test_calendar_draft_persists_partial_event_details(tmp_path):
    db = database(tmp_path)
    db.upsert_calendar_draft(1, 99, None, "tomorrow", "19:00", None, None, "Asia/Singapore", 30)
    reopened = Database(db.path)
    reopened.initialize()

    draft = reopened.get_calendar_draft(1, 99)

    assert draft["date_expression"] == "tomorrow"
    assert draft["event_time"] == "19:00"
    assert draft["location"] is None


def test_update_pending_action_stages_editable_draft_and_cancels_old_action(tmp_path):
    db = database(tmp_path)
    start = datetime(2026, 10, 5, 19, tzinfo=timezone.utc)
    action_id = db.create_pending_action(1, "Dinner with Louis", start, start + timedelta(hours=2), "UTC", None, 30)

    staged = db.stage_action_for_update(action_id, 1, 99, 30)
    draft = db.get_calendar_draft(1, 99)

    assert staged is not None
    assert db.get_action(action_id)["status"] == "cancelled"
    assert draft["title"] == "Dinner with Louis"
    assert draft["date_expression"] == "05 October 2026"
    assert draft["event_time"] == "19:00"
