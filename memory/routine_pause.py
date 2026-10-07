"""Canonical permanent-pause mutation on a caller-owned transaction."""
from __future__ import annotations

import sqlite3


def apply_indefinite_pause(
    connection: sqlite3.Connection, routine_id: int, *, reason: str = "user_requested",
) -> None:
    """Preserve existing pause semantics without committing or opening storage.

    Lifecycle state remains active while paused_indefinitely blocks dispatch.
    Both the legacy memory API and dated feedback call this same mutation.
    The caller owns transaction rollback, error translation and telemetry.
    """
    connection.execute("""UPDATE routines
        SET paused_until=NULL, paused_indefinitely=1, pause_reason=?,
            unanswered_reminder_streak=0, state='active', is_active=1
        WHERE id=?""", (reason, routine_id))
