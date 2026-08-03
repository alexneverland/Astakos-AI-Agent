"""Schema initialization for persisted user-managed lists."""

from __future__ import annotations

import sqlite3

from config import STATE_DB


def init_list_store(db_path: str = STATE_DB) -> None:
    """Create and migrate the lists table before any agent tool can use it."""
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS lists (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                list_name TEXT,
                item TEXT,
                added_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                external_content_sources_json TEXT NOT NULL DEFAULT '[]'
            )
            """
        )
        columns = {row[1] for row in conn.execute("PRAGMA table_info(lists)")}
        if "external_content_sources_json" not in columns:
            conn.execute(
                "ALTER TABLE lists "
                "ADD COLUMN external_content_sources_json TEXT NOT NULL DEFAULT '[]'"
            )
        conn.commit()
    finally:
        conn.close()
