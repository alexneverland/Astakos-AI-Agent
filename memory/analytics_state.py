"""
Incremental analytics state for passive routine detection.

The nightly analytics job should not re-process the same 30 days forever.
This module stores progress and candidate routine occurrences in SQLite.
"""

from __future__ import annotations

import os
import sqlite3
import threading
from datetime import datetime
from difflib import SequenceMatcher
from typing import Any

from memory.routine_db import normalize_day, normalize_time

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "analytics_state.db")
DEFAULT_KEY = "routine_analytics"

_db_lock = threading.Lock()


def _connect(db_path: str = DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def init_db(db_path: str = DB_PATH) -> None:
    with _connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS analytics_progress (
                key TEXT PRIMARY KEY,
                last_rowid INTEGER NOT NULL DEFAULT 0,
                bootstrap_completed INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS analytics_candidates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                day_of_week TEXT NOT NULL,
                time_bucket TEXT NOT NULL,
                event_name TEXT NOT NULL,
                event_type TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'candidate',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                promoted_at TEXT,
                promotion_result TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_analytics_candidates_slot
            ON analytics_candidates(day_of_week, time_bucket, event_type, status)
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS analytics_occurrences (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                candidate_id INTEGER NOT NULL,
                message_rowid INTEGER NOT NULL UNIQUE,
                message_id TEXT,
                date TEXT NOT NULL,
                time TEXT NOT NULL,
                week_id TEXT NOT NULL,
                channel TEXT,
                content_preview TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY(candidate_id) REFERENCES analytics_candidates(id)
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_analytics_occ_candidate
            ON analytics_occurrences(candidate_id, date, time)
            """
        )


def get_progress(
    key: str = DEFAULT_KEY,
    *,
    db_path: str = DB_PATH,
    initialize: bool = True,
) -> dict[str, Any]:
    if initialize:
        init_db(db_path)
    elif not os.path.exists(db_path):
        return {"key": key, "last_rowid": 0, "bootstrap_completed": False, "updated_at": None}

    with _connect(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM analytics_progress WHERE key=?",
            (key,),
        ).fetchone()
    if not row:
        return {"key": key, "last_rowid": 0, "bootstrap_completed": False, "updated_at": None}
    return {
        "key": row["key"],
        "last_rowid": int(row["last_rowid"] or 0),
        "bootstrap_completed": bool(row["bootstrap_completed"]),
        "updated_at": row["updated_at"],
    }


def set_progress(
    *,
    last_rowid: int,
    bootstrap_completed: bool | None = None,
    key: str = DEFAULT_KEY,
    db_path: str = DB_PATH,
) -> None:
    init_db(db_path)
    current = get_progress(key, db_path=db_path)
    completed = current["bootstrap_completed"] if bootstrap_completed is None else bool(bootstrap_completed)
    now = datetime.now().isoformat(timespec="seconds")
    with _db_lock, _connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO analytics_progress(key, last_rowid, bootstrap_completed, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET
                last_rowid=excluded.last_rowid,
                bootstrap_completed=excluded.bootstrap_completed,
                updated_at=excluded.updated_at
            """,
            (key, int(last_rowid), int(completed), now),
        )


def _event_similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a.lower().strip(), b.lower().strip()).ratio()


def _find_candidate(
    conn: sqlite3.Connection,
    *,
    day_of_week: str,
    time_bucket: str,
    event_name: str,
    event_type: str,
    similarity_threshold: float,
) -> sqlite3.Row | None:
    rows = conn.execute(
        """
        SELECT *
        FROM analytics_candidates
        WHERE day_of_week=? AND time_bucket=? AND event_type=?
          AND status IN ('candidate', 'promoted')
        ORDER BY updated_at DESC, id DESC
        """,
        (day_of_week, time_bucket, event_type),
    ).fetchall()
    for row in rows:
        if _event_similarity(event_name, row["event_name"]) >= similarity_threshold:
            return row
    return None


def add_occurrence(
    *,
    day_of_week: str,
    time_bucket: str,
    event_name: str,
    event_type: str,
    message: dict[str, Any],
    week_id: str,
    db_path: str = DB_PATH,
    similarity_threshold: float = 0.60,
) -> dict[str, Any]:
    """Add one extracted activity occurrence and merge it into a candidate slot."""
    init_db(db_path)
    now = datetime.now().isoformat(timespec="seconds")
    day = normalize_day(day_of_week)
    bucket = normalize_time(time_bucket)
    event = str(event_name).strip()
    ev_type = str(event_type or "general").strip() or "general"
    rowid = int(message.get("rowid") or 0)
    if rowid <= 0:
        raise ValueError("message rowid is required for incremental analytics")

    with _db_lock, _connect(db_path) as conn:
        existing = conn.execute(
            "SELECT candidate_id FROM analytics_occurrences WHERE message_rowid=?",
            (rowid,),
        ).fetchone()
        if existing:
            return {"action": "duplicate_occurrence", "candidate_id": existing["candidate_id"]}

        candidate = _find_candidate(
            conn,
            day_of_week=day,
            time_bucket=bucket,
            event_name=event,
            event_type=ev_type,
            similarity_threshold=similarity_threshold,
        )
        if candidate:
            candidate_id = int(candidate["id"])
            action = "added_occurrence"
            if candidate["event_name"] != event and candidate["status"] == "candidate":
                conn.execute(
                    """
                    UPDATE analytics_candidates
                    SET event_name=?, updated_at=?
                    WHERE id=?
                    """,
                    (event, now, candidate_id),
                )
                action = "merged_candidate"
            else:
                conn.execute(
                    "UPDATE analytics_candidates SET updated_at=? WHERE id=?",
                    (now, candidate_id),
                )
        else:
            cur = conn.execute(
                """
                INSERT INTO analytics_candidates(
                    day_of_week, time_bucket, event_name, event_type,
                    status, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, 'candidate', ?, ?)
                """,
                (day, bucket, event, ev_type, now, now),
            )
            candidate_id = int(cur.lastrowid)
            action = "created_candidate"

        conn.execute(
            """
            INSERT INTO analytics_occurrences(
                candidate_id, message_rowid, message_id, date, time,
                week_id, channel, content_preview, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                candidate_id,
                rowid,
                message.get("id"),
                message.get("date") or "",
                message.get("time") or "",
                week_id,
                message.get("channel"),
                str(message.get("content") or "")[:240],
                now,
            ),
        )
    return {"action": action, "candidate_id": candidate_id}


def list_candidates(
    *,
    status: str | None = None,
    db_path: str = DB_PATH,
) -> list[dict[str, Any]]:
    init_db(db_path)
    params: list[Any] = []
    where = ""
    if status:
        where = "WHERE c.status=?"
        params.append(status)
    with _connect(db_path) as conn:
        rows = conn.execute(
            f"""
            SELECT
                c.*,
                COUNT(o.id) AS occurrence_count,
                COUNT(DISTINCT o.week_id) AS week_count,
                MIN(o.date) AS first_date,
                MAX(o.date) AS last_date
            FROM analytics_candidates c
            LEFT JOIN analytics_occurrences o ON o.candidate_id=c.id
            {where}
            GROUP BY c.id
            ORDER BY c.updated_at DESC, c.id DESC
            """,
            params,
        ).fetchall()
    return [dict(row) for row in rows]


def eligible_candidates(
    *,
    min_occurrences: int,
    min_weeks: int,
    everyday_days: int,
    db_path: str = DB_PATH,
) -> list[dict[str, Any]]:
    ready = []
    for candidate in list_candidates(status="candidate", db_path=db_path):
        required_weeks = 1 if candidate["day_of_week"] == "Everyday" else min_weeks
        required_occurrences = everyday_days if candidate["day_of_week"] == "Everyday" else min_occurrences
        if candidate["occurrence_count"] >= required_occurrences and candidate["week_count"] >= required_weeks:
            ready.append(candidate)
    return ready


def mark_promoted(
    candidate_id: int,
    *,
    result: str,
    db_path: str = DB_PATH,
) -> None:
    init_db(db_path)
    now = datetime.now().isoformat(timespec="seconds")
    with _db_lock, _connect(db_path) as conn:
        conn.execute(
            """
            UPDATE analytics_candidates
            SET status='promoted', promoted_at=?, promotion_result=?, updated_at=?
            WHERE id=?
            """,
            (now, result, now, int(candidate_id)),
        )


def state_stats(*, db_path: str = DB_PATH) -> dict[str, int]:
    init_db(db_path)
    with _connect(db_path) as conn:
        candidate_count = conn.execute("SELECT COUNT(*) FROM analytics_candidates").fetchone()[0]
        occurrence_count = conn.execute("SELECT COUNT(*) FROM analytics_occurrences").fetchone()[0]
        promoted_count = conn.execute(
            "SELECT COUNT(*) FROM analytics_candidates WHERE status='promoted'"
        ).fetchone()[0]
    return {
        "candidates": int(candidate_count),
        "occurrences": int(occurrence_count),
        "promoted": int(promoted_count),
    }
