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


def _event_pattern_key(event: Mapping[str, Any]) -> tuple[str, ...] | None:
    """Return a conservative, stable grouping key for a valid confirmed event.

    A named observation is identified by its subject, named item, and canonical
    action kind. Extractor taxonomy is retained for validation and display, but
    is not an identity for named observations because equivalent facts may
    receive evolving labels. Legacy events without an action kind retain the
    stricter full-taxonomy grouping rather than being semantically guessed.
    """
    if _signature_text(event.get("record_state")) != "confirmed":
        return None
    required = tuple(_signature_text(event.get(field)) for field in _REQUIRED_PATTERN_FIELDS)
    if not all(required):
        return None
    if _canonical_event_date(event.get("event_date")) is None:
        return None
    item = _signature_text(event.get("item")) or None
    if item is not None:
        action_kind = _signature_text(event.get("action_kind"))
        if action_kind and action_kind != "other":
            return "named", required[2], item, action_kind
    return "taxonomy", required[0], required[1], required[2], item or "", required[3]


def _event_display_fields(event: Mapping[str, Any]) -> tuple[str, str | None, str, str, str | None, str]:
    """Return normalized candidate fields from one structurally valid event."""
    return (
        _signature_text(event.get("event_type")),
        _signature_text(event.get("action_kind")) or None,
        _signature_text(event.get("category")),
        _signature_text(event.get("subject")),
        _signature_text(event.get("item")) or None,
        _signature_text(event.get("status")),
    )


def summarize_behavioral_pattern_progress(
    events: Iterable[Mapping[str, Any]],
) -> dict[str, int]:
    """Summarize read-only evidence progress without creating candidates."""
    confirmed_event_count = 0
    grouped_dates: dict[tuple[str, ...], set[str]] = defaultdict(set)

    for event in events:
        if _signature_text(event.get("record_state")) == "confirmed":
            confirmed_event_count += 1
        key = _event_pattern_key(event)
        event_date = _canonical_event_date(event.get("event_date"))
        if key is not None and event_date is not None:
            grouped_dates[key].add(event_date)

    strongest_distinct_dates = max(
        (len(event_dates) for event_dates in grouped_dates.values()),
        default=0,
    )
    return {
        "confirmed_event_count": confirmed_event_count,
        "required_distinct_dates": MINIMUM_DISTINCT_EVENT_DATES,
        "strongest_distinct_dates": strongest_distinct_dates,
    }


def aggregate_behavioral_pattern_candidates(
    events: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Return evidence-only candidates from repeated confirmed event signatures.

    This function is pure: it does not persist, infer a routine, or invoke an
    LLM. A signature must occur on at least three distinct calendar dates.
    """
    grouped_events: dict[tuple[str, ...], list[tuple[str, Mapping[str, Any]]]] = defaultdict(list)
    for event in events:
        key = _event_pattern_key(event)
        if key is None:
            continue
        event_date = _canonical_event_date(event.get("event_date"))
        if event_date is None:
            continue
        grouped_events[key].append((event_date, event))

    candidates: list[dict[str, Any]] = []
    for grouped in grouped_events.values():
        event_dates = [event_date for event_date, _ in grouped]
        distinct_dates = sorted(set(event_dates))
        if len(distinct_dates) < MINIMUM_DISTINCT_EVENT_DATES:
            continue
        _, representative_event = max(
            grouped,
            key=lambda record: (record[0], _event_display_fields(record[1])),
        )
        event_type, action_kind, category, subject, item, status = _event_display_fields(representative_event)
        candidates.append({
            "event_type": event_type,
            "action_kind": action_kind,
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
            str(candidate["action_kind"] or ""),
            str(candidate["category"]),
            str(candidate["subject"]),
            str(candidate["item"] or ""),
            str(candidate["status"]),
        ),
        reverse=True,
    )
