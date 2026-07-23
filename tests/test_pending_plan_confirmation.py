from datetime import datetime, timedelta

from langchain_core.messages import HumanMessage

import core.planner as planner
from memory.pending_plans import is_pending_plan_fresh


def _pending(created_at: str) -> dict:
    return {
        "goal": "Example plan",
        "tasks": [{"step": 1, "description": "Do work", "instruction": "Do work"}],
        "created_at": created_at,
    }


def test_pending_plan_fresh_within_five_minutes():
    now = datetime(2026, 7, 23, 9, 0, 0)

    assert is_pending_plan_fresh(
        (now - timedelta(minutes=5)).isoformat(),
        now=now,
    ) is True


def test_pending_plan_fresh_rejects_expired_or_invalid_timestamp():
    now = datetime(2026, 7, 23, 9, 0, 0)

    assert is_pending_plan_fresh(
        (now - timedelta(minutes=5, seconds=1)).isoformat(),
        now=now,
    ) is False
    assert is_pending_plan_fresh("not-a-timestamp", now=now) is False


def test_fresh_pending_confirmation_uses_configured_marker(monkeypatch):
    pending = _pending(datetime.now().isoformat())
    monkeypatch.setattr(
        "memory.pending_plans.get_pending_plan",
        lambda user_id: pending,
    )

    result = planner.get_fresh_pending_plan_confirmation(
        {"channel": "web"},
        "πάμε!",
    )

    assert result == pending


def test_expired_pending_confirmation_is_not_loaded(monkeypatch):
    pending = _pending((datetime.now() - timedelta(minutes=5, seconds=1)).isoformat())
    monkeypatch.setattr(
        "memory.pending_plans.get_pending_plan",
        lambda user_id: pending,
    )

    result = planner.get_fresh_pending_plan_confirmation(
        {"channel": "web"},
        "πάμε",
    )

    assert result is None


def test_precheck_preserves_expired_plan_without_executing(monkeypatch):
    pending = _pending((datetime.now() - timedelta(minutes=5, seconds=1)).isoformat())
    cleared_user_ids = []
    monkeypatch.setattr(
        "memory.pending_plans.get_pending_plan",
        lambda user_id: pending,
    )
    monkeypatch.setattr(
        "memory.pending_plans.clear_pending_plan",
        lambda user_id: cleared_user_ids.append(user_id),
    )

    result = planner.pre_check_node({
        "channel": "web",
        "messages": [HumanMessage(content="πάμε")],
    })

    assert result == {}
    assert cleared_user_ids == []


def test_precheck_executes_fresh_plan_confirmation(monkeypatch):
    pending = _pending(datetime.now().isoformat())
    cleared_user_ids = []
    monkeypatch.setattr(
        "memory.pending_plans.get_pending_plan",
        lambda user_id: pending,
    )
    monkeypatch.setattr(
        "memory.pending_plans.clear_pending_plan",
        lambda user_id: cleared_user_ids.append(user_id),
    )

    result = planner.pre_check_node({
        "channel": "web",
        "messages": [HumanMessage(content="πάμε")],
    })

    assert result["plan_tasks"] == pending["tasks"]
    assert result["plan_active"] is True
    assert result["next_agent"] == "__plan_confirmed__"
    assert cleared_user_ids == ["web:default"]
