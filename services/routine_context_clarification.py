"""Select routine context questions from consequential scoped uncertainty."""

from __future__ import annotations

import json
from contextlib import contextmanager
from contextvars import ContextVar
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
from itertools import product
from typing import Any

from memory.routine_context_clarification import ClarificationStore, QuestionRequest
from services.routine_conditions import evaluate_routine_conditions
from services.routine_context_evidence import ContextEvidence, VOLATILE_FLAGS


_MATRIX_REPLY_TARGET: ContextVar[str | None] = ContextVar("routine_matrix_reply_target", default=None)


def current_matrix_reply_target() -> str | None:
    """Read transport-authenticated Reply correlation in this task/thread only."""
    return _MATRIX_REPLY_TARGET.get()


@contextmanager
def matrix_reply_scope(target: str | None) -> Iterator[None]:
    """Propagate correlation through async wrappers and asyncio.to_thread safely."""
    token = _MATRIX_REPLY_TARGET.set(target)
    try:
        yield
    finally:
        _MATRIX_REPLY_TARGET.reset(token)


def is_current_context_question_target(target: str) -> bool:
    """Recognize only an exact confirmed Matrix question, never an approval."""
    from pathlib import Path
    from config import BASE_DIR
    from memory.routine_context_clarification import ATHENS

    path = Path(BASE_DIR) / "astakos_routine_context_questions.json"
    if not path.is_file():
        return False
    try:
        pending = ClarificationStore(path).snapshot()["pending"]
        return bool(pending and pending["status"] == "sent" and pending["history_recorded"]
                    and pending["channel"] == "matrix" and pending["external_id"] == target
                    and datetime.now(ATHENS) < datetime.fromisoformat(pending["slot_at"]))
    except (OSError, ValueError, RuntimeError, TimeoutError):
        return False


def _condition_flags(condition: Mapping[str, Any]) -> set[str]:
    """Read structured flag identifiers from existing condition payloads."""
    raw = condition.get("condition_payload")
    try:
        payload = json.loads(raw) if isinstance(raw, str) else raw
    except (TypeError, ValueError):
        return set()
    if not isinstance(payload, Mapping):
        return set()
    kind = condition.get("condition_type")
    flag = payload.get("flag")
    if kind == "context_flag":
        if isinstance(flag, str):
            return {flag} & set(VOLATILE_FLAGS)
        return set(payload) & set(VOLATILE_FLAGS)
    if kind == "location":
        if flag in {"user_at_home", "user_out_of_home", "out_of_home"}:
            return {"user_out_of_home"}
        if flag in {"at_home", "home", "family_at_home"}:
            return {"family_at_home"}
    return set()


def consequential_unknown_flags(
    conditions: Sequence[dict[str, Any]],
    runtime_context: Mapping[str, Any],
    evidence: Mapping[str, ContextEvidence],
    *,
    now: datetime,
) -> tuple[str, ...]:
    """Return unknown flags whose value can change final condition allowance."""
    dependencies = set().union(*(_condition_flags(row) for row in conditions)) if conditions else set()
    unknown = tuple(flag for flag in VOLATILE_FLAGS
                    if flag in dependencies and evidence.get(flag, ContextEvidence()).effective_value is None)
    if not unknown:
        return ()
    base = dict(runtime_context)
    for flag in VOLATILE_FLAGS:
        base[flag] = evidence.get(flag, ContextEvidence()).effective_value
    outcomes: dict[tuple[bool, ...], bool] = {}
    for assignment in product((False, True), repeat=len(unknown)):
        projected = dict(base)
        projected.update(zip(unknown, assignment))
        outcomes[assignment] = bool(evaluate_routine_conditions(
            list(conditions), projected, now=now,
        )["allowed"])
    consequential: list[str] = []
    for index, flag in enumerate(unknown):
        if any(outcome != outcomes[assignment[:index] + (not assignment[index],) + assignment[index + 1:]]
               for assignment, outcome in outcomes.items()):
            consequential.append(flag)
    return tuple(consequential)


@dataclass(frozen=True)
class RoutineCandidate:
    """One already-eligible upcoming slot supplied by the routine scheduler."""

    id: str
    name: str
    slot_at: datetime
    conditions: tuple[dict[str, Any], ...]
    dependencies: tuple[str, ...] = ()


def candidate_unknown_flags(
    candidate: RoutineCandidate, context: Mapping[str, Any],
    evidence: Mapping[str, ContextEvidence], *, now: datetime,
) -> tuple[str, ...]:
    """Combine validated semantic dependencies with consequential conditions."""
    scoped = consequential_unknown_flags(candidate.conditions, context, evidence, now=now)
    if scoped:
        return scoped
    # Semantic dependencies cannot undo a known independently blocking condition.
    from services.routine_context import project_routine_context
    if not evaluate_routine_conditions(list(candidate.conditions),
                                        project_routine_context(context, evidence), now=now)["allowed"]:
        return ()
    return tuple(flag for flag in VOLATILE_FLAGS if flag in candidate.dependencies
                 and evidence.get(flag, ContextEvidence()).effective_value is None)


def prepare_question(
    *, candidates: Sequence[RoutineCandidate], runtime_context: Mapping[str, Any],
    evidence: Mapping[str, ContextEvidence], channel: str, now: datetime,
    history_marker: str, classify: Callable[[dict[str, Any]], Any],
    still_current: Callable[[], bool],
    current_time: Callable[[], datetime] | None = None,
    evaluation_claim: Callable[..., bool] | None = None,
) -> QuestionRequest | None:
    """Ask a tool-free model to phrase one validated, still-relevant question."""
    if channel not in {"matrix", "telegram"} or now.tzinfo is None:
        return None
    eligible: list[tuple[RoutineCandidate, tuple[str, ...]]] = []
    for candidate in candidates:
        if candidate.slot_at.tzinfo is None:
            continue
        remaining = (candidate.slot_at - now).total_seconds()
        if not 0 < remaining <= 15 * 60:
            continue
        flags = candidate_unknown_flags(candidate, runtime_context, evidence, now=now)
        if flags:
            eligible.append((candidate, flags))
    if not eligible:
        return None
    eligible = eligible[:5]
    packet = {
        "now": now.isoformat(),
        "candidates": [
            {"id": item.id, "name": item.name[:200], "slot_at": item.slot_at.isoformat(),
             "unknown_flags": list(flags)}
            for item, flags in eligible
        ],
        "evidence": {flag: {"status": evidence[flag].status,
                             "reason": evidence[flag].reason,
                             "effective_value": evidence[flag].effective_value,
                             "recorded_at": (evidence[flag].recorded_at.isoformat()
                                             if evidence[flag].recorded_at else None),
                             "valid_until": (evidence[flag].valid_until.isoformat()
                                             if evidence[flag].valid_until else None)}
                     for flag in VOLATILE_FLAGS if flag in evidence},
    }
    fingerprint = sha256(json.dumps(
        [history_marker, channel, packet["candidates"], packet["evidence"],
         {key: runtime_context.get(key) for key in sorted(runtime_context)
          if key not in VOLATILE_FLAGS}],
        ensure_ascii=False, sort_keys=True, default=str,
    ).encode("utf-8")).hexdigest()
    if evaluation_claim is not None and not evaluation_claim(fingerprint, now=now):
        return None
    try:
        decision = classify(packet)
    except Exception:
        return None
    if not still_current() or not isinstance(decision, dict) or set(decision) != {
            "routine_ids", "flags", "question"}:
        return None
    ids, flags, question = decision["routine_ids"], decision["flags"], decision["question"]
    if (not isinstance(ids, list) or not 1 <= len(ids) <= 5
            or not isinstance(flags, list) or not 1 <= len(flags) <= 5
            or not isinstance(question, str) or not 1 <= len(question.strip()) <= 500):
        return None
    selected = [item for item, _ in eligible if item.id in ids]
    if (any(not isinstance(value, str) for value in ids)
            or len(selected) != len(ids) or len(set(ids)) != len(ids)
            or any(not isinstance(value, str) for value in flags)
            or len(set(flags)) != len(flags)):
        return None
    allowed = set().union(*(set(unknown) for item, unknown in eligible if item.id in ids))
    if not set(flags) <= allowed:
        return None
    checked_at = current_time() if current_time is not None else now
    slot = min(item.slot_at for item in selected)
    if checked_at >= slot:
        return None
    sorted_flags = tuple(flag for flag in VOLATILE_FLAGS if flag in flags)
    identity = sha256(json.dumps([history_marker, ids, sorted_flags, slot.isoformat()],
                                 ensure_ascii=False).encode("utf-8")).hexdigest()[:32]
    topic = sha256(json.dumps(sorted_flags).encode("utf-8")).hexdigest()[:32]
    return QuestionRequest(
        id=identity, topic=topic, routine_ids=tuple(ids), flags=sorted_flags,
        slot_at=slot, question=question.strip(), channel=channel,
    )


def deliver_question(
    *, store: ClarificationStore, question: QuestionRequest, now: datetime,
    selected_channel: Callable[[], str], still_current: Callable[[], bool],
    budget: Callable[[], bool], sender: Callable[[str, str, str], Any],
    record: Callable[..., Any],
    current_time: Callable[[], datetime] | None = None,
) -> str:
    """Send once, holding uncertainty and repairing history from durable receipt."""
    clock = current_time if current_time is not None else lambda: now
    try:
        sent_in_this_call = False
        snapshot = store.snapshot()
        confirmed = next((row for row in snapshot["requests"]
                          if row["id"] == question.id and row["external_id"]), None)
        # Recording an already confirmed receipt never authorizes another send.
        # Repair must survive an expired slot or a changed external channel.
        if confirmed is not None:
            if confirmed["history_recorded"]:
                return "recorded"
            return _record_question_receipt(store, confirmed, record)
        if (selected_channel() != question.channel or not still_current()
                or clock() >= question.slot_at):
            return "stale"
        pending = snapshot["pending"]
        if pending is None:
            if not store.reserve(question, now=clock()):
                return "held"
            pending = store.snapshot()["pending"]
        if pending is None or pending["id"] != question.id:
            return "held"
        if pending["status"] == "reserved":
            if not still_current() or selected_channel() != question.channel:
                return "stale"
            if not store.begin_send(question.id, now=clock(), budget=budget, current_time=clock):
                return "held"
            pending = store.snapshot()["pending"]
        elif pending["status"] == "sending" and question.channel != "matrix":
            return "held"
        if pending is None:
            return "held"
        if pending["status"] == "sending":
            if (not still_current() or selected_channel() != question.channel
                    or clock() >= question.slot_at):
                return "stale"
            receipt = sender(
                question.channel, pending["question"],
                "astakos-routine-question-" + question.id,
            )
            if (getattr(receipt, "channel", None) != question.channel
                    or not getattr(receipt, "external_id", None)):
                return "held"
            if not store.mark_sent(question.id, external_id=str(receipt.external_id), now=clock()):
                return "held"
            sent_in_this_call = True
            pending = store.snapshot()["pending"]
        if pending is None or pending["status"] != "sent":
            return "held"
        if _record_question_receipt(store, pending, record) != "recorded":
            return "held"
        return "delivered" if sent_in_this_call else "recorded"
    except (OSError, ValueError, RuntimeError, TimeoutError):
        return "held"


def _record_question_receipt(
    store: ClarificationStore, pending: dict, record: Callable[..., Any],
) -> str:
    """Repair canonical history with the original immutable delivery identity."""
    if pending["history_recorded"]:
        return "recorded"
    record(
        role="assistant", content=pending["question"], channel=pending["channel"],
        agent="Routine_Context", message_id="routine-clarification-" + pending["id"],
        timestamp=datetime.fromisoformat(pending["sent_at"]),
        metadata={"external_message_id": pending["external_id"],
                  "routine_context_question_id": pending["id"]},
    )
    return "recorded" if store.mark_recorded(pending["id"]) else "held"


@dataclass(frozen=True)
class QuestionAnswer:
    """Tell channel arbitration whether a context reply owns this message."""

    consumed: bool = False
    outcome: str = "unrelated"

    @property
    def reply(self) -> str:
        """Render a localized acknowledgement, never an action-success claim."""
        from core.i18n import t

        key = self.outcome if self.outcome in {"resolved", "partial", "declined", "deferred"} else "deferred"
        return t("routine_context." + key)


def process_question_answer(
    *, store: ClarificationStore, user_text: str, channel: str, now: datetime,
    trusted_owner: bool, external_derived: bool = False,
    competing_confirmation: bool = False, reply_to_id: str | None = None,
    current_time: Callable[[], datetime] | None = None,
    still_authoritative: Callable[[], bool] = lambda: True,
) -> QuestionAnswer:
    """Interpret a delivered question, then commit canonical flags once.

    Channel adapters must supply authenticated owner provenance and competing
    approval/completion/draft/asset state. This function never executes tools,
    sends messages or marks any routine complete.
    """
    if (not trusted_owner or external_derived or competing_confirmation
            or channel not in {"web", "telegram", "matrix"}):
        return QuestionAnswer()
    clock = current_time if current_time is not None else lambda: now
    try:
        pending = store.snapshot()["pending"]
        if (pending is None or pending["status"] != "sent" or not pending["history_recorded"]
                or not (datetime.fromisoformat(pending["sent_at"]) <= now <= clock()
                        < datetime.fromisoformat(pending["slot_at"]))
                or (reply_to_id is not None and reply_to_id != pending["external_id"])
                or not still_authoritative()):
            return QuestionAnswer()
        from services.context_extractor import extract_and_update_context_flags

        result = extract_and_update_context_flags(
            user_text, channel=channel,
            clarification_context={"question": pending["question"], "flags": pending["flags"]},
            clarification_commit=lambda persist: store.commit_answer(
                pending["id"], received_at=now, current_time=clock, persist=persist,
                still_authoritative=still_authoritative,
            ),
        )
        if result is None:
            return QuestionAnswer(False, "uncertain")
        if result.relation == "refused":
            if still_authoritative() and store.close(pending["id"], outcome="declined", now=clock()):
                return QuestionAnswer(True, "declined")
            return QuestionAnswer(False, "uncertain")
        if result.relation == "related" and result.applied_flags:
            completed = set(pending["flags"]) <= result.applied_flags
            return QuestionAnswer(True, "resolved" if completed else "partial")
        if result.relation == "related":
            return QuestionAnswer(True, "deferred")
        return QuestionAnswer(False, result.relation)
    except (OSError, ValueError, RuntimeError, TimeoutError):
        return QuestionAnswer(False, "uncertain")


def context_confirmation_conflict() -> bool:
    """Defer to actionable confirmations across the shared conversation."""
    from core.approval import list_pending
    from core.messenger_draft import active_draft_status
    from memory.routine_db import load_pending_confirmations
    from memory.pending_assets import get_latest_pending_asset_any

    return bool(list_pending() or load_pending_confirmations() or active_draft_status()[0]
                or any(get_latest_pending_asset_any(channel)
                       for channel in ("web", "telegram", "matrix")))


def try_context_question_reply(
    user_text: str, channel: str, *, trusted_owner: bool,
    external_derived: bool = False, reply_to_id: str | None = None,
) -> QuestionAnswer:
    """Production adapter; an absent ledger is a no-op and never creates state."""
    from pathlib import Path
    from config import BASE_DIR
    from memory.routine_context_clarification import ATHENS

    path = Path(BASE_DIR) / "astakos_routine_context_questions.json"
    if not trusted_owner or external_derived or not path.is_file():
        return QuestionAnswer()
    try:
        if channel == "matrix" and reply_to_id is None:
            reply_to_id = current_matrix_reply_target()
        version = _answer_version()
        return process_question_answer(
            store=ClarificationStore(path), user_text=user_text, channel=channel,
            now=datetime.now(ATHENS), current_time=lambda: datetime.now(ATHENS),
            trusted_owner=trusted_owner, external_derived=external_derived,
            competing_confirmation=context_confirmation_conflict(), reply_to_id=reply_to_id,
            still_authoritative=lambda: (
                not context_confirmation_conflict() and _answer_version() == version),
        )
    except Exception as exc:
        print(f"[RoutineContext]: answer deferred ({type(exc).__name__})")
        return QuestionAnswer(False, "uncertain")


def _answer_version() -> str:
    """Version canonical stored state, GPS evidence and shared history before inference.

    Do not include continually changing age counters. Re-read this packet inside
    the ledger commit gate, immediately before the canonical writer executes.
    """
    from memory.conversation_history import get_max_rowid
    from memory.routine_db import get_context_state
    from memory.routine_context_clarification import ATHENS
    from services.routine_context import build_routine_context_evidence
    evidence = build_routine_context_evidence(datetime.now(ATHENS))
    packet = [get_max_rowid(),
              {flag: get_context_state(flag) for flag in VOLATILE_FLAGS},
              {flag: (item.effective_value, item.source, item.recorded_at,
                      item.valid_until, item.status, item.reason)
               for flag, item in evidence.items()}]
    return sha256(json.dumps(packet, sort_keys=True, default=str).encode()).hexdigest()
