"""Pending routine decisions received through the trusted Matrix channel."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from langchain_core.messages import SystemMessage


@dataclass(frozen=True)
class MatrixRoutineDraftOffer:
    """Deferred trusted authorization for one persisted routine draft offer."""

    routine_id: int
    sent_at: datetime
    event_name: str
    context: SystemMessage


def process_pending_routine_confirmation(
    user_text: str,
    *,
    channel: str = "matrix",
) -> SystemMessage | MatrixRoutineDraftOffer | None:
    """Apply one validated pending-routine decision and return trusted graph context."""
    if channel != "matrix":
        raise ValueError("Matrix routine completion requires channel='matrix'")

    from core.messenger_draft import active_draft_status
    from memory import routine_db
    from memory.event_log import log_event
    from services.routine_completion_context import build_routine_completion_context
    from services.routine_completion_helper import decide_completion
    from services.routine_completion_selector import select_routine

    pending = routine_db.load_pending_confirmations()
    if not pending:
        return _process_nonpending_routine(user_text)

    candidates = {
        routine_id: (
            data.get("event", "") if isinstance(data, dict) else str(data)
        )
        for routine_id, data in pending.items()
    }
    active_draft, _, _ = active_draft_status()
    draft_offer_ids = frozenset(
        routine_id
        for routine_id, data in pending.items()
        if not active_draft and isinstance(data, dict) and data.get("draft_offer") is True
    )
    selector_candidates = {
        routine_id: (
            f"{event_name}\n[MESSENGER_DRAFT_OFFER]"
            if routine_id in draft_offer_ids else event_name
        )
        for routine_id, event_name in candidates.items()
    }
    decision = decide_completion(
        user_text=user_text,
        candidates=selector_candidates,
        pool="pending",
        semantic_selector=select_routine,
        draft_offer_ids=draft_offer_ids,
    )
    if decision.routine_id is None or decision.action == "pass_through":
        return _process_nonpending_routine(user_text)

    if decision.action == "draft":
        from services.routine_completion_context import get_pending_messenger_draft_offer

        accepted = get_pending_messenger_draft_offer(pending, decision.routine_id)
        pending_data = pending.get(decision.routine_id, {})
        sent_at = pending_data.get("sent_at") if isinstance(pending_data, dict) else None
        if accepted is None or not isinstance(sent_at, datetime):
            return None
        event_name = str(pending_data.get("event") or "").strip()
        return MatrixRoutineDraftOffer(
            routine_id=decision.routine_id,
            sent_at=sent_at,
            event_name=event_name,
            context=accepted.context,
        )

    completion_context = build_routine_completion_context()
    routine_id = decision.routine_id
    pending_data = pending.get(routine_id, {})
    event_name = (
        pending_data.get("event", "?")
        if isinstance(pending_data, dict)
        else str(pending_data)
    )

    if decision.action == "complete":
        routine_db.confirm_routine(routine_id)
        routine_db.mark_routine_responded(routine_id)
        routine_db.mark_routine_triggered_today(routine_id)
        event_type = "confirmed"
    elif decision.action == "acknowledge":
        routine_db.mark_routine_acknowledged(routine_id)
        event_type = "routine_acknowledged"
    elif decision.action == "skip_today":
        skip_result = routine_db.record_routine_skip_today(routine_id)
        log_event(
            "routines",
            "routine_skipped_today",
            routine_id=routine_id,
            event=event_name,
            skip_streak=skip_result["skip_streak"],
            cooldown_applied=skip_result["cooldown_applied"],
        )
        routine_db.remove_pending_confirmation(routine_id)
        _drop_pending_runtime_confirmation(routine_id)
        return completion_context
    elif decision.action == "pause":
        routine_db.pause_routine_indefinitely(routine_id)
        event_type = "routine_paused"
    else:
        return None

    routine_db.remove_pending_confirmation(routine_id)
    _drop_pending_runtime_confirmation(routine_id)
    log_event(
        "routines",
        event_type,
        routine_id=routine_id,
        event=event_name,
    )
    return completion_context


def _drop_pending_runtime_confirmation(routine_id: int) -> None:
    """Keep the shared scheduler snapshot consistent with persisted resolution."""
    from clients.telegram_bot import pending_routine_confirmations

    pending_routine_confirmations.pop(routine_id, None)


def _process_nonpending_routine(user_text: str) -> SystemMessage | None:
    """Resolve preemptive today or catalogue decisions without a pending prompt."""
    from memory import routine_db
    from memory.event_log import log_event
    from services.routine_completion_context import build_routine_completion_context
    from services.routine_completion_helper import decide_completion, relevant_catalog_candidates
    from services.routine_completion_selector import select_routine

    day_name = datetime.now().strftime("%A")
    today_candidates = {
        routine["id"]: routine["event"]
        for routine in routine_db.get_eligible_preemptive_routines_for_day(day_name)
    }
    decision = decide_completion(
        user_text=user_text,
        candidates=today_candidates,
        pool="today",
        semantic_selector=select_routine,
    )
    if decision.routine_id is not None and decision.action != "pass_through":
        routine_id = decision.routine_id
        event_name = today_candidates[routine_id]
        if decision.action == "complete":
            routine_db.mark_routine_triggered_today(routine_id)
            event_type = "preemptive_completed"
        elif decision.action == "acknowledge":
            routine_db.mark_routine_acknowledged(routine_id)
            event_type = "routine_acknowledged"
        elif decision.action == "skip_today":
            skip = routine_db.record_routine_skip_today(routine_id)
            event_type = "routine_skipped_today"
        elif decision.action == "pause":
            routine_db.pause_routine_indefinitely(routine_id)
            event_type = "routine_paused"
        else:
            return None
        details = {"skip_streak": skip["skip_streak"]} if decision.action == "skip_today" else {}
        log_event("routines", event_type, routine_id=routine_id, event=event_name, **details)
        return build_routine_completion_context()

    catalog = {
        routine["id"]: routine["event"]
        for routine in routine_db.get_active_routine_catalog()
    }
    pause_candidates = relevant_catalog_candidates(user_text, catalog)
    catalog_decision = decide_completion(
        user_text=user_text,
        candidates=pause_candidates,
        pool="catalog",
        semantic_selector=select_routine,
    )
    if catalog_decision.action != "pause" or catalog_decision.routine_id is None:
        return None
    routine_id = catalog_decision.routine_id
    routine_db.pause_routine_indefinitely(routine_id)
    log_event(
        "routines", "routine_paused", routine_id=routine_id,
        event=pause_candidates[routine_id],
    )
    return build_routine_completion_context()
