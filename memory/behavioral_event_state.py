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
            CREATE TABLE IF NOT EXISTS behavioral_event_bootstrap_boundaries (
                key TEXT PRIMARY KEY,
                last_rowid INTEGER NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS behavioral_event_replay_state (
                key TEXT PRIMARY KEY,
                boundary_rowid INTEGER NOT NULL,
                cursor_rowid INTEGER NOT NULL,
                target_rowid INTEGER NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS behavioral_event_sources (
                source_message_id TEXT PRIMARY KEY,
                event_id INTEGER NOT NULL REFERENCES behavioral_events(id)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS behavioral_event_schema_state (
                key TEXT PRIMARY KEY,
                applied_at TEXT NOT NULL
            )
            """
        )
        migration = conn.execute(
            """
            INSERT OR IGNORE INTO behavioral_event_schema_state(key, applied_at)
            VALUES ('source_backfill_v1', ?)
            """,
            (datetime.now().isoformat(timespec="seconds"),),
        )
        if migration.rowcount == 1:
            conn.execute(
                """
                INSERT OR IGNORE INTO behavioral_event_sources(source_message_id, event_id)
                SELECT source_message_id, MIN(id)
                FROM behavioral_events
                GROUP BY source_message_id
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
        claim = conn.execute(
            """
            INSERT OR IGNORE INTO behavioral_event_sources(source_message_id, event_id)
            VALUES (?, 0)
            """,
            (source_message_id,),
        )
        if claim.rowcount == 0:
            existing = conn.execute(
                "SELECT event_id FROM behavioral_event_sources WHERE source_message_id=?",
                (source_message_id,),
            ).fetchone()
            return {"action": "duplicate_source", "event_id": int(existing["event_id"])}
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
        conn.execute(
            "UPDATE behavioral_event_sources SET event_id=? WHERE source_message_id=?",
            (int(cursor.lastrowid), source_message_id),
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
    consumed_boundary: int | None = None,
    key: str = "behavioral_events",
    db_path: str = DB_PATH,
) -> None:
    """Advance progress and clear only the replay boundary this batch consumed."""
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
        if consumed_boundary is not None and int(consumed_boundary) < int(last_rowid):
            conn.execute(
                """
                DELETE FROM behavioral_event_bootstrap_boundaries
                WHERE key=? AND last_rowid=?
                """,
                (key, int(consumed_boundary)),
            )


def get_pending_replay(
    *,
    key: str = "behavioral_events",
    db_path: str = DB_PATH,
) -> dict[str, int] | None:
    """Return a delayed-boundary replay cursor, if an older row arrived late."""
    init_db(db_path)
    with _conn(db_path) as conn:
        row = conn.execute(
            """
            SELECT boundary_rowid, cursor_rowid, target_rowid
            FROM behavioral_event_replay_state WHERE key=?
            """,
            (key,),
        ).fetchone()
    if row is None:
        return None
    return {
        "boundary_rowid": int(row["boundary_rowid"]),
        "cursor_rowid": int(row["cursor_rowid"]),
        "target_rowid": int(row["target_rowid"]),
    }


def advance_pending_replay(
    *,
    cursor_rowid: int,
    key: str = "behavioral_events",
    db_path: str = DB_PATH,
) -> None:
    """Advance a replay cursor and remove it only once it reaches its target."""
    init_db(db_path)
    with _db_lock, _conn(db_path) as conn:
        conn.execute(
            """
            UPDATE behavioral_event_replay_state
            SET cursor_rowid=MAX(cursor_rowid, ?)
            WHERE key=?
            """,
            (int(cursor_rowid), key),
        )
        conn.execute(
            """
            DELETE FROM behavioral_event_replay_state
            WHERE key=? AND cursor_rowid >= target_rowid
            """,
            (key,),
        )


def get_initialization_boundary(
    *,
    key: str = "behavioral_events",
    db_path: str = DB_PATH,
) -> int | None:
    """Return the earliest pending replay boundary, if one is registered."""
    init_db(db_path)
    with _conn(db_path) as conn:
        row = conn.execute(
            "SELECT last_rowid FROM behavioral_event_bootstrap_boundaries WHERE key=?",
            (key,),
        ).fetchone()
    return int(row["last_rowid"]) if row is not None else None


def register_initialization_boundary(
    *,
    last_rowid: int,
    key: str = "behavioral_events",
    db_path: str = DB_PATH,
) -> dict[str, Any]:
    """Persist the earliest newly written row before background intake runs."""
    if int(last_rowid) < 0:
        raise ValueError("behavioral event last_rowid must not be negative")
    init_db(db_path)
    with _db_lock, _conn(db_path) as conn:
        progress = conn.execute(
            "SELECT last_rowid, updated_at FROM behavioral_event_progress WHERE key=?",
            (key,),
        ).fetchone()
        if progress is not None and int(last_rowid) < int(progress["last_rowid"]):
            conn.execute(
                """
                INSERT INTO behavioral_event_replay_state(
                    key, boundary_rowid, cursor_rowid, target_rowid
                ) VALUES (?, ?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    boundary_rowid=MIN(behavioral_event_replay_state.boundary_rowid, excluded.boundary_rowid),
                    cursor_rowid=MIN(behavioral_event_replay_state.cursor_rowid, excluded.cursor_rowid),
                    target_rowid=MAX(behavioral_event_replay_state.target_rowid, excluded.target_rowid)
                """,
                (key, int(last_rowid), int(last_rowid), int(progress["last_rowid"])),
            )
            replay = conn.execute(
                "SELECT boundary_rowid FROM behavioral_event_replay_state WHERE key=?",
                (key,),
            ).fetchone()
            return {"key": key, "last_rowid": int(replay["boundary_rowid"]), "updated_at": progress["updated_at"]}
        conn.execute(
            """
            INSERT INTO behavioral_event_bootstrap_boundaries(key, last_rowid)
            VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET
                last_rowid=MIN(behavioral_event_bootstrap_boundaries.last_rowid, excluded.last_rowid)
            """,
            (key, int(last_rowid)),
        )
        boundary = conn.execute(
            "SELECT last_rowid FROM behavioral_event_bootstrap_boundaries WHERE key=?",
            (key,),
        ).fetchone()
    return {"key": key, "last_rowid": int(boundary["last_rowid"]), "updated_at": None}


def initialize_progress_if_missing(
    *,
    last_rowid: int,
    key: str = "behavioral_events",
    db_path: str = DB_PATH,
) -> dict[str, Any]:
    """Return the durable bootstrap boundary without regressing progress."""
    if int(last_rowid) < 0:
        raise ValueError("behavioral event last_rowid must not be negative")
    init_db(db_path)
    with _db_lock, _conn(db_path) as conn:
        progress = conn.execute(
            "SELECT last_rowid, updated_at FROM behavioral_event_progress WHERE key=?",
            (key,),
        ).fetchone()
        if progress is not None:
            return {
                "key": key,
                "last_rowid": int(progress["last_rowid"]),
                "updated_at": progress["updated_at"],
            }
        conn.execute(
            """
            INSERT INTO behavioral_event_bootstrap_boundaries(key, last_rowid)
            VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET
                last_rowid=MIN(behavioral_event_bootstrap_boundaries.last_rowid, excluded.last_rowid)
            """,
            (key, int(last_rowid)),
        )
        row = conn.execute(
            "SELECT last_rowid FROM behavioral_event_bootstrap_boundaries WHERE key=?",
            (key,),
        ).fetchone()
    return {
        "key": key,
        "last_rowid": int(row["last_rowid"]),
        "updated_at": None,
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
