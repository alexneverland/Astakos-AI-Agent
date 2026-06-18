import json
from datetime import datetime


def evaluate_routine_conditions(conditions: list[dict], context: dict, now: datetime | None = None) -> dict:
    """
    Evaluates a list of routine conditions using AND logic.
    
    Returns:
    {
        "allowed": True/False,
        "results": [result_dict1, result_dict2, ...],
        "matched_count": int,
        "failed_count": int,
    }
    """
    if not conditions:
        return {
            "allowed": True,
            "results": [],
            "matched_count": 0,
            "failed_count": 0,
        }

    results = []
    allowed = True
    matched_count = 0
    failed_count = 0

    for cond in conditions:
        res = evaluate_routine_condition(cond, context, now)
        results.append(res)
        
        if res.get("matched"):
            matched_count += 1
            
        if not res.get("allowed"):
            allowed = False
            failed_count += 1

    return {
        "allowed": allowed,
        "results": results,
        "matched_count": matched_count,
        "failed_count": failed_count,
    }

def evaluate_routine_condition(condition: dict, context: dict, now: datetime | None = None) -> dict:
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

    condition_type = condition.get("condition_type")
    payload_raw = condition.get("condition_payload")
    mode = condition.get("condition_mode") or "allow_when_true"

    if not condition_type:
        return {
            "allowed": True,
            "matched": False,
            "reason": "no_condition",
        }

    try:
        if isinstance(payload_raw, dict):
            payload = payload_raw
        elif isinstance(payload_raw, str):
            payload = json.loads(payload_raw) if payload_raw else {}
        elif payload_raw is None:
            payload = {}
        else:
            payload = {}
    except Exception as e:
        print(f"[ConditionEval Error] Could not parse payload_raw: {payload_raw}, Error: {e}")
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
            "actual_value": actual,
        }

    if mode == "suppress_when_true":
        return {
            "allowed": not matched,
            "matched": matched,
            "reason": "context_flag_suppressed" if matched else "context_flag_not_suppressed",
            "actual_value": actual,
        }

    return {
        "allowed": False,
        "matched": False,
        "reason": f"unknown_condition_mode:{mode}",
        "actual_value": actual,
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
            "actual_value": actual,
        }

    if mode == "suppress_when_true":
        return {
            "allowed": not matched,
            "matched": matched,
            "reason": "shift_mode_suppressed" if matched else "shift_mode_not_suppressed",
            "actual_value": actual,
        }

    return {
        "allowed": False,
        "matched": False,
        "reason": f"unknown_condition_mode:{mode}",
        "actual_value": actual,
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
