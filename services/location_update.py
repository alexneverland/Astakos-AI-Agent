"""Shared validation and persistence for trusted location updates."""

from __future__ import annotations

import json
import math
import os
import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import Callable


def parse_geo_uri(value: str) -> tuple[float, float] | None:
    """Parse a bounded RFC 5870 latitude/longitude pair."""
    raw = str(value or "").strip()
    if not raw.lower().startswith("geo:"):
        return None
    coordinates = raw[4:].split(";", 1)[0].split(",")
    if len(coordinates) < 2:
        return None
    try:
        latitude = float(coordinates[0])
        longitude = float(coordinates[1])
    except (TypeError, ValueError):
        return None
    if not math.isfinite(latitude) or not math.isfinite(longitude):
        return None
    if not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
        return None
    return latitude, longitude


def sync_live_location_out_of_home_state(latitude: float, longitude: float) -> None:
    """Update the routine home-context flag from a trusted live GPS point."""
    from config import HOME_COORDS, HOME_RADIUS_M
    from memory.routine_db import get_context_state, set_context_state

    try:
        home_lat, home_lon = float(HOME_COORDS[0]), float(HOME_COORDS[1])
        home_radius_m = float(HOME_RADIUS_M)
    except (IndexError, TypeError, ValueError):
        return
    if (home_lat, home_lon) == (0.0, 0.0) or home_radius_m <= 0:
        return

    earth_radius_m = 6_371_000
    lat_delta = math.radians(latitude - home_lat)
    lon_delta = math.radians(longitude - home_lon)
    arc = (
        math.sin(lat_delta / 2) ** 2
        + math.cos(math.radians(home_lat))
        * math.cos(math.radians(latitude))
        * math.sin(lon_delta / 2) ** 2
    )
    distance_m = 2 * earth_radius_m * math.asin(math.sqrt(arc))
    desired_value = "true" if distance_m > home_radius_m else "false"
    state = get_context_state("user_out_of_home") or {}
    current_value = str(state.get("value") or "").strip().lower()
    expires_at = str(state.get("expires_at") or "").strip()
    today = datetime.now().strftime("%Y-%m-%d")
    if current_value == desired_value and (not expires_at or expires_at >= today):
        return
    set_context_state("user_out_of_home", desired_value, expires_at=today)


def record_location_update(
    latitude: float,
    longitude: float,
    *,
    live_update: bool,
    storage_file: str | os.PathLike[str] | None = None,
    now_ts: float | None = None,
) -> str | None:
    """Persist one trusted GPS point atomically and acknowledge static pins."""
    if parse_geo_uri(f"geo:{latitude},{longitude}") is None:
        raise ValueError("Location coordinates are outside valid bounds")
    if storage_file is None:
        from config import GPS_STORAGE_FILE

        storage_file = GPS_STORAGE_FILE
    target = Path(storage_file)
    existing: dict = {}
    try:
        loaded = json.loads(target.read_text(encoding="utf-8"))
        if isinstance(loaded, dict):
            existing = loaded
    except (OSError, ValueError, json.JSONDecodeError):
        pass
    timestamp = time.time() if now_ts is None else float(now_ts)
    existing.update({"lat": latitude, "lon": longitude, "timestamp": timestamp})
    existing.setdefault("anchor_lat", latitude)
    existing.setdefault("anchor_lon", longitude)
    existing.setdefault("anchor_timestamp", timestamp)

    target.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=target.parent,
            prefix=f".{target.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            json.dump(existing, temporary, ensure_ascii=False)
            temporary_path = Path(temporary.name)
        os.replace(temporary_path, target)
        temporary_path = None
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)

    if live_update:
        sync_live_location_out_of_home_state(latitude, longitude)
        return None
    from core.i18n import t

    return t("clients.telegram_bot.bot_msg_location", lat=latitude, lon=longitude)


def process_location_update(
    latitude: float,
    longitude: float,
    *,
    live_update: bool,
    source_channel: str,
    send_reminder: Callable[[str], object],
    storage_file: str | os.PathLike[str] | None = None,
) -> str | None:
    """Persist a trusted point and deliver matching location reminders."""
    if source_channel not in {"telegram", "matrix"}:
        raise ValueError("Location source must be an active external channel")
    reply = record_location_update(
        latitude, longitude, live_update=live_update, storage_file=storage_file
    )
    dispatch_location_reminders(latitude, longitude, send_reminder=send_reminder)
    return reply


def dispatch_location_reminders(
    latitude: float,
    longitude: float,
    *,
    send_reminder: Callable[[str], object],
) -> None:
    """Deliver and complete location reminders through one shared path."""
    from config import HOME_COORDS, HOME_RADIUS_M, STATE_DB
    from core.i18n import t
    from memory.location_reminders import (
        find_triggered_location_reminders,
        finish_location_reminder,
    )

    for reminder_id, task, kind in find_triggered_location_reminders(
        db_path=STATE_DB,
        lat=latitude,
        lon=longitude,
        home_coords=(float(HOME_COORDS[0]), float(HOME_COORDS[1])),
        home_radius_m=float(HOME_RADIUS_M),
        distance_meters=_haversine_distance_meters,
    ):
        message = (
            f"📍 REMINDER (You reached home!): {task}"
            if kind == "home"
            else t("clients.telegram_bot.bot_msg_reminder_leave_current", task=task)
        )
        send_reminder(message)
        finish_location_reminder(db_path=STATE_DB, reminder_id=reminder_id)


def _haversine_distance_meters(
    lat1: float, lon1: float, lat2: float, lon2: float
) -> float:
    """Return the distance between two GPS points in metres."""
    radius_m = 6_371_000
    lat_delta = math.radians(lat2 - lat1)
    lon_delta = math.radians(lon2 - lon1)
    arc = (
        math.sin(lat_delta / 2) ** 2
        + math.cos(math.radians(lat1))
        * math.cos(math.radians(lat2))
        * math.sin(lon_delta / 2) ** 2
    )
    return 2 * radius_m * math.asin(math.sqrt(arc))
