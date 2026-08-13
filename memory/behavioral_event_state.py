"""Local persistence for validated behavioral-event records.

This module deliberately has no connection to prompts, agents, routines, or
notifications. It is the isolated data foundation for later behavioral analysis.
"""

from __future__ import annotations

import os
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime
from typing import Any, Mapping

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "behavioral_events.db")

_db_lock = threading.Lock()


def _connect(db_path: str = DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


@contextmanager
def _conn(db_path: str = DB_PATH):
    conn = _connect(db_path)
    try:
        with conn:
            yield conn
    finally:
        conn.close()


def init_db(db_path: str = DB_PATH) -> None:
    """Create the isolated behavioral-event schema if it does not exist."""
    with _conn(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS behavioral_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_type TEXT NOT NULL,
                category TEXT NOT NULL,
                subject TEXT NOT NULL,
                item TEXT,
                item_detail TEXT,
                status TEXT NOT NULL,
                event_date TEXT NOT NULL,
                confidence REAL NOT NULL,
                negated INTEGER NOT NULL DEFAULT 0,
                hypothetical INTEGER NOT NULL DEFAULT 0,
                reported_by_user INTEGER NOT NULL DEFAULT 0,
                record_state TEXT NOT NULL CHECK(record_state IN ('confirmed', 'candidate')),
                source_message_id TEXT NOT NULL,
                source_rowid INTEGER NOT NULL,
                source_channel TEXT NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE(source_message_id, event_type, item, status, event_date)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS behavioral_event_progress (
                key TEXT PRIMARY KEY,
                last_rowid INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_behavioral_events_state_date
            ON behavioral_events(record_state, event_date DESC)
            """
        )


def _required_text(event: Mapping[str, Any], field: str) -> str:
    value = str(event.get(field) or "").strip()
    if not value:
        raise ValueError(f"behavioral event requires {field}")
    return value


def _optional_text(event: Mapping[str, Any], field: str) -> str | None:
    value = str(event.get(field) or "").strip()
    return value or None


def _required_boolean(event: Mapping[str, Any], field: str) -> int:
    value = event.get(field)
    if not isinstance(value, bool):
        raise ValueError(f"behavioral event requires boolean {field}")
    return int(value)


def _event_values(event: Mapping[str, Any]) -> tuple[Any, ...]:
    record_state = _required_text(event, "record_state")
    if record_state not in {"confirmed", "candidate"}:
        raise ValueError("behavioral event record_state must be confirmed or candidate")
    try:
        confidence = float(event.get("confidence"))
    except (TypeError, ValueError) as exc:
        raise ValueError("behavioral event requires numeric confidence") from exc
    if not 0.0 <= confidence <= 1.0:
        raise ValueError("behavioral event confidence must be between 0 and 1")
    try:
        source_rowid = int(event.get("source_rowid"))
    except (TypeError, ValueError) as exc:
        raise ValueError("behavioral event requires source_rowid") from exc
    if source_rowid <= 0:
        raise ValueError("behavioral event source_rowid must be positive")

    return (
        _required_text(event, "event_type"),
        _required_text(event, "category"),
        _required_text(event, "subject"),
        _optional_text(event, "item"),
        _optional_text(event, "item_detail"),
        _required_text(event, "status"),
        _required_text(event, "event_date"),
        confidence,
        _required_boolean(event, "negated"),
        _required_boolean(event, "hypothetical"),
        _required_boolean(event, "reported_by_user"),
        record_state,
        _required_text(event, "source_message_id"),
        source_rowid,
        _required_text(event, "source_channel"),
        datetime.now().isoformat(timespec="seconds"),
    )


def record_event(event: Mapping[str, Any], *, db_path: str = DB_PATH) -> dict[str, Any]:
    """Persist one validated event, returning a no-op for any source replay."""
    values = _event_values(event)
    init_db(db_path)
    source_message_id = _required_text(event, "source_message_id")
    with _db_lock, _conn(db_path) as conn:
        existing = conn.execute(
            """
            SELECT id FROM behavioral_events
            WHERE source_message_id=?
            """,
            (source_message_id,),
        ).fetchone()
        if existing:
            return {"action": "duplicate_source", "event_id": int(existing["id"])}
        cursor = conn.execute(
            """
            INSERT INTO behavioral_events (
                event_type, category, subject, item, item_detail, status,
                event_date, confidence, negated, hypothetical, reported_by_user,
                record_state, source_message_id, source_rowid, source_channel,
                created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            values,
        )
    return {"action": "recorded", "event_id": int(cursor.lastrowid)}


def get_progress(*, key: str = "behavioral_events", db_path: str = DB_PATH) -> dict[str, Any]:
    """Return the independent conversation-history watermark for event intake."""
    init_db(db_path)
    with _conn(db_path) as conn:
        row = conn.execute(
            "SELECT last_rowid, updated_at FROM behavioral_event_progress WHERE key=?",
            (key,),
        ).fetchone()
    if row is None:
        return {"key": key, "last_rowid": 0, "updated_at": None}
    return {
        "key": key,
        "last_rowid": int(row["last_rowid"]),
        "updated_at": row["updated_at"],
    }


def set_progress(
    *,
    last_rowid: int,
    key: str = "behavioral_events",
    db_path: str = DB_PATH,
) -> None:
    """Advance the intake watermark after a fully handled message batch."""
    if int(last_rowid) < 0:
        raise ValueError("behavioral event last_rowid must not be negative")
    init_db(db_path)
    with _db_lock, _conn(db_path) as conn:
        conn.execute(
            """
            INSERT INTO behavioral_event_progress(key, last_rowid, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET
                last_rowid=MAX(behavioral_event_progress.last_rowid, excluded.last_rowid),
                updated_at=excluded.updated_at
            """,
            (key, int(last_rowid), datetime.now().isoformat(timespec="seconds")),
        )


def initialize_progress_if_missing(
    *,
    last_rowid: int,
    key: str = "behavioral_events",
    db_path: str = DB_PATH,
) -> dict[str, Any]:
    """Keep the earliest concurrent bootstrap boundary for background intake."""
    if int(last_rowid) < 0:
        raise ValueError("behavioral event last_rowid must not be negative")
    init_db(db_path)
    with _db_lock, _conn(db_path) as conn:
        conn.execute(
            """
            INSERT INTO behavioral_event_progress(key, last_rowid, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET
                last_rowid=MIN(behavioral_event_progress.last_rowid, excluded.last_rowid),
                updated_at=excluded.updated_at
            """,
            (key, int(last_rowid), datetime.now().isoformat(timespec="seconds")),
        )
        row = conn.execute(
            "SELECT last_rowid, updated_at FROM behavioral_event_progress WHERE key=?",
            (key,),
        ).fetchone()
    return {
        "key": key,
        "last_rowid": int(row["last_rowid"]),
        "updated_at": row["updated_at"],
    }


def list_events(
    *,
    record_state: str | None = None,
    db_path: str = DB_PATH,
) -> list[dict[str, Any]]:
    """Return events ordered newest first for inspection or later aggregation."""
    init_db(db_path)
    query = "SELECT * FROM behavioral_events"
    params: tuple[Any, ...] = ()
    if record_state is not None:
        if record_state not in {"confirmed", "candidate"}:
            raise ValueError("record_state must be confirmed or candidate")
        query += " WHERE record_state=?"
        params = (record_state,)
    query += " ORDER BY event_date DESC, id DESC"
    with _conn(db_path) as conn:
        rows = conn.execute(query, params).fetchall()
    return [dict(row) for row in rows]
