from unittest.mock import patch

import clients.telegram_bot as telegram_bot


def test_followup_decision_fails_closed_on_llm_error():
    item = {
        "topic": "outing",
        "subject": "Park",
        "source_channel": "telegram",
        "source_agent": "Chat_Agent",
        "source_user_text": "We will go to the park later.",
        "source_ai_text": "I will check in later.",
        "followup_after_ts": "2026-07-17T12:00:00",
    }

    with patch("services.gemini.safe_gemini_call", side_effect=Exception("boom")):
        decision = telegram_bot._build_followup_decision_with_llm(
            item,
            recent_context="",
            state_snapshot={"user_at_work": True},
        )

    assert decision["decision"] == "skip"
    assert decision["skip_action"] == "defer"
    assert decision["reason"] == "llm_decision_failed_safe_defer"


import json
from datetime import datetime, timedelta

from memory.pending_followups import (
    create_pending_followup,
    defer_followup,
    ensure_pending_followups_table,
    get_due_pending_followups,
)


def test_defer_followup_increments_defer_count(monkeypatch, tmp_path):
    test_db = str(tmp_path / "followups.db")
    monkeypatch.setattr("memory.pending_followups.STATE_DB", test_db)

    ensure_pending_followups_table()

    due_dt = datetime.now() + timedelta(minutes=5)

    followup_id = create_pending_followup(
        source_channel="telegram",
        source_agent="Chat_Agent",
        topic="outing",
        subject="Park check-in",
        source_user_text="We may go later",
        source_ai_text="I will ask you later",
        followup_after_ts=due_dt.isoformat(timespec="seconds"),
        confidence=0.8,
        metadata={
            "reason": "follow up later",
            "target_window": "same_day_short_checkin",
            "ttl_hours": 6,
            "delay_minutes_raw": 60,
            "delay_minutes_final": 60,
            "defer_count": 0,
        },
        ttl_hours=6,
    )

    defer_followup(
        followup_id,
        delay_minutes=60,
        reason="deferred:test",
        target_window="same_day_short_checkin",
        topic="outing",
    )

    check_ts = (datetime.now() + timedelta(minutes=65)).isoformat(timespec="seconds")
    due_items = get_due_pending_followups(check_ts)
    item = next(x for x in due_items if x["id"] == followup_id)
    assert int(item["metadata"].get("defer_count") or 0) == 1


def test_should_force_light_outing_followup_safety_guards():
    from clients.telegram_bot import _should_force_light_outing_followup
    from memory.pending_followups import _local_now

    now_str = _local_now().isoformat(timespec="seconds")

    # 1. defer_count=1 -> False
    item = {
        "topic": "outing",
        "source_user_text": "θα πάω να τους βρω",
        "metadata": {"defer_count": 1},
        "followup_after_ts": now_str,
    }
    assert _should_force_light_outing_followup(item) is False

    # 2. times_sent=1 -> False
    item2 = {
        "topic": "outing",
        "source_user_text": "θα πάω να τους βρω",
        "times_sent": 1,
        "followup_after_ts": now_str,
    }
    assert _should_force_light_outing_followup(item2) is False

    # 3. γενικό «πάω πάρκο» -> False (no longer triggers)
    item3 = {
        "topic": "outing",
        "source_user_text": "θα πάω πάρκο",
        "followup_after_ts": now_str,
    }
    assert _should_force_light_outing_followup(item3) is False

    # 4. ρητό «να τους βρω» χωρίς defer/sent -> True
    item4 = {
        "topic": "outing",
        "source_user_text": "θα πάω να τους βρω",
        "followup_after_ts": now_str,
    }
    assert _should_force_light_outing_followup(item4) is True
