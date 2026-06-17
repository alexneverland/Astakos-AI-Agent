import sqlite3
from datetime import datetime

from memory.routine_db import get_connection


def ensure_runtime_state_table() -> None:
    conn = get_connection(write=True)
    cursor = conn.cursor()

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS runtime_state (
            key TEXT PRIMARY KEY,
            value TEXT,
            updated_at TEXT
        )
        """
    )

    conn.commit()
    conn.close()


def set_runtime_state(key: str, value: str | None) -> None:
    conn = get_connection(write=True)
    cursor = conn.cursor()

    cursor.execute(
        """
        INSERT INTO runtime_state (key, value, updated_at)
        VALUES (?, ?, ?)
        ON CONFLICT(key) DO UPDATE SET
            value=excluded.value,
            updated_at=excluded.updated_at
        """,
        (
            key,
            value,
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        ),
    )

    conn.commit()
    conn.close()


def get_runtime_state(key: str, default=None):
    conn = get_connection()
    cursor = conn.cursor()

    row = cursor.execute(
        "SELECT value FROM runtime_state WHERE key = ?",
        (key,),
    ).fetchone()

    conn.close()

    if not row:
        return default
    return row[0]


def get_all_runtime_state() -> dict:
    conn = get_connection()
    cursor = conn.cursor()

    rows = cursor.execute(
        "SELECT key, value, updated_at FROM runtime_state ORDER BY key"
    ).fetchall()

    conn.close()

    return {
        key: {
            "value": value,
            "updated_at": updated_at,
        }
        for key, value, updated_at in rows
    }


def set_current_shift(value: str | None) -> None:
    allowed = {None, "morning", "afternoon", "night"}
    if value not in allowed:
        raise ValueError(f"Invalid current_shift: {value}")
    set_runtime_state("current_shift", value)


def get_current_shift() -> str | None:
    value = get_runtime_state("current_shift", default=None)
    if value in {"morning", "afternoon", "night"}:
        return value
    return None


ensure_runtime_state_table()
