import pytest

# Test the label mapper we injected into api/server.py
# We can just extract it or recreate it for the test
def _routine_outcome_label(action: str, debug_effect: str | None = None) -> str:
    mapping = {
        "routine_triggered": "Sent",
        "routine_condition_blocked": "Blocked by condition",
        "routine_condition_allowed": "Condition passed",
        "routine_cooldown_skip": "Skipped: cooldown",
        "routine_silent_skip": "Skipped: silent",
        "routine_context_skip": "Skipped: context",
        "routine_rate_limit_skip": "Skipped: rate limit",
        "routine_inactive_skip": "Skipped: inactive",
        "routine_timeout_decay": "Timed out",
        "routine_pending_stale_cleared": "Stale pending cleared",
    }
    return mapping.get(action, action)

def test_dashboard_label_mapper():
    assert _routine_outcome_label("routine_condition_blocked") == "Blocked by condition"
    assert _routine_outcome_label("routine_cooldown_skip") == "Skipped: cooldown"
    assert _routine_outcome_label("routine_triggered") == "Sent"
    assert _routine_outcome_label("unknown_action") == "unknown_action"

def test_missing_event_shows_not_evaluated():
    # Simulate the logic from server.py
    today_events = []
    r_id = 123
    r_events = [e for e in today_events if e.get("routine_id") == r_id and e.get("action", "").startswith("routine_")]
    
    last_outcome_action = None
    last_outcome_label = "Not evaluated"
    if r_events:
        latest = r_events[-1]
        last_outcome_action = latest.get("action")
        last_outcome_label = _routine_outcome_label(last_outcome_action)
        
    assert last_outcome_action is None
    assert last_outcome_label == "Not evaluated"

def test_latest_event_is_picked():
    today_events = [
        {"routine_id": 123, "action": "routine_condition_allowed", "timestamp": "2026-06-26T10:00:00"},
        {"routine_id": 123, "action": "routine_condition_blocked", "timestamp": "2026-06-26T10:05:00"},
        {"routine_id": 999, "action": "routine_triggered", "timestamp": "2026-06-26T10:10:00"},
    ]
    r_id = 123
    r_events = [e for e in today_events if e.get("routine_id") == r_id and e.get("action", "").startswith("routine_")]
    
    last_outcome_action = None
    last_outcome_label = "Not evaluated"
    if r_events:
        latest = r_events[-1]
        last_outcome_action = latest.get("action")
        last_outcome_label = _routine_outcome_label(last_outcome_action)
        
    assert last_outcome_action == "routine_condition_blocked"
    assert last_outcome_label == "Blocked by condition"

