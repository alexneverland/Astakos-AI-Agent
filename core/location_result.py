"""Closed, instruction-free contract for locally projected GPS results."""

import json
import math
from typing import Any

LOCATION_SCHEMA = "astakos_location_v1"
LOCATION_MAX_AGE_SECONDS = 86400


def finite_number(value: Any) -> bool:
    """Reject booleans, strings and non-finite values at the trust boundary."""
    try:
        return type(value) in (int, float) and math.isfinite(value)
    except OverflowError:
        return False


def location_payload(status: str, lat: float | None = None,
                     lon: float | None = None, timestamp: float | None = None,
                     is_home: bool | None = None) -> str:
    """Serialize only the closed location fields, never source text."""
    return json.dumps(dict(schema=LOCATION_SCHEMA, status=status, lat=lat,
                           lon=lon, timestamp=timestamp, is_home=is_home), allow_nan=False)


def is_validated_location_result(content: str) -> bool:
    """Recognize instruction-free data, not arbitrary JSON or GPS tool errors."""
    try:
        data = json.loads(content)
    except (TypeError, ValueError):
        return False
    if not isinstance(data, dict) or set(data) != {
        "schema", "status", "lat", "lon", "timestamp", "is_home"
    }:
        return False
    if data["schema"] != LOCATION_SCHEMA:
        return False
    status = data["status"]
    if status in ("missing", "invalid"):
        return all(data[key] is None for key in ("lat", "lon", "timestamp", "is_home"))
    if status not in ("current", "stale"):
        return False
    if not all(finite_number(data[key]) for key in ("lat", "lon", "timestamp")):
        return False
    if not (-90 <= data["lat"] <= 90 and -180 <= data["lon"] <= 180 and data["timestamp"] > 0):
        return False
    return data["is_home"] is None or (status == "current" and type(data["is_home"]) is bool)
