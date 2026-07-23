"""Durable GPS anchors for reminders that fire after leaving the current place."""

import json
import sqlite3
import time
from typing import Any, Callable

import config


LEAVE_CURRENT_LOCATION = "leave_current_location"
LEAVE_CURRENT_LOCATION_RADIUS_M = 300.0
FRESH_LOCATION_MAX_AGE_SECONDS = 10 * 60


def _ensure_location_reminder_anchors_table(conn: sqlite3.Connection) -> None:
    """Create the companion table without modifying the legacy reminders schema."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS location_reminder_anchors (
            reminder_id INTEGER PRIMARY KEY,
            anchor_lat REAL NOT NULL,
            anchor_lon REAL NOT NULL,
            exit_radius_m REAL NOT NULL,
            created_at REAL NOT NULL
        )
        """
    )


def get_fresh_current_location(*, now_ts: float | None = None) -> tuple[float, float] | None:
    """Return the most recent live GPS point only when it is still trustworthy."""
    now_ts = time.time() if now_ts is None else now_ts
    try:
        with open(config.GPS_STORAGE_FILE, "r", encoding="utf-8") as location_file:
            data: dict[str, Any] = json.load(location_file)
        lat = float(data["lat"])
        lon = float(data["lon"])
        timestamp = float(data["timestamp"])
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None

    age_seconds = now_ts - timestamp
    if not 0 <= age_seconds <= FRESH_LOCATION_MAX_AGE_SECONDS:
        return None
    return lat, lon


def save_leave_current_location_anchor(
    conn: sqlite3.Connection,
    *,
    reminder_id: int,
    anchor_lat: float,
    anchor_lon: float,
    now_ts: float | None = None,
) -> None:
    """Attach the current GPS point to an already-created leave-place reminder."""
    _ensure_location_reminder_anchors_table(conn)
    conn.execute(
        """
        INSERT OR REPLACE INTO location_reminder_anchors
            (reminder_id, anchor_lat, anchor_lon, exit_radius_m, created_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            reminder_id,
            anchor_lat,
            anchor_lon,
            LEAVE_CURRENT_LOCATION_RADIUS_M,
            time.time() if now_ts is None else now_ts,
        ),
    )


def find_departed_current_location_reminders(
    conn: sqlite3.Connection,
    *,
    lat: float,
    lon: float,
    distance_meters: Callable[[float, float, float, float], float],
) -> list[tuple[int, str]]:
    """Return pending leave-place reminders whose anchor has been exited."""
    _ensure_location_reminder_anchors_table(conn)
    rows = conn.execute(
        """
        SELECT reminders.id, reminders.task, anchors.anchor_lat, anchors.anchor_lon,
               anchors.exit_radius_m
        FROM reminders
        JOIN location_reminder_anchors AS anchors ON anchors.reminder_id = reminders.id
        WHERE reminders.status = 'pending' AND reminders.time = ?
        """,
        (f"loc:{LEAVE_CURRENT_LOCATION}",),
    ).fetchall()
    return [
        (reminder_id, task)
        for reminder_id, task, anchor_lat, anchor_lon, radius_m in rows
        if distance_meters(anchor_lat, anchor_lon, lat, lon) > radius_m
    ]


def complete_location_reminder(conn: sqlite3.Connection, reminder_id: int) -> None:
    """Complete a reminder and remove its anchor in the same transaction."""
    _ensure_location_reminder_anchors_table(conn)
    conn.execute("UPDATE reminders SET status='done' WHERE id=?", (reminder_id,))
    conn.execute("DELETE FROM location_reminder_anchors WHERE reminder_id=?", (reminder_id,))
