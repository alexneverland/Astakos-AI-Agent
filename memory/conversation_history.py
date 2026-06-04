"""
Shared conversation history store for all Astakos channels.

SQLite is used instead of JSON so web and Telegram processes can append safely
without clobbering each other's writes.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime
from typing import Any

from config import CONVERSATION_DB_FILE


def _connect(db_path: str = CONVERSATION_DB_FILE) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def init_db(db_path: str = CONVERSATION_DB_FILE) -> None:
    with _connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS conversation_messages (
                id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                channel TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                date TEXT NOT NULL,
                time TEXT NOT NULL,
                agent TEXT,
                metadata_json TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_conversation_time
            ON conversation_messages(timestamp)
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_conversation_channel_time
            ON conversation_messages(channel, timestamp)
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_conversation_session_time
            ON conversation_messages(session_id, timestamp)
            """
        )


def default_session_id(ts: datetime | None = None) -> str:
    current = ts or datetime.now()
    return current.strftime("%Y-%m-%d")


def append_message(
    *,
    role: str,
    content: str,
    channel: str,
    session_id: str | None = None,
    agent: str | None = None,
    metadata: dict[str, Any] | None = None,
    timestamp: datetime | None = None,
    db_path: str = CONVERSATION_DB_FILE,
) -> dict[str, Any]:
    ts = timestamp or datetime.now()
    message = {
        "id": str(uuid.uuid4()),
        "session_id": session_id or default_session_id(ts),
        "channel": channel,
        "role": role,
        "content": content,
        "timestamp": ts.isoformat(timespec="seconds"),
        "date": ts.strftime("%Y-%m-%d"),
        "time": ts.strftime("%H:%M"),
        "agent": agent,
        "metadata": metadata or {},
    }

    init_db(db_path)
    with _connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO conversation_messages (
                id, session_id, channel, role, content,
                timestamp, date, time, agent, metadata_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                message["id"],
                message["session_id"],
                message["channel"],
                message["role"],
                message["content"],
                message["timestamp"],
                message["date"],
                message["time"],
                message["agent"],
                json.dumps(message["metadata"], ensure_ascii=False),
            ),
        )
    return message


def load_messages(
    *,
    limit: int = 50,
    channel: str | None = None,
    session_id: str | None = None,
    db_path: str = CONVERSATION_DB_FILE,
) -> list[dict[str, Any]]:
    init_db(db_path)
    clauses = []
    params: list[Any] = []
    if channel:
        clauses.append("channel = ?")
        params.append(channel)
    if session_id:
        clauses.append("session_id = ?")
        params.append(session_id)

    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    query = f"""
        SELECT *
        FROM conversation_messages
        {where}
        ORDER BY timestamp DESC, id DESC
        LIMIT ?
    """
    params.append(limit)

    with _connect(db_path) as conn:
        rows = conn.execute(query, params).fetchall()

    messages = [_row_to_message(row) for row in rows]
    messages.reverse()
    return messages


def load_recent_context(
    *,
    channel: str,
    global_limit: int = 12,
    channel_limit: int = 10,
    total_limit: int = 20,
    db_path: str = CONVERSATION_DB_FILE,
) -> list[dict[str, Any]]:
    """
    Returns a small mixed context window.

    It includes recent messages from all channels plus extra recent messages from
    the current channel, then de-duplicates and returns them chronologically.
    """
    mixed = load_messages(limit=global_limit, db_path=db_path)
    current_channel = load_messages(limit=channel_limit, channel=channel, db_path=db_path)

    by_id = {message["id"]: message for message in mixed}
    by_id.update({message["id"]: message for message in current_channel})

    messages = sorted(
        by_id.values(),
        key=lambda message: (message["timestamp"], message["id"]),
    )
    if total_limit and len(messages) > total_limit:
        messages = messages[-total_limit:]
    return messages


def _row_to_message(row: sqlite3.Row) -> dict[str, Any]:
    metadata_raw = row["metadata_json"] or "{}"
    try:
        metadata = json.loads(metadata_raw)
    except json.JSONDecodeError:
        metadata = {}

    return {
        "id": row["id"],
        "session_id": row["session_id"],
        "channel": row["channel"],
        "role": row["role"],
        "content": row["content"],
        "timestamp": row["timestamp"],
        "date": row["date"],
        "time": row["time"],
        "agent": row["agent"],
        "metadata": metadata,
    }
