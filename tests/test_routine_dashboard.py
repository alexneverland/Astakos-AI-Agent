from api.server import _latest_routine_outcome, _routine_outcome_label


def test_dashboard_label_mapper() -> None:
    """Renders readable labels for scheduler and manual routine outcomes."""
    assert _routine_outcome_label("routine_condition_blocked") == "Blocked by condition"
    assert _routine_outcome_label("routine_cooldown_skip") == "Skipped: cooldown"
    assert _routine_outcome_label("routine_triggered") == "Sent"
    assert _routine_outcome_label("preemptive_completed") == "Completed today"
    assert _routine_outcome_label("confirmed") == "Confirmed"
    assert _routine_outcome_label("unknown_action") == "Recorded: Unknown action"


def test_missing_event_has_no_dashboard_outcome() -> None:
    """Keeps the dashboard's no-event state distinct from lifecycle outcomes."""
    assert _latest_routine_outcome([], 123) is None


def test_latest_event_is_picked_including_manual_completion() -> None:
    """Includes manual completion events that do not use the routine_ prefix."""
    today_events = [
        {"routine_id": 123, "action": "routine_condition_allowed", "timestamp": "2026-06-26T10:00:00"},
        {"routine_id": 123, "action": "preemptive_completed", "timestamp": "2026-06-26T10:05:00"},
        {"routine_id": 999, "action": "routine_triggered", "timestamp": "2026-06-26T10:10:00"},
    ]

    latest = _latest_routine_outcome(today_events, 123)

    assert latest is not None
    assert latest["action"] == "preemptive_completed"
    assert _routine_outcome_label(latest["action"]) == "Completed today"
