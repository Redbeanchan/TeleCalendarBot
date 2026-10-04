from datetime import datetime, timedelta, timezone

from app.database import Database


def test_calendar_write_requires_pending_confirmation(tmp_path):
    """The repository exposes only proposal creation; claim is the confirmation gate."""
    db = Database(tmp_path / "db")
    db.initialize()
    start = datetime.now(timezone.utc) + timedelta(days=1)
    action_id = db.create_pending_action(10, "Meeting", start, start + timedelta(hours=1), "UTC", None, 30)
    action = db.get_action(action_id)
    assert action["status"] == "pending"
    assert action["google_event_id"] is None
    assert db.claim_action(action_id, 999) is None


def test_calendar_notification_deduplicates(tmp_path):
    db = Database(tmp_path / "db")
    db.initialize()
    start = datetime.now(timezone.utc)
    assert db.mark_calendar_notice("event", start, 30)
    assert not db.mark_calendar_notice("event", start, 30)
