"""Deterministic, read-only aggregation of confirmed behavioral events."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping
from datetime import date
from typing import Any


MINIMUM_DISTINCT_EVENT_DATES = 3
_REQUIRED_PATTERN_FIELDS = (
    "event_type",
    "category",
    "subject",
    "status",
)


def _text(value: Any) -> str:
    """Return normalized text, or an empty string for missing values."""
    return str(value or "").strip()


def _signature_text(value: Any) -> str:
    """Return deterministic case-insensitive text for a grouping signature."""
    return _text(value).casefold()


def _canonical_event_date(value: Any) -> str | None:
    """Return an ISO calendar date, or ``None`` for an invalid date value."""
    try:
        return date.fromisoformat(_text(value)).isoformat()
    except ValueError:
        return None


def _event_pattern_key(event: Mapping[str, Any]) -> tuple[str, str, str, str | None, str] | None:
    """Return the stable grouping key for one confirmed, structurally valid event."""
    if _signature_text(event.get("record_state")) != "confirmed":
        return None
    required = tuple(_signature_text(event.get(field)) for field in _REQUIRED_PATTERN_FIELDS)
    if not all(required):
        return None
    if _canonical_event_date(event.get("event_date")) is None:
        return None
    item = _signature_text(event.get("item")) or None
    return required[0], required[1], required[2], item, required[3]


def aggregate_behavioral_pattern_candidates(
    events: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Return evidence-only candidates from repeated confirmed event signatures.

    This function is pure: it does not persist, infer a routine, or invoke an
    LLM. A signature must occur on at least three distinct calendar dates.
    """
    grouped_dates: dict[tuple[str, str, str, str | None, str], list[str]] = defaultdict(list)
    for event in events:
        key = _event_pattern_key(event)
        if key is None:
            continue
        event_date = _canonical_event_date(event.get("event_date"))
        if event_date is None:
            continue
        grouped_dates[key].append(event_date)

    candidates: list[dict[str, Any]] = []
    for key, event_dates in grouped_dates.items():
        distinct_dates = sorted(set(event_dates))
        if len(distinct_dates) < MINIMUM_DISTINCT_EVENT_DATES:
            continue
        event_type, category, subject, item, status = key
        candidates.append({
            "event_type": event_type,
            "category": category,
            "subject": subject,
            "item": item,
            "status": status,
            "occurrence_count": len(event_dates),
            "first_date": distinct_dates[0],
            "last_date": distinct_dates[-1],
        })

    return sorted(
        candidates,
        key=lambda candidate: (
            int(candidate["occurrence_count"]),
            str(candidate["last_date"]),
            str(candidate["event_type"]),
            str(candidate["category"]),
            str(candidate["subject"]),
            str(candidate["item"] or ""),
            str(candidate["status"]),
        ),
        reverse=True,
    )
