"""Read-only, privacy-bounded diagnostics for authenticated routine Debug."""
from collections.abc import Mapping, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

from memory.routine_context_clarification import ClarificationStore
from services.routine_context_evidence import ContextEvidence, VOLATILE_FLAGS


def latest_clarification_check(events: Sequence[Mapping[str, Any]]) -> dict[str, str] | None:
    """Return recorded bounded scheduler status, not guessed delivery or text."""
    allowed = {"error", "quiet", "muted", "paused", "recent_activity", "recent_reminder",
               "confirmation", "inactive_runtime", "deferred", "not_due", "waiting_answer",
               "delivery_uncertain", "resolved", "recorded", "delivered", "stale", "held"}
    checks = []
    for event in events:
        if event.get("action") != "context_clarification_poll":
            continue
        stamp = event.get("timestamp")
        if not isinstance(stamp, str) or len(stamp) > 40:
            continue
        try:
            datetime.fromisoformat(stamp)
        except ValueError:
            continue
        outcome = event.get("outcome")
        checks.append({"at": stamp, "outcome": outcome if isinstance(outcome, str) and outcome in allowed else "error"})
    return max(checks, key=lambda row: row["at"]) if checks else None


def clarification_diagnostics(
    path: Path, now: datetime, evidence: Mapping[str, ContextEvidence],
) -> dict[str, Any]:
    """Expose lifecycle/source/validity, never question text or raw coordinates."""
    result = {"pending": None, "delivered_today": 0, "error": False,
              "evidence": {flag: {"value": item.effective_value, "source": item.source,
                                  "status": item.status, "reason": item.reason,
                                  "age_seconds": item.age_seconds,
                                  "valid_until": item.valid_until.isoformat() if item.valid_until else None}
                           for flag in VOLATILE_FLAGS
                           for item in [evidence.get(flag, ContextEvidence())]}}
    if not path.is_file():
        return result
    try:
        state = ClarificationStore(path).snapshot()
        pending = state["pending"]
        if pending:
            result["pending"] = {key: pending[key] for key in
                                  ("id", "status", "routine_ids", "flags", "slot_at", "channel", "history_recorded")}
            if datetime.fromisoformat(pending["slot_at"]) <= now:
                result["pending"]["status"] = "expired"
        result["delivered_today"] = sum(bool(row["external_id"])
            and datetime.fromisoformat(row["sent_at"]).astimezone(now.tzinfo).date() == now.date()
            for row in state["requests"])
    except (OSError, ValueError, RuntimeError, TimeoutError):
        result["error"] = True
    return result
