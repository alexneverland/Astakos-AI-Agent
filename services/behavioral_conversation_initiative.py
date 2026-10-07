"""Conservative unsolicited behavioral conversation with durable delivery."""
from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta, timezone
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
    # Legacy history/clock values are host-local; new context receipts include
    # offsets. Compare instants, preserving offsets rather than stripping them.
    instant = now.astimezone(timezone.utc)
    return all(instant - datetime.fromisoformat(row["timestamp"]).astimezone(timezone.utc)
               >= timedelta(minutes=15) for row in rows)


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
    unavailable: Callable[[], bool | str], budget: Callable[[], bool],
    current_context: Callable[[], dict[str, Any]],
) -> str:
    """Deliver at most one fresh opener; uncertain sends remain durable and held.

    The lock spans the lifecycle across processes. Matrix can safely retry the
    same transaction while fresh; Telegram cannot prove ambiguous delivery.
    Confirmed sends repair only history on restart, never the external send.
    """
    diagnostic: dict[str, Any] = dict(run_id=uuid4().hex, entry_point="initiative_worker",
                                    reason="started", stage="load", model_evaluated=False)

    def outcome(result: str, reason: str) -> str:
        """Record metadata only; preserve the existing delivery return contract."""
        diagnostic.update(result=result, reason=reason)
        return result

    try:
        with store.lock():
            state = store.load()
            pending = state["pending"]
            if pending is not None and pending["external_id"] is not None:
                diagnostic["stage"] = "history"
                return outcome(_finish_record(state, store, record), "history_repaired")
            now, channel = clock(), selected_channel()
            diagnostic.update(at=now.isoformat(), channel=channel if channel in {"matrix", "telegram"} else "inactive")
            rows, prefs, context = history_loader(), preferences.load(), current_context()
            diagnostic["stage"] = "gates"
            if channel not in {"matrix", "telegram"}:
                return outcome("held" if pending else "skip", "inactive_channel")
            blocked = unavailable()
            if blocked:
                reason = blocked if blocked in {"shutdown", "inactive_runtime", "quiet_hours", "proactive_muted", "recent_reminder"} else "unavailable"
                return outcome("held" if pending else "skip", reason)
            if not _idle(rows, now):
                return outcome("held" if pending else "skip", "recent_activity" if rows else "missing_history")
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
                    return outcome("held", "ambiguous_pending_delivery")
            else:
                delivered = state["delivered"]
                delivered_times = [datetime.fromisoformat(item["delivered_at"]).astimezone()
                                   for item in delivered]
                instant = now.astimezone(timezone.utc)
                if any(stamp.astimezone(timezone.utc) > instant or
                       stamp.date() == now.astimezone().date() for stamp in delivered_times):
                    return outcome("skip", "daily_limit_or_future_delivery")
                recent = [item for item, stamp in zip(delivered, delivered_times)
                          if instant - stamp.astimezone(timezone.utc) < timedelta(days=7)]
                diagnostic["stage"] = "evidence"
                packets = evidence_loader(today=now.date(), window_days=30)
                evidence = [packet for packet in packets
                            if _topic(packet) not in {item["topic"] for item in recent}]
                diagnostic["candidate_count"] = len(evidence)
                if not evidence:
                    return outcome("skip", "topic_cooldown" if packets else "no_eligible_patterns")
                evaluation = dict(day=now.date().isoformat(), snapshot=_snapshot(rows), preferences=prefs, context=context)
                if state["evaluated"] == evaluation:
                    return outcome("skip", "already_evaluated")
                state["evaluated"] = evaluation
                store.save(state)  # Do not retry the same model decision every poll.
                diagnostic.update(stage="classify", model_evaluated=True)
                raw = classify({
                    "now": now.isoformat(), "evidence": evidence, "preferences": prefs,
                    "recent_openers": [{"text": item["text"], "at": item["delivered_at"]} for item in recent],
                    "current_context": context,
                    "recent_history": [{"role": row["role"], "text": row["content"][:1000], "at": row["timestamp"]}
                                       for row in rows if not external_content_source_names(row.get("metadata", {}))],
                })
                if not _decision_valid(raw, evidence):
                    return outcome("skip", "invalid_model_decision")
                diagnostic.update(selected_index=raw["selected_index"], blocked=raw["blocked"],
                                  recently_discussed=raw["recently_discussed"])
                if raw["selected_index"] is None:
                    return outcome("skip", "model_no_topic")
                if raw["blocked"]:
                    return outcome("skip", "model_blocked")
                if raw["recently_discussed"]:
                    return outcome("skip", "recently_discussed")
                if not raw["message"].strip():
                    return outcome("skip", "empty_model_message")
                pending = dict(id=uuid4().hex, topic=_topic(evidence[raw["selected_index"]]),
                               channel=channel, text=raw["message"].strip(), created_at=now.isoformat(),
                               snapshot=_snapshot(rows), preferences=prefs, context=context, external_id=None, delivered_at=None)
            # Slow classification must not authorize a stale send or bypass new opt-outs.
            diagnostic["stage"] = "freshness"
            if (selected_channel() != channel or unavailable() or preferences.load() != prefs
                    or _snapshot(history_loader()) != _snapshot(rows) or current_context() != context
                    or clock().date() != now.date() or not _idle(rows, clock())):
                return outcome("held" if state["pending"] else "skip", "changed_context")
            if not budget():
                return outcome("held" if state["pending"] else "skip", "proactive_budget")
            state["pending"] = pending
            store.save(state)  # Intent before I/O: a crash cannot create a blind retry.
            diagnostic["stage"] = "delivery"
            receipt = sender(channel, pending["text"], "astakos-behavioral-" + pending["id"])
            if receipt.channel != channel or not receipt.external_id:
                raise ValueError("Invalid initiative delivery receipt")
            pending["external_id"] = str(receipt.external_id)
            pending["delivered_at"] = clock().isoformat()
            diagnostic["stage"] = "receipt"
            store.save(state)  # Preserve confirmed receipt even if history fails.
            diagnostic["stage"] = "history"
            return outcome(_finish_record(state, store, record), "delivered")
    except Exception as exc:
        _logger.warning("Behavioral initiative skipped or held (stage=%s, error=%s)",
                        diagnostic["stage"], type(exc).__name__)
        diagnostic["error_type"] = type(exc).__name__
        reason = {"classify": "model_error", "delivery": "delivery_error",
                  "history": "history_error", "receipt": "receipt_persistence_error"}.get(diagnostic["stage"], "worker_error")
        return outcome("held", reason)
    finally:
        diagnostic.setdefault("at", datetime.now().isoformat())
        _logger.info("Behavioral initiative check %s", json.dumps(diagnostic, ensure_ascii=True))
        try:
            store.record_diagnostic(diagnostic)
        except Exception as exc:
            _logger.warning("Behavioral initiative diagnostics unavailable (%s)", type(exc).__name__)


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
