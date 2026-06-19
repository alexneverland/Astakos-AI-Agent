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
