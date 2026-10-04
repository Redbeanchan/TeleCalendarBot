from __future__ import annotations

import sqlite3
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone as dt_timezone
from pathlib import Path
from typing import Iterator
from zoneinfo import ZoneInfo

from dateutil.rrule import rrulestr


def utcnow() -> datetime:
    return datetime.now(dt_timezone.utc)


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

    def create_reminder(self, user_id: int, chat_id: int, title: str, when: datetime, timezone: str,
                        recurrence_rule: str | None = None) -> str:
        reminder_id = str(uuid.uuid4())
        with self.transaction(immediate=True) as db:
            db.execute(
                "INSERT INTO reminders(id,telegram_user_id,telegram_chat_id,title,scheduled_at_utc,original_timezone,created_at,status,recurrence_rule) VALUES(?,?,?,?,?,?,?,'pending',?)",
                (reminder_id, user_id, chat_id, title, when.astimezone(dt_timezone.utc).isoformat(), timezone, utcnow().isoformat(), recurrence_rule),
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
            row = db.execute("SELECT * FROM reminders WHERE id=? AND status='delivering'", (reminder_id,)).fetchone()
            if row and sent and row["recurrence_rule"]:
                anchor = datetime.fromisoformat(row["scheduled_at_utc"]).astimezone(ZoneInfo(row["original_timezone"]))
                next_due = rrulestr(row["recurrence_rule"], dtstart=anchor).after(max(utcnow(), anchor))
                db.execute("UPDATE reminders SET status='pending',scheduled_at_utc=?,sent=0,sent_at=? WHERE id=? AND status='delivering'",
                           (next_due.astimezone(dt_timezone.utc).isoformat(), utcnow().isoformat(), reminder_id))
                return
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

    def get_calendar_draft(self, user_id: int, chat_id: int) -> sqlite3.Row | None:
        with self.connect() as db:
            return db.execute(
                "SELECT * FROM calendar_drafts WHERE telegram_user_id=? AND telegram_chat_id=?",
                (user_id, chat_id),
            ).fetchone()

    def upsert_calendar_draft(self, user_id: int, chat_id: int, title: str | None, date_expression: str | None,
                              event_time: str | None, end_time: str | None, location: str | None,
                              timezone: str, ttl_minutes: int) -> None:
        now = utcnow()
        with self.transaction(immediate=True) as db:
            db.execute(
                """INSERT INTO calendar_drafts(
                     telegram_user_id,telegram_chat_id,title,date_expression,event_time,end_time,location,timezone,updated_at,expires_at
                   ) VALUES(?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(telegram_user_id,telegram_chat_id) DO UPDATE SET
                     title=excluded.title, date_expression=excluded.date_expression, event_time=excluded.event_time,
                     end_time=excluded.end_time, location=excluded.location, timezone=excluded.timezone,
                     updated_at=excluded.updated_at, expires_at=excluded.expires_at""",
                (
                    user_id, chat_id, title, date_expression, event_time, end_time, location, timezone,
                    now.isoformat(), (now + timedelta(minutes=ttl_minutes)).isoformat(),
                ),
            )

    def list_reminders(self, user_id: int, chat_id: int):
        with self.connect() as db:
            return db.execute("SELECT * FROM reminders WHERE telegram_user_id=? AND telegram_chat_id=? AND status IN ('pending','delivering') ORDER BY scheduled_at_utc",
                              (user_id, chat_id)).fetchall()

    def cancel_reminder(self, reminder_id: str, user_id: int, chat_id: int) -> bool:
        with self.transaction(immediate=True) as db:
            return bool(db.execute("UPDATE reminders SET status='cancelled' WHERE id=? AND telegram_user_id=? AND telegram_chat_id=? AND status IN ('pending','delivering')",
                                   (reminder_id, user_id, chat_id)).rowcount)

    def clear_calendar_draft(self, user_id: int, chat_id: int) -> None:
        with self.transaction(immediate=True) as db:
            db.execute(
                "DELETE FROM calendar_drafts WHERE telegram_user_id=? AND telegram_chat_id=?",
                (user_id, chat_id),
            )

    def stage_action_for_update(self, action_id: str, user_id: int, chat_id: int, ttl_minutes: int) -> sqlite3.Row | None:
        action = self.get_action(action_id)
        if action is None or action["telegram_user_id"] != user_id or action["status"] != "pending":
            return None
        start = datetime.fromisoformat(action["start_datetime"])
        end = datetime.fromisoformat(action["end_datetime"])
        self.upsert_calendar_draft(
            user_id, chat_id, action["event_title"], start.strftime("%d %B %Y"), start.strftime("%H:%M"),
            end.strftime("%H:%M"), action["location"], action["timezone"], ttl_minutes,
        )
        self.cancel_action(action_id, user_id)
        return action

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
CREATE TABLE IF NOT EXISTS calendar_drafts(
 telegram_user_id INTEGER NOT NULL, telegram_chat_id INTEGER NOT NULL,
 title TEXT, date_expression TEXT, event_time TEXT, end_time TEXT, location TEXT,
 timezone TEXT NOT NULL, updated_at TEXT NOT NULL, expires_at TEXT NOT NULL,
 PRIMARY KEY(telegram_user_id, telegram_chat_id)
);
CREATE INDEX IF NOT EXISTS idx_calendar_drafts_expiry ON calendar_drafts(expires_at);
CREATE TABLE IF NOT EXISTS processed_updates(update_id INTEGER PRIMARY KEY, processed_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS calendar_notifications(
 event_id TEXT NOT NULL, event_start TEXT NOT NULL, minutes_before INTEGER NOT NULL,
 sent_at TEXT NOT NULL, PRIMARY KEY(event_id,event_start,minutes_before)
);
"""
