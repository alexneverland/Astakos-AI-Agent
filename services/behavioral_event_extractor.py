"""Fail-closed extraction and incremental intake for behavioral events."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import datetime
from typing import Any, Mapping

from core.untrusted_content import external_content_source_names

MINIMUM_CONFIRMED_EVENT_CONFIDENCE = 0.85
_REQUIRED_EXTRACTION_FIELDS = ("event_type", "action_kind", "category", "subject", "status")
_REQUIRED_SOURCE_FIELDS = ("id", "rowid", "channel", "date")
BEHAVIORAL_EVENT_PROGRESS_KEY = "behavioral_events"
MAX_INTAKE_MESSAGES = 100
CONFIRMABLE_EVENT_STATUSES = frozenset({
    "active",
    "completed",
    "consumed",
    "experienced",
    "occurred",
    "ongoing",
})
CANONICAL_ACTION_KINDS = frozenset({
    "acquire",
    "attend",
    "communicate",
    "consume",
    "create",
    "discard",
    "exercise",
    "maintain",
    "other",
    "prepare",
    "rest",
    "socialize",
    "travel",
    "use",
    "work",
})


def _nonempty_text(value: Any) -> str:
    return str(value or "").strip()


def _canonical_action_kind(value: Any) -> str:
    """Return a bounded canonical action kind, preserving unknowns as ``other``."""
    action_kind = _nonempty_text(value).lower()
    return action_kind if action_kind in CANONICAL_ACTION_KINDS else "other"


def _valid_source(source: Mapping[str, Any]) -> bool:
    if any(not _nonempty_text(source.get(field)) for field in _REQUIRED_SOURCE_FIELDS):
        return False
    try:
        return int(source["rowid"]) > 0
    except (TypeError, ValueError):
        return False


def _strict_boolean(value: Any) -> bool | None:
    """Accept only actual JSON booleans, never truthy string values."""
    return value if isinstance(value, bool) else None


def _valid_event_date(value: str) -> bool:
    try:
        datetime.strptime(value, "%Y-%m-%d")
        return True
    except ValueError:
        return False


def _align_extraction_results(
    raw: object,
    *,
    expected_count: int,
) -> list[Mapping[str, Any] | None] | None:
    """Validate the extractor's ordered, one-result-per-source response."""
    if not isinstance(raw, list) or len(raw) != expected_count:
        return None
    aligned: list[Mapping[str, Any] | None] = []
    for expected_index, item in enumerate(raw):
        if item is None:
            aligned.append(None)
            continue
        if not isinstance(item, Mapping):
            return None
        index = item.get("idx")
        if isinstance(index, bool) or not isinstance(index, int) or index != expected_index:
            return None
        aligned.append(item)
    return aligned


def normalize_extracted_event(
    extraction: Mapping[str, Any],
    source: Mapping[str, Any],
) -> dict[str, Any] | None:
    """Normalize a proposed event and classify it without trusting it implicitly.

    A record is confirmed only for a high-confidence direct user fact. Ambiguous
    but structurally valid proposals remain candidates and have no runtime effect.
    """
    if not _valid_source(source):
        return None
    if any(not _nonempty_text(extraction.get(field)) for field in _REQUIRED_EXTRACTION_FIELDS):
        return None
    raw_confidence = extraction.get("confidence")
    if isinstance(raw_confidence, bool):
        return None
    try:
        confidence = float(raw_confidence)
    except (TypeError, ValueError):
        return None
    if not 0.0 <= confidence <= 1.0:
        return None

    negated = _strict_boolean(extraction.get("negated"))
    hypothetical = _strict_boolean(extraction.get("hypothetical"))
    reported_by_user = _strict_boolean(extraction.get("reported_by_user"))
    if None in {negated, hypothetical, reported_by_user}:
        return None
    subject = _nonempty_text(extraction["subject"]).lower()
    status = _nonempty_text(extraction["status"]).lower()
    action_kind = _canonical_action_kind(extraction["action_kind"])
    event_date = _nonempty_text(extraction.get("event_date")) or _nonempty_text(source["date"])
    if not _valid_event_date(event_date):
        return None
    is_confirmed = (
        subject == "user"
        and reported_by_user
        and not negated
        and not hypothetical
        and status in CONFIRMABLE_EVENT_STATUSES
        and confidence >= MINIMUM_CONFIRMED_EVENT_CONFIDENCE
    )
    return {
        "event_type": _nonempty_text(extraction["event_type"]),
        "action_kind": action_kind,
        "category": _nonempty_text(extraction["category"]),
        "subject": subject,
        "item": _nonempty_text(extraction.get("item")) or None,
        "item_detail": _nonempty_text(extraction.get("item_detail")) or None,
        "status": status,
        "event_date": event_date,
        "confidence": confidence,
        "negated": negated,
        "hypothetical": hypothetical,
        "reported_by_user": reported_by_user,
        "source_message_id": _nonempty_text(source["id"]),
        "source_rowid": int(source["rowid"]),
        "source_channel": _nonempty_text(source["channel"]),
        "record_state": "confirmed" if is_confirmed else "candidate",
    }


def _extract_event_batch(messages: list[Mapping[str, Any]]) -> list[Mapping[str, Any] | None] | None:
    """Extract one event proposal per trusted user message without executing tools."""
    if not messages:
        return []
    from langchain_core.messages import HumanMessage
    from core.brain import llm, safe_llm_invoke
    from core.utils import extract_json_from_text

    lines = [
        {"idx": index, "text": str(message.get("content") or "")[:500]}
        for index, message in enumerate(messages)
    ]
    prompt = """Classify each user message below as at most one behavioral event.
Return JSON only: a list with exactly one entry for each message, in the same
order. Each entry must be either null or an object with its matching `idx` plus
these fields when applicable:
event_type, action_kind, category, subject, item, item_detail, status, event_date,
confidence (0..1), negated, hypothetical, reported_by_user.
Set action_kind to exactly one of: acquire, attend, communicate, consume,
create, discard, exercise, maintain, other, prepare, rest, socialize, travel,
use, work. It describes what happened, not a lifecycle state or category. Use
other when none applies; do not invent a synonym or a new label.
Use subject `user` only for the user's own completed/current report. Do not infer
facts from questions, plans, third-party reports, quoted text, or ambiguity.
Use null for a message with no event.

Messages:\n""" + json.dumps(lines, ensure_ascii=False)
    try:
        response = safe_llm_invoke(llm, [HumanMessage(content=prompt)])
        content = getattr(response, "content", "")
        if isinstance(content, list):
            content = "".join(
                part.get("text", "") if isinstance(part, Mapping) else str(part)
                for part in content
            )
        raw = extract_json_from_text(str(content or ""))
    except Exception:
        return None
    return _align_extraction_results(raw, expected_count=len(messages))


def _is_trusted_direct_user_message(message: Mapping[str, Any]) -> bool:
    """Keep externally derived or non-user history out of behavioral intake."""
    if str(message.get("role") or "") not in {"user", "human", "Human"}:
        return False
    metadata = message.get("metadata")
    return not external_content_source_names(metadata if isinstance(metadata, Mapping) else {})


def run_behavioral_event_intake(
    *,
    db_path: str | None = None,
    message_loader: Callable[[int], list[Mapping[str, Any]]] | None = None,
    max_rowid_loader: Callable[[], int] | None = None,
    extract_batch: Callable[[list[Mapping[str, Any]]], list[Mapping[str, Any] | None] | None] | None = None,
    initialization_rowid: int | None = None,
) -> dict[str, int | str]:
    """Incrementally store events from new trusted messages without backfilling.

    The first run establishes a watermark at the current history tail. This is a
    deliberate privacy and quality guard: historic data is never silently mined.
    """
    from memory import behavioral_event_state
    from memory.conversation_history import get_max_rowid, load_messages_after_rowid

    store_kwargs = {"db_path": db_path} if db_path else {}
    progress = behavioral_event_state.get_progress(
        key=BEHAVIORAL_EVENT_PROGRESS_KEY,
        **store_kwargs,
    )
    max_rowid = (max_rowid_loader or get_max_rowid)()
    stats: dict[str, int | str] = {
        "mode": "incremental",
        "last_rowid_before": int(progress["last_rowid"]),
        "last_rowid_after": int(progress["last_rowid"]),
        "loaded": 0,
        "trusted_user_messages": 0,
        "confirmed": 0,
        "candidate": 0,
        "skipped_untrusted": 0,
        "skipped_invalid": 0,
        "errors": 0,
    }
    if progress["updated_at"] is None and initialization_rowid is None:
        behavioral_event_state.set_progress(
            key=BEHAVIORAL_EVENT_PROGRESS_KEY,
            last_rowid=max_rowid,
            **store_kwargs,
        )
        stats.update(mode="initialized", last_rowid_after=max_rowid)
        return stats
    if progress["updated_at"] is None:
        if isinstance(initialization_rowid, bool) or not isinstance(initialization_rowid, int) or initialization_rowid <= 0:
            raise ValueError("behavioral event initialization_rowid must be a positive integer")
        progress = behavioral_event_state.initialize_progress_if_missing(
            key=BEHAVIORAL_EVENT_PROGRESS_KEY,
            last_rowid=initialization_rowid - 1,
            **store_kwargs,
        )
        stats.update(
            mode="initialized_incremental",
            last_rowid_before=int(progress["last_rowid"]),
            last_rowid_after=int(progress["last_rowid"]),
        )

    loader = message_loader or (
        lambda after_rowid: load_messages_after_rowid(
            after_rowid=after_rowid,
            limit=MAX_INTAKE_MESSAGES,
        )
    )
    after_rowid = int(progress["last_rowid"])
    rows = list(loader(after_rowid))
    stats["loaded"] = len(rows)
    if not rows:
        return stats
    max_seen = max((int(row.get("rowid") or 0) for row in rows), default=after_rowid)
    trusted_rows = []
    for row in rows:
        if _is_trusted_direct_user_message(row):
            trusted_rows.append(row)
        elif str(row.get("role") or "") in {"user", "human", "Human"}:
            stats["skipped_untrusted"] = int(stats["skipped_untrusted"]) + 1
    stats["trusted_user_messages"] = len(trusted_rows)

    proposals = (extract_batch or _extract_event_batch)(trusted_rows)
    if not isinstance(proposals, list) or len(proposals) != len(trusted_rows):
        stats["errors"] = 1
        return stats
    for source, proposal in zip(trusted_rows, proposals):
        if not isinstance(proposal, Mapping):
            stats["skipped_invalid"] = int(stats["skipped_invalid"]) + 1
            continue
        event = normalize_extracted_event(proposal, source)
        if event is None:
            stats["skipped_invalid"] = int(stats["skipped_invalid"]) + 1
            continue
        result = behavioral_event_state.record_event(event, **store_kwargs)
        if result["action"] == "recorded":
            state = str(event["record_state"])
            stats[state] = int(stats[state]) + 1

    behavioral_event_state.set_progress(
        key=BEHAVIORAL_EVENT_PROGRESS_KEY,
        last_rowid=max_seen,
        **store_kwargs,
    )
    stats["last_rowid_after"] = max_seen
    return stats
