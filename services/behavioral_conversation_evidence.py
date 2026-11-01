"""Read-only dated evidence from the existing behavioral pattern detector.

No consumer is enabled here: these packets neither send messages nor modify
memory, routines, prompts or storage. Occurrence time is deliberately unknown.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Mapping
from datetime import date, datetime, timedelta
import json
from typing import Any

from core.untrusted_content import external_content_source_names
from services.behavioral_event_extractor import normalize_extracted_event
from services.behavioral_pattern_aggregator import aggregate_behavioral_pattern_candidates

_logger = logging.getLogger(__name__)
MAX_PATTERN_PACKETS = 3
MAX_CONVERSATION_PATTERN_PACKETS = 12
MAX_SOURCE_REFS = 12


def load_followup_topic_context(now: datetime | None = None) -> list[dict[str, Any]]:
    """Expose reserved/recent topics to both consumers without changing their queue."""
    from memory.pending_followups import load_followup_conversation_topics
    topics = []
    for row in load_followup_conversation_topics(now or datetime.now()):
        metadata = json.loads(row.get("metadata_json") or "{}")
        if not isinstance(metadata, dict) or external_content_source_names(metadata):
            continue
        if row.get("source_channel") not in {"web", "matrix", "telegram"}:
            continue
        if any(len(str(row.get(key) or "")) > maximum for key, maximum in
               (("topic", 160), ("subject", 160), ("source_user_text", 500))):
            continue
        topics.append({key: row.get(key) for key in (
            "id", "topic", "subject", "status", "source_user_text",
            "followup_after_ts", "expires_at", "sent_at",
        )})
        if len(topics) == 20:
            break
    return topics


def build_behavioral_evidence(
    events: Iterable[Mapping[str, Any]], *, today: date, window_days: int,
    max_patterns: int = MAX_PATTERN_PACKETS,
) -> list[dict[str, Any]]:
    """Reuse canonical validation/grouping within an explicit inclusive window.

    Rows from every supported conversation channel participate together.
    Source replay is counted once; qualifying dates are kept even when the
    source-reference list is bounded. No daily-frequency claim is inferred.
    """
    if type(window_days) is not int or not 1 <= window_days <= 366:
        raise ValueError("window_days must be an integer between 1 and 366")
    if type(max_patterns) is not int or not 1 <= max_patterns <= MAX_CONVERSATION_PATTERN_PACKETS:
        raise ValueError("max_patterns must be an integer between 1 and 12")
    start = today - timedelta(days=window_days - 1)
    eligible: list[dict[str, Any]] = []
    seen_sources: set[str] = set()
    for event in events:
        if event.get("record_state") != "confirmed":
            continue
        if external_content_source_names(event.get("metadata") or {}):
            continue
        rowid = event.get("source_rowid")
        if type(rowid) is not int or rowid <= 0:
            continue
        if event.get("source_channel") not in {"web", "telegram", "matrix"}:
            continue
        flags = {name: event.get(name) for name in ("negated", "hypothetical", "reported_by_user")}
        if any(type(value) not in (bool, int) or value not in (0, 1) for value in flags.values()):
            continue
        if isinstance(event.get("confidence"), bool):
            continue
        if any(len(str(event.get(name) or "")) > 160 for name in (
            "event_type", "action_kind", "category", "subject", "item", "status", "source_message_id",
        )):
            continue
        try:
            event_day = date.fromisoformat(str(event.get("event_date") or ""))
        except ValueError:
            continue
        if not start <= event_day <= today:
            continue
        normalized = normalize_extracted_event(
            {**event, **{name: bool(value) for name, value in flags.items()}},
            {
                "id": event.get("source_message_id"), "rowid": rowid,
                "channel": event.get("source_channel"), "date": event_day.isoformat(),
            },
        )
        if normalized is None or normalized["record_state"] != "confirmed":
            continue
        source_id = normalized["source_message_id"]
        if source_id in seen_sources:
            continue
        seen_sources.add(source_id)
        eligible.append(normalized)

    candidates = aggregate_behavioral_pattern_candidates(eligible, include_evidence=True)
    for candidate in candidates:
        candidate["source_refs"] = candidate["source_refs"][-MAX_SOURCE_REFS:]
        candidate["window_start"] = start.isoformat()
        candidate["window_end"] = today.isoformat()
    return candidates[:max_patterns]


def load_behavioral_evidence(
    *, today: date, window_days: int, db_path: str | None = None,
    max_patterns: int = MAX_PATTERN_PACKETS,
) -> list[dict[str, Any]]:
    """Read the existing observation store without initialization or migration."""
    from memory.behavioral_event_state import list_events

    kwargs = {"db_path": db_path} if db_path is not None else {}
    try:
        events = list_events(record_state="confirmed", initialize=False, **kwargs)
    except Exception as exc:
        _logger.warning("Behavioral evidence unavailable (%s)", type(exc).__name__)
        return []
    return build_behavioral_evidence(events, today=today, window_days=window_days,
                                     max_patterns=max_patterns)
