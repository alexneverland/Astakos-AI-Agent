"""Conservative unsolicited behavioral conversation with durable delivery."""
from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta
from hashlib import sha256
import json
import logging
from typing import Any
from uuid import uuid4

from core.untrusted_content import external_content_source_names
from memory.behavioral_conversation_preferences import PreferenceStore
from memory.behavioral_initiative_state import InitiativeStore
from services.behavioral_pattern_aggregator import _event_pattern_key

_logger = logging.getLogger(__name__)


def _topic(packet: dict[str, Any]) -> str:
    """Reuse detector identity rather than inventing a second grouping policy."""
    key = _event_pattern_key(dict(packet, record_state="confirmed", event_date=packet["first_date"]))
    if key is None:
        raise ValueError("Invalid behavioral topic")
    return sha256(json.dumps(key).encode()).hexdigest()


def _snapshot(rows: list[dict[str, Any]]) -> list[str]:
    """Correlate all shared messages, including reminders and external copies."""
    return [str(row["id"]) for row in rows]


def _idle(rows: list[dict[str, Any]], now: datetime) -> bool:
    """Require known valid timestamps and fifteen minutes without any message."""
    if not rows:
        return False
    return all(now - datetime.fromisoformat(row["timestamp"]) >= timedelta(minutes=15) for row in rows)


def _decision_valid(raw: Any, evidence: list[dict[str, Any]]) -> bool:
    """Enforce the bounded structured send contract, not human phrase meaning."""
    if not isinstance(raw, dict) or set(raw) != {"selected_index", "blocked", "recently_discussed", "message"}:
        return False
    index = raw["selected_index"]
    return (
        (index is None or (type(index) is int and 0 <= index < len(evidence)))
        and type(raw["blocked"]) is bool and type(raw["recently_discussed"]) is bool
        and isinstance(raw["message"], str) and len(raw["message"]) <= 500
    )


def run_initiative(
    *, store: InitiativeStore, preferences: PreferenceStore,
    history_loader: Callable[[], list[dict[str, Any]]],
    evidence_loader: Callable[..., list[dict[str, Any]]],
    classify: Callable[[dict[str, Any]], Any],
    sender: Callable[..., Any], record: Callable[..., Any],
    clock: Callable[[], datetime], selected_channel: Callable[[], str],
    unavailable: Callable[[], bool], budget: Callable[[], bool],
    current_context: Callable[[], dict[str, Any]],
) -> str:
    """Deliver at most one fresh opener; uncertain sends remain durable and held.

    The lock spans the lifecycle across processes. Matrix can safely retry the
    same transaction while fresh; Telegram cannot prove ambiguous delivery.
    Confirmed sends repair only history on restart, never the external send.
    """
    try:
        with store.lock():
            state = store.load()
            pending = state["pending"]
            if pending is not None and pending["external_id"] is not None:
                return _finish_record(state, store, record)
            now, channel = clock(), selected_channel()
            rows, prefs, context = history_loader(), preferences.load(), current_context()
            if channel not in {"matrix", "telegram"} or unavailable() or not _idle(rows, now):
                return "held" if pending else "skip"
            if pending is not None:
                fresh = (
                    pending["channel"] == channel == "matrix"
                    and pending["snapshot"] == _snapshot(rows)
                    and pending["preferences"] == prefs
                    and pending["context"] == context
                    and datetime.fromisoformat(pending["created_at"]).date() == now.date()
                )
                if not fresh:
                    _logger.warning("Behavioral initiative ambiguous send held (%s)", pending["id"])
                    return "held"
            else:
                delivered = state["delivered"]
                if any(datetime.fromisoformat(item["delivered_at"]) > now or
                       datetime.fromisoformat(item["delivered_at"]).date() == now.date() for item in delivered):
                    return "skip"
                recent = [item for item in delivered if now - datetime.fromisoformat(item["delivered_at"]) < timedelta(days=7)]
                evidence = [packet for packet in evidence_loader(today=now.date(), window_days=30)
                            if _topic(packet) not in {item["topic"] for item in recent}]
                if not evidence:
                    return "skip"
                evaluation = dict(day=now.date().isoformat(), snapshot=_snapshot(rows), preferences=prefs, context=context)
                if state["evaluated"] == evaluation:
                    return "skip"
                state["evaluated"] = evaluation
                store.save(state)  # Do not retry the same model decision every poll.
                raw = classify({
                    "now": now.isoformat(), "evidence": evidence, "preferences": prefs,
                    "recent_openers": [{"text": item["text"], "at": item["delivered_at"]} for item in recent],
                    "current_context": context,
                    "recent_history": [{"role": row["role"], "text": row["content"][:1000], "at": row["timestamp"]}
                                       for row in rows if not external_content_source_names(row.get("metadata", {}))],
                })
                if not _decision_valid(raw, evidence) or raw["selected_index"] is None or raw["blocked"] or raw["recently_discussed"] or not raw["message"].strip():
                    return "skip"
                pending = dict(id=uuid4().hex, topic=_topic(evidence[raw["selected_index"]]),
                               channel=channel, text=raw["message"].strip(), created_at=now.isoformat(),
                               snapshot=_snapshot(rows), preferences=prefs, context=context, external_id=None, delivered_at=None)
            # Slow classification must not authorize a stale send or bypass new opt-outs.
            if (selected_channel() != channel or unavailable() or preferences.load() != prefs
                    or _snapshot(history_loader()) != _snapshot(rows) or current_context() != context
                    or clock().date() != now.date() or not _idle(rows, clock())):
                return "held" if state["pending"] else "skip"
            if not budget():
                return "held" if state["pending"] else "skip"
            state["pending"] = pending
            store.save(state)  # Intent before I/O: a crash cannot create a blind retry.
            receipt = sender(channel, pending["text"], "astakos-behavioral-" + pending["id"])
            if receipt.channel != channel or not receipt.external_id:
                raise ValueError("Invalid initiative delivery receipt")
            pending["external_id"] = str(receipt.external_id)
            pending["delivered_at"] = clock().isoformat()
            store.save(state)  # Preserve confirmed receipt even if history fails.
            return _finish_record(state, store, record)
    except Exception as exc:
        _logger.warning("Behavioral initiative skipped or held (%s)", type(exc).__name__)
        return "held"


def _finish_record(state: dict[str, Any], store: InitiativeStore, record: Callable[..., Any]) -> str:
    """Repair one confirmed receipt locally with a durable unique history ID."""
    pending = state["pending"]
    record(role="assistant", content=pending["text"], channel=pending["channel"],
           agent="Behavioral_Agent", message_id="behavioral-" + pending["id"],
           timestamp=datetime.fromisoformat(pending["delivered_at"]),
           metadata={"external_message_id": pending["external_id"]})
    state["delivered"] = (state["delivered"] + [pending])[-32:]
    state["pending"] = None
    store.save(state)
    _logger.info("Behavioral initiative delivered (%s)", pending["id"])
    return "delivered"
