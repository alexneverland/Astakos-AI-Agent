# ================================================================
# Project: Astakos AI Agent 🦞
# Developer: Lazaros (Piston-7)
# Description: Explicit Routine Lifecycle State Machine
# Copyright (c) 2026 - All Rights Reserved
# ================================================================

from enum import Enum
from core.exceptions import RoutineConflictError


class RoutineState(Enum):
    LEARNED         = "learned"          # 1η αναφορά — inactive, δεν ειδοποιεί
    ACTIVE          = "active"           # ≥2 αναφορές — ειδοποιεί κανονικά
    TRIGGER_PENDING = "trigger_pending"  # Notification στάλθηκε, περιμένει απάντηση
    CONFIRMED       = "confirmed"        # Χρήστης είπε "ναι" → αμέσως ACTIVE
    IGNORED         = "ignored"          # Timeout — cooldown doubled → ACTIVE
    DISMISSED       = "dismissed"        # Χρήστης είπε "όχι" → decay → ACTIVE/DECAYED
    DECAYED         = "decayed"          # Confidence < 0.1 → προς ARCHIVED
    ARCHIVED        = "archived"         # Νεκρή — δεν ειδοποιεί, μόνο re-teach επιτρέπεται


# ────────────────────────────────────────────────────────────────
# VALID TRANSITIONS MAP
# ────────────────────────────────────────────────────────────────

VALID_TRANSITIONS: dict[RoutineState, list[RoutineState]] = {
    RoutineState.LEARNED: [
        RoutineState.ACTIVE,     # 2η αναφορά
        RoutineState.ARCHIVED,   # manual delete
    ],
    RoutineState.ACTIVE: [
        RoutineState.TRIGGER_PENDING,  # notification sent
        RoutineState.DECAYED,          # confidence drops < 0.1
        RoutineState.ARCHIVED,         # manual delete
    ],
    RoutineState.TRIGGER_PENDING: [
        RoutineState.CONFIRMED,   # user: "ναι"
        RoutineState.IGNORED,     # timeout (30')
        RoutineState.DISMISSED,   # user: "όχι"
    ],
    RoutineState.CONFIRMED: [
        RoutineState.ACTIVE,      # auto-immediate μετά από confirm
    ],
    RoutineState.IGNORED: [
        RoutineState.ACTIVE,      # cooldown expired, ready again
        RoutineState.DECAYED,     # confidence < 0.1 μετά από πολλά ignores
    ],
    RoutineState.DISMISSED: [
        RoutineState.ACTIVE,      # confidence ακόμα OK μετά από decay
        RoutineState.DECAYED,     # confidence < 0.1
    ],
    RoutineState.DECAYED: [
        RoutineState.ARCHIVED,    # τελικός θάνατος
        RoutineState.ACTIVE,      # re-taught (νέο upsert)
    ],
    RoutineState.ARCHIVED: [
        RoutineState.LEARNED,     # re-teach από μηδέν
    ],
}


def validate_transition(from_state: RoutineState, to_state: RoutineState) -> None:
    """
    Raises RoutineConflictError αν η μετάβαση δεν επιτρέπεται.
    Χρήση: validate_transition(current_state, RoutineState.TRIGGER_PENDING)
    """
    allowed = VALID_TRANSITIONS.get(from_state, [])
    if to_state not in allowed:
        raise RoutineConflictError(
            f"Μη έγκυρη μετάβαση: {from_state.value} → {to_state.value}",
            context={
                "from":    from_state.value,
                "to":      to_state.value,
                "allowed": [s.value for s in allowed],
            }
        )


def is_notifiable(state: RoutineState) -> bool:
    """True αν η ρουτίνα μπορεί να ειδοποιήσει τώρα."""
    return state == RoutineState.ACTIVE


def state_from_str(s: str) -> RoutineState:
    """Safe parse — unknown strings → LEARNED (safe default)."""
    try:
        return RoutineState(s)
    except ValueError:
        return RoutineState.LEARNED
