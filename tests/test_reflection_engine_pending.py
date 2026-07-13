import os
import sys
import sqlite3
import config

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _set_temp_db(monkeypatch, tmp_path):
    import services.reflection_engine as ref_eng
    import config

    db_path = tmp_path / "reflections_test.db"
    monkeypatch.setattr(config, "ROUTINES_DB", str(db_path))
    ref_eng._ensure_table()
    
    conn = sqlite3.connect(str(db_path))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS routines (
            id INTEGER PRIMARY KEY,
            day_of_week TEXT,
            time_str TEXT,
            event_name TEXT,
            event_type TEXT,
            confidence REAL,
            decay_counter INTEGER,
            is_active INTEGER,
            mention_count INTEGER,
            ignore_count INTEGER,
            notify_cooldown_hours REAL,
            state TEXT
        )
    """)
    conn.commit()
    conn.close()
    
    return ref_eng


def test_pending_reflection_blocks_duplicate_creation(monkeypatch, tmp_path):
    re = _set_temp_db(monkeypatch, tmp_path)

    re._save_reflection(
        source="routine",
        observation="Το πάρκο αγνοείται συχνά",
        action="increase_cooldown",
        confidence=0.62,
        lesson="Ίσως είναι πολύ συχνό.",
        applied=False,
        routine_id=12,
        action_value=48,
    )

    assert re._already_reflected(
        "Το πάρκο αγνοείται συχνά",
        "increase_cooldown",
        routine_id=12,
        action_value=48,
    ) is True


def test_load_pending_reflections_ignores_applied_and_rejected(monkeypatch, tmp_path):
    re = _set_temp_db(monkeypatch, tmp_path)

    pending_id = re._save_reflection(
        source="routine",
        observation="Το πάρκο αγνοείται συχνά",
        action="increase_cooldown",
        confidence=0.62,
        lesson="Ίσως είναι πολύ συχνό.",
        applied=False,
        routine_id=12,
        action_value=48,
    )
    applied_id = re._save_reflection(
        source="routine",
        observation="Το ξυπνητήρι πέτυχε",
        action="reduce_frequency",
        confidence=0.91,
        lesson="Καλά ρυθμισμένο.",
        applied=True,
        routine_id=13,
        action_value=None,
    )
    rejected_id = re._save_reflection(
        source="routine",
        observation="Μην αλλάξεις την ώρα στο πάρκο",
        action="change_time",
        confidence=0.64,
        lesson="Ο χρήστης δεν το θέλει.",
        applied=False,
        routine_id=14,
        action_value="18:00",
    )
    re.mark_reflection_rejected(rejected_id)

    loaded = re.load_pending_reflections()

    assert pending_id in loaded
    assert applied_id not in loaded
    assert rejected_id not in loaded
    assert loaded[pending_id]["routine_id"] == 12
    assert loaded[pending_id]["action_value"] == "48"


def test_run_reflection_dedupes_same_run_duplicates(monkeypatch, tmp_path):
    re = _set_temp_db(monkeypatch, tmp_path)

    monkeypatch.setattr(re, "_load_today_events", lambda days_back=1: [{"event": "x"}])
    monkeypatch.setattr(re, "_get_routine_stats", lambda: [])
    monkeypatch.setattr(re, "_load_conversation_traces", lambda days_back=1: [])
    monkeypatch.setattr(re, "_apply_action", lambda reflection: True)

    reflections = [
        {
            "source": "general",
            "routine_id": None,
            "observation": "Το bot επαναλαμβάνει το ίδιο lesson.",
            "action": "save_to_memory",
            "action_value": None,
            "confidence": 0.95,
            "lesson": "Να αποφεύγεται το διπλό save ίδιου lesson.",
        },
        {
            "source": "general",
            "routine_id": None,
            "observation": "Το bot επαναλαμβάνει το ίδιο lesson.",
            "action": "save_to_memory",
            "action_value": None,
            "confidence": 0.95,
            "lesson": "Να αποφεύγεται το διπλό save ίδιου lesson.",
        },
    ]
    monkeypatch.setattr(re, "_analyze_with_llm", lambda events, routine_stats, traces: reflections)

    stats = re.run_reflection()

    assert stats["analyzed"] == 2
    assert stats["applied"] == 1
    assert stats["skipped"] == 1

def test_reflection_increase_cooldown_clamps_to_min(monkeypatch, tmp_path):
    re = _set_temp_db(monkeypatch, tmp_path)

    conn = sqlite3.connect(config.ROUTINES_DB)
    conn.execute(
        """
        INSERT INTO routines (
            id, day_of_week, time_str, event_name, event_type,
            confidence, decay_counter, is_active, mention_count,
            ignore_count, notify_cooldown_hours, state
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            1, "Monday", "10:00", "Test routine", "general",
            0.8, 0, 1, 2, 0, 20.0, "active"
        )
    )
    conn.commit()
    conn.close()

    ok = re._apply_action({
        "action": "increase_cooldown",
        "routine_id": 1,
        "action_value": 1,
        "lesson": "test",
    })

    assert ok is True

    conn = sqlite3.connect(config.ROUTINES_DB)
    row = conn.execute(
        "SELECT notify_cooldown_hours FROM routines WHERE id=1"
    ).fetchone()
    conn.close()

    assert row[0] == 4.0

def test_reflection_reduce_frequency_clamps_to_max(monkeypatch, tmp_path):
    re = _set_temp_db(monkeypatch, tmp_path)

    conn = sqlite3.connect(config.ROUTINES_DB)
    conn.execute(
        """
        INSERT INTO routines (
            id, day_of_week, time_str, event_name, event_type,
            confidence, decay_counter, is_active, mention_count,
            ignore_count, notify_cooldown_hours, state
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            2, "Monday", "11:00", "Test routine 2", "general",
            0.8, 0, 1, 2, 0, 40.0, "active"
        )
    )
    conn.commit()
    conn.close()

    ok = re._apply_action({
        "action": "reduce_frequency",
        "routine_id": 2,
        "action_value": None,
        "lesson": "test",
    })

    assert ok is True

    conn = sqlite3.connect(config.ROUTINES_DB)
    row = conn.execute(
        "SELECT notify_cooldown_hours FROM routines WHERE id=2"
    ).fetchone()
    conn.close()

    assert row[0] == 72.0
