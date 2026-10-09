"""Bounded durable intake of authenticated owner location fixes."""
from __future__ import annotations

import json
import logging
import math
import os
import tempfile
import time
from pathlib import Path
from typing import Callable

from filelock import FileLock

MAX_AGE_SECONDS = 600
MAX_ACCURACY_METERS = 100
MAX_PENDING_POINTS = 100
logger = logging.getLogger(__name__)


def default_auth_file() -> Path:
    """Return the private opt-in verifier, separate from Web credentials."""
    from config import BASE_DIR
    return Path(BASE_DIR) / "credentials" / "owntracks-auth.json"


def parse_location(payload: dict, *, now_ts: float) -> dict | None:
    """Validate actual fixes; irrelevant, stale and ping reports are no-ops."""
    if payload.get("_type") != "location" or payload.get("t") == "p":
        return None
    values = [payload.get(name) for name in ("lat", "lon", "tst", "acc")]
    if any(type(value) not in (int, float) or not math.isfinite(value) for value in values):
        raise ValueError("Invalid location")
    lat, lon, timestamp, accuracy = values
    if (not -90 <= lat <= 90 or not -180 <= lon <= 180
            or type(timestamp) is not int or timestamp <= 0 or accuracy < 0):
        raise ValueError("Invalid location")
    if not 0 <= now_ts - timestamp <= MAX_AGE_SECONDS or accuracy > MAX_ACCURACY_METERS:
        return None
    return dict(zip(("lat", "lon", "tst", "acc"), values))


def write_private_json(path: Path, value: dict) -> None:
    """Commit private state with restrictive mode and atomic durable replacement."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: str | None = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix=".owntracks-", delete=False) as stream:
            temporary = stream.name
            os.chmod(temporary, 0o600)
            json.dump(value, stream, allow_nan=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            Path(temporary).unlink(missing_ok=True)


class OwnTracksStore:
    """Serialize a bounded queue and permanent monotonic timestamp watermark."""

    def __init__(self, path: Path | None = None) -> None:
        if path is None:
            from config import BASE_DIR
            path = Path(BASE_DIR) / "owntracks-pending.json"
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = FileLock(str(self.path) + ".lock", timeout=5)

    def _load(self) -> dict:
        """Read state; corruption fails closed rather than resetting deduplication."""
        if not self.path.exists():
            return {"watermark": 0, "pending": []}
        state = json.loads(self.path.read_text(encoding="utf-8"))
        if (not isinstance(state, dict) or type(state.get("watermark")) is not int
                or not isinstance(state.get("pending"), list)
                or len(state["pending"]) > MAX_PENDING_POINTS):
            raise ValueError("Invalid OwnTracks state")
        return state

    def pending(self) -> list[dict]:
        """Return a snapshot without claiming delivery or consuming points."""
        with self.lock:
            return self._load()["pending"]

    def enqueue(self, point: dict) -> bool:
        """Durably admit one newer minimal point, bounding storage under flooding."""
        with self.lock:
            state = self._load()
            if point["tst"] <= state["watermark"]:
                return False
            state["watermark"] = point["tst"]
            state["pending"].append({name: point[name] for name in ("lat", "lon", "tst", "acc")})
            state["pending"] = state["pending"][-MAX_PENDING_POINTS:]
            write_private_json(self.path, state)
            return True


def drain_owntracks(*, store: OwnTracksStore | None = None, channel: str | None = None,
                   send_reminder: Callable[[str], object] | None = None,
                   now_ts: float | None = None) -> None:
    """Consume fresh points only in the selected external worker, never the API."""
    if not default_auth_file().exists() and store is None:
        return
    from core.messaging_channel import resolve_external_channel
    from services.location_update import process_location_update
    from services.external_assistant_delivery import deliver_external_assistant_text

    channel = channel or resolve_external_channel()
    if send_reminder is None:
        def send_reminder(message: str) -> object:
            return deliver_external_assistant_text(message, agent="Reminder_Agent",
                                                   target_channel=channel)
    store = store or OwnTracksStore()
    with store.lock:
        state = store._load()
        # Claim before processing: an interrupted delivery must never be blindly
        # repeated. A failed reminder remains pending for the next actual fix.
        points = state["pending"]
        if not points:
            return
        state["pending"] = []
        write_private_json(store.path, state)
        for point in points:
            current_time = time.time() if now_ts is None else now_ts
            validated = parse_location({"_type": "location", **point}, now_ts=current_time)
            if validated is None:
                continue
            try:
                process_location_update(point["lat"], point["lon"], live_update=True,
                    source_channel=channel, send_reminder=send_reminder,
                    observed_at=point["tst"], now_ts=current_time)
            except Exception:
                logger.warning("OwnTracks point processing failed; pending reminders await a new fix")
