import sqlite3
from pathlib import Path

import pytest

import memory.pending_followups as pf


@pytest.fixture()
def temp_state_db(tmp_path, monkeypatch):
    db_path = tmp_path / "state_followups.db"
    monkeypatch.setattr(pf, "STATE_DB", str(db_path))
    pf.ensure_pending_followups_table()
    return db_path


def _fetch_all(db_path: Path):
    conn = sqlite3.connect(str(db_path))
    try:
        return conn.execute(
            """
            SELECT id, topic, subject, status, followup_after_ts, expires_at, resolution_reason
            FROM pending_followups
            ORDER BY id ASC
            """
        ).fetchall()
    finally:
        conn.close()


def test_create_pending_followup(temp_state_db):
    followup_id = pf.create_pending_followup(
        source_channel="telegram",
        source_agent="Chat_Agent",
        topic="food_purchase",
        subject="μπριζόλες λαιμού",
        source_user_text="Θύμισέ μου να πάρω τις μπριζόλες λαιμού",
        source_ai_text="Έγινε μάστορα.",
        followup_after_ts="2030-01-01T19:00:00",
        confidence=0.82,
        metadata={"reason": "natural next step"},
    )

    assert isinstance(followup_id, int)

    rows = _fetch_all(temp_state_db)
    assert len(rows) == 1
    assert rows[0][1] == "food_purchase"
    assert rows[0][2] == "μπριζόλες λαιμού"
    assert rows[0][3] == "pending"


def test_duplicate_pending_followup_same_topic_subject_is_skipped(temp_state_db):
    first_id = pf.create_pending_followup(
        source_channel="telegram",
        source_agent="Chat_Agent",
        topic="food_purchase",
        subject="μπριζόλες λαιμού",
        source_user_text="Θύμισέ μου να πάρω τις μπριζόλες λαιμού",
        source_ai_text="Έγινε.",
        followup_after_ts="2030-01-01T19:00:00",
        confidence=0.75,
        metadata={},
    )

    second_id = pf.create_pending_followup(
        source_channel="web",
        source_agent="Home_Agent",
        topic="food_purchase",
        subject="μπριζόλες λαιμού",
        source_user_text="Πήρα τις μπριζόλες",
        source_ai_text="ΟΚ.",
        followup_after_ts="2030-01-01T20:00:00",
        confidence=0.90,
        metadata={},
    )

    assert isinstance(first_id, int)
    assert second_id is None

    rows = _fetch_all(temp_state_db)
    assert len(rows) == 1


def test_get_due_pending_followups_returns_only_due_items(temp_state_db):
    pf.create_pending_followup(
        source_channel="telegram",
        source_agent="Chat_Agent",
        topic="food_purchase",
        subject="μπριζόλες λαιμού",
        source_user_text="Θύμισέ μου να πάρω τις μπριζόλες",
        source_ai_text="Έγινε.",
        followup_after_ts="2030-01-01T19:00:00",
        confidence=0.80,
        metadata={},
    )

    pf.create_pending_followup(
        source_channel="telegram",
        source_agent="Chat_Agent",
        topic="outing",
        subject="συνάντηση με Σοφία",
        source_user_text="Θα πάω να τους βρω",
        source_ai_text="ΟΚ.",
        followup_after_ts="2030-01-02T22:00:00",
        confidence=0.80,
        metadata={},
    )

    due = pf.get_due_pending_followups("2030-01-01T20:00:00")

    assert len(due) == 1
    assert due[0]["topic"] == "food_purchase"
    assert due[0]["subject"] == "μπριζόλες λαιμού"


def test_resolve_followup_marks_row_resolved(temp_state_db):
    followup_id = pf.create_pending_followup(
        source_channel="telegram",
        source_agent="Chat_Agent",
        topic="outing",
        subject="συνάντηση με Σοφία",
        source_user_text="Θα πάω να τους βρω",
        source_ai_text="ΟΚ.",
        followup_after_ts="2030-01-01T19:00:00",
        confidence=0.88,
        metadata={},
    )

    pf.resolve_followup(followup_id, "resolved_by_recent_user_message")

    rows = _fetch_all(temp_state_db)
    assert len(rows) == 1
    assert rows[0][3] == "resolved"
    assert rows[0][6] == "resolved_by_recent_user_message"


def test_mark_followup_sent_marks_row_sent(temp_state_db):
    followup_id = pf.create_pending_followup(
        source_channel="telegram",
        source_agent="Chat_Agent",
        topic="family_plan",
        subject="βραδινό φαγητό",
        source_user_text="Πήρα πράγματα για το βράδυ",
        source_ai_text="Τέλεια.",
        followup_after_ts="2030-01-01T19:00:00",
        confidence=0.66,
        metadata={},
    )

    pf.mark_followup_sent(followup_id)

    rows = _fetch_all(temp_state_db)
    assert len(rows) == 1
    assert rows[0][3] == "sent"


def test_expire_old_followups_marks_expired(temp_state_db):
    pf.create_pending_followup(
        source_channel="telegram",
        source_agent="Chat_Agent",
        topic="task_progress",
        subject="δουλειά σπιτιού",
        source_user_text="Αργότερα θα το κάνω",
        source_ai_text="Έγινε.",
        followup_after_ts="2030-01-01T10:00:00",
        confidence=0.70,
        metadata={},
    )

    pf.expire_old_followups("2030-01-03T10:00:00")

    rows = _fetch_all(temp_state_db)
    assert len(rows) == 1
    assert rows[0][3] == "expired"
    assert rows[0][6] == "ttl_expired"


def test_maybe_create_followup_from_exchange_inserts_when_llm_candidate_is_valid(temp_state_db, monkeypatch):
    monkeypatch.setattr(
        pf,
        "extract_followup_candidate_with_llm",
        lambda user_text, ai_text, agent_name: {
            "should_follow_up": True,
            "topic": "food_purchase",
            "subject": "μπριζόλες λαιμού",
            "delay_minutes": 180,
            "confidence": 0.81,
            "reason": "worth checking later",
        },
    )

    followup_id = pf.maybe_create_followup_from_exchange(
        user_text="Θύμισέ μου να πάρω τις μπριζόλες λαιμού",
        ai_text="Έγινε μάστορα.",
        agent_name="Home_Agent",
        channel="web",
    )

    assert isinstance(followup_id, int)

    rows = _fetch_all(temp_state_db)
    assert len(rows) == 1
    assert rows[0][1] == "food_purchase"


def test_maybe_create_followup_from_exchange_skips_low_confidence(temp_state_db, monkeypatch):
    monkeypatch.setattr(
        pf,
        "extract_followup_candidate_with_llm",
        lambda user_text, ai_text, agent_name: {
            "should_follow_up": True,
            "topic": "food_purchase",
            "subject": "μπριζόλες λαιμού",
            "delay_minutes": 180,
            "confidence": 0.30,
            "reason": "too weak",
        },
    )

    followup_id = pf.maybe_create_followup_from_exchange(
        user_text="Θύμισέ μου να πάρω τις μπριζόλες λαιμού",
        ai_text="Έγινε μάστορα.",
        agent_name="Home_Agent",
        channel="web",
    )

    assert followup_id is None
    rows = _fetch_all(temp_state_db)
    assert rows == []


def test_maybe_resolve_followups_from_user_message_resolves_matching_pending(temp_state_db):
    pf.create_pending_followup(
        source_channel="telegram",
        source_agent="Chat_Agent",
        topic="food_purchase",
        subject="μπριζόλες λαιμού",
        source_user_text="Θύμισέ μου να πάρω τις μπριζόλες λαιμού",
        source_ai_text="Έγινε.",
        followup_after_ts="2030-01-01T19:00:00",
        confidence=0.82,
        metadata={},
    )

    pf.maybe_resolve_followups_from_user_message("Τις πήρα τελικά τις μπριζόλες λαιμού")

    rows = _fetch_all(temp_state_db)
    assert len(rows) == 1
    assert rows[0][3] == "resolved"
    assert rows[0][6] == "resolved_by_recent_user_message"
