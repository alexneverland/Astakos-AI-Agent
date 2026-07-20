import json
import sqlite3
from datetime import datetime
from pathlib import Path

import pytest

import clients.telegram_bot as bot
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
        subject="συνάντηση με Partner",
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
        subject="συνάντηση με Partner",
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


def test_expire_old_followups_also_expires_sent_rows(temp_state_db):
    followup_id = pf.create_pending_followup(
        source_channel="telegram",
        source_agent="Chat_Agent",
        topic="family_plan",
        subject="βραδινό φαγητό",
        source_user_text="Το βράδυ θα δούμε τι θα κάνουμε",
        source_ai_text="Οκ.",
        followup_after_ts="2030-01-01T19:00:00+02:00",
        confidence=0.72,
        metadata={},
    )

    pf.mark_followup_sent(followup_id)
    pf.expire_old_followups("2030-01-03T10:00:00+02:00")

    rows = _fetch_all(temp_state_db)
    assert len(rows) == 1
    assert rows[0][3] == "expired"
    assert rows[0][6] == "ttl_expired"


def test_maybe_create_followup_from_exchange_inserts_when_llm_candidate_is_valid(temp_state_db, monkeypatch):
    monkeypatch.setattr(
        pf,
        "extract_followup_candidate_with_llm",
        lambda user_text, ai_text, agent_name, active_followups_text="": {
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



def test_maybe_create_followup_does_not_reopen_sent_item(temp_state_db, monkeypatch):
    followup_id = pf.create_pending_followup(
        source_channel="telegram",
        source_agent="Chat_Agent",
        topic="outing",
        subject="βολτα στο παρκο",
        source_user_text="Είμαι στο πάρκο",
        source_ai_text="Καλά να περάσετε",
        followup_after_ts="2030-01-01T19:00:00+02:00",
        confidence=0.80,
        metadata={},
    )
    pf.mark_followup_sent(followup_id)

    monkeypatch.setattr(
        pf,
        "extract_followup_candidate_with_llm",
        lambda user_text, ai_text, agent_name, active_followups_text="": {
            "should_follow_up": True,
            "update_existing_id": followup_id,
            "delay_minutes": 60,
            "reason": "new information",
        },
    )

    deferred = []
    monkeypatch.setattr(
        pf,
        "defer_followup",
        lambda **kwargs: deferred.append(kwargs),
    )

    result = pf.maybe_create_followup_from_exchange(
        user_text="Μόλις ήρθα στο πάρκο με τον Αλέξανδρο.",
        ai_text="Ωραία, να περάσετε καλά.",
        agent_name="Home_Agent",
        channel="telegram",
    )

    assert result is None
    assert deferred == []

    stored = next(
        item
        for item in pf.find_pending_followups(limit=10, active_only=False)
        if item["id"] == followup_id
    )
    assert stored["status"] == "sent"


def test_maybe_create_followup_from_exchange_skips_low_confidence(temp_state_db, monkeypatch):
    monkeypatch.setattr(
        pf,
        "extract_followup_candidate_with_llm",
        lambda user_text, ai_text, agent_name, active_followups_text="": {
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


def test_maybe_resolve_followups_from_user_message_uses_llm_resolution(temp_state_db, monkeypatch):
    followup_id = pf.create_pending_followup(
        source_channel="telegram",
        source_agent="Chat_Agent",
        topic="outing",
        subject="συνάντηση με Partner",
        source_user_text="Σε λίγο φεύγω να βρω τη Partner",
        source_ai_text="ΟΚ.",
        followup_after_ts="2030-01-01T19:00:00",
        confidence=0.80,
        metadata={},
    )

    monkeypatch.setattr(
        pf,
        "classify_followup_resolution_with_llm",
        lambda **kwargs: {
            "resolves": True,
            "resolution_type": "completed",
            "confidence": 0.91,
            "reason": "user said they found them",
        },
    )

    monkeypatch.setattr(
        pf,
        "classify_followup_deferral_with_llm",
        lambda **kwargs: {"should_defer": False},
    )

    pf.maybe_resolve_followups_from_user_message("Τους βρήκα τελικά στο πάρκο")

    rows = _fetch_all(temp_state_db)
    assert len(rows) == 1
    assert rows[0][3] == "resolved"
    assert rows[0][6] == "resolved_by_user:completed"

    followup = next(
        item
        for item in pf.find_pending_followups(limit=10, active_only=False)
        if item["id"] == followup_id
    )
    assert followup["outcome_score"] == 1.0


def test_maybe_resolve_followups_from_user_message_skips_low_confidence_llm(temp_state_db, monkeypatch):
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

    monkeypatch.setattr(
        pf,
        "classify_followup_resolution_with_llm",
        lambda **kwargs: {
            "resolves": True,
            "resolution_type": "completed",
            "confidence": 0.30,
            "reason": "too weak",
        },
    )

    pf.maybe_resolve_followups_from_user_message("Ναι οκ")

    rows = _fetch_all(temp_state_db)
    assert len(rows) == 1
    assert rows[0][3] == "pending"


def test_maybe_resolve_followups_from_user_message_resolves_sent_followup(temp_state_db, monkeypatch):
    followup_id = pf.create_pending_followup(
        source_channel="telegram",
        source_agent="Chat_Agent",
        topic="food_purchase",
        subject="\u03bc\u03c0\u03c1\u03b9\u03b6\u03cc\u03bb\u03b5\u03c2 \u03bb\u03b1\u03b9\u03bc\u03bf\u03cd",
        source_user_text="\u0398\u03cd\u03bc\u03b9\u03c3\u03ad \u03bc\u03bf\u03c5 \u03bd\u03b1 \u03c0\u03ac\u03c1\u03c9 \u03c4\u03b9\u03c2 \u03bc\u03c0\u03c1\u03b9\u03b6\u03cc\u03bb\u03b5\u03c2",
        source_ai_text="\u0388\u03b3\u03b9\u03bd\u03b5.",
        followup_after_ts="2030-01-01T19:00:00",
        confidence=0.80,
        metadata={},
    )
    pf.mark_followup_sent(followup_id)

    monkeypatch.setattr(
        pf,
        "classify_followup_resolution_with_llm",
        lambda **kwargs: {
            "resolves": True,
            "resolution_type": "completed",
            "confidence": 0.92,
            "reason": "user said they bought them",
        },
    )

    monkeypatch.setattr(
        pf,
        "classify_followup_deferral_with_llm",
        lambda **kwargs: {"should_defer": False},
    )

    resolved = pf.maybe_resolve_followups_from_user_message(
        "\u03a4\u03b9\u03c2 \u03c0\u03ae\u03c1\u03b1 \u03c4\u03ce\u03c1\u03b1 \u03ba\u03b1\u03b9 \u03c6\u03b5\u03cd\u03b3\u03c9 \u03b1\u03c0\u03cc \u03c4\u03b7 \u03b4\u03bf\u03c5\u03bb\u03b5\u03b9\u03ac"
    )

    rows = _fetch_all(temp_state_db)
    assert resolved == 1
    assert len(rows) == 1
    assert rows[0][3] == "resolved"
    assert rows[0][6] == "resolved_by_user:completed"


def test_build_followup_arc_key_collapses_similar_subjects():
    key1 = pf.build_followup_arc_key("food_purchase", "μπριζόλες λαιμού")
    key2 = pf.build_followup_arc_key("food_purchase", "λαιμού μπριζόλες")
    assert key1 == key2


def test_create_pending_followup_dedupes_same_arc_key(temp_state_db):
    first_id = pf.create_pending_followup(
        source_channel="telegram",
        source_agent="Chat_Agent",
        topic="food_purchase",
        subject="μπριζόλες λαιμού",
        source_user_text="Θύμισέ μου να πάρω μπριζόλες λαιμού",
        source_ai_text="Έγινε.",
        followup_after_ts="2030-01-01T19:00:00",
        confidence=0.8,
        metadata={},
    )

    second_id = pf.create_pending_followup(
        source_channel="web",
        source_agent="Home_Agent",
        topic="food_purchase",
        subject="λαιμού μπριζόλες",
        source_user_text="Θα τις ψήσω το βράδυ",
        source_ai_text="ΟΚ.",
        followup_after_ts="2030-01-01T20:00:00",
        confidence=0.9,
        metadata={},
    )

    assert isinstance(first_id, int)
    assert second_id is None





def test_maybe_create_followup_from_exchange_stores_raw_and_final_delay(temp_state_db, monkeypatch):
    monkeypatch.setattr(
        pf,
        "extract_followup_candidate_with_llm",
        lambda user_text, ai_text, agent_name, active_followups_text="": {
            "should_follow_up": True,
            "topic": "outing",
            "subject": "συνάντηση με Partner",
            "delay_minutes": 500,
            "confidence": 0.88,
            "reason": "worth checking later",
        },
    )

    followup_id = pf.maybe_create_followup_from_exchange(
        user_text="Σε λίγο φεύγω να βρω τη Partner",
        ai_text="Έγινε.",
        agent_name="Chat_Agent",
        channel="telegram",
    )

    assert isinstance(followup_id, int)

    conn = sqlite3.connect(str(temp_state_db))
    try:
        row = conn.execute(
            "SELECT metadata_json FROM pending_followups WHERE id=?",
            (followup_id,),
        ).fetchone()
    finally:
        conn.close()

    metadata = json.loads(row[0])
    assert metadata["delay_minutes_raw"] == 500
    assert isinstance(metadata["delay_minutes_final"], int)
    assert metadata["delay_minutes_final"] >= 60


def test_find_pending_followups_includes_debug_fields(temp_state_db):
    followup_id = pf.create_pending_followup(
        source_channel="web",
        source_agent="Home_Agent",
        topic="food_purchase",
        subject="brizoles laimou",
        source_user_text="thymise mou na paro tis brizoles",
        source_ai_text="egine",
        followup_after_ts="2030-01-01T19:00:00",
        confidence=0.82,
        metadata={"delay_minutes_raw": 180, "delay_minutes_final": 180},
    )

    items = pf.find_pending_followups(limit=10)
    row = next(item for item in items if item["id"] == followup_id)

    assert row["source_channel"] == "web"
    assert row["source_agent"] == "Home_Agent"
    assert row["source_user_text"] == "thymise mou na paro tis brizoles"
    assert row["last_decision"] in ("created", "", None)
    assert "decision_reason" in row
    assert "outcome_score" in row
    assert "times_sent" in row
    assert "arc_key" in row and row["arc_key"]
    assert "metadata" in row and row["metadata"]["delay_minutes_final"] == 180
    assert "due_in_minutes" in row


def test_find_pending_followups_active_only_hides_resolved(temp_state_db):
    pending_id = pf.create_pending_followup(
        source_channel="web",
        source_agent="Home_Agent",
        topic="food_purchase",
        subject="brizoles laimou",
        source_user_text="thymise mou na paro tis brizoles",
        source_ai_text="egine",
        followup_after_ts="2030-01-01T19:00:00",
        confidence=0.82,
        metadata={"delay_minutes_raw": 180, "delay_minutes_final": 180},
    )
    resolved_id = pf.create_pending_followup(
        source_channel="web",
        source_agent="Home_Agent",
        topic="outing",
        subject="volta sto parko",
        source_user_text="pao parko",
        source_ai_text="ok",
        followup_after_ts="2030-01-01T20:00:00",
        confidence=0.70,
        metadata={"delay_minutes_raw": 60, "delay_minutes_final": 60},
    )
    pf.resolve_followup(resolved_id, "resolved_by_recent_user_message")

    active_rows = pf.find_pending_followups(limit=10, active_only=True)
    all_rows = pf.find_pending_followups(limit=10, active_only=False)

    active_ids = {row["id"] for row in active_rows}
    all_ids = {row["id"] for row in all_rows}

    assert pending_id in active_ids
    assert resolved_id not in active_ids
    assert resolved_id in all_ids


def test_maybe_create_followup_from_exchange_skips_linkedin_post_flow(temp_state_db):
    followup_id = pf.maybe_create_followup_from_exchange(
        user_text="φτιάξε ένα linkedin post για αυτο",
        ai_text="Ορίστε το LinkedIn post που ετοίμασα.",
        agent_name="Web_Agent",
        channel="web",
    )

    assert followup_id is None


def test_job_check_pending_followups_skips_when_recent_global_followup(monkeypatch):
    sent = []
    marked = []
    outcomes = []

    monkeypatch.setattr(bot, "expire_old_followups", lambda now_iso: None)
    monkeypatch.setattr(
        bot,
        "get_due_pending_followups",
        lambda now_iso: [
            {
                "id": 7,
                "topic": "food_purchase",
                "subject": "brizoles laimou",
                "source_user_text": "thymise mou na paro tis brizoles",
            }
        ],
    )
    monkeypatch.setattr(bot, "_load_recent_proactive_context", lambda limit=10: "")
    global_cooldowns = []
    monkeypatch.setattr(
        bot,
        "has_recent_sent_followup",
        lambda within_minutes: global_cooldowns.append(within_minutes) or True,
    )
    monkeypatch.setattr(
        bot,
        "has_recent_sent_followup_for_arc",
        lambda arc_key, within_minutes=240: False,
    )
    monkeypatch.setattr(bot, "_build_followup_decision_with_llm", lambda item, recent_context, state_snapshot: {}, raising=False)
    monkeypatch.setattr(bot, "send_telegram_msg", lambda msg: sent.append(msg))
    monkeypatch.setattr(bot, "mark_followup_sent", lambda followup_id: marked.append(followup_id))
    monkeypatch.setattr(
        bot,
        "record_followup_outcome",
        lambda followup_id, score, reason: outcomes.append((followup_id, score, reason)),
    )

    bot.job_check_pending_followups()

    assert sent == []
    assert marked == []
    assert outcomes == []
    assert global_cooldowns == [30]


def test_job_check_pending_followups_uses_short_global_cooldown_for_live_location_departure(monkeypatch):
    global_cooldowns = []
    llm_calls = []

    monkeypatch.setattr(bot, "expire_old_followups", lambda now_iso: None)
    monkeypatch.setattr(
        bot,
        "get_due_pending_followups",
        lambda now_iso: [
            {
                "id": 8,
                "topic": "departure",
                "subject": "stable_location_departure",
                "source_agent": "Location_Event",
                "source_user_text": "Live location detected departure.",
            }
        ],
    )
    monkeypatch.setattr(bot, "_load_recent_proactive_context", lambda limit=10: "")
    monkeypatch.setattr(
        bot,
        "has_recent_sent_followup",
        lambda within_minutes: global_cooldowns.append(within_minutes) or True,
    )
    monkeypatch.setattr(
        bot,
        "_build_followup_decision_with_llm",
        lambda *args: llm_calls.append(args),
    )

    bot.job_check_pending_followups()

    assert global_cooldowns == [5]
    assert llm_calls == []


def test_live_location_departure_continues_after_short_global_cooldown(monkeypatch):
    global_cooldowns = []
    arc_cooldowns = []
    llm_calls = []
    skip_calls = []

    monkeypatch.setattr(bot, "expire_old_followups", lambda now_iso: None)
    monkeypatch.setattr(
        bot,
        "get_due_pending_followups",
        lambda now_iso: [
            {
                "id": 10,
                "topic": "departure",
                "subject": "stable_location_departure",
                "source_agent": "Location_Event",
                "source_user_text": "Live location detected departure.",
            }
        ],
    )
    monkeypatch.setattr(bot, "_load_recent_proactive_context", lambda limit=10: "")
    monkeypatch.setattr(
        bot,
        "has_recent_sent_followup",
        lambda within_minutes: global_cooldowns.append(within_minutes) or False,
    )
    monkeypatch.setattr(
        bot,
        "has_recent_sent_followup_for_arc",
        lambda arc_key, within_minutes: arc_cooldowns.append(within_minutes) or False,
    )
    monkeypatch.setattr(bot, "_build_followup_state_snapshot", lambda: {})
    monkeypatch.setattr(
        bot,
        "_build_followup_decision_with_llm",
        lambda item, recent_context, state_snapshot: llm_calls.append(
            (item, recent_context, state_snapshot)
        ) or {
            "decision": "skip",
            "skip_action": "resolve",
            "stage": "skip",
            "message": "",
            "reason": "test",
        },
    )
    monkeypatch.setattr(
        bot,
        "_apply_followup_skip_outcome",
        lambda item, decision: skip_calls.append((item["id"], decision["skip_action"]))
        or "resolved",
    )

    bot.job_check_pending_followups()

    assert global_cooldowns == [5]
    assert arc_cooldowns == [240]
    assert len(llm_calls) == 1
    assert skip_calls == [(10, "resolve")]


def test_job_check_pending_followups_uses_default_cooldown_for_other_departure(monkeypatch):
    global_cooldowns = []
    llm_calls = []

    monkeypatch.setattr(bot, "expire_old_followups", lambda now_iso: None)
    monkeypatch.setattr(
        bot,
        "get_due_pending_followups",
        lambda now_iso: [
            {
                "id": 9,
                "topic": "departure",
                "subject": "manual_departure",
                "source_agent": "Chat_Agent",
                "source_user_text": "I am leaving now.",
            }
        ],
    )
    monkeypatch.setattr(bot, "_load_recent_proactive_context", lambda limit=10: "")
    monkeypatch.setattr(
        bot,
        "has_recent_sent_followup",
        lambda within_minutes: global_cooldowns.append(within_minutes) or True,
    )
    monkeypatch.setattr(
        bot,
        "_build_followup_decision_with_llm",
        lambda *args: llm_calls.append(args),
    )

    bot.job_check_pending_followups()

    assert global_cooldowns == [30]
    assert llm_calls == []


def test_enqueue_followup_pipeline_skips_create_after_resolution_update(monkeypatch):
    created = []

    monkeypatch.setattr(bot, "maybe_resolve_followups_from_user_message", lambda text: 1)
    monkeypatch.setattr(bot, "looks_like_followup_resolution_update", lambda text: True)
    monkeypatch.setattr(
        bot,
        "extract_followup_candidate_with_llm",
        lambda user_text, ai_text, agent_name, active_followups_text="": {
            "should_follow_up": True,
            "topic": "food_purchase",
            "subject": "brizoles laimou",
            "delay_minutes": 90,
            "confidence": 0.8,
            "reason": "same arc",
        },
    )
    monkeypatch.setattr(
        bot,
        "get_recently_resolved_followups",
        lambda limit=5, within_seconds=180: [
            {
                "topic": "food_purchase",
                "subject": "brizoles laimou",
                "arc_key": pf.build_followup_arc_key("food_purchase", "brizoles laimou"),
            }
        ],
    )
    monkeypatch.setattr(bot, "candidate_is_distinct_from_recently_resolved", lambda candidate, recent: False)
    monkeypatch.setattr(
        bot,
        "create_pending_followup_from_candidate",
        lambda **kwargs: created.append(kwargs),
    )

    bot._enqueue_followup_pipeline(
        "τις πήρα τώρα και φεύγω",
        "ωραία μάστορα",
        "Chat_Agent",
        "telegram",
    )

    assert created == []


def test_enqueue_followup_pipeline_allows_distinct_new_arc_after_resolution(monkeypatch):
    created = []

    monkeypatch.setattr(bot, "maybe_resolve_followups_from_user_message", lambda text: 1)
    monkeypatch.setattr(bot, "looks_like_followup_resolution_update", lambda text: True)
    monkeypatch.setattr(
        bot,
        "extract_followup_candidate_with_llm",
        lambda user_text, ai_text, agent_name, active_followups_text="": {
            "should_follow_up": True,
            "topic": "outing",
            "subject": "παρκο με οικογενεια",
            "delay_minutes": 60,
            "confidence": 0.82,
            "reason": "new arc",
        },
    )
    monkeypatch.setattr(
        bot,
        "get_recently_resolved_followups",
        lambda limit=5, within_seconds=180: [
            {
                "topic": "food_purchase",
                "subject": "brizoles laimou",
                "arc_key": pf.build_followup_arc_key("food_purchase", "brizoles laimou"),
            }
        ],
    )
    monkeypatch.setattr(bot, "candidate_is_distinct_from_recently_resolved", lambda candidate, recent: True)
    monkeypatch.setattr(
        bot,
        "create_pending_followup_from_candidate",
        lambda **kwargs: created.append(kwargs) or 77,
    )

    bot._enqueue_followup_pipeline(
        "τις πήρα τώρα και πάω να τους βρω στο πάρκο",
        "ωραία μάστορα",
        "Chat_Agent",
        "telegram",
    )

    assert len(created) == 1
    assert created[0]["candidate"]["topic"] == "outing"


def test_candidate_is_distinct_from_recently_resolved_allows_same_topic_new_arc():
    candidate = {
        "topic": "outing",
        "subject": "poto me sofia",
    }
    recent_resolved = [
        {
            "topic": "outing",
            "subject": "parko me alexandro",
            "arc_key": pf.build_followup_arc_key("outing", "parko me alexandro"),
        }
    ]

    assert pf.candidate_is_distinct_from_recently_resolved(candidate, recent_resolved) is True


def test_job_check_pending_followups_persists_sent_message(monkeypatch):
    sent = []
    marked = []
    outcomes = []

    monkeypatch.setattr(bot, "expire_old_followups", lambda now_iso: None)
    monkeypatch.setattr(
        bot,
        "get_due_pending_followups",
        lambda now_iso: [
            {
                "id": 9,
                "topic": "food_purchase",
                "subject": "brizoles laimou",
                "source_user_text": "thymise mou na paro tis brizoles",
            }
        ],
    )
    monkeypatch.setattr(bot, "_load_recent_proactive_context", lambda limit=10: "")
    monkeypatch.setattr(bot, "has_recent_sent_followup", lambda within_minutes=90: False)
    monkeypatch.setattr(
        bot,
        "has_recent_sent_followup_for_arc",
        lambda arc_key, within_minutes=240: False,
    )
    monkeypatch.setattr(bot, "_build_followup_state_snapshot", lambda: {})
    monkeypatch.setattr(
        bot,
        "_build_followup_decision_with_llm",
        lambda item, recent_context, state_snapshot: {
            "decision": "send",
            "stage": "decision_pending",
            "message": "κανε τις μπριζολες οπως τις σκεφτεσαι;",
            "reason": "test",
        },
    )
    monkeypatch.setattr(
        bot,
        "_send_and_record_assistant",
        lambda msg, chat_id=None, agent=None: sent.append((msg, agent)) or 123,
    )
    monkeypatch.setattr(
        bot,
        "mark_followup_sent",
        lambda followup_id, reason=None: marked.append((followup_id, reason)),
    )
    monkeypatch.setattr(
        bot,
        "record_followup_outcome",
        lambda followup_id, score, reason: outcomes.append((followup_id, score, reason)),
    )

    bot.job_check_pending_followups()

    assert sent == [("κανε τις μπριζολες οπως τις σκεφτεσαι;", "FollowUp_Agent")]
    assert marked == [(9, "followup_sent:decision_pending")]
    assert outcomes == [(9, 0.2, "followup_sent:decision_pending")]


def test_job_check_pending_followups_does_not_mark_sent_when_telegram_send_fails(monkeypatch):
    marked = []
    outcomes = []

    monkeypatch.setattr(bot, "expire_old_followups", lambda now_iso: None)
    monkeypatch.setattr(
        bot,
        "get_due_pending_followups",
        lambda now_iso: [
            {
                "id": 10,
                "topic": "food_purchase",
                "subject": "brizoles laimou",
                "source_user_text": "thymise mou na paro tis brizoles",
            }
        ],
    )
    monkeypatch.setattr(bot, "_load_recent_proactive_context", lambda limit=10: "")
    monkeypatch.setattr(bot, "has_recent_sent_followup", lambda within_minutes=90: False)
    monkeypatch.setattr(
        bot,
        "has_recent_sent_followup_for_arc",
        lambda arc_key, within_minutes=240: False,
    )
    monkeypatch.setattr(bot, "_build_followup_state_snapshot", lambda: {})
    monkeypatch.setattr(
        bot,
        "_build_followup_decision_with_llm",
        lambda item, recent_context, state_snapshot: {
            "decision": "send",
            "stage": "decision_pending",
            "message": "κανε τις μπριζολες οπως τις σκεφτεσαι;",
            "reason": "test",
        },
    )
    monkeypatch.setattr(
        bot,
        "_send_and_record_assistant",
        lambda msg, chat_id=None, agent=None: None,
    )
    monkeypatch.setattr(
        bot,
        "mark_followup_sent",
        lambda followup_id, reason=None: marked.append((followup_id, reason)),
    )
    monkeypatch.setattr(
        bot,
        "record_followup_outcome",
        lambda followup_id, score, reason: outcomes.append((followup_id, score, reason)),
    )

    bot.job_check_pending_followups()

    assert marked == []
    assert outcomes == []


def test_job_check_pending_followups_respects_outing_skip_decision(monkeypatch):
    sent = []
    skip_calls = []

    monkeypatch.setattr(bot, "expire_old_followups", lambda now_iso: None)
    monkeypatch.setattr(
        bot,
        "get_due_pending_followups",
        lambda now_iso: [
            {
                "id": 11,
                "topic": "outing",
                "subject": "βόλτα στο πάρκο",
                "source_user_text": "πάω πάρκο να τους βρω τώρα",
                "source_ai_text": "ωραία",
                "source_channel": "telegram",
                "source_agent": "Chat_Agent",
                "followup_after_ts": "2030-01-01T20:20:00",
            }
        ],
    )
    monkeypatch.setattr(
        bot,
        "_load_recent_proactive_context",
        lambda limit=10: "Lazaros: I am already at the park with Alexandros.",
    )
    monkeypatch.setattr(bot, "has_recent_sent_followup", lambda within_minutes=90: False)
    monkeypatch.setattr(
        bot,
        "has_recent_sent_followup_for_arc",
        lambda arc_key, within_minutes=240: False,
    )
    monkeypatch.setattr(bot, "_build_followup_state_snapshot", lambda: {})
    monkeypatch.setattr(
        bot,
        "_build_followup_decision_with_llm",
        lambda item, recent_context, state_snapshot: {
            "decision": "skip",
            "skip_action": "resolve",
            "stage": "skip",
            "message": "",
            "reason": "already_active",
        },
    )
    monkeypatch.setattr(
        bot,
        "_apply_followup_skip_outcome",
        lambda item, decision: skip_calls.append(
            (item["id"], decision["skip_action"], decision["reason"])
        ) or "resolved",
    )
    monkeypatch.setattr(
        bot,
        "_send_and_record_assistant",
        lambda msg, chat_id=None, agent=None: sent.append((msg, agent)) or 456,
    )

    bot.job_check_pending_followups()

    assert sent == []
    assert skip_calls == [(11, "resolve", "already_active")]



def test_job_check_pending_followups_does_not_skip_just_because_subject_is_in_recent_context(monkeypatch):
    sent = []
    marked = []
    outcomes = []

    monkeypatch.setattr(bot, "expire_old_followups", lambda now_iso: None)
    monkeypatch.setattr(
        bot,
        "get_due_pending_followups",
        lambda now_iso: [
            {
                "id": 12,
                "topic": "outing",
                "subject": "volta sto parko",
                "source_user_text": "pao parko na tous vro",
            }
        ],
    )
    monkeypatch.setattr(
        bot,
        "_load_recent_proactive_context",
        lambda limit=10: "Lazaros: pao parko na tous vro\nAssistant: egine, kali volta",
    )
    monkeypatch.setattr(bot, "has_recent_sent_followup", lambda within_minutes=90: False)
    monkeypatch.setattr(
        bot,
        "has_recent_sent_followup_for_arc",
        lambda arc_key, within_minutes=240: False,
    )
    monkeypatch.setattr(bot, "_build_followup_state_snapshot", lambda: {})
    monkeypatch.setattr(
        bot,
        "_build_followup_decision_with_llm",
        lambda item, recent_context, state_snapshot: {
            "decision": "send",
            "stage": "decision_pending",
            "message": "Tous vrikes telika gia volta sto parko?",
            "reason": "test",
        },
    )
    monkeypatch.setattr(
        bot,
        "_send_and_record_assistant",
        lambda msg, chat_id=None, agent=None: sent.append((msg, agent)) or 789,
    )
    monkeypatch.setattr(
        bot,
        "mark_followup_sent",
        lambda followup_id, reason=None: marked.append((followup_id, reason)),
    )
    monkeypatch.setattr(
        bot,
        "record_followup_outcome",
        lambda followup_id, score, reason: outcomes.append((followup_id, score, reason)),
    )

    bot.job_check_pending_followups()

    assert sent == [("Tous vrikes telika gia volta sto parko?", "FollowUp_Agent")]
    assert marked == [(12, "followup_sent:decision_pending")]
    assert outcomes == [(12, 0.2, "followup_sent:decision_pending")]


def test_followup_safe_fallback_is_non_assumptive():
    import clients.telegram_bot as bot

    item = {
        "topic": "food_purchase",
        "subject": "μπριζόλες λαιμού",
    }

    msg = bot._build_safe_followup_fallback(item, "decision_pending")
    assert "Πώς πήγε" not in msg
    assert "μπριζόλες λαιμού" in msg


def test_followup_decision_fallback_defaults_to_non_assumptive(monkeypatch):
    import clients.telegram_bot as bot

    monkeypatch.setattr(
        bot,
        "_build_followup_state_snapshot",
        lambda: {},
    )

    class DummyResponse:
        text = "not json"

    import services.gemini as gemini
    monkeypatch.setattr(
        gemini,
        "safe_gemini_call",
        lambda prompt: DummyResponse(),
    )

    item = {
        "topic": "food_purchase",
        "subject": "μπριζόλες λαιμού",
        "source_user_text": "θύμισέ μου να τις πάρω",
        "source_ai_text": "έγινε",
        "source_channel": "web",
        "source_agent": "Home_Agent",
        "followup_after_ts": "2030-01-01T18:00:00",
    }

    result = bot._build_followup_decision_with_llm(item, "", {})
    assert result["decision"] == "skip"
    assert result["skip_action"] == "defer"
    assert result["stage"] == "skip"
    assert result["reason"] == "llm_decision_failed_safe_defer"


def test_normalize_followup_delay_food_purchase_tomorrow_targets_next_day_lunch_window():
    from datetime import datetime
    from memory.pending_followups import normalize_followup_delay

    now = datetime(2026, 7, 3, 22, 0, 0)
    delay = normalize_followup_delay(
        "food_purchase",
        287,
        "οι μπριζόλες αύριο",
        now=now,
    )

    # from 22:00 today until 11:30 tomorrow = 810 minutes (plus jitter)
    assert abs(delay - 810) <= 35


def test_normalize_followup_delay_food_purchase_tomorrow_from_evening_still_targets_lunch():
    from datetime import datetime
    from memory.pending_followups import normalize_followup_delay

    now = datetime(2026, 7, 3, 19, 0, 0)
    delay = normalize_followup_delay(
        "food_purchase",
        287,
        "τελικά αύριο θα τις κάνουμε",
        now=now,
    )

    # from 19:00 today until 11:30 tomorrow = 990 minutes (plus jitter)
    assert abs(delay - 990) <= 35


def test_normalize_followup_delay_food_purchase_tonight_stays_short():
    from datetime import datetime
    from memory.pending_followups import normalize_followup_delay

    now = datetime(2026, 7, 3, 20, 0, 0)
    delay = normalize_followup_delay(
        "food_purchase",
        90,
        "μόλις πήρα τις μπριζόλες, απόψε θα τις ψήσουμε",
        now=now,
    )

    assert 30 <= delay <= 120


def test_normalize_followup_delay_same_day_short_checkin():
    from datetime import datetime
    from memory.pending_followups import normalize_followup_delay

    now = datetime(2026, 7, 3, 18, 0, 0)
    delay = normalize_followup_delay(
        "outing",
        120,
        "πάω τώρα να τους βρω στο πάρκο",
        target_window="same_day_short_checkin",
        now=now,
    )

    assert 20 <= delay <= 90


def test_normalize_followup_delay_next_day_late_morning():
    from datetime import datetime
    from memory.pending_followups import normalize_followup_delay

    now = datetime(2026, 7, 3, 22, 0, 0)
    delay = normalize_followup_delay(
        "food_purchase",
        287,
        "οι μπριζόλες αύριο",
        target_window="next_day_late_morning",
        now=now,
    )

    assert abs(delay - 810) <= 35


def test_normalize_followup_delay_next_day_afternoon():
    from datetime import datetime
    from memory.pending_followups import normalize_followup_delay

    now = datetime(2026, 7, 3, 20, 0, 0)
    delay = normalize_followup_delay(
        "appointment",
        180,
        "αύριο θα δούμε για το interview",
        target_window="next_day_afternoon",
        now=now,
    )

    assert delay > 12 * 60


def test_normalize_followup_delay_fallback_food_tomorrow_without_window():
    from datetime import datetime
    from memory.pending_followups import normalize_followup_delay

    now = datetime(2026, 7, 3, 22, 0, 0)
    delay = normalize_followup_delay(
        "food_purchase",
        287,
        "οι μπριζόλες αύριο",
        target_window="",
        now=now,
    )

    assert abs(delay - 810) <= 35


def test_create_pending_followup_preserves_target_window(monkeypatch, temp_state_db):
    from memory import pending_followups as pf

    candidate = {
        "should_follow_up": True,
        "topic": "food_purchase",
        "subject": "ψήσιμο μπριζόλας",
        "delay_minutes": 180,
        "target_window": "next_day_late_morning",
        "confidence": 0.85,
        "reason": "user moved cooking to tomorrow",
    }

    followup_id = pf.create_pending_followup_from_candidate(
        candidate=candidate,
        source_channel="telegram",
        source_agent="Home_Agent",
        source_user_text="οι μπριζόλες αύριο",
        source_ai_text="ok",
    )

    rows = pf.find_pending_followups(limit=10)
    row = next(item for item in rows if item["id"] == followup_id)
    assert row["metadata"]["target_window"] == "next_day_late_morning"
    assert row["metadata"]["ttl_hours"] == 18


def test_normalize_followup_delay_explicit_timer_returns_clamped_delay():
    from datetime import datetime
    from memory.pending_followups import normalize_followup_delay

    now = datetime(2026, 7, 3, 20, 0, 0)
    delay = normalize_followup_delay(
        "general_progress",
        125,
        "σε 2 ώρες ρώτα με",
        target_window="explicit_timer",
        now=now,
    )

    assert delay == 125


def test_compute_followup_ttl_hours_next_day_window():
    from memory.pending_followups import _compute_followup_ttl_hours

    ttl = _compute_followup_ttl_hours(
        delay_minutes=810,
        target_window="next_day_late_morning",
        topic="food_purchase",
    )
    assert ttl == 18


def test_compute_followup_ttl_hours_explicit_timer_medium():
    from memory.pending_followups import _compute_followup_ttl_hours

    ttl = _compute_followup_ttl_hours(
        delay_minutes=8 * 60,
        target_window="explicit_timer",
        topic="general_progress",
    )
    assert ttl == 12


def test_next_day_morning_on_friday_night_targets_weekend_later_morning():
    from datetime import datetime
    from memory.pending_followups import FOLLOWUP_LOCAL_TZ, normalize_followup_delay

    now = datetime(2030, 1, 4, 22, 0, tzinfo=FOLLOWUP_LOCAL_TZ)

    delay = normalize_followup_delay(
        topic="outing",
        suggested_minutes=600,
        source_user_text="αύριο να με ρωτήσεις",
        target_window="next_day_morning",
        now=now,
    )

    assert delay == 13 * 60


def test_next_day_late_morning_on_weekend_stays_as_requested():
    from datetime import datetime
    from memory.pending_followups import FOLLOWUP_LOCAL_TZ, normalize_followup_delay

    now = datetime(2030, 1, 4, 22, 0, tzinfo=FOLLOWUP_LOCAL_TZ)

    delay = normalize_followup_delay(
        topic="food_purchase",
        suggested_minutes=700,
        source_user_text="οι μπριζόλες αύριο",
        target_window="next_day_late_morning",
        now=now,
    )

    assert abs(delay - (13 * 60 + 30)) <= 35


def test_defer_followup_moves_due_time_and_keeps_pending(temp_state_db):
    followup_id = pf.create_pending_followup(
        source_channel="telegram",
        source_agent="Chat_Agent",
        topic="food_purchase",
        subject="μπριζόλες λαιμού",
        source_user_text="θυμισέ μου για τις μπριζόλες",
        source_ai_text="έγινε",
        followup_after_ts="2030-01-01T19:00:00+02:00",
        confidence=0.8,
        metadata={},
    )

    pf.defer_followup(
        followup_id,
        delay_minutes=180,
        reason="deferred:user_said_tomorrow",
    )

    rows = pf.find_pending_followups(limit=10)
    row = rows[0]
    assert row["status"] == "pending"
    assert row["last_decision"] == "deferred"
    assert row["decision_reason"] == "deferred:user_said_tomorrow"


def test_maybe_resolve_followups_from_user_message_defers_when_user_postpones(temp_state_db, monkeypatch):
    pf.create_pending_followup(
        source_channel="telegram",
        source_agent="Chat_Agent",
        topic="food_purchase",
        subject="μπριζόλες λαιμού",
        source_user_text="θυμισέ μου για τις μπριζόλες",
        source_ai_text="έγινε",
        followup_after_ts="2030-01-01T19:00:00+02:00",
        confidence=0.8,
        metadata={},
    )

    monkeypatch.setattr(
        pf,
        "classify_followup_resolution_with_llm",
        lambda **kwargs: {
            "resolves": False,
            "resolution_type": "",
            "confidence": 0.2,
            "reason": "not resolved",
        },
    )

    monkeypatch.setattr(
        pf,
        "classify_followup_deferral_with_llm",
        lambda **kwargs: {
            "should_defer": True,
            "delay_minutes": 720,
            "target_window": "next_day_late_morning",
            "reason": "user postponed to tomorrow",
            "confidence": 0.88,
        },
    )

    pf.maybe_resolve_followups_from_user_message("όχι σήμερα, αύριο οι μπριζόλες")

    row = pf.find_pending_followups(limit=10)[0]
    assert row["status"] == "pending"
    assert row["last_decision"] == "deferred"
    assert "postponed" in row["decision_reason"]


def test_resolve_followup_sets_iso_resolved_at(temp_state_db):
    followup_id = pf.create_pending_followup(
        source_channel="telegram",
        source_agent="Chat_Agent",
        topic="outing",
        subject="συνάντηση με Partner",
        source_user_text="σε λίγο φεύγω να τη βρω",
        source_ai_text="οκ",
        followup_after_ts="2030-01-01T19:00:00+02:00",
        confidence=0.80,
        metadata={},
    )

    pf.resolve_followup(followup_id, "resolved_by_user:completed")

    conn = sqlite3.connect(str(temp_state_db))
    try:
        row = conn.execute(
            "SELECT resolved_at FROM pending_followups WHERE id=?",
            (followup_id,),
        ).fetchone()
    finally:
        conn.close()

    assert row is not None
    assert "T" in row[0]


def test_defer_followup_refreshes_expiry_and_metadata(temp_state_db):
    followup_id = pf.create_pending_followup(
        source_channel="telegram",
        source_agent="Chat_Agent",
        topic="food_purchase",
        subject="μπριζόλες λαιμού",
        source_user_text="θυμισέ μου για τις μπριζόλες",
        source_ai_text="έγινε",
        followup_after_ts="2030-01-01T19:00:00+02:00",
        confidence=0.80,
        metadata={"target_window": "same_day_evening"},
    )

    pf.defer_followup(
        followup_id,
        delay_minutes=720,
        reason="deferred:user_said_tomorrow",
        target_window="next_day_late_morning",
        topic="food_purchase",
    )

    row = pf.find_pending_followups(limit=10)[0]

    assert row["status"] == "pending"
    assert row["last_decision"] == "deferred"
    assert row["decision_reason"] == "deferred:user_said_tomorrow"
    assert row["metadata"]["target_window"] == "next_day_late_morning"
    assert row["metadata"]["ttl_hours"] == 18


def test_defer_followup_sets_expires_after_followup_after_ts(temp_state_db):
    followup_id = pf.create_pending_followup(
        source_channel="telegram",
        source_agent="Chat_Agent",
        topic="outing",
        subject="συνάντηση με Partner",
        source_user_text="μετά θα πάω",
        source_ai_text="οκ",
        followup_after_ts="2030-01-01T19:00:00+02:00",
        confidence=0.80,
        metadata={},
    )

    pf.defer_followup(
        followup_id,
        delay_minutes=180,
        reason="deferred:user_postponed",
        target_window="after_likely_completion",
        topic="outing",
    )

    row = pf.find_pending_followups(limit=10)[0]
    due_dt = datetime.fromisoformat(row["followup_after_ts"])
    exp_dt = datetime.fromisoformat(row["expires_at"])

    assert exp_dt > due_dt


def test_backfill_legacy_followups_populates_missing_metadata_and_reanchors_pending(temp_state_db):
    conn = sqlite3.connect(str(temp_state_db))
    try:
        conn.execute(
            """
            INSERT INTO pending_followups (
                source_channel, source_agent, topic, subject, source_user_text, source_ai_text,
                followup_after_ts, expires_at, confidence, status, resolution_reason, metadata_json,
                created_at, arc_key
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "telegram",
                "Home_Agent",
                "food_purchase",
                "ψήσιμο μπριζόλας",
                "Οι μπριζόλες αύριο",
                "Οκ",
                "2030-01-02T03:30:00+02:00",
                "2030-01-02T15:30:00+02:00",
                0.8,
                "pending",
                "",
                json.dumps({"reason": "legacy row", "delay_minutes_raw": 720}, ensure_ascii=False),
                "2030-01-01 19:30:00",
                pf.build_followup_arc_key("food_purchase", "ψήσιμο μπριζόλας"),
            ),
        )
        conn.commit()
    finally:
        conn.close()

    updated = pf.backfill_legacy_followups()
    assert updated == 1

    row = pf.find_pending_followups(limit=10)[0]
    assert row["metadata"]["target_window"] == "next_day_late_morning"
    assert row["metadata"]["ttl_hours"] == 18
    assert row["metadata"]["delay_minutes_final"] >= 8 * 60
    assert "T11:" in row["followup_after_ts"] or "T12:" in row["followup_after_ts"]


def test_active_followup_same_theme_detects_related_food_variants():
    assert pf._active_followup_is_same_theme(
        topic="food_purchase",
        subject="ψήσιμο μπριζόλας",
        source_user_text="οι μπριζόλες αύριο",
        reason="follow up on steak preparation",
        existing_topic="food_purchase",
        existing_subject="συνοδευτικό για μπριζόλες",
        existing_source_user_text="θα αποφασίσουμε αν θα κάνουμε πατάτες ή ρύζι με τις μπριζόλες",
        existing_reason="check meal decision later",
    ) is True


def test_create_pending_followup_skips_same_theme_active_arc(temp_state_db):
    first_id = pf.create_pending_followup(
        source_channel="telegram",
        source_agent="Chat_Agent",
        topic="food_purchase",
        subject="ψήσιμο μπριζόλας",
        source_user_text="οι μπριζόλες αύριο",
        source_ai_text="έγινε μάστορα",
        followup_after_ts="2030-01-01T19:00:00",
        confidence=0.82,
        metadata={"reason": "follow up on steak preparation"},
    )

    second_id = pf.create_pending_followup(
        source_channel="telegram",
        source_agent="Chat_Agent",
        topic="food_purchase",
        subject="συνοδευτικό για μπριζόλες",
        source_user_text="θα αποφασίσουμε αν θα κάνουμε πατάτες ή ρύζι με τις μπριζόλες",
        source_ai_text="οκ",
        followup_after_ts="2030-01-01T20:00:00",
        confidence=0.81,
        metadata={"reason": "check meal decision later"},
    )

    assert isinstance(first_id, int)
    assert second_id is None

    rows = _fetch_all(temp_state_db)
    assert len(rows) == 1


def test_create_pending_followup_allows_different_theme_same_topic(temp_state_db):
    first_id = pf.create_pending_followup(
        source_channel="telegram",
        source_agent="Chat_Agent",
        topic="food_purchase",
        subject="μπριζόλες λαιμού",
        source_user_text="πήρα μπριζόλες για αύριο",
        source_ai_text="έγινε",
        followup_after_ts="2030-01-01T19:00:00",
        confidence=0.82,
        metadata={"reason": "follow up on steaks"},
    )

    second_id = pf.create_pending_followup(
        source_channel="telegram",
        source_agent="Chat_Agent",
        topic="food_purchase",
        subject="ψώνια για γλυκό",
        source_user_text="μετά θα πάρω και παγωτό για το βράδυ",
        source_ai_text="οκ",
        followup_after_ts="2030-01-01T20:00:00",
        confidence=0.81,
        metadata={"reason": "follow up on dessert"},
    )

    assert isinstance(first_id, int)
    assert isinstance(second_id, int)

    rows = _fetch_all(temp_state_db)
    assert len(rows) == 2


def test_active_followup_same_theme_does_not_merge_generic_single_token_outings():
    assert pf._active_followup_is_same_theme(
        topic="outing",
        subject="βόλτα με Partner",
        source_user_text="θα βγω με τη Partner",
        reason="follow up on outing",
        existing_topic="outing",
        existing_subject="βόλτα με Αλέξανδρο",
        existing_source_user_text="πήγα τον Αλέξανδρο βόλτα",
        existing_reason="check outing later",
    ) is False


def test_create_pending_followup_allows_same_topic_when_overlap_is_only_generic(temp_state_db):
    first_id = pf.create_pending_followup(
        source_channel="telegram",
        source_agent="Chat_Agent",
        topic="outing",
        subject="βόλτα με Partner",
        source_user_text="θα βγω με τη Partner",
        source_ai_text="έγινε",
        followup_after_ts="2030-01-01T19:00:00",
        confidence=0.82,
        metadata={"reason": "follow up on outing"},
    )

    second_id = pf.create_pending_followup(
        source_channel="telegram",
        source_agent="Chat_Agent",
        topic="outing",
        subject="βόλτα με Αλέξανδρο",
        source_user_text="πήγα τον Αλέξανδρο βόλτα",
        source_ai_text="οκ",
        followup_after_ts="2030-01-01T20:00:00",
        confidence=0.81,
        metadata={"reason": "check outing later"},
    )

    assert isinstance(first_id, int)
    assert isinstance(second_id, int)

    rows = _fetch_all(temp_state_db)
    assert len(rows) == 2


def test_maybe_create_followup_skips_mixed_messenger_send_exchange(temp_state_db):
    result = pf.maybe_create_followup_from_exchange(
        user_text="Στείλε το μήνυμα. Τώρα βγήκαμε βόλτα με τον Αλέξανδρο.",
        ai_text="Έγινε, μάστορα.",
        agent_name="Home_Agent",
        channel="telegram",
    )

    assert result is None

def test_maybe_create_followup_skips_operational_reminder_exchange(temp_state_db):
    import memory.pending_followups as pf

    followup_id = pf.maybe_create_followup_from_exchange(
        user_text="θύμισε μου αύριο 5:30 να ξυπνήσω γιατί είμαι πρωινός",
        ai_text="✅ Υπενθύμιση ρυθμίστηκε για τις 2026-07-06 05:30!",
        agent_name="Home_Agent",
        channel="telegram",
    )

    assert followup_id is None
    assert pf.find_pending_followups(limit=10) == []

def test_maybe_create_followup_skips_wakeup_shift_reminder_exchange(temp_state_db):
    import memory.pending_followups as pf

    followup_id = pf.maybe_create_followup_from_exchange(
        user_text="Ναι φίλε τελειώνουμε φαι και πάμε και λογικά θα κοιμηθώ εγώ πρώτος αύριο πρωινός στην δουλειά 5:30 ξύπνημα",
        ai_text="✅ Υπενθύμιση ρυθμίστηκε για τις 2026-07-06 05:30!",
        agent_name="Home_Agent",
        channel="telegram",
    )

    assert followup_id is None
    assert pf.find_pending_followups(limit=10) == []

def test_maybe_create_followup_non_reminder_flow_still_allowed(temp_state_db, monkeypatch):
    import memory.pending_followups as pf

    monkeypatch.setattr(
        pf,
        "extract_followup_candidate_with_llm",
        lambda user_text, ai_text, agent_name, active_followups_text="": {
            "should_follow_up": True,
            "topic": "food_purchase",
            "subject": "μπριζόλες λαιμού",
            "delay_minutes": 180,
            "confidence": 0.86,
            "reason": "worth checking later",
            "target_window": "same_day_evening",
        },
    )

    followup_id = pf.maybe_create_followup_from_exchange(
        user_text="πήρα τις μπριζόλες λαιμού και θα δούμε το βράδυ πώς θα τις κάνουμε",
        ai_text="ωραία, το κρατάω",
        agent_name="Home_Agent",
        channel="telegram",
    )

    assert isinstance(followup_id, int)
    rows = pf.find_pending_followups(limit=10)
    assert len(rows) == 1
    assert rows[0]["topic"] == "food_purchase"

def test_looks_like_operational_reminder_exchange_detects_alarm_pair():
    import memory.pending_followups as pf

    assert pf.looks_like_operational_reminder_exchange(
        "θύμισε μου αύριο 5:30 να ξυπνήσω",
        "✅ Υπενθύμιση ρυθμίστηκε για τις 2026-07-06 05:30!",
    ) is True


def test_followup_decision_returns_structural_skip_action(monkeypatch):
    import clients.telegram_bot as bot
    import services.gemini as gemini

    class DummyResponse:
        text = '{"decision":"skip","skip_action":"resolve","stage":"skip","message":"","reason":"already done"}'

    monkeypatch.setattr(gemini, "safe_gemini_call", lambda prompt: DummyResponse())

    result = bot._build_followup_decision_with_llm(
        {"topic": "outing", "subject": "πάρκο", "source_user_text": "πήγαμε πάρκο"},
        "",
        {},
    )

    assert result["decision"] == "skip"
    assert result["skip_action"] == "resolve"


def test_departure_decision_requires_verified_recent_context(monkeypatch):
    import clients.telegram_bot as bot
    import services.gemini as gemini

    class DummyResponse:
        text = (
            '{"decision":"send","skip_action":"none",'
            '"stage":"decision_pending","message":"How did it go?",'
            '"reason":"departure detected","context_evidence":""}'
        )

    monkeypatch.setattr(gemini, "safe_gemini_call", lambda prompt: DummyResponse())

    result = bot._build_followup_decision_with_llm(
        {
            "topic": "departure",
            "subject": "stable_location_departure",
            "source_user_text": "Live location detected departure.",
        },
        "User: general unrelated chat",
        {},
    )

    assert result["decision"] == "skip"
    assert result["skip_action"] == "resolve"


def test_departure_decision_accepts_verbatim_recent_context_evidence(monkeypatch):
    import clients.telegram_bot as bot
    import services.gemini as gemini

    class DummyResponse:
        text = (
            '{"decision":"send","skip_action":"none",'
            '"stage":"decision_pending","message":"Finished at the gym?",'
            '"reason":"recent activity is still relevant",'
            '"context_evidence":"went to the gym"}'
        )

    monkeypatch.setattr(gemini, "safe_gemini_call", lambda prompt: DummyResponse())

    result = bot._build_followup_decision_with_llm(
        {
            "topic": "departure",
            "subject": "stable_location_departure",
            "source_user_text": "Live location detected departure.",
        },
        "User: I went to the gym and will leave soon.",
        {},
    )

    assert result["decision"] == "send"
    assert result["message"] == "Finished at the gym?"


def test_departure_skip_resolves_instead_of_deferring(monkeypatch):
    import clients.telegram_bot as bot
    import memory.pending_followups as pf

    resolved = []
    decisions = []

    monkeypatch.setattr(
        pf,
        "resolve_followup",
        lambda followup_id, reason: resolved.append((followup_id, reason)),
    )
    monkeypatch.setattr(
        pf,
        "_set_followup_decision",
        lambda followup_id, decision, reason: decisions.append(
            (followup_id, decision, reason)
        ),
    )

    outcome = bot._apply_followup_skip_outcome(
        {"id": 42, "topic": "departure", "metadata": {}},
        {
            "decision": "skip",
            "skip_action": "defer",
            "reason": "no verified recent context",
        },
    )

    assert outcome == "resolved"
    assert resolved == [(42, "resolved_by_skip:no verified recent context")]
    assert decisions == [(42, "resolved", "no verified recent context")]



def test_next_day_window_never_targets_today_morning():
    from datetime import datetime
    from memory.pending_followups import FOLLOWUP_LOCAL_TZ, normalize_followup_delay

    now = datetime(2026, 7, 6, 8, 0, tzinfo=FOLLOWUP_LOCAL_TZ)

    delay = normalize_followup_delay(
        topic="appointment",
        suggested_minutes=720,
        source_user_text="αύριο το πρωί",
        target_window="next_day_morning",
        now=now,
    )

    assert delay > 20 * 60
