"""Read-only evidence for future routine clarification, not dispatch defaults."""

from __future__ import annotations

import json
import math
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any

STORED_VALIDITY = timedelta(hours=2)
GPS_VALIDITY = timedelta(minutes=15)
VOLATILE_FLAGS = (
    "user_out_of_home", "family_at_home", "partner_with_user",
    "kid1_with_user", "kid1_with_partner",
)


@dataclass(frozen=True)
class ContextEvidence:
    """A bounded observation; persistence time is not a proven event time."""

    effective_value: bool | None = None
    stored_value: bool | None = None
    source: str = "none"
    recorded_at: datetime | None = None
    valid_until: datetime | None = None
    age_seconds: float | None = None
    status: str = "unknown"
    reason: str = "missing"


def _require_aware(now: datetime) -> None:
    """Require one explicit evaluation timezone rather than host-time guesses."""
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("Evaluation time must have a timezone")


def _recorded_time(raw: Any, now: datetime) -> datetime | None:
    """Interpret legacy local times, rejecting ambiguous/nonexistent instants."""
    try:
        if not isinstance(raw, str) or len(raw) <= 10:
            return None
        parsed = datetime.fromisoformat(raw)
        if parsed.tzinfo is not None:
            return parsed.astimezone(now.tzinfo)
        candidates = []
        for fold in (0, 1):
            local = parsed.replace(tzinfo=now.tzinfo, fold=fold)
            restored = local.astimezone(timezone.utc).astimezone(now.tzinfo)
            if restored.replace(tzinfo=None) == parsed:
                candidates.append(local)
        if not candidates or len({item.timestamp() for item in candidates}) != 1:
            return None
        return candidates[0]
    except (ValueError, OverflowError, OSError):
        return None


def evaluate_stored_evidence(
    record: Mapping[str, Any] | None, *, now: datetime,
) -> ContextEvidence:
    """Evaluate a volatile boolean without refreshing or changing its record."""
    _require_aware(now)
    if record is None:
        return ContextEvidence()
    if not isinstance(record, Mapping):
        return ContextEvidence(source="stored_context", reason="invalid_value")
    raw = record.get("value")
    value = raw if isinstance(raw, bool) else None
    if isinstance(raw, str):
        value = {"true": True, "false": False}.get(raw.strip().lower())
    details: dict[str, Any] = {"source": "stored_context", "stored_value": value}
    if value is None:
        return ContextEvidence(**details, reason="invalid_value")
    recorded = _recorded_time(record.get("updated_at"), now)
    if recorded is None:
        return ContextEvidence(**details, reason="invalid_timestamp")
    age = (now.astimezone(timezone.utc) - recorded.astimezone(timezone.utc)).total_seconds()
    details.update(recorded_at=recorded, age_seconds=age)
    if age < 0:
        return ContextEvidence(**details, reason="future_timestamp")
    try:
        until = (recorded.astimezone(timezone.utc) + STORED_VALIDITY).astimezone(now.tzinfo)
        expiry = record.get("expires_at")
        if expiry is not None and expiry != "":
            expires_on = date.fromisoformat(expiry)
            if expires_on.isoformat() != expiry:
                raise ValueError("Noncanonical expiry date")
            midnight = datetime.combine(expires_on + timedelta(days=1), time(), now.tzinfo)
            until = min(until, midnight, key=lambda item: item.timestamp())
            if now.timestamp() >= midnight.timestamp():
                return ContextEvidence(**details, valid_until=until, reason="expired")
    except (TypeError, ValueError, OverflowError):
        return ContextEvidence(**details, reason="invalid_expiry")
    if now.timestamp() >= until.timestamp():
        return ContextEvidence(**details, valid_until=until, reason="stale")
    return ContextEvidence(
        **details, valid_until=until, effective_value=value, status="known", reason="fresh",
    )


def evaluate_gps_evidence(
    point: Mapping[str, Any] | None, *, now: datetime,
    location_resolver: Callable[[float, float], bool | None],
) -> ContextEvidence:
    """Bound recorded owner-location evidence; do not infer live/accuracy metadata."""
    _require_aware(now)
    if point is None:
        return ContextEvidence()
    details: dict[str, Any] = {"source": "gps"}
    try:
        if not isinstance(point, Mapping) or any(
            isinstance(point.get(key), bool) for key in ("lat", "lon")
        ):
            raise ValueError("Invalid coordinate type")
        lat, lon = float(point.get("lat")), float(point.get("lon"))
        if (not math.isfinite(lat) or not math.isfinite(lon)
                or not -90 <= lat <= 90 or not -180 <= lon <= 180):
            raise ValueError("Invalid coordinates")
    except (TypeError, ValueError, OverflowError):
        return ContextEvidence(**details, reason="invalid_point")
    try:
        raw_stamp = point.get("timestamp")
        if isinstance(raw_stamp, bool):
            raise ValueError("Invalid timestamp type")
        stamp = float(raw_stamp)
        if not math.isfinite(stamp) or stamp <= 0:
            raise ValueError("Invalid timestamp")
        recorded = datetime.fromtimestamp(stamp, now.tzinfo)
        until = (recorded.astimezone(timezone.utc) + GPS_VALIDITY).astimezone(now.tzinfo)
    except (TypeError, ValueError, OverflowError, OSError):
        return ContextEvidence(**details, reason="invalid_timestamp")
    age = now.timestamp() - stamp
    details.update(recorded_at=recorded, valid_until=until, age_seconds=age)
    if age < 0:
        return ContextEvidence(**details, reason="future_timestamp")
    if now.timestamp() >= until.timestamp():
        return ContextEvidence(**details, reason="stale")
    try:
        is_home = location_resolver(lat, lon)
    except Exception:
        return ContextEvidence(**details, reason="read_error")
    if not isinstance(is_home, bool):
        return ContextEvidence(**details, reason="invalid_geometry")
    return ContextEvidence(
        **details, effective_value=not is_home, status="known", reason="fresh",
    )


def evaluate_context_evidence(
    records: Mapping[str, Mapping[str, Any] | None], point: Mapping[str, Any] | None,
    *, now: datetime, location_resolver: Callable[[float, float], bool | None],
) -> dict[str, ContextEvidence]:
    """Reconcile five volatile states without changing any persisted observation."""
    evidence = {
        key: evaluate_stored_evidence(records.get(key), now=now) for key in VOLATILE_FLAGS
    }
    stored = evidence["user_out_of_home"]
    gps = evaluate_gps_evidence(point, now=now, location_resolver=location_resolver)
    if stored.status == "known" and gps.status == "known":
        if stored.effective_value != gps.effective_value:
            evidence["user_out_of_home"] = replace(
                stored, effective_value=None, source="conflict", status="unknown",
                reason="conflict", valid_until=min(
                    stored.valid_until, gps.valid_until, key=lambda item: item.timestamp(),
                ),
            )
    elif gps.status == "known" or stored.reason == "missing":
        evidence["user_out_of_home"] = replace(gps, stored_value=stored.stored_value)
    household = evidence["family_at_home"]
    if household.effective_value is True and (
        stored.effective_value is True or gps.effective_value is True
    ):
        evidence["family_at_home"] = replace(
            household, effective_value=None, source="conflict", status="unknown", reason="conflict",
        )
    return evidence


def load_gps_point(path: str | Path) -> Any:
    """Read a bounded persisted point; let the caller report failures safely."""
    with Path(path).open("rb") as stream:
        payload = stream.read(8193)
    if len(payload) > 8192:
        raise ValueError("Location record exceeds evidence read limit")
    return json.loads(payload)


def build_evidence_snapshot(
    *, now: datetime, state_reader: Callable[[str], Mapping[str, Any] | None],
    gps_loader: Callable[[], Any], location_resolver: Callable[[float, float], bool | None],
) -> dict[str, ContextEvidence]:
    """Load one bounded snapshot through read abstractions with isolated errors."""
    _require_aware(now)
    records: dict[str, Mapping[str, Any] | None] = {}
    failed_keys: set[str] = set()
    for key in VOLATILE_FLAGS:
        try:
            records[key] = state_reader(key)
        except Exception:
            records[key] = None
            failed_keys.add(key)
    gps_failed = False
    try:
        point = gps_loader()
    except Exception:
        point = None
        gps_failed = True
    evidence = evaluate_context_evidence(records, point, now=now, location_resolver=location_resolver)
    for key in failed_keys:
        if evidence[key].status != "known":
            evidence[key] = ContextEvidence(source="stored_context", reason="read_error")
    owner = evidence["user_out_of_home"]
    if gps_failed and owner.reason == "missing":
        evidence["user_out_of_home"] = ContextEvidence(source="gps", reason="read_error")
    return evidence
