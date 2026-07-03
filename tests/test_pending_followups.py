import json
import sqlite3
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


def test_maybe_resolve_followups_from_user_message_uses_llm_resolution(temp_state_db, monkeypatch):
    pf.create_pending_followup(
        source_channel="telegram",
        source_agent="Chat_Agent",
        topic="outing",
        subject="συνάντηση με Σοφία",
        source_user_text="Σε λίγο φεύγω να βρω τη Σοφία",
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

    pf.maybe_resolve_followups_from_user_message("Τους βρήκα τελικά στο πάρκο")

    rows = _fetch_all(temp_state_db)
    assert len(rows) == 1
    assert rows[0][3] == "resolved"
    assert rows[0][6] == "resolved_by_user:completed"


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


def test_normalize_followup_delay_clamps_outing_window():
    assert pf.normalize_followup_delay("outing", 20, "") == 45
    assert pf.normalize_followup_delay("outing", 500, "") == 180
    assert pf.normalize_followup_delay("outing", 90, "") == 90


def test_normalize_followup_delay_clamps_food_purchase_window():
    assert pf.normalize_followup_delay("food_purchase", 20, "θα τις κάνω το βράδυ") == 60
    assert pf.normalize_followup_delay("food_purchase", 500, "θα τις κάνω το βράδυ") == 240
    assert pf.normalize_followup_delay("food_purchase", 120, "θα τις κάνω το βράδυ") == 120


def test_maybe_create_followup_from_exchange_stores_raw_and_final_delay(temp_state_db, monkeypatch):
    monkeypatch.setattr(
        pf,
        "extract_followup_candidate_with_llm",
        lambda user_text, ai_text, agent_name: {
            "should_follow_up": True,
            "topic": "outing",
            "subject": "συνάντηση με Σοφία",
            "delay_minutes": 500,
            "confidence": 0.88,
            "reason": "worth checking later",
        },
    )

    followup_id = pf.maybe_create_followup_from_exchange(
        user_text="Σε λίγο φεύγω να βρω τη Σοφία",
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
    assert metadata["delay_minutes_final"] == 180


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
    monkeypatch.setattr(bot, "has_recent_sent_followup", lambda within_minutes=90: True)
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


def test_enqueue_followup_pipeline_skips_create_after_resolution_update(monkeypatch):
    created = []

    monkeypatch.setattr(bot, "maybe_resolve_followups_from_user_message", lambda text: 1)
    monkeypatch.setattr(bot, "looks_like_followup_resolution_update", lambda text: True)
    monkeypatch.setattr(
        bot,
        "maybe_create_followup_from_exchange",
        lambda **kwargs: created.append(kwargs),
    )

    bot._enqueue_followup_pipeline(
        "Ï„Î¹Ï‚ Ï€Î®ÏÎ± Ï„ÏŽÏÎ± ÎºÎ±Î¹ Ï†ÎµÏÎ³Ï‰",
        "Ï‰ÏÎ±Î¯Î± Î¼Î¬ÏƒÏ„Î¿ÏÎ±",
        "Chat_Agent",
        "telegram",
    )

    assert created == []


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
        lambda msg, chat_id=None, agent=None: sent.append((msg, agent)),
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
    assert result["decision"] == "send"
    assert result["stage"] == "decision_pending"
    assert "Πώς πήγε" not in result["message"]
