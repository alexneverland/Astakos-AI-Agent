"""Read-only presentation helpers; diagnostics never activate feedback policy."""
from __future__ import annotations

import math
from datetime import datetime, timezone

from services.routine_feedback import ATHENS, aware


def cooldown_diagnostics(stored_hours: object, last_notified: object, *,
                         effective_hours: float, now: datetime) -> dict:
    """Separate stored configuration from the cooldown the current scheduler uses.

    Legacy naive timestamps were recorded in the owner's local calendar. Compare
    offset-aware timestamps as instants and expose invalid data as unknown.
    """
    result = {"cooldown_hours": stored_hours, "effective_cooldown_hours": effective_hours,
              "cooldown_remaining_h": None, "cooldown_read_error": False}
    try:
        hours = float(effective_hours)
        if not math.isfinite(hours) or hours < 0:
            raise ValueError("Invalid cooldown")
        if last_notified is None:
            result["cooldown_remaining_h"] = 0
            return result
        sent = datetime.fromisoformat(last_notified)
        if sent.tzinfo is None:
            sent = sent.replace(tzinfo=ATHENS)
        elapsed = (aware(now).astimezone(timezone.utc) - sent.astimezone(timezone.utc)).total_seconds()
        if elapsed < 0:
            raise ValueError("Future receipt")
        result["cooldown_remaining_h"] = round(max(0, hours - elapsed / 3600), 1)
    except (TypeError, ValueError, OverflowError):
        result["cooldown_read_error"] = True
    return result
