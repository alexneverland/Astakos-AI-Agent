"""Bounded routine dependency decisions on the existing slow worker."""
from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime
from hashlib import sha256
import json
from pathlib import Path
import threading
from functools import wraps
from typing import Any

from memory.routine_context_clarification import ClarificationStore
from services.routine_context_clarification import (
    RoutineCandidate, _condition_flags, candidate_unknown_flags,
)
from services.routine_context_evidence import ContextEvidence, VOLATILE_FLAGS

_queue_lock = threading.Lock()
_queued = False
_dispatch_lock = threading.RLock()


def serialized_routine_dispatch(callback: Callable[..., Any]) -> Callable[..., Any]:
    """Serialize periodic and answer-driven dispatch on the existing runtime."""
    @wraps(callback)
    def dispatch(*args: Any, **kwargs: Any) -> Any:
        """Skip a competing tick; the owner of the lock performs normal dispatch."""
        if not _dispatch_lock.acquire(blocking=False):
            return None
        try:
            return callback(*args, **kwargs)
        finally:
            _dispatch_lock.release()
    return dispatch


def drain_context_answer_dispatch() -> bool:
    """Consume Web or local answer wakeups from the existing external fast worker.

    Its existing two-second queue wait bounds idle wakeup latency without a new
    scheduler/thread. Only the active external process may call normal dispatch;
    its normal gates and deadline revalidation remain authoritative.
    """
    from clients import telegram_bot as bot
    from config import BASE_DIR
    from core.messaging_channel import resolve_external_channel
    from memory.routine_context_clarification import ATHENS
    if (bot._external_background_runtime_channel != resolve_external_channel()
            or bot.shutdown_event.is_set()):
        return False
    path = Path(BASE_DIR) / "astakos_routine_context_questions.json"
    if not path.is_file() or not _dispatch_lock.acquire(blocking=False):
        return False
    try:
        if not ClarificationStore(path).claim_dispatch(now=datetime.now(ATHENS)):
            return False
        bot.job_check_routines()
        return True
    finally:
        _dispatch_lock.release()


def dependency_key(routine: RoutineCandidate, context: Mapping[str, Any]) -> str:
    """Tie interpretation to the stored routine/slot, not volatile polling ages."""
    data = [routine.id, routine.name, routine.slot_at.isoformat(), routine.conditions,
            {key: value for key, value in context.items() if key not in VOLATILE_FLAGS}]
    return "dep-" + sha256(json.dumps(data, sort_keys=True, default=str).encode()).hexdigest()


def resolve_dependencies(
    routine: RoutineCandidate, context: Mapping[str, Any], store: ClarificationStore,
    now: datetime, classify: Callable[[dict[str, Any]], Any] | None = None,
) -> tuple[str, ...] | None:
    """Use explicit condition identifiers first, otherwise one tool-free decision."""
    structured = set().union(*(_condition_flags(row) for row in routine.conditions)) if routine.conditions else set()
    if structured:
        return ()  # Explicit conditions are evaluated separately, not reinterpreted.
    key = dependency_key(routine, context)
    cached = store.evaluation_flags(key, now=now)
    if cached is not None or classify is None:
        return cached
    if not store.claim_evaluation(key, now=now):
        return None
    try:
        result = classify({"routine": {"id": routine.id, "name": routine.name[:500],
                           "slot_at": routine.slot_at.isoformat(), "conditions": routine.conditions},
                           "context": dict(context), "flags": list(VOLATILE_FLAGS)})
        flags = result.get("flags") if isinstance(result, dict) and set(result) == {"flags"} else None
        if (not isinstance(flags, list) or len(flags) > 5
                or any(flag not in VOLATILE_FLAGS for flag in flags)
                or len(set(flags)) != len(flags)):
            return None
        ordered = tuple(flag for flag in VOLATILE_FLAGS if flag in flags)
        store.record_evaluation_flags(key, ordered, now=now)
        return ordered
    except (OSError, ValueError, TypeError, RuntimeError, TimeoutError):
        return None


def routine_context_block(
    routine: RoutineCandidate, context: Mapping[str, Any],
    evidence: Mapping[str, ContextEvidence], store: ClarificationStore, now: datetime,
) -> bool:
    """Hold unknown relevant context; never let null suppression imply certainty."""
    from dataclasses import replace
    from services.routine_conditions import evaluate_routine_conditions
    from services.routine_context import project_routine_context
    from services.routine_context_clarification import consequential_unknown_flags
    if (not consequential_unknown_flags(routine.conditions, context, evidence, now=now)
            and not evaluate_routine_conditions(list(routine.conditions),
                    project_routine_context(context, evidence), now=now)["allowed"]):
        return False  # Preserve independent known blockers and their normal diagnostics.
    flags = resolve_dependencies(routine, context, store, now)
    if flags is None:
        return any(evidence.get(flag, ContextEvidence()).effective_value is None for flag in VOLATILE_FLAGS)
    return bool(candidate_unknown_flags(replace(routine, dependencies=flags), context, evidence, now=now))


def question_blocks_dispatch(
    store: ClarificationStore, now: datetime, routine: RoutineCandidate,
) -> bool:
    """Do not introduce another confirmation or replay a questioned past slot."""
    state = store.snapshot()
    pending = state["pending"]
    if pending and datetime.fromisoformat(pending["slot_at"]) > now:
        return True
    return any(routine.id in row["routine_ids"]
               and datetime.fromisoformat(row["slot_at"]) == routine.slot_at
               and now >= routine.slot_at for row in state["requests"])


def dispatch_context_current(
    routines: tuple[RoutineCandidate, ...], context: Mapping[str, Any],
    store: ClarificationStore, now: datetime, *, late_grace_minutes: int | None = None,
) -> bool:
    """Revalidate canonical gates; late recovery requires an explicit grace window."""
    from clients import telegram_bot as bot
    from memory import routine_db as db
    from services.routine_context import build_runtime_routine_context, build_routine_context_evidence, project_routine_context
    if bot.is_quiet_hours() or bot.is_proactive_muted() or bot._active_routine_pause_until():
        return False
    evidence = build_routine_context_evidence(now)
    current = project_routine_context(build_runtime_routine_context(now), evidence)
    if current != context:
        return False
    for routine in routines:
        rid = int(routine.id)
        eligible = {str(row["id"]): row for row in db.get_eligible_preemptive_routines_for_day(
            routine.slot_at.strftime("%A"), now=now)}
        row = eligible.get(routine.id)
        if (row is None or row["time"] != routine.slot_at.strftime("%H:%M")
                or row["event"] != routine.name):
            return False
        timely = 0 <= (routine.slot_at - now).total_seconds() <= 900
        if late_grace_minutes is not None:
            timely = (type(late_grace_minutes) is int and late_grace_minutes > 0
                      and 0 < (now - routine.slot_at).total_seconds() <= late_grace_minutes * 60)
        if (not timely
                or question_blocks_dispatch(store, now, routine)
                or db.is_routine_temporarily_inactive_meta(db.get_routine_schedule_meta(rid), now=now)[0]
                or db.get_routine_muted_until(rid)
                or bot.is_duplicate_routine(rid, db.get_routine_notify_info(rid)["cooldown_hours"])
                or tuple(db.get_routine_conditions(rid)) != routine.conditions
                or routine_context_block(routine, current, evidence, store, now)):
            return False
    return True


def classify_packet(packet: dict[str, Any], *, dependencies: bool = False) -> Any:
    """Call a tool-free model with only provenance-wrapped bounded data."""
    from langchain_core.messages import HumanMessage, SystemMessage
    from core.brain import llm, safe_llm_invoke
    from core.untrusted_content import format_untrusted_tool_result
    from core.utils import extract_json_from_text
    from config import RESPONSE_LANGUAGE
    name = "routine_context_dependencies.md" if dependencies else "routine_context_question.md"
    prompt = (Path(__file__).resolve().parents[1] / "prompts" / name).read_text(encoding="utf-8")
    reference = {**packet, "language": RESPONSE_LANGUAGE}
    if not dependencies:
        from core.utils import load_agent_prompt
        # Share conversational personality without importing Chat's tool policy.
        personality = load_agent_prompt("Chat_Agent").partition("═══ PERSONALITY ═══")[2].partition("═══")[0].strip()
        prompt = personality + "\n\n" + prompt
        reference["recent_conversation"] = _question_wording_history()
    response = safe_llm_invoke(llm, [SystemMessage(content=prompt), HumanMessage(content=
        format_untrusted_tool_result("routine context evidence", json.dumps(
            reference, default=str, ensure_ascii=False)))])
    content = response.content
    if isinstance(content, list):
        content = "".join(item.get("text", "") for item in content if isinstance(item, dict))
    return extract_json_from_text(str(content))


def _question_wording_history() -> list[dict[str, Any]]:
    """Read bounded shared dialogue for style, never for authoritative flags."""
    from memory.conversation_history import default_session_id, load_messages
    try:
        messages = load_messages(limit=6, session_id=default_session_id())
        return [{"role": row["role"], "channel": row.get("channel"),
                 "timestamp": row.get("timestamp"), "content": row["content"][:800]}
                for row in messages[-6:]
                if row.get("role") in {"user", "assistant"}
                and isinstance(row.get("content"), str)]
    except Exception:
        # Optional wording context must not disable the canonical question path.
        return []


def load_poll_snapshot(now: datetime, store: ClarificationStore, *, classify: Callable | None = None):
    """Read eligible slots through routine/history abstractions, never raw SQL."""
    from dataclasses import replace
    from datetime import timedelta
    from clients import telegram_bot as bot
    from memory import routine_db as db
    from memory.conversation_history import get_max_rowid
    from services.routine_conditions import evaluate_routine_conditions
    from services.routine_context import build_runtime_routine_context, build_routine_context_evidence, project_routine_context
    from services.routine_context_clarification_poll import PollSnapshot

    evidence = build_routine_context_evidence(now)
    context = project_routine_context(build_runtime_routine_context(now), evidence)
    catalog = []
    for date in {now.date(), (now + timedelta(minutes=15)).date()}:
        for row in db.get_eligible_preemptive_routines_for_day(date.strftime("%A"), now=now):
            try:
                hour, minute = map(int, row["time"].split(":"))
                slot = datetime.combine(date, datetime.min.time(), tzinfo=now.tzinfo).replace(hour=hour, minute=minute)
            except (TypeError, ValueError):
                continue
            if not 0 < (slot - now).total_seconds() <= 900:
                continue
            rid = row["id"]
            if (db.is_routine_temporarily_inactive_meta(db.get_routine_schedule_meta(rid), now=now)[0]
                    or db.get_routine_muted_until(rid)
                    or bot.is_duplicate_routine(rid, db.get_routine_notify_info(rid)["cooldown_hours"])):
                continue
            conditions = tuple(db.get_routine_conditions(rid))
            routine = RoutineCandidate(str(rid), row["event"], slot, conditions)
            if (not candidate_unknown_flags(routine, context, evidence, now=now)
                    and not evaluate_routine_conditions(list(conditions), context, now=now)["allowed"]):
                continue
            meta = db.get_routine_condition(rid)
            catalog.append((routine, meta))
    catalog.sort(key=lambda item: (-item[1].get("priority", 0), -bool(item[0].conditions), int(item[0].id)))
    candidates, groups = [], set()
    for routine, meta in catalog:
        # Preserve the existing scheduler's group resolution; no new NL parser.
        group = meta.get("conflict_group") or (routine.name.lower().split() or [routine.name.lower()])[0]
        if group in groups:
            continue
        groups.add(group)
        flags = resolve_dependencies(routine, context, store, now, classify)
        if flags is not None:
            candidates.append(replace(routine, dependencies=flags))
        if len(groups) >= 5:
            break
    return PollSnapshot(tuple(candidates), context, evidence, str(get_max_rowid()))


def clarification_unavailable() -> bool | str:
    """Apply existing selected-process, quiet, activity and ambiguity gates."""
    from clients import telegram_bot as bot
    from core.messaging_channel import resolve_external_channel
    from memory.event_log import has_recent_reminder_delivery
    from services.routine_context_clarification import context_confirmation_conflict
    if bot.shutdown_event.is_set() or bot._external_background_runtime_channel != resolve_external_channel():
        return "inactive_runtime"
    if bot.is_quiet_hours():
        return "quiet"
    if bot.is_proactive_muted():
        return "muted"
    if bot._active_routine_pause_until():
        return "paused"
    if bot.should_skip_proactive_for_recent_activity(quiet=True):
        return "recent_activity"
    if has_recent_reminder_delivery(datetime.now()):
        return "recent_reminder"
    if context_confirmation_conflict():
        return "confirmation"
    return False


def schedule_context_clarification(enqueue: Callable) -> None:
    """Coalesce existing routine ticks without adding a scheduler or interval."""
    global _queued
    with _queue_lock:
        if _queued:
            return
        _queued = True
    try:
        enqueue(run_context_clarification_job)
    except Exception:
        _release_queue()
        raise


def _release_queue() -> None:
    """Release only the in-process debounce, not durable question state."""
    global _queued
    with _queue_lock:
        _queued = False


def run_context_clarification_job() -> None:
    """Use the selected external worker and canonical single-history transport."""
    from uuid import uuid4
    run_id = uuid4().hex
    log_event = None
    channel = None
    try:
        from memory.event_log import log_event
        from memory.routine_context_clarification import ATHENS
        from config import BASE_DIR
        from clients import telegram_bot as bot
        from core.messaging_channel import resolve_external_channel
        from memory.conversation_history import append_message
        from services.external_delivery import external_delivery_router as router
        from services.routine_context_clarification_poll import run_clarification_poll
        store = ClarificationStore(Path(BASE_DIR) / "astakos_routine_context_questions.json")
        channel = resolve_external_channel()
        # Dependency generation happens once up front, outside short ledger locks.
        if not clarification_unavailable():
            load_poll_snapshot(datetime.now(ATHENS), store,
                               classify=lambda packet: classify_packet(packet, dependencies=True))
        outcome = run_clarification_poll(store=store, clock=lambda: datetime.now(ATHENS),
            selected_channel=resolve_external_channel,
            snapshot_loader=lambda now: load_poll_snapshot(now, store),
            unavailable=clarification_unavailable, classify=classify_packet,
            budget=bot.can_send_proactive,
            sender=lambda channel, text, identity: (
                router.send_idempotent_matrix_text(text, transaction_id=identity)
                if channel == "matrix" else router.send_text_to(channel, text)),
            record=append_message)
    except Exception:
        outcome = "error"
    finally:
        _release_queue()
    if outcome in {"error", "delivered"}:
        print(f"[RoutineContext]: clarification poll {outcome}")
    if log_event is not None:
        log_event("routines", "context_clarification_poll", outcome=outcome,
                  run_id=run_id, entry_point="routine_scheduler", channel=channel,
                  debug_type="scheduler_decision", debug_source="context_clarification",
                  debug_effect=outcome)


# The worker still executes this poll and reports errors; no-op ticks need no
# terminal banner. Structured decision telemetry above remains available.
run_context_clarification_job.quiet_queue_log = True
