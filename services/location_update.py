"""Shared validation and persistence for trusted location updates."""

from __future__ import annotations

import json
import math
import os
import tempfile
import time
from pathlib import Path


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
        return None
    from core.i18n import t

    return t("clients.telegram_bot.bot_msg_location", lat=latitude, lon=longitude)
