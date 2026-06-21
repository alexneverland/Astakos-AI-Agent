import sqlite3

import pytest

from memory import session_memory


@pytest.fixture
def isolated_state_db(tmp_path, monkeypatch):
    state_db = tmp_path / "state.db"
    monkeypatch.setattr(session_memory, "STATE_DB", str(state_db))
    return state_db


def test_slow_sifter_replay_guard_skips_same_exchange(isolated_state_db, monkeypatch):
    saved = []

    monkeypatch.setattr(
        session_memory.memory,
        "save",
        lambda **kwargs: saved.append(kwargs),
    )

    class DummyResponse:
        text = """
        [
          {
            "fact": "[USER_FACT]: Στις 2026-06-21, το ποδόσφαιρο του Αλέξανδρου σταματάει για το καλοκαίρι και ξαναρχίζει τον Σεπτέμβριο.",
            "category": "family",
            "topic": "activity",
            "topic_detail": "football season",
            "relation_type": "state_update",
            "state_markers": ["paused", "seasonal_break"],
            "time_scope": "2026-06-21",
            "confidence": 0.92
          }
        ]
        """

    monkeypatch.setattr(session_memory, "safe_gemini_call", lambda prompt: DummyResponse())

    user_text = "Είναι καλοκαίρι ο Αλέξανδρος δεν έχει ποδόσφαιρο ξανά τον Σεπτέμβριο"
    ai_text = "Έγινε μάστορα, το κρατάω ότι οι προπονήσεις σταματούν για το καλοκαίρι."

    session_memory.run_memory_sifter_slow(
        user_text=user_text,
        ai_text=ai_text,
        agent_name="Home_Agent",
        channel="telegram",
        deterministic_seed_facts=[],
    )

    session_memory.run_memory_sifter_slow(
        user_text=user_text,
        ai_text=ai_text,
        agent_name="Home_Agent",
        channel="telegram",
        deterministic_seed_facts=[],
    )

    assert len(saved) == 1
    assert "ποδόσφαιρο του Αλέξανδρου" in saved[0]["fact"]

    conn = sqlite3.connect(str(isolated_state_db))
    try:
        rows = conn.execute(
            "SELECT fingerprint, channel, agent_name FROM memory_sifter_runs"
        ).fetchall()
    finally:
        conn.close()

    assert len(rows) == 1
    assert rows[0][1] == "telegram"
    assert rows[0][2] == "Home_Agent"


def test_slow_sifter_allows_new_follow_up_not_replay(isolated_state_db, monkeypatch):
    saved = []

    monkeypatch.setattr(
        session_memory.memory,
        "save",
        lambda **kwargs: saved.append(kwargs),
    )

    responses = [
        """
        [
          {
            "fact": "[USER_FACT]: Στις 2026-06-21, ο Αλέξανδρος σταματάει το ποδόσφαιρο για το καλοκαίρι.",
            "category": "family",
            "topic": "activity",
            "topic_detail": "football season",
            "relation_type": "state_update",
            "state_markers": ["paused", "seasonal_break"],
            "time_scope": "2026-06-21",
            "confidence": 0.90
          }
        ]
        """,
        """
        [
          {
            "fact": "[USER_FACT]: Στις 2026-06-21, το ποδόσφαιρο του Αλέξανδρου ξαναρχίζει τον Σεπτέμβριο.",
            "category": "family",
            "topic": "activity",
            "topic_detail": "football season restart",
            "relation_type": "follow_up",
            "state_markers": ["scheduled"],
            "time_scope": "2026-06-21",
            "confidence": 0.91
          }
        ]
        """,
    ]

    class DummyResponse:
        def __init__(self, text):
            self.text = text

    def fake_gemini(_prompt):
        return DummyResponse(responses.pop(0))

    monkeypatch.setattr(session_memory, "safe_gemini_call", fake_gemini)

    session_memory.run_memory_sifter_slow(
        user_text="Είναι καλοκαίρι ο Αλέξανδρος δεν έχει ποδόσφαιρο",
        ai_text="Το κράτησα.",
        agent_name="Home_Agent",
        channel="telegram",
        deterministic_seed_facts=[],
    )

    session_memory.run_memory_sifter_slow(
        user_text="Ξανά ποδόσφαιρο από Σεπτέμβριο",
        ai_text="Οκ, το σημείωσα κι αυτό.",
        agent_name="Home_Agent",
        channel="telegram",
        deterministic_seed_facts=[],
    )

    assert len(saved) == 2
    assert "καλοκαίρι" in saved[0]["fact"]
    assert "Σεπτέμβριο" in saved[1]["fact"]


def test_slow_sifter_skips_seed_duplicate(isolated_state_db, monkeypatch):
    saved = []

    monkeypatch.setattr(
        session_memory.memory,
        "save",
        lambda **kwargs: saved.append(kwargs),
    )

    class DummyResponse:
        text = """
        [
          {
            "fact": "[USER_FACT]: Στις 2026-06-21, ο Αλέξανδρος σταματάει το ποδόσφαιρο για το καλοκαίρι.",
            "category": "family",
            "topic": "activity",
            "topic_detail": "football season",
            "relation_type": "state_update",
            "state_markers": ["paused", "seasonal_break"],
            "time_scope": "2026-06-21",
            "confidence": 0.90
          }
        ]
        """

    monkeypatch.setattr(session_memory, "safe_gemini_call", lambda prompt: DummyResponse())

    session_memory.run_memory_sifter_slow(
        user_text="Είναι καλοκαίρι ο Αλέξανδρος δεν έχει ποδόσφαιρο",
        ai_text="Το κράτησα.",
        agent_name="Home_Agent",
        channel="telegram",
        deterministic_seed_facts=[
            "[USER_FACT]: Στις 2026-06-21, ο Αλέξανδρος σταματάει το ποδόσφαιρο για το καλοκαίρι."
        ],
    )

    assert saved == []

def test_slow_sifter_skips_same_day_family_near_duplicate(isolated_state_db, monkeypatch):
    saved = []

    monkeypatch.setattr(
        session_memory.memory,
        "save",
        lambda **kwargs: saved.append(kwargs),
    )

    responses = [
        """
        [
          {
            "fact": "[USER_FACT]: Στις 2026-06-21, ο Αλέξανδρος σταματάει το ποδόσφαιρο για το καλοκαίρι.",
            "category": "family",
            "topic": "activity",
            "topic_detail": "football season",
            "relation_type": "state_update",
            "state_markers": ["paused", "seasonal_break"],
            "time_scope": "2026-06-21",
            "confidence": 0.90
          },
          {
            "fact": "[USER_FACT]: Στις 2026-06-21, οι ποδοσφαιρικές δραστηριότητες του Αλέξανδρου παγώνουν για το καλοκαίρι.",
            "category": "family",
            "topic": "activity",
            "topic_detail": "football season",
            "relation_type": "state_update",
            "state_markers": ["paused", "seasonal_break"],
            "time_scope": "2026-06-21",
            "confidence": 0.91
          }
        ]
        """
    ]

    class DummyResponse:
        def __init__(self, text):
            self.text = text

    def fake_gemini(_prompt):
        return DummyResponse(responses.pop(0))

    monkeypatch.setattr(session_memory, "safe_gemini_call", fake_gemini)

    session_memory.run_memory_sifter_slow(
        user_text="Είναι καλοκαίρι ο Αλέξανδρος δεν έχει ποδόσφαιρο. Το ποδόσφαιρο του Αλέξανδρου παγώνει για το καλοκαίρι",
        ai_text="Το κράτησα. Οκ, το σημείωσα.",
        agent_name="Home_Agent",
        channel="telegram",
        deterministic_seed_facts=[],
    )

    assert len(saved) == 1
    assert "Αλέξανδρος" in saved[0]["fact"]
    assert "καλοκαίρι" in saved[0]["fact"]

def test_slow_sifter_no_mark_on_parse_error(isolated_state_db, monkeypatch):
    saved = []

    monkeypatch.setattr(
        session_memory.memory,
        "save",
        lambda **kwargs: saved.append(kwargs),
    )

    responses = [
        """
        [
          {
            "fact": "[USER_FACT]: Στις 2026-06-21, Invalid JSON
        """,
        """
        [
          {
            "fact": "[USER_FACT]: Στις 2026-06-21, valid fact.",
            "category": "family",
            "topic": "test",
            "topic_detail": "test",
            "relation_type": "state_update",
            "state_markers": [],
            "time_scope": "",
            "confidence": 0.90
          }
        ]
        """
    ]

    class DummyResponse:
        def __init__(self, text):
            self.text = text

    def fake_gemini(_prompt):
        return DummyResponse(responses.pop(0))

    monkeypatch.setattr(session_memory, "safe_gemini_call", fake_gemini)

    user_text = "Testing parse error fallback"
    ai_text = "Got it."

    session_memory.run_memory_sifter_slow(
        user_text=user_text,
        ai_text=ai_text,
        agent_name="Home_Agent",
        channel="telegram",
        deterministic_seed_facts=[],
    )
    assert len(saved) == 0

    session_memory.run_memory_sifter_slow(
        user_text=user_text,
        ai_text=ai_text,
        agent_name="Home_Agent",
        channel="telegram",
        deterministic_seed_facts=[],
    )

    assert len(saved) == 1
    assert "valid fact" in saved[0]["fact"]
