# ================================================================
# Project: Astakos AI Agent 🦞
# Description: Explicit Routine Lifecycle State Machine
# Copyright (c) 2026 - All Rights Reserved
# ================================================================

from core.i18n import t
from enum import Enum
from core.exceptions import RoutineConflictError


class RoutineState(Enum):
    LEARNED         = "learned"          # 1st report — inactive, does not notify
    ACTIVE          = "active"           # ≥2 reports — alerts normally
    TRIGGER_PENDING = "trigger_pending"  # Notification sent, awaiting reply
    CONFIRMED       = "confirmed"        # User said "yes" → immediately ACTIVE
    IGNORED         = "ignored"          # Timeout — cooldown doubled → ACTIVE
    DISMISSED       = "dismissed"        # User said "no" → decay → ACTIVE/DECAYED
    DECAYED         = "decayed"          # Confidence < 0.1 → to ARCHIVED
    ARCHIVED        = "archived"         # Dead — does not notify, only re-teach is allowed


# ────────────────────────────────────────────────────────────────
# VALID TRANSITIONS MAP
# ────────────────────────────────────────────────────────────────

VALID_TRANSITIONS: dict[RoutineState, list[RoutineState]] = {
    RoutineState.LEARNED: [
        RoutineState.ACTIVE,     # 2nd report
        RoutineState.ARCHIVED,   # manual delete
    ],
    RoutineState.ACTIVE: [
        RoutineState.TRIGGER_PENDING,  # notification sent
        RoutineState.DECAYED,          # confidence drops < 0.1
        RoutineState.ARCHIVED,         # manual delete
    ],
    RoutineState.TRIGGER_PENDING: [
        RoutineState.CONFIRMED,
        RoutineState.IGNORED,
        RoutineState.DISMISSED,
        RoutineState.DECAYED,
        RoutineState.ACTIVE,
    ],
    RoutineState.CONFIRMED: [
        RoutineState.ACTIVE,      # auto-immediate after confirm
    ],
    RoutineState.IGNORED: [
        RoutineState.ACTIVE,      # cooldown expired, ready again
        RoutineState.DECAYED,     # confidence < 0.1 after many ignores
    ],
    RoutineState.DISMISSED: [
        RoutineState.ACTIVE,      # confidence still OK after decay
        RoutineState.DECAYED,     # confidence < 0.1
    ],
    RoutineState.DECAYED: [
        RoutineState.ARCHIVED,    # final death
        RoutineState.ACTIVE,      # re-taught (new upsert)
    ],
    RoutineState.ARCHIVED: [
        RoutineState.LEARNED,     # re-teach from scratch
    ],
}


def validate_transition(from_state: RoutineState, to_state: RoutineState) -> None:
    """
    Raises RoutineConflictError if the transition is not allowed.
    Usage: validate_transition(current_state, RoutineState.TRIGGER_PENDING)
    """
    if from_state == to_state:
        return
        
    allowed = VALID_TRANSITIONS.get(from_state, [])
    if to_state not in allowed:
        raise RoutineConflictError(
            t("core.routine_state.invalid_transition", from_state=from_state.value, to_state=to_state.value),
            context={
                "from":    from_state.value,
                "to":      to_state.value,
                "allowed": [s.value for s in allowed],
            }
        )


def is_notifiable(state: RoutineState) -> bool:
    """True if the routine can notify now."""
    return state == RoutineState.ACTIVE


def state_from_str(s: str) -> RoutineState:
    """Safe parse — unknown strings → LEARNED (safe default)."""
    try:
        return RoutineState(s)
    except ValueError:
        return RoutineState.LEARNED
