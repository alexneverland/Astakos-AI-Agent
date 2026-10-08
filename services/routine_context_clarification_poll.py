"""Injected clarification worker lifecycle, before live scheduler activation."""
from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from datetime import datetime
from hashlib import sha256
import json
from typing import Any

from memory.routine_context_clarification import ClarificationStore, QuestionRequest
from services.routine_context_clarification import (
    RoutineCandidate, candidate_unknown_flags, deliver_question, prepare_question,
)
from services.routine_context_evidence import ContextEvidence, VOLATILE_FLAGS


@dataclass(frozen=True)
class PollSnapshot:
    """Current eligible candidates, shared-history cursor and canonical context."""

    candidates: tuple[RoutineCandidate, ...]
    runtime_context: Mapping[str, Any]
    evidence: Mapping[str, ContextEvidence]
    history_marker: str

    def fingerprint(self) -> str:
        """Compare decision inputs, not an age counter that changes every poll."""
        data = [self.history_marker, self.runtime_context,
                [(row.id, row.name, row.slot_at, row.conditions, row.dependencies) for row in self.candidates],
                {flag: (item.effective_value, item.status, item.reason,
                        item.recorded_at, item.valid_until)
                 for flag in VOLATILE_FLAGS
                 for item in [self.evidence.get(flag, ContextEvidence())]}]
        return sha256(json.dumps(data, sort_keys=True, default=str,
                                 ensure_ascii=False).encode("utf-8")).hexdigest()


def _request(row: Mapping[str, Any]) -> QuestionRequest:
    """Restore the validated durable identity without regenerating its text."""
    return QuestionRequest(id=row["id"], topic=row["topic"],
        routine_ids=tuple(row["routine_ids"]), flags=tuple(row["flags"]),
        slot_at=datetime.fromisoformat(row["slot_at"]),
        question=row["question"], channel=row["channel"], correlation=row.get("correlation"),
        routine_slots=tuple((rid, datetime.fromisoformat(at))
                            for rid, at in row.get("routine_slots", {}).items()))


def run_clarification_poll(
    *, store: ClarificationStore, clock: Callable[[], datetime],
    selected_channel: Callable[[], str],
    snapshot_loader: Callable[[datetime], PollSnapshot],
    unavailable: Callable[[], bool | str], classify: Callable[[dict[str, Any]], Any],
    budget: Callable[[], bool], sender: Callable[[str, str, str], Any],
    record: Callable[..., Any],
    closed_routine_ids: Callable[[datetime], set[int]] | None = None,
) -> str:
    """Revalidate after model latency and reuse durable delivery/answer boundaries.

    The caller must supply normal-scheduler eligibility and interruption gates.
    This worker never marks a routine notified, completes it, or executes tools.
    """
    try:
        now = clock()
        if now.tzinfo is None:
            return "error"
        # A confirmed receipt is history repair only, even after a slot expires.
        for row in store.snapshot()["requests"]:
            if row["external_id"] and not row["history_recorded"]:
                outcome = deliver_question(store=store, question=_request(row), now=now,
                    selected_channel=selected_channel, still_current=lambda: False,
                    budget=budget, sender=sender, record=record, current_time=clock)
                if outcome != "recorded":
                    return "delivery_uncertain"
        pending = store.snapshot()["pending"]
        if pending is not None and pending["status"] == "sent" and closed_routine_ids is not None:
            # Retiring an obsolete question is local bookkeeping, not a new
            # proactive message: recent activity must not delay it until expiry.
            # Legacy single-routine questions have an unambiguous slot. Older
            # groups lack individual dates: retain them rather than guess.
            slots = pending.get("routine_slots", {
                pending["routine_ids"][0]: pending["slot_at"]
            } if len(pending["routine_ids"]) == 1 else {})
            if (slots and all(int(rid) in closed_routine_ids(datetime.fromisoformat(at))
                              for rid, at in slots.items())
                    and store.close(pending["id"], outcome="resolved", now=now)):
                return "resolved"
        store.expire(now=now)
        reason = unavailable()
        if reason:
            return reason if isinstance(reason, str) else "deferred"
        channel = selected_channel()
        if channel not in {"matrix", "telegram"}:
            return "deferred"
        snapshot = snapshot_loader(now)
        fingerprint = snapshot.fingerprint()

        def fresh() -> bool:
            """Reload all authoritative inputs immediately before delivery."""
            return (not unavailable() and selected_channel() == channel
                    and snapshot_loader(clock()).fingerprint() == fingerprint)

        pending = store.snapshot()["pending"]
        if pending is not None:
            if pending["status"] == "sent":
                sent_at = datetime.fromisoformat(pending["sent_at"])
                sufficient = all(
                    snapshot.evidence.get(flag, ContextEvidence()).effective_value is not None
                    and snapshot.evidence[flag].recorded_at is not None
                    and snapshot.evidence[flag].recorded_at >= sent_at
                    for flag in pending["flags"])
                if sufficient and fresh() and store.close(pending["id"], outcome="resolved", now=clock()):
                    return "resolved"
                return "waiting_answer"
            if (pending.get("correlation") == fingerprint and fresh()
                    and pending["channel"] == channel):
                return deliver_question(store=store, question=_request(pending), now=clock(),
                    selected_channel=selected_channel, still_current=fresh, budget=budget,
                    sender=sender, record=record, current_time=clock)
            # Legacy/unrelated correlation never permits blind replay.
            return "delivery_uncertain"
        question = prepare_question(candidates=snapshot.candidates,
            runtime_context=snapshot.runtime_context, evidence=snapshot.evidence,
            channel=channel, now=now, history_marker=snapshot.history_marker,
            classify=classify, still_current=fresh, current_time=clock,
            evaluation_claim=store.claim_evaluation, question_allowed=store.can_ask)
        if question is None:
            relevant = any(0 < (row.slot_at - now).total_seconds() <= 900
                and candidate_unknown_flags(row, snapshot.runtime_context, snapshot.evidence, now=now)
                for row in snapshot.candidates)
            return "deferred" if relevant else "not_due"
        question = replace(question, correlation=fingerprint)
        return deliver_question(store=store, question=question, now=clock(),
            selected_channel=selected_channel, still_current=fresh, budget=budget,
            sender=sender, record=record, current_time=clock)
    except (OSError, ValueError, TypeError, RuntimeError, TimeoutError):
        return "error"
