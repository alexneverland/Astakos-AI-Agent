"""Durable lifecycle state for trusted Matrix message processing.

This module owns persistence only. It does not import a Matrix SDK, invoke the
assistant graph, or perform outbound delivery.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime
from typing import Any, Iterator

from config import STATE_DB

MATRIX_EVENT_STATUSES = frozenset({"processing", "reply_pending", "replied"})
MATRIX_REPLY_MODES = frozenset({"text", "voice"})

_db_lock = threading.Lock()


class MatrixEventStateError(RuntimeError):
    """Raised when a Matrix event attempts an unsafe lifecycle transition."""


def _required_identifier(value: str, field: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise ValueError(f"Matrix event requires {field}")
    return normalized


def _timestamp(value: datetime | None = None) -> str:
    return (value or datetime.now()).isoformat(timespec="seconds")


def _connect(db_path: str = STATE_DB) -> sqlite3.Connection:
    connection = sqlite3.connect(db_path, timeout=30)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA busy_timeout=5000")
    return connection


@contextmanager
def _conn(db_path: str = STATE_DB) -> Iterator[sqlite3.Connection]:
    connection = _connect(db_path)
    try:
        with connection:
            yield connection
    finally:
        connection.close()


def init_matrix_event_state(db_path: str = STATE_DB) -> None:
    """Create the isolated Matrix event lifecycle table when absent."""
    with _db_lock, _conn(db_path) as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS matrix_event_state (
                event_id TEXT PRIMARY KEY,
                room_id TEXT NOT NULL,
                sender_id TEXT NOT NULL,
                status TEXT NOT NULL
                    CHECK(status IN ('processing', 'reply_pending', 'replied')),
                reply_text TEXT,
                reply_mode TEXT NOT NULL DEFAULT 'text'
                    CHECK(reply_mode IN ('text', 'voice')),
                attachment_paths_json TEXT NOT NULL DEFAULT '[]',
                text_sent INTEGER NOT NULL DEFAULT 0,
                attachments_sent_count INTEGER NOT NULL DEFAULT 0,
                failure_code TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                replied_at TEXT
            )
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_matrix_event_state_status_updated
            ON matrix_event_state(status, updated_at)
            """
        )
        columns = {
            str(row[1])
            for row in connection.execute("PRAGMA table_info(matrix_event_state)")
        }
        if "reply_mode" not in columns:
            connection.execute(
                "ALTER TABLE matrix_event_state "
                "ADD COLUMN reply_mode TEXT NOT NULL DEFAULT 'text'"
            )
        if "attachment_paths_json" not in columns:
            connection.execute(
                "ALTER TABLE matrix_event_state "
                "ADD COLUMN attachment_paths_json TEXT NOT NULL DEFAULT '[]'"
            )
        if "text_sent" not in columns:
            connection.execute(
                "ALTER TABLE matrix_event_state "
                "ADD COLUMN text_sent INTEGER NOT NULL DEFAULT 0"
            )
        if "attachments_sent_count" not in columns:
            connection.execute(
                "ALTER TABLE matrix_event_state "
                "ADD COLUMN attachments_sent_count INTEGER NOT NULL DEFAULT 0"
            )


def reserve_matrix_event(
    *,
    event_id: str,
    room_id: str,
    sender_id: str,
    timestamp: datetime | None = None,
    db_path: str = STATE_DB,
) -> dict[str, str]:
    """Reserve one trusted Matrix event exactly once before graph execution."""
    normalized_event_id = _required_identifier(event_id, "event_id")
    normalized_room_id = _required_identifier(room_id, "room_id")
    normalized_sender_id = _required_identifier(sender_id, "sender_id")
    now = _timestamp(timestamp)

    init_matrix_event_state(db_path)
    with _db_lock, _conn(db_path) as connection:
        cursor = connection.execute(
            """
            INSERT OR IGNORE INTO matrix_event_state (
                event_id, room_id, sender_id, status,
                reply_text, reply_mode, failure_code, created_at, updated_at, replied_at
            ) VALUES (?, ?, ?, 'processing', NULL, 'text', NULL, ?, ?, NULL)
            """,
            (
                normalized_event_id,
                normalized_room_id,
                normalized_sender_id,
                now,
                now,
            ),
        )
        if cursor.rowcount == 1:
            return {
                "action": "reserved",
                "event_id": normalized_event_id,
                "status": "processing",
            }

        row = connection.execute(
            """
            SELECT room_id, sender_id, status
            FROM matrix_event_state
            WHERE event_id = ?
            """,
            (normalized_event_id,),
        ).fetchone()

    if row is None:
        raise MatrixEventStateError("Matrix event reservation could not be read")
    if row["room_id"] != normalized_room_id or row["sender_id"] != normalized_sender_id:
        raise MatrixEventStateError("Matrix event identity mismatch for reserved event_id")
    return {
        "action": "already_reserved",
        "event_id": normalized_event_id,
        "status": str(row["status"]),
    }


def store_matrix_event_reply(
    event_id: str,
    reply_text: str,
    *,
    reply_mode: str = "text",
    attachment_paths: tuple[str, ...] = (),
    timestamp: datetime | None = None,
    db_path: str = STATE_DB,
) -> dict[str, str]:
    """Persist the final reply before the transport attempts delivery."""
    normalized_event_id = _required_identifier(event_id, "event_id")
    normalized_reply = str(reply_text or "").strip()
    if not normalized_reply:
        raise ValueError("Matrix event requires reply_text")
    normalized_mode = str(reply_mode or "").strip().lower()
    if normalized_mode not in MATRIX_REPLY_MODES:
        raise ValueError("Matrix event requires reply_mode 'text' or 'voice'")
    normalized_paths = tuple(
        path
        for raw_path in attachment_paths
        if (path := str(raw_path or "").strip())
    )
    if len(normalized_paths) > 5:
        raise ValueError("Matrix event supports at most five attachment paths")
    paths_json = json.dumps(normalized_paths, ensure_ascii=False)
    now = _timestamp(timestamp)

    init_matrix_event_state(db_path)
    with _db_lock, _conn(db_path) as connection:
        row = connection.execute(
            """
            SELECT status, reply_text, reply_mode, attachment_paths_json
            FROM matrix_event_state WHERE event_id = ?
            """,
            (normalized_event_id,),
        ).fetchone()
        if row is None:
            raise MatrixEventStateError("Matrix event must be reserved before storing a reply")

        status = str(row["status"])
        existing_reply = row["reply_text"]
        if status == "processing":
            connection.execute(
                """
                UPDATE matrix_event_state
                SET status='reply_pending', reply_text=?, reply_mode=?,
                    attachment_paths_json=?, text_sent=0,
                    attachments_sent_count=0,
                    failure_code=NULL, updated_at=?
                WHERE event_id=? AND status='processing'
                """,
                (
                    normalized_reply,
                    normalized_mode,
                    paths_json,
                    now,
                    normalized_event_id,
                ),
            )
            return {
                "action": "reply_stored",
                "event_id": normalized_event_id,
                "status": "reply_pending",
            }
        if (
            status == "reply_pending"
            and existing_reply == normalized_reply
            and str(row["reply_mode"]) == normalized_mode
            and str(row["attachment_paths_json"]) == paths_json
        ):
            return {
                "action": "reply_already_stored",
                "event_id": normalized_event_id,
                "status": "reply_pending",
            }
        if status == "reply_pending":
            raise MatrixEventStateError("Matrix event already has a different reply")
        raise MatrixEventStateError(f"Matrix event is already {status}")


def mark_matrix_event_processed(
    event_id: str,
    *,
    timestamp: datetime | None = None,
    db_path: str = STATE_DB,
) -> dict[str, str]:
    """Finish a reserved event that intentionally produces no outbound reply."""
    normalized_event_id = _required_identifier(event_id, "event_id")
    now = _timestamp(timestamp)
    init_matrix_event_state(db_path)
    with _db_lock, _conn(db_path) as connection:
        row = connection.execute(
            "SELECT status FROM matrix_event_state WHERE event_id = ?",
            (normalized_event_id,),
        ).fetchone()
        if row is None:
            raise MatrixEventStateError("Matrix event must be reserved before completion")
        status = str(row["status"])
        if status == "replied":
            return {"action": "already_processed", "event_id": normalized_event_id, "status": status}
        if status != "processing":
            raise MatrixEventStateError("Only a processing Matrix event can finish without reply")
        connection.execute(
            """
            UPDATE matrix_event_state
            SET status='replied', updated_at=?, replied_at=?
            WHERE event_id=? AND status='processing'
            """,
            (now, now, normalized_event_id),
        )
    return {"action": "processed", "event_id": normalized_event_id, "status": "replied"}


def mark_matrix_reply_text_sent(
    event_id: str,
    *,
    timestamp: datetime | None = None,
    db_path: str = STATE_DB,
) -> dict[str, str]:
    """Persist successful primary text or voice delivery, idempotently."""
    normalized_event_id = _required_identifier(event_id, "event_id")
    now = _timestamp(timestamp)
    init_matrix_event_state(db_path)
    with _db_lock, _conn(db_path) as connection:
        row = connection.execute(
            "SELECT status, text_sent FROM matrix_event_state WHERE event_id = ?",
            (normalized_event_id,),
        ).fetchone()
        if row is None or str(row["status"]) != "reply_pending":
            raise MatrixEventStateError("Matrix reply text requires reply_pending state")
        if int(row["text_sent"]):
            return {
                "action": "text_already_sent",
                "event_id": normalized_event_id,
                "status": "reply_pending",
            }
        connection.execute(
            """
            UPDATE matrix_event_state SET text_sent=1, updated_at=?
            WHERE event_id=? AND status='reply_pending' AND text_sent=0
            """,
            (now, normalized_event_id),
        )
    return {
        "action": "text_marked_sent",
        "event_id": normalized_event_id,
        "status": "reply_pending",
    }


def mark_matrix_attachment_sent(
    event_id: str,
    *,
    expected_index: int,
    timestamp: datetime | None = None,
    db_path: str = STATE_DB,
) -> dict[str, str]:
    """Advance one attachment only when it is the next persisted stage."""
    normalized_event_id = _required_identifier(event_id, "event_id")
    if expected_index < 0:
        raise ValueError("Matrix attachment expected_index must be non-negative")
    now = _timestamp(timestamp)
    init_matrix_event_state(db_path)
    with _db_lock, _conn(db_path) as connection:
        row = connection.execute(
            """
            SELECT status, attachment_paths_json, attachments_sent_count
            FROM matrix_event_state WHERE event_id = ?
            """,
            (normalized_event_id,),
        ).fetchone()
        if row is None or str(row["status"]) != "reply_pending":
            raise MatrixEventStateError("Matrix attachment requires reply_pending state")
        paths = json.loads(str(row["attachment_paths_json"]) or "[]")
        current = int(row["attachments_sent_count"])
        if current != expected_index:
            raise MatrixEventStateError("Matrix attachments must be marked in delivery order")
        if expected_index >= len(paths):
            raise MatrixEventStateError("Matrix attachment index is outside the reply")
        connection.execute(
            """
            UPDATE matrix_event_state
            SET attachments_sent_count=?, updated_at=?
            WHERE event_id=? AND status='reply_pending'
              AND attachments_sent_count=?
            """,
            (current + 1, now, normalized_event_id, current),
        )
    return {
        "action": "attachment_marked_sent",
        "event_id": normalized_event_id,
        "status": "reply_pending",
    }


def mark_matrix_event_replied(
    event_id: str,
    *,
    timestamp: datetime | None = None,
    db_path: str = STATE_DB,
) -> dict[str, str]:
    """Mark a persisted pending reply delivered, idempotently."""
    normalized_event_id = _required_identifier(event_id, "event_id")
    now = _timestamp(timestamp)

    init_matrix_event_state(db_path)
    with _db_lock, _conn(db_path) as connection:
        row = connection.execute(
            """
            SELECT status, text_sent, attachment_paths_json,
                   attachments_sent_count
            FROM matrix_event_state WHERE event_id = ?
            """,
            (normalized_event_id,),
        ).fetchone()
        if row is None:
            raise MatrixEventStateError("Matrix event must be reserved before marking replied")

        status = str(row["status"])
        if status == "replied":
            return {
                "action": "already_replied",
                "event_id": normalized_event_id,
                "status": "replied",
            }
        if status != "reply_pending":
            raise MatrixEventStateError("Matrix event must be reply_pending before marking replied")
        attachment_count = len(
            json.loads(str(row["attachment_paths_json"]) or "[]")
        )
        if not int(row["text_sent"]) or int(row["attachments_sent_count"]) != attachment_count:
            raise MatrixEventStateError(
                "Matrix event cannot be replied before all delivery stages complete"
            )

        connection.execute(
            """
            UPDATE matrix_event_state
            SET status='replied', replied_at=?, updated_at=?
            WHERE event_id=? AND status='reply_pending'
            """,
            (now, now, normalized_event_id),
        )
    return {
        "action": "marked_replied",
        "event_id": normalized_event_id,
        "status": "replied",
    }


def get_matrix_event(
    event_id: str,
    *,
    db_path: str = STATE_DB,
) -> dict[str, Any] | None:
    """Return one Matrix lifecycle row without exposing any other state data."""
    normalized_event_id = _required_identifier(event_id, "event_id")
    init_matrix_event_state(db_path)
    with _conn(db_path) as connection:
        row = connection.execute(
            "SELECT * FROM matrix_event_state WHERE event_id = ?",
            (normalized_event_id,),
        ).fetchone()
    return dict(row) if row is not None else None


def list_pending_matrix_replies(
    *,
    limit: int = 100,
    db_path: str = STATE_DB,
) -> list[dict[str, Any]]:
    """Return saved replies that may be delivered without rerunning the graph."""
    if limit <= 0:
        return []
    init_matrix_event_state(db_path)
    with _conn(db_path) as connection:
        rows = connection.execute(
            """
            SELECT event_id, room_id, sender_id, reply_text, reply_mode,
                   attachment_paths_json, text_sent, attachments_sent_count,
                   status
            FROM matrix_event_state
            WHERE status='reply_pending' AND reply_text IS NOT NULL
            ORDER BY created_at ASC, event_id ASC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    pending: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        item["attachment_paths"] = tuple(
            str(path) for path in json.loads(item.pop("attachment_paths_json"))
        )
        pending.append(item)
    return pending


def list_stale_matrix_processing(
    *,
    older_than: datetime,
    limit: int = 100,
    db_path: str = STATE_DB,
) -> list[dict[str, Any]]:
    """Report interrupted graph work for manual recovery without reclaiming it."""
    if limit <= 0:
        return []
    cutoff = _timestamp(older_than)
    init_matrix_event_state(db_path)
    with _conn(db_path) as connection:
        rows = connection.execute(
            """
            SELECT *
            FROM matrix_event_state
            WHERE status='processing' AND created_at < ?
            ORDER BY created_at ASC, event_id ASC
            LIMIT ?
            """,
            (cutoff, limit),
        ).fetchall()
    return [dict(row) for row in rows]
