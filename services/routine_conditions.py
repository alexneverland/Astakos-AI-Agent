import json
from datetime import datetime


def evaluate_routine_condition(routine: dict, context: dict, now: datetime | None = None) -> dict:
    """
    Evaluates a single routine condition.

    Returns:
    {
        "allowed": True/False,
        "matched": True/False,
        "reason": "...",
    }
    """
    current = now or datetime.now()

    condition_type = routine.get("condition_type")
    payload_raw = routine.get("condition_payload")
    mode = routine.get("condition_mode") or "allow_when_true"

    if not condition_type:
        return {
            "allowed": True,
            "matched": False,
            "reason": "no_condition",
        }

    try:
        payload = json.loads(payload_raw) if payload_raw else {}
    except Exception:
        return {
            "allowed": False,
            "matched": False,
            "reason": "invalid_condition_payload",
        }

    if condition_type == "context_flag":
        return _evaluate_context_flag(payload, mode, context)

    if condition_type == "shift_mode":
        return _evaluate_shift_mode(payload, mode, context)

    if condition_type == "date_range":
        return _evaluate_date_range(payload, mode, current)

    return {
        "allowed": True,
        "matched": False,
        "reason": f"unknown_condition_type:{condition_type}",
    }


def _evaluate_context_flag(payload: dict, mode: str, context: dict) -> dict:
    flag = payload.get("flag")
    expected = payload.get("equals")

    if not flag:
        return {
            "allowed": False,
            "matched": False,
            "reason": "missing_flag",
        }

    actual = context.get(flag)
    matched = (actual == expected)

    if mode == "allow_when_true":
        return {
            "allowed": matched,
            "matched": matched,
            "reason": "context_flag_allow" if matched else "context_flag_blocked",
        }

    if mode == "suppress_when_true":
        return {
            "allowed": not matched,
            "matched": matched,
            "reason": "context_flag_suppressed" if matched else "context_flag_not_suppressed",
        }

    return {
        "allowed": False,
        "matched": False,
        "reason": f"unknown_condition_mode:{mode}",
    }


def _evaluate_shift_mode(payload: dict, mode: str, context: dict) -> dict:
    flag = payload.get("flag", "current_shift")
    expected = payload.get("equals")
    actual = context.get(flag)

    matched = (actual == expected)

    if mode == "allow_when_true":
        return {
            "allowed": matched,
            "matched": matched,
            "reason": "shift_mode_allow" if matched else "shift_mode_blocked",
        }

    if mode == "suppress_when_true":
        return {
            "allowed": not matched,
            "matched": matched,
            "reason": "shift_mode_suppressed" if matched else "shift_mode_not_suppressed",
        }

    return {
        "allowed": False,
        "matched": False,
        "reason": f"unknown_condition_mode:{mode}",
    }


def _evaluate_date_range(payload: dict, mode: str, now: datetime) -> dict:
    date_from = payload.get("from")
    date_until = payload.get("until")
    today = now.strftime("%Y-%m-%d")

    matched = True
    if date_from and today < date_from:
        matched = False
    if date_until and today > date_until:
        matched = False

    if mode == "allow_when_true":
        return {
            "allowed": matched,
            "matched": matched,
            "reason": "date_range_allow" if matched else "date_range_blocked",
        }

    if mode == "suppress_when_true":
        return {
            "allowed": not matched,
            "matched": matched,
            "reason": "date_range_suppressed" if matched else "date_range_not_suppressed",
        }

    return {
        "allowed": False,
        "matched": False,
        "reason": f"unknown_condition_mode:{mode}",
    }
