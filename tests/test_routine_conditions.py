from datetime import datetime
from services.routine_conditions import evaluate_routine_condition


def test_context_flag_allow_when_true():
    routine = {
        "condition_type": "context_flag",
        "condition_payload": '{"flag":"alexandros_away_from_home","equals":true}',
        "condition_mode": "allow_when_true",
    }
    context = {"alexandros_away_from_home": True}

    result = evaluate_routine_condition(routine, context, now=datetime(2026, 6, 17))
    assert result["allowed"] is True


def test_context_flag_suppress_when_true():
    routine = {
        "condition_type": "context_flag",
        "condition_payload": '{"flag":"alexandros_away_from_home","equals":true}',
        "condition_mode": "suppress_when_true",
    }
    context = {"alexandros_away_from_home": True}

    result = evaluate_routine_condition(routine, context, now=datetime(2026, 6, 17))
    assert result["allowed"] is False


def test_shift_mode_blocks_other_shift():
    routine = {
        "condition_type": "shift_mode",
        "condition_payload": '{"flag":"current_shift","equals":"afternoon"}',
        "condition_mode": "allow_when_true",
    }
    context = {"current_shift": "morning"}

    result = evaluate_routine_condition(routine, context, now=datetime(2026, 6, 17))
    assert result["allowed"] is False


def test_date_range_allows_inside_window():
    routine = {
        "condition_type": "date_range",
        "condition_payload": '{"from":"2026-06-15","until":"2026-06-25"}',
        "condition_mode": "allow_when_true",
    }
    context = {}

    result = evaluate_routine_condition(routine, context, now=datetime(2026, 6, 17))
    assert result["allowed"] is True

def test_context_flag_multi_key_allow_when_all_match():
    routine = {
        "condition_type": "context_flag",
        "condition_payload": '{"alexandros_present": true, "family_at_home": true}',
        "condition_mode": "allow_when_true",
    }
    context = {
        "alexandros_present": True,
        "family_at_home": True,
    }

    result = evaluate_routine_condition(routine, context, now=datetime(2026, 6, 17))
    assert result["allowed"] is True
    assert result["matched"] is True
    assert result["reason"] == "context_flag_allow"


def test_context_flag_multi_key_allow_blocks_on_first_mismatch():
    routine = {
        "condition_type": "context_flag",
        "condition_payload": '{"alexandros_present": true, "family_at_home": true}',
        "condition_mode": "allow_when_true",
    }
    context = {
        "alexandros_present": True,
        "family_at_home": False,
    }

    result = evaluate_routine_condition(routine, context, now=datetime(2026, 6, 17))
    assert result["allowed"] is False
    assert result["matched"] is False
    assert result["reason"] == "context_flag_mismatch_family_at_home"


def test_context_flag_empty_payload_is_not_treated_as_match():
    routine = {
        "condition_type": "context_flag",
        "condition_payload": '{}',
        "condition_mode": "allow_when_true",
    }
    context = {}

    result = evaluate_routine_condition(routine, context, now=datetime(2026, 6, 17))
    assert result["allowed"] is False
    assert result["matched"] is False
    assert result["reason"] == "missing_flag"

