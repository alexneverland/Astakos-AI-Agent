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
            "fact": "[USER_FACT]: On 2026-06-21, Alexandros's football stops for the summer and resumes in September.",
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
    assert "Alexandros's football" in saved[0]["fact"]

    conn = sqlite3.connect(str(isolated_state_db))
    try:
        rows = conn.execute(
            "SELECT fingerprint, channel, agent_name FROM memory_sifter_runs"
        ).fetchall()
    finally:
        conn.close()

    assert len(rows) == 2
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
            "fact": "[USER_FACT]: On 2026-06-21, Alexandros stops playing football for the summer.",
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
            "fact": "[USER_FACT]: On 2026-06-21, Alexandros's football restarts in September.",
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
    assert "summer" in saved[0]["fact"]
    assert "September" in saved[1]["fact"]


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
            "fact": "[USER_FACT]: On 2026-06-21, Alexandros stops playing football for the summer.",
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
            "[USER_FACT]: On 2026-06-21, Alexandros stops playing football for the summer."
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
            "fact": "[USER_FACT]: On 2026-06-21, Alexandros stops playing football for the summer.",
            "category": "family",
            "entities": ["Αλέξανδρος", "ποδόσφαιρο"],
            "topic": "activity",
            "topic_detail": "football season",
            "relation_type": "state_update",
            "state_markers": ["paused", "seasonal_break"],
            "time_scope": "2026-06-21",
            "confidence": 0.90
          },
          {
            "fact": "[USER_FACT]: On 2026-06-21, Alexandros's football activities are paused for the summer.",
            "category": "family",
            "entities": ["Αλέξανδρος", "ποδόσφαιρο"],
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
    assert "Alexandros" in saved[0]["fact"]
    assert "summer" in saved[0]["fact"]

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
            "fact": "[USER_FACT]: On 2026-06-21, Invalid JSON
        """,
        """
        [
          {
            "fact": "[USER_FACT]: On 2026-06-21, this is a very valid and sufficiently long fact.",
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
    assert "valid and sufficiently long fact" in saved[0]["fact"]

def test_sifter_assistant_paraphrase_guard(monkeypatch):
    from memory import session_memory
    
    # Clean up replay DB to prevent test pollution
    import sqlite3
    try:
        conn = sqlite3.connect(session_memory.STATE_DB)
        conn.execute("DELETE FROM memory_sifter_runs")
        conn.commit()
        conn.close()
    except Exception:
        pass

    saved = []
    def mock_save(**kwargs):
        saved.append(kwargs)
    monkeypatch.setattr(session_memory.memory, "save", mock_save)
    
    # 1. Reject assistant paraphrase
    monkeypatch.setattr(session_memory, "safe_gemini_call", lambda _: type("Resp", (), {"text": "[\n{\"fact\": \"[USER_FACT]: Σημειώθηκε η πρωινή βάρδια. Καλή αρχή από αύριο, μάστορα\", \"category\": \"lazaros\", \"analysis\": \"None\"}\n]"})())
    
    session_memory.run_memory_sifter_slow(
        user_text="Από αύριο είμαι πρωινός UNIQUE_TEST_1",
        ai_text="Σημειώθηκε η πρωινή βάρδια. Καλή αρχή από αύριο, μάστορα UNIQUE_TEST_1",
        agent_name="Chat_Agent",
        channel="telegram",
    )
    assert len(saved) == 0

    # 2. Accept pure user fact
    monkeypatch.setattr(session_memory, "safe_gemini_call", lambda _: type("Resp", (), {"text": "[\n{\"fact\": \"[USER_FACT]: Ο Λάζαρος ενημέρωσε ότι από τη Δευτέρα 2026-06-22 είναι πρωινή βάρδια\", \"category\": \"lazaros\", \"analysis\": \"None\"}\n]"})())
    
    session_memory.run_memory_sifter_slow(
        user_text="Από Δευτέρα είμαι πρωινός, θα πάω δουλειά νωρίς UNIQUE_TEST_2",
        ai_text="Το κατέγραψα, καλή αρχή UNIQUE_TEST_2",
        agent_name="Chat_Agent",
        channel="telegram",
    )
    assert len(saved) == 1

def test_slow_sifter_skips_operational_asset_confirmation(isolated_state_db, monkeypatch):
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
            "fact": "[PHOTO]: Done, I have saved it to my memory.",
            "category": "photos",
            "topic": "misc",
            "topic_detail": "archive",
            "relation_type": "None",
            "state_markers": [],
            "time_scope": "None",
            "confidence": 0.90
          }
        ]
        """

    monkeypatch.setattr(session_memory, "safe_gemini_call", lambda prompt: DummyResponse())

    user_text = "Ναι, αποθήκευσέ το"
    ai_text = "Έγινε, μάστορα. Την αποθήκευσα στη μνήμη μου."

    session_memory.run_memory_sifter_slow(
        user_text=user_text,
        ai_text=ai_text,
        agent_name="Chat_Agent",
        channel="telegram",
        deterministic_seed_facts=[],
    )

    assert len(saved) == 0


def test_family_duplicate_tool_and_sifter_variants_are_collapsed(isolated_state_db, monkeypatch):
    saved = []

    def fake_save(**kwargs):
        saved.append(kwargs)
        return True

    from memory import session_memory
    monkeypatch.setattr(session_memory.memory, 'save', fake_save)

    tool_candidate = session_memory.build_canonical_memory_candidate(
        fact='[USER_FACT]: Στις 2026-06-25, ο Λάζαρος έκλεισε εισιτήρια για τη Γεωργία τον Αύγουστο.',
        category='family',
        entities=['Γεωργία', 'Εισιτήρια', 'Ταξίδι', 'Διακοπές'],
        source='telegram',
        agent_name='Tool_save_to_memory',
        reason='user_stated',
        confidence=0.85,
    )

    saved.append(tool_candidate)

    sifter_candidate = session_memory.build_canonical_memory_candidate(
        fact='[USER_FACT]: Στις 2026-06-25, ο Λάζαρος έκλεισε εισιτήρια για τη Γεωργία για τον Αύγουστο.',
        category='family',
        source='telegram',
        agent_name='Dev_Agent',
        reason='agent_inferred',
        confidence=0.9,
    )

    assert session_memory._family_fact_same_day_near_duplicate(
        sifter_candidate,
        [tool_candidate],
    ) is True


def test_slow_sifter_skips_operational_reminder_exchange(monkeypatch):
    from memory import session_memory as sm

    saved = []

    monkeypatch.setattr(sm.memory, 'save', lambda *args, **kwargs: saved.append((args, kwargs)))

    sm.run_memory_sifter_slow(
        'θυμησε μου στις 19:00 πριν φυγω απο την δουλεια να παρω τις μπριζολες',
        '✅ Υπενθύμιση ρυθμίστηκε για τις 2026-07-03 19:00!',
        'Home_Agent',
        'web',
    )

    assert saved == []
