"""
Shared conversation history store for all Astakos channels.

SQLite is used instead of JSON so web and Telegram processes can append safely
without clobbering each other's writes.
"""

from __future__ import annotations

from core.i18n import t
import json
import os
import re
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from datetime import datetime
from typing import Any

from config import CONVERSATION_DB_FILE

LEGACY_FALLBACK_DATE = "1970-01-01"

# [DEDUP GUARD]: In-memory set — prevents rapid double-writes for the same item
# (channel, role, content) within DEDUP_TTL_SECONDS seconds.
_dedup_lock = threading.Lock()
_dedup_recent: dict[tuple, float] = {}  # key → last_write_epoch
DEDUP_TTL_SECONDS = 5.0


def _dedup_key(
    channel: str,
    role: str,
    content: str,
    metadata: dict[str, Any] | None = None,
    db_path: str = CONVERSATION_DB_FILE,
) -> tuple:
    """Build a rapid-write deduplication key without discarding message provenance."""
    metadata_key = json.dumps(
        metadata or {},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return (os.path.abspath(db_path), channel, role, content[:200], metadata_key)


def _is_recent_duplicate(key: tuple) -> bool:
    """True if the same (channel, role, content[:200]) was written less than DEDUP_TTL_SECONDS ago."""
    now = time.monotonic()
    with _dedup_lock:
        # Clean up old records
        expired = [k for k, t in _dedup_recent.items() if now - t > DEDUP_TTL_SECONDS * 10]
        for k in expired:
            del _dedup_recent[k]
        last = _dedup_recent.get(key)
        if last is not None and (now - last) < DEDUP_TTL_SECONDS:
            return True
        _dedup_recent[key] = now
        return False
LEGACY_UUID_NAMESPACE = uuid.uuid5(uuid.NAMESPACE_URL, "astakos:legacy-conversation-history")


def _connect(db_path: str = CONVERSATION_DB_FILE) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


@contextmanager
def _conn(db_path: str = CONVERSATION_DB_FILE):
    c = _connect(db_path)
    try:
        with c:
            yield c
    finally:
        c.close()


def init_db(db_path: str = CONVERSATION_DB_FILE) -> None:
    with _conn(db_path) as conn:
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
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS session_exchanges (
                id TEXT PRIMARY KEY,
                timestamp TEXT NOT NULL,
                date TEXT NOT NULL,
                time TEXT NOT NULL,
                channel TEXT NOT NULL,
                agent TEXT NOT NULL,
                user_text TEXT NOT NULL,
                ai_text TEXT NOT NULL,
                summarized_at TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_session_exchanges_unsummarized
            ON session_exchanges(summarized_at, timestamp)
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_session_exchanges_channel_time
            ON session_exchanges(channel, timestamp)
            """
        )


def default_session_id(ts: datetime | None = None) -> str:
    current = ts or datetime.now()
    return current.strftime("%Y-%m-%d")



# ── Code-session content truncation ─────────────────────────────
# Assistant messages that contain diffs/terminal output/grep results
# saved truncated: only the first summary paragraph.
# This way, they do not pollute load_recent_context and temporal search.
_CODE_MARKERS = (
    "```diff",
    "terminal output",
    "💻 terminal",
    "grep_project_files",
    t("prompts.ext_str_230"),
    "read_project_file",
    "edit_project_file",
    "▶ ",   # grep match marker
    "+++ b/",
    "--- a/",
)
_MAX_ASSISTANT_CONTENT = 600  # chars — above this + code marker → truncate


def _truncate_code_content(role: str, text: str) -> str:
    """
    If the message is from the assistant and contains code session markers,
    we keep only the first non-empty paragraph (summary line) + marker.
    """
    if role not in ("assistant", "ai"):
        return text
    if len(text) <= _MAX_ASSISTANT_CONTENT:
        return text
    low = text.lower()
    if not any(m in low for m in _CODE_MARKERS):
        return text

    # Keep up to the first ``` block or up to 400 chars_
    cut = text.find("```")
    if cut == -1:
        # Without code block: keep the first paragraphof
        cut = text.find("\n\n")
    if cut == -1 or cut > 400:
        cut = 400
    truncated = text[:cut].rstrip()
    return truncated + t("prompts.ext_code_session_content")


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
        "content": _truncate_code_content(role, content),
        "timestamp": ts.isoformat(timespec="seconds"),
        "date": ts.strftime("%Y-%m-%d"),
        "time": ts.strftime("%H:%M"),
        "agent": agent,
        "metadata": metadata or {},
    }

    # [DEDUP GUARD]: Prevents rapid double-writes
    _key = _dedup_key(channel, role, content, message["metadata"], db_path)
    if _is_recent_duplicate(_key):
        print(f"\033[93m[ConvHistory]: Dedup skip — {channel}/{role} '{content[:40]}'[0m")
        return message

    init_db(db_path)
    with _conn(db_path) as conn:
        cursor = conn.execute(
            """
            INSERT OR IGNORE INTO conversation_messages (
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
        if cursor.rowcount == 1:
            message["rowid"] = cursor.lastrowid
    return message


def import_legacy_message(
    *,
    entry: dict[str, Any],
    channel: str,
    source: str,
    legacy_index: int,
    fallback_date: str = LEGACY_FALLBACK_DATE,
    db_path: str = CONVERSATION_DB_FILE,
) -> dict[str, Any]:
    content = str(entry.get("content", "")).strip()
    if not content:
        return {"inserted": False, "skipped": True, "reason": "empty_content"}

    original_role = str(entry.get("role", "")).strip()
    role = _normalize_legacy_role(original_role)
    ts, date_missing = _parse_legacy_timestamp(entry, fallback_date=fallback_date)
    metadata = {
        "legacy_source": source,
        "legacy_index": legacy_index,
        "legacy_original_role": original_role,
        "legacy_date_missing": date_missing,
    }
    message_id = _legacy_message_id(
        source=source,
        legacy_index=legacy_index,
        channel=channel,
        role=role,
        content=content,
        timestamp=ts,
    )
    message = {
        "id": message_id,
        "session_id": default_session_id(ts),
        "channel": channel,
        "role": role,
        "content": content,
        "timestamp": ts.isoformat(timespec="seconds"),
        "date": ts.strftime("%Y-%m-%d"),
        "time": ts.strftime("%H:%M"),
        "agent": None,
        "metadata": metadata,
    }

    init_db(db_path)
    with _conn(db_path) as conn:
        cursor = conn.execute(
            """
            INSERT OR IGNORE INTO conversation_messages (
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
    return {"inserted": cursor.rowcount == 1, "skipped": cursor.rowcount == 0, "message": message}


def backfill_legacy_history(
    history: list[dict[str, Any]],
    *,
    channel: str,
    source: str,
    fallback_date: str = LEGACY_FALLBACK_DATE,
    db_path: str = CONVERSATION_DB_FILE,
) -> dict[str, int]:
    stats = {"total": 0, "inserted": 0, "skipped": 0, "empty": 0}
    for index, entry in enumerate(history):
        stats["total"] += 1
        if not isinstance(entry, dict):
            stats["skipped"] += 1
            continue
        result = import_legacy_message(
            entry=entry,
            channel=channel,
            source=source,
            legacy_index=index,
            fallback_date=fallback_date,
            db_path=db_path,
        )
        if result.get("reason") == "empty_content":
            stats["empty"] += 1
        elif result["inserted"]:
            stats["inserted"] += 1
        else:
            stats["skipped"] += 1
    return stats


def append_exchange(
    *,
    user_text: str,
    ai_text: str,
    agent: str,
    channel: str,
    timestamp: datetime | None = None,
    db_path: str = CONVERSATION_DB_FILE,
) -> dict[str, Any]:
    ts = timestamp or datetime.now()
    exchange = {
        "id": str(uuid.uuid4()),
        "timestamp": ts.isoformat(timespec="seconds"),
        "date": ts.strftime("%Y-%m-%d"),
        "time": ts.strftime("%H:%M"),
        "channel": channel,
        "agent": agent,
        "user": user_text,
        "ai": ai_text,
        "summarized_at": None,
    }

    init_db(db_path)
    with _conn(db_path) as conn:
        conn.execute(
            """
            INSERT INTO session_exchanges (
                id, timestamp, date, time, channel, agent,
                user_text, ai_text, summarized_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                exchange["id"],
                exchange["timestamp"],
                exchange["date"],
                exchange["time"],
                exchange["channel"],
                exchange["agent"],
                exchange["user"],
                exchange["ai"],
                exchange["summarized_at"],
            ),
        )
    return exchange


def load_unsummarized_exchanges(
    *,
    limit: int = 200,
    db_path: str = CONVERSATION_DB_FILE,
) -> list[dict[str, Any]]:
    init_db(db_path)
    with _conn(db_path) as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM session_exchanges
            WHERE summarized_at IS NULL
            ORDER BY timestamp ASC, id ASC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()

    return [_row_to_exchange(row) for row in rows]


def mark_exchanges_summarized(
    exchange_ids: list[str],
    *,
    timestamp: datetime | None = None,
    db_path: str = CONVERSATION_DB_FILE,
) -> None:
    if not exchange_ids:
        return
    summarized_at = (timestamp or datetime.now()).isoformat(timespec="seconds")
    init_db(db_path)
    placeholders = ",".join("?" for _ in exchange_ids)
    with _conn(db_path) as conn:
        conn.execute(
            f"""
            UPDATE session_exchanges
            SET summarized_at = ?
            WHERE id IN ({placeholders})
            """,
            [summarized_at, *exchange_ids],
        )


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
        SELECT rowid, *
        FROM conversation_messages
        {where}
        ORDER BY timestamp DESC, rowid DESC
        LIMIT ?
    """
    params.append(limit)

    with _conn(db_path) as conn:
        rows = conn.execute(query, params).fetchall()

    messages = [_row_to_message(row) for row in rows]
    for msg, row in zip(messages, rows):
        msg["rowid"] = row["rowid"] if hasattr(row, "keys") else row[0]
    messages.reverse()
    return messages


def load_messages_since(
    *,
    since_date: str,
    roles: list[str] | tuple[str, ...] | None = None,
    channel: str | None = None,
    limit: int | None = None,
    db_path: str = CONVERSATION_DB_FILE,
) -> list[dict[str, Any]]:
    init_db(db_path)
    clauses = ["date >= ?"]
    params: list[Any] = [since_date]
    if roles:
        placeholders = ",".join("?" for _ in roles)
        clauses.append(f"role IN ({placeholders})")
        params.extend(roles)
    if channel:
        clauses.append("channel = ?")
        params.append(channel)

    where_clause = " AND ".join(clauses)

    with _conn(db_path) as conn:
        if limit is not None:
            # We get the MOST RECENT `limit` messages within the window
            # (ORDER BY ... DESC + LIMIT) and then we resort them
            # chronologically (ASC) in the final result._
            #
            # Before, the LIMIT was applied to already ASC sorted data:
            # when the window (since_date..today) contained more_of_thought
            # messages from the `limit` (e.g. 1968 messages in 30 days while
            # temporal_history_for_query calls with limit=1500), the query
            # return the 1500 OLDEST -- cutting off the entire oldest
            # recent week out of the result. Thus the SQL/temporal
            # memory layer was essentially blind to "what we said"
            # recently", even though the question asked for exactly that.
            rows = conn.execute(
                f"""
                SELECT * FROM (
                    SELECT rowid, *
                    FROM conversation_messages
                    WHERE {where_clause}
                    ORDER BY timestamp DESC, rowid DESC
                    LIMIT ?
                )
                ORDER BY timestamp ASC, rowid ASC
                """,
                params + [limit],
            ).fetchall()
        else:
            rows = conn.execute(
                f"""
                SELECT rowid, *
                FROM conversation_messages
                WHERE {where_clause}
                ORDER BY timestamp ASC, rowid ASC
                """,
                params,
            ).fetchall()

    msgs = [_row_to_message(row) for row in rows]
    for msg, row in zip(msgs, rows):
        msg["rowid"] = row["rowid"] if hasattr(row, "keys") else row[0]
    return msgs


def load_messages_after_rowid(
    *,
    after_rowid: int,
    channel: str | None = None,
    limit: int = 50,
    db_path: str = CONVERSATION_DB_FILE,
) -> list[dict[str, Any]]:
    """
    Returns messages with rowid > after_rowid, sorted chronologically.
    The rowid is the implicit SQLite integer key — monotonically increasing.
    Used for polling by the Web UI to retrieve only new messages.
    """
    init_db(db_path)
    clauses = ["rowid > ?"]
    params: list[Any] = [after_rowid]
    if channel:
        clauses.append("channel = ?")
        params.append(channel)
    params.append(limit)
    with _conn(db_path) as conn:
        rows = conn.execute(
            f"""
            SELECT rowid, * FROM conversation_messages
            WHERE {' AND '.join(clauses)}
            ORDER BY rowid ASC
            LIMIT ?
            """,
            params,
        ).fetchall()
    msgs = [_row_to_message(row) for row in rows]
    # Add rowid to the dict for the frontend to use
    for msg, row in zip(msgs, rows):
        msg["rowid"] = row["rowid"] if hasattr(row, "keys") else row[0]
    return msgs


def get_max_rowid(
    *,
    db_path: str = CONVERSATION_DB_FILE,
) -> int:
    """Returns the maximum rowid in the conversation_messages table (0 if it is empty)."""
    init_db(db_path)
    with _conn(db_path) as conn:
        row = conn.execute("SELECT MAX(rowid) FROM conversation_messages").fetchone()
    val = row[0] if row else None
    return int(val) if val is not None else 0


def load_last_user_activity(
    *,
    channel: str | None = None,
    db_path: str = CONVERSATION_DB_FILE,
) -> dict[str, Any] | None:
    init_db(db_path)
    params: list[Any] = []
    channel_clause = ""
    if channel:
        channel_clause = "AND channel = ?"
        params.append(channel)

    with _conn(db_path) as conn:
        row = conn.execute(
            f"""
            SELECT *
            FROM conversation_messages
            WHERE role IN ('user', 'human', 'Human')
            {channel_clause}
            ORDER BY timestamp DESC, rowid DESC
            LIMIT 1
            """,
            params,
        ).fetchone()

    return _row_to_message(row) if row else None


def seconds_since_last_user_activity(
    *,
    channel: str | None = None,
    now: datetime | None = None,
    db_path: str = CONVERSATION_DB_FILE,
) -> float | None:
    last = load_last_user_activity(channel=channel, db_path=db_path)
    if not last:
        return None
    try:
        last_ts = datetime.fromisoformat(last["timestamp"])
    except (TypeError, ValueError):
        return None
    return ((now or datetime.now()) - last_ts).total_seconds()


def load_conversation_stats(
    *,
    db_path: str = CONVERSATION_DB_FILE,
) -> dict[str, Any]:
    init_db(db_path)
    with _conn(db_path) as conn:
        messages_total = conn.execute(
            "SELECT COUNT(*) FROM conversation_messages"
        ).fetchone()[0]
        messages_by_channel = dict(conn.execute(
            """
            SELECT channel, COUNT(*)
            FROM conversation_messages
            GROUP BY channel
            """
        ).fetchall())
        messages_by_role = dict(conn.execute(
            """
            SELECT role, COUNT(*)
            FROM conversation_messages
            GROUP BY role
            """
        ).fetchall())
        session_exchanges_total = conn.execute(
            "SELECT COUNT(*) FROM session_exchanges"
        ).fetchone()[0]
        unsummarized_exchanges = conn.execute(
            """
            SELECT COUNT(*)
            FROM session_exchanges
            WHERE summarized_at IS NULL
            """
        ).fetchone()[0]
        unsummarized_by_channel = dict(conn.execute(
            """
            SELECT channel, COUNT(*)
            FROM session_exchanges
            WHERE summarized_at IS NULL
            GROUP BY channel
            """
        ).fetchall())

    return {
        "db_path": db_path,
        "messages_total": messages_total,
        "messages_by_channel": messages_by_channel,
        "messages_by_role": messages_by_role,
        "session_exchanges_total": session_exchanges_total,
        "unsummarized_exchanges": unsummarized_exchanges,
        "unsummarized_by_channel": unsummarized_by_channel,
    }


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
        # SQLite rowid preserves insertion order for same-second messages;
        # non-SQLite entries retain their stable legacy id ordering.
        key=lambda message: (message["timestamp"], message.get("rowid", message["id"])),
    )
    if total_limit and len(messages) > total_limit:
        messages = messages[-total_limit:]
    return messages


def purge_history_by_substrings(
    substrings: list[str] | tuple[str, ...],
    *,
    db_path: str = CONVERSATION_DB_FILE,
) -> dict[str, int]:
    """Delete stale history rows that contain any of the given substrings."""
    patterns = [str(item or "").strip() for item in substrings if str(item or "").strip()]
    if not patterns:
        return {"conversation_messages": 0, "session_exchanges": 0}

    init_db(db_path)
    with _conn(db_path) as conn:
        deleted_messages = 0
        deleted_exchanges = 0
        for pattern in patterns:
            like = f"%{pattern}%"
            cursor = conn.execute(
                """
                DELETE FROM conversation_messages
                WHERE content LIKE ?
                """,
                (like,),
            )
            deleted_messages += cursor.rowcount or 0

            cursor = conn.execute(
                """
                DELETE FROM session_exchanges
                WHERE user_text LIKE ? OR ai_text LIKE ?
                """,
                (like, like),
            )
            deleted_exchanges += cursor.rowcount or 0

    return {
        "conversation_messages": deleted_messages,
        "session_exchanges": deleted_exchanges,
    }


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


def _normalize_legacy_role(role: str) -> str:
    normalized = role.strip().lower()
    if normalized in ("human", "user"):
        return "user"
    if normalized in ("ai", "assistant", "bot"):
        return "assistant"
    return normalized or "user"


def _parse_legacy_timestamp(entry: dict[str, Any], *, fallback_date: str) -> tuple[datetime, bool]:
    raw_date = str(entry.get("date", "") or "").strip()
    raw_time = str(entry.get("time", "") or "").strip()
    content = str(entry.get("content", "") or "")

    date_missing = not _is_valid_date(raw_date)
    date_part = raw_date if not date_missing else fallback_date

    if not raw_time:
        match = re.match(r"^\[(\d{1,2}:\d{2})(?::\d{2})?\]", content)
        if match:
            raw_time = match.group(1)
    time_part = _normalize_time(raw_time)

    try:
        return datetime.fromisoformat(f"{date_part}T{time_part}"), date_missing
    except ValueError:
        return datetime.fromisoformat(f"{fallback_date}T00:00:00"), True


def _is_valid_date(value: str) -> bool:
    try:
        datetime.strptime(value, "%Y-%m-%d")
        return True
    except ValueError:
        return False


def _normalize_time(value: str) -> str:
    match = re.match(r"^(\d{1,2}):(\d{2})(?::(\d{2}))?$", value.strip())
    if not match:
        return "00:00:00"
    hour = max(0, min(23, int(match.group(1))))
    minute = max(0, min(59, int(match.group(2))))
    second = max(0, min(59, int(match.group(3) or 0)))
    return f"{hour:02d}:{minute:02d}:{second:02d}"


def _legacy_message_id(
    *,
    source: str,
    legacy_index: int,
    channel: str,
    role: str,
    content: str,
    timestamp: datetime,
) -> str:
    raw = "|".join([
        source,
        str(legacy_index),
        channel,
        role,
        timestamp.isoformat(timespec="seconds"),
        content,
    ])
    return str(uuid.uuid5(LEGACY_UUID_NAMESPACE, raw))


def _row_to_exchange(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "timestamp": row["timestamp"],
        "date": row["date"],
        "time": row["time"],
        "channel": row["channel"],
        "agent": row["agent"],
        "user": row["user_text"],
        "ai": row["ai_text"],
        "summarized_at": row["summarized_at"],
    }

def build_asset_context_text(channel: str, limit: int = 8) -> str:
    entries = load_recent_context(
        channel=channel,
        global_limit=limit,
        channel_limit=limit,
        total_limit=limit,
    )

    lines = []
    for entry in entries:
        content = str(entry.get("content") or "").strip()
        if not content:
            continue
        if content.startswith(("[USER_UPLOADED_FILE]", "[USER_UPLOADED_PHOTO]")):
            continue

        content = content[:700]
        if entry.get("role") not in {"user", "human", "Human"}:
            from core.untrusted_content import format_untrusted_persisted_content
            content = format_untrusted_persisted_content(
                content,
                entry.get("metadata"),
            )
        speaker = t("prompts.ext_str_437") if entry.get("role") == "user" else t("prompts.ext_str_350")
        lines.append(f"{speaker}: {content}")

    return "\n".join(lines[-limit:])

