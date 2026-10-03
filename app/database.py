from __future__ import annotations

import sqlite3
import threading
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Iterator


def utcnow() -> datetime:
    return datetime.now(UTC)


class Database:
    """Small transactional SQLite repository. Each operation owns its connection."""

    def __init__(self, path: Path | str):
        self.path = Path(path)
        self._init_lock = threading.Lock()

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=15, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=15000")
        return connection

    @contextmanager
    def transaction(self, immediate: bool = False) -> Iterator[sqlite3.Connection]:
        connection = self.connect()
        try:
            connection.execute("BEGIN IMMEDIATE" if immediate else "BEGIN")
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._init_lock, self.connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("PRAGMA synchronous=NORMAL")
            db.executescript(SCHEMA)

    def create_reminder(self, user_id: int, chat_id: int, title: str, when: datetime, timezone: str) -> str:
        reminder_id = str(uuid.uuid4())
        with self.transaction(immediate=True) as db:
            db.execute(
                "INSERT INTO reminders(id,telegram_user_id,telegram_chat_id,title,scheduled_at_utc,original_timezone,created_at,status) VALUES(?,?,?,?,?,?,?,'pending')",
                (reminder_id, user_id, chat_id, title, when.astimezone(UTC).isoformat(), timezone, utcnow().isoformat()),
            )
        return reminder_id

    def claim_due_reminders(self, limit: int = 20) -> list[sqlite3.Row]:
        now = utcnow().isoformat()
        with self.transaction(immediate=True) as db:
            rows = db.execute(
                "SELECT * FROM reminders WHERE status='pending' AND scheduled_at_utc<=? ORDER BY scheduled_at_utc LIMIT ?", (now, limit)
            ).fetchall()
            for row in rows:
                db.execute("UPDATE reminders SET status='delivering' WHERE id=? AND status='pending'", (row["id"],))
            return rows

    def finish_reminder(self, reminder_id: str, sent: bool) -> None:
        with self.transaction(immediate=True) as db:
            db.execute(
                "UPDATE reminders SET status=?, sent=?, sent_at=? WHERE id=? AND status='delivering'",
                ("sent" if sent else "pending", int(sent), utcnow().isoformat() if sent else None, reminder_id),
            )

    def recover_deliveries(self) -> None:
        with self.transaction(immediate=True) as db:
            db.execute("UPDATE reminders SET status='pending' WHERE status='delivering'")
            db.execute("UPDATE pending_actions SET status='pending' WHERE status='executing'")

    def create_pending_action(self, user_id: int, title: str, start: datetime, end: datetime, timezone: str,
                              location: str | None, ttl_minutes: int) -> str:
        action_id = str(uuid.uuid4())
        now = utcnow()
        with self.transaction(immediate=True) as db:
            db.execute(
                """INSERT INTO pending_actions(id,telegram_user_id,action_type,event_title,start_datetime,end_datetime,timezone,location,created_at,expires_at,status,idempotency_key)
                   VALUES(?,?,'create',?,?,?,?,?,?,?,'pending',?)""",
                (action_id, user_id, title, start.isoformat(), end.isoformat(), timezone, location, now.isoformat(),
                 (now + timedelta(minutes=ttl_minutes)).isoformat(), f"calendar-create:{action_id}"),
            )
        return action_id

    def get_action(self, action_id: str) -> sqlite3.Row | None:
        with self.connect() as db:
            return db.execute("SELECT * FROM pending_actions WHERE id=?", (action_id,)).fetchone()

    def claim_action(self, action_id: str, user_id: int) -> sqlite3.Row | None:
        with self.transaction(immediate=True) as db:
            db.execute("UPDATE pending_actions SET status='expired' WHERE id=? AND status='pending' AND expires_at<=?", (action_id, utcnow().isoformat()))
            changed = db.execute(
                "UPDATE pending_actions SET status='executing',confirmed_at=? WHERE id=? AND telegram_user_id=? AND status='pending'",
                (utcnow().isoformat(), action_id, user_id),
            ).rowcount
            return db.execute("SELECT * FROM pending_actions WHERE id=?", (action_id,)).fetchone() if changed else None

    def complete_action(self, action_id: str, google_event_id: str | None, error: str | None = None) -> None:
        with self.transaction(immediate=True) as db:
            db.execute(
                "UPDATE pending_actions SET status=?,google_event_id=?,executed_at=?,last_error=? WHERE id=? AND status='executing'",
                ("failed" if error else "executed", google_event_id, utcnow().isoformat(), error, action_id),
            )

    def release_action(self, action_id: str, error: str) -> None:
        with self.transaction(immediate=True) as db:
            db.execute("UPDATE pending_actions SET status='pending',last_error=? WHERE id=? AND status='executing'", (error[:500], action_id))

    def cancel_action(self, action_id: str, user_id: int) -> bool:
        with self.transaction(immediate=True) as db:
            return bool(db.execute(
                "UPDATE pending_actions SET status='cancelled' WHERE id=? AND telegram_user_id=? AND status='pending'", (action_id, user_id)
            ).rowcount)

    def mark_update(self, update_id: int) -> bool:
        try:
            with self.transaction(immediate=True) as db:
                db.execute("INSERT INTO processed_updates(update_id,processed_at) VALUES(?,?)", (update_id, utcnow().isoformat()))
            return True
        except sqlite3.IntegrityError:
            return False

    def mark_calendar_notice(self, event_id: str, start: datetime, minutes: int) -> bool:
        try:
            with self.transaction(immediate=True) as db:
                db.execute("INSERT INTO calendar_notifications(event_id,event_start,minutes_before,sent_at) VALUES(?,?,?,?)",
                           (event_id, start.isoformat(), minutes, utcnow().isoformat()))
            return True
        except sqlite3.IntegrityError:
            return False


SCHEMA = """
CREATE TABLE IF NOT EXISTS reminders(
 id TEXT PRIMARY KEY, telegram_user_id INTEGER NOT NULL, telegram_chat_id INTEGER NOT NULL,
 title TEXT NOT NULL, scheduled_at_utc TEXT NOT NULL, original_timezone TEXT NOT NULL,
 created_at TEXT NOT NULL, sent INTEGER NOT NULL DEFAULT 0, sent_at TEXT, status TEXT NOT NULL,
 recurrence_rule TEXT, snoozed_until TEXT
);
CREATE INDEX IF NOT EXISTS idx_reminders_due ON reminders(status, scheduled_at_utc);
CREATE TABLE IF NOT EXISTS pending_actions(
 id TEXT PRIMARY KEY, telegram_user_id INTEGER NOT NULL, action_type TEXT NOT NULL,
 event_title TEXT NOT NULL, start_datetime TEXT NOT NULL, end_datetime TEXT NOT NULL,
 timezone TEXT NOT NULL, location TEXT, google_event_id TEXT, created_at TEXT NOT NULL,
 expires_at TEXT NOT NULL, confirmed_at TEXT, executed_at TEXT, status TEXT NOT NULL,
 idempotency_key TEXT NOT NULL UNIQUE, last_error TEXT
);
CREATE INDEX IF NOT EXISTS idx_actions_status ON pending_actions(status, expires_at);
CREATE TABLE IF NOT EXISTS processed_updates(update_id INTEGER PRIMARY KEY, processed_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS calendar_notifications(
 event_id TEXT NOT NULL, event_start TEXT NOT NULL, minutes_before INTEGER NOT NULL,
 sent_at TEXT NOT NULL, PRIMARY KEY(event_id,event_start,minutes_before)
);
"""
