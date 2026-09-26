"""Goal check-ins must be grounded in recorded goal activity."""

import json
from datetime import datetime, timedelta
from unittest.mock import patch
from zoneinfo import ZoneInfo

from services.goal_followup_timing import (
    format_goal_followup_context,
    goal_followup_due,
    select_goals_for_followup,
)


def test_new_submission_is_not_due_even_if_semantic_search_would_find_nothing():
    now = datetime(2026, 9, 26, 10, 15)
    goal = {
        "project": "Kaggle",
        "description": "Submission scored 0.06",
        "metadata": {"last_activity_at": (now - timedelta(minutes=20)).timestamp()},
    }

    assert goal_followup_due(goal, now=now) is False


def test_old_goal_is_due_only_with_a_known_activity_timestamp():
    now = datetime(2026, 9, 26, 10, 15)
    goal = {"metadata": {"last_activity_at": (now - timedelta(days=8)).timestamp()}}

    assert goal_followup_due(goal, now=now) is True
    assert goal_followup_due({"metadata": {}}, now=now) is False
    assert goal_followup_due({"metadata": {"timestamp": "invalid"}}, now=now) is False


def test_newer_creation_or_change_wins_over_stale_legacy_timestamp():
    now = datetime(2026, 9, 26, 10, 15)
    old = (now - timedelta(days=20)).timestamp()
    recent = (now - timedelta(minutes=20)).timestamp()

    assert goal_followup_due({"metadata": {"timestamp": old, "created_at": recent}}, now=now) is False
    assert goal_followup_due({"metadata": {"timestamp": old, "updated_at": recent}}, now=now) is False


def test_spring_clock_change_does_not_make_goal_due_after_only_167_hours():
    athens = ZoneInfo("Europe/Athens")
    activity = datetime(2026, 3, 23, 10, tzinfo=athens)
    goal = {"metadata": {"last_activity_at": activity.timestamp()}}

    assert goal_followup_due(goal, now=datetime(2026, 3, 30, 10, tzinfo=athens)) is False
    assert goal_followup_due(goal, now=datetime(2026, 3, 30, 11, tzinfo=athens)) is True


def test_autumn_clock_change_makes_goal_due_after_168_hours():
    athens = ZoneInfo("Europe/Athens")
    activity = datetime(2026, 10, 19, 10, tzinfo=athens)
    goal = {"metadata": {"last_activity_at": activity.timestamp()}}

    assert goal_followup_due(goal, now=datetime(2026, 10, 26, 8, 59, tzinfo=athens)) is False
    assert goal_followup_due(goal, now=datetime(2026, 10, 26, 9, tzinfo=athens)) is True


def test_context_includes_known_start_and_latest_change_without_inventing_legacy_start():
    now = datetime(2026, 9, 26, 10, 15)
    created = (now - timedelta(days=20)).timestamp()
    updated = (now - timedelta(days=8)).timestamp()
    goal = {
        "project": "Kaggle", "description": "Submission scored 0.06",
        "progress": 25, "milestones": "baseline submitted",
        "metadata": {
            "created_at": created, "updated_at": updated,
            "last_activity_at": updated,
            "goal_events_json": json.dumps([
                {"at": created, "kind": "created", "detail": "Goal created"},
                {"at": updated, "kind": "updated", "detail": "Submission scored 0.06"},
            ]),
        },
    }

    context = format_goal_followup_context(goal)
    assert "2026-09-06" in context
    assert "2026-09-18" in context
    assert "Submission scored 0.06" in context

    legacy = format_goal_followup_context({"project": "Legacy", "metadata": {"timestamp": updated}})
    assert "Created:" not in legacy


def test_recent_goal_never_reaches_semantic_lookup():
    now = datetime(2026, 9, 26, 10, 15)
    goal = {"project": "Kaggle", "metadata": {"timestamp": (now - timedelta(minutes=20)).timestamp()}}

    def unexpected_lookup(_: dict) -> bool:
        raise AssertionError("recent goal must not be searched")

    assert select_goals_for_followup([goal], now=now, has_recent_memory=unexpected_lookup) == []


def test_old_goal_is_selected_only_when_recent_memory_check_is_reliably_empty():
    now = datetime(2026, 9, 26, 10, 15)
    goal = {"project": "Kaggle", "metadata": {"timestamp": (now - timedelta(days=8)).timestamp()}}

    assert select_goals_for_followup([goal], now=now, has_recent_memory=lambda _: False) == [goal]
    assert select_goals_for_followup([goal], now=now, has_recent_memory=lambda _: True) == []

    def unavailable_lookup(_: dict) -> bool:
        raise RuntimeError("index unavailable")

    assert select_goals_for_followup([goal], now=now, has_recent_memory=unavailable_lookup) == []


def test_scheduler_sends_nothing_for_the_just_recorded_kaggle_result():
    """The live job path must stop before embedding or outbound delivery."""
    from clients import telegram_bot

    now = datetime(2026, 9, 26, 10, 15)
    recent_goal = {
        "project": "Kaggle", "description": "Submission scored 0.06",
        "metadata": {"timestamp": (now - timedelta(minutes=20)).timestamp()},
    }

    class FixedDatetime:
        @staticmethod
        def now() -> datetime:
            return now

    with patch.object(telegram_bot, "datetime", FixedDatetime), \
         patch.object(telegram_bot.os.path, "exists", return_value=False), \
         patch("memory.vector_store.get_active_goals", return_value=[recent_goal]), \
         patch("memory.vector_store.vector_store.embeddings.embed_query") as embed, \
         patch.object(telegram_bot, "_send_and_record_assistant") as send:
        telegram_bot.job_goal_followup()

    embed.assert_not_called()
    send.assert_not_called()
