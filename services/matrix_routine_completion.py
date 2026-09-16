"""Pending routine decisions received through the trusted Matrix channel."""

from __future__ import annotations

from langchain_core.messages import SystemMessage


def process_pending_routine_confirmation(
    user_text: str,
    *,
    channel: str = "matrix",
) -> SystemMessage | None:
    """Apply one validated pending-routine decision and return trusted graph context."""
    if channel != "matrix":
        raise ValueError("Matrix routine completion requires channel='matrix'")

    from memory import routine_db
    from memory.event_log import log_event
    from services.routine_completion_context import build_routine_completion_context
    from services.routine_completion_helper import decide_completion
    from services.routine_completion_selector import select_routine

    pending = routine_db.load_pending_confirmations()
    if not pending:
        return None

    candidates = {
        routine_id: (
            data.get("event", "") if isinstance(data, dict) else str(data)
        )
        for routine_id, data in pending.items()
    }
    draft_offer_ids = frozenset(
        routine_id
        for routine_id, data in pending.items()
        if isinstance(data, dict) and data.get("draft_offer") is True
    )
    decision = decide_completion(
        user_text=user_text,
        candidates=candidates,
        pool="pending",
        semantic_selector=select_routine,
        draft_offer_ids=draft_offer_ids,
    )
    if decision.routine_id is None or decision.action in {"pass_through", "draft"}:
        return None

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
        return completion_context
    elif decision.action == "pause":
        routine_db.pause_routine_indefinitely(routine_id)
        event_type = "routine_paused"
    else:
        return None

    routine_db.remove_pending_confirmation(routine_id)
    log_event(
        "routines",
        event_type,
        routine_id=routine_id,
        event=event_name,
    )
    return completion_context
