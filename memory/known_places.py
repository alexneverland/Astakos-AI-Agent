"""Canonical local geometry for configured and owner-saved named places."""

from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any

from filelock import FileLock

from core.location_result import finite_number
from services.location_update import _haversine_distance_meters

CURRENT_POINT_MAX_AGE_SECONDS = 600
MAX_PLACES = 100


def _store_path() -> Path:
    """Resolve private runtime state without adding a configuration setting."""
    import config
    return Path(config.BASE_DIR) / "known_places.json"


def _valid_geometry(place: dict[str, Any]) -> bool:
    """Validate exact coordinate/radius bounds without interpreting a name."""
    return (all(finite_number(place.get(k)) for k in ("lat", "lon", "radius_m"))
            and -90 <= place["lat"] <= 90 and -180 <= place["lon"] <= 180
            and 0 < place["radius_m"] <= 10000)


def _load_custom(path: Path) -> list[dict[str, Any]]:
    """Fail closed on a damaged store instead of replacing user state."""
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    if (not isinstance(data, dict) or set(data) != {"schema", "places"}
            or data["schema"] != "astakos_known_places_v1"
            or not isinstance(data["places"], list) or len(data["places"]) > MAX_PLACES):
        raise ValueError("invalid_place_store")
    names = set()
    for p in data["places"]:
        if (not isinstance(p, dict) or set(p) != {"name", "lat", "lon", "radius_m", "observed_at"}
                or not isinstance(p["name"], str) or not 1 <= len(p["name"].strip()) <= 120
                or p["name"].casefold() in names | {"home", "work"}
                or not _valid_geometry(p) or not finite_number(p["observed_at"])
                or p["observed_at"] <= 0):
            raise ValueError("invalid_place_store")
        names.add(p["name"].casefold())
    return data["places"]


def _configured_places() -> list[dict[str, Any]]:
    """Project the existing home/work geometry without copying or changing it."""
    import config
    places = []
    for name, coords, radius in (("home", config.HOME_COORDS, config.HOME_RADIUS_M),
                                 ("work", config.WORK_COORDS, config.WORK_RADIUS_M)):
        if not isinstance(coords, (list, tuple)) or len(coords) != 2:
            continue
        place = dict(name=name, lat=coords[0], lon=coords[1], radius_m=radius,
                     source="configured")
        if _valid_geometry(place) and tuple(coords) != (0, 0):
            places.append(place)
    return places


def list_known_places() -> list[dict[str, Any]]:
    """Read configured and saved locations through one registry."""
    return _configured_places() + [dict(p, source="owner_saved") for p in _load_custom(_store_path())]


def read_fresh_point() -> dict[str, float] | None:
    """Read a fresh canonical owner fix; never use an assistant's coordinates."""
    import config
    try:
        point = json.loads(Path(config.GPS_STORAGE_FILE).read_text(encoding="utf-8"))
        if not isinstance(point, dict):
            return None
        lat, lon, stamp = (point.get(k) for k in ("lat", "lon", "timestamp"))
        if (not all(finite_number(v) for v in (lat, lon, stamp))
                or not -90 <= lat <= 90 or not -180 <= lon <= 180 or stamp <= 0
                or not 0 <= time.time()-stamp <= CURRENT_POINT_MAX_AGE_SECONDS):
            return None
        return dict(lat=lat, lon=lon, timestamp=stamp)
    except (OSError, ValueError, TypeError):
        return None


def save_current_place(name: str, radius_m: float = 100) -> dict[str, Any] | None:
    """Atomically persist the fresh GPS snapshot and return the confirmed record."""
    if (not isinstance(name, str) or not 1 <= len(name.strip()) <= 120
            or not all(ch.isprintable() for ch in name)
            or name.strip().casefold() in {"home", "work"}
            or not finite_number(radius_m) or not 25 <= radius_m <= 2000):
        raise ValueError("invalid_place_request")
    point = read_fresh_point()
    if point is None:
        return None
    name = name.strip()
    place = dict(name=name, lat=point["lat"], lon=point["lon"], radius_m=radius_m,
                 observed_at=point["timestamp"])
    path = _store_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with FileLock(str(path) + ".lock", timeout=5):
        places = _load_custom(path)
        places = [p for p in places if p["name"].casefold() != name.casefold()]
        if len(places) >= MAX_PLACES:
            raise ValueError("place_limit")
        places.append(place)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                             prefix=".known-places-", suffix=".tmp", delete=False) as stream:
                temporary = Path(stream.name)
                json.dump(dict(schema="astakos_known_places_v1", places=places), stream,
                          ensure_ascii=False, allow_nan=False)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
    return place


def locate_known_places() -> dict[str, Any]:
    """Match fresh owner GPS geometrically; infer no work or family flags."""
    point = read_fresh_point()
    if point is None:
        return dict(status="unavailable", reason="no_fresh_gps")
    matches = []
    for place in list_known_places():
        distance = _haversine_distance_meters(place["lat"], place["lon"], point["lat"], point["lon"])
        if distance <= place["radius_m"]:
            matches.append(dict(place, distance_m=round(distance, 1)))
    matches.sort(key=lambda place: place["distance_m"])
    return dict(status="located", point=point, matches=matches)
