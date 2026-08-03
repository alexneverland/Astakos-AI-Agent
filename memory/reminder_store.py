"""Schema initialization for persisted local reminders."""

from __future__ import annotations

import sqlite3

from config import STATE_DB


def init_reminder_store(db_path: str = STATE_DB) -> None:
    """Create and migrate reminder storage before reminder tools are available.

    An immediate transaction serializes startup in the Web and Telegram
    processes, preventing concurrent legacy-schema migrations.
    """
    conn = sqlite3.connect(db_path, timeout=5)
    try:
        conn.execute("PRAGMA busy_timeout=5000")
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS reminders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task TEXT,
                time TEXT,
                status TEXT DEFAULT 'pending',
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                external_content_sources_json TEXT NOT NULL DEFAULT '[]'
            )
            """
        )
        columns = {row[1] for row in conn.execute("PRAGMA table_info(reminders)")}
        if "external_content_sources_json" not in columns:
            conn.execute(
                "ALTER TABLE reminders "
                "ADD COLUMN external_content_sources_json TEXT NOT NULL DEFAULT '[]'"
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
