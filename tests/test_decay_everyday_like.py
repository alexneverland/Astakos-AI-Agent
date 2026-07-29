from collections.abc import Iterator
from pathlib import Path
from types import ModuleType

import pytest
import config


@pytest.fixture(autouse=True)
def routine_db(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> Iterator[ModuleType]:
    """Import and route each decay test to a fresh temporary routine DB."""
    test_db = tmp_path / "routines.db"
    monkeypatch.setattr(config, "ROUTINES_DB", str(test_db), raising=False)

    import memory.routine_db as routine_db

    monkeypatch.setattr(routine_db, "DB_PATH", str(test_db))
    routine_db.setup_db()
    assert Path(routine_db.DB_PATH) == test_db
    yield routine_db


def test_decay_everyday_like(routine_db: ModuleType):
    conn = routine_db.get_connection()
    c = conn.cursor()
    c.execute("DELETE FROM routines WHERE event_name LIKE 'TEST_%'")
    conn.commit()

    test_cases = [
        ("Everyday", True),
        ("Weekdays", True),
        ("Εργάσιμες", True),
        ("καθημερινές", True),
        ("Weekends", False),
        ("Σαββατοκύριακο", False),
        ("Monday", False)
    ]

    for day_of_week, should_be_active in test_cases:
        event_name = f"TEST_{day_of_week}"
        routine_db.upsert_routine(day_of_week, "10:00", event_name, "general", 1.0)

        c.execute("SELECT id FROM routines WHERE event_name=?", (event_name,))
        r_id = c.fetchone()[0]

        c.execute("UPDATE routines SET state='trigger_pending', confidence=1.0 WHERE id=?", (r_id,))
        conn.commit()

        routine_db.decay_routine(r_id)

        c.execute("SELECT state FROM routines WHERE id=?", (r_id,))
        state = c.fetchone()[0]

        if should_be_active:
            assert state == routine_db.RoutineState.ACTIVE.value, f"Failed for {day_of_week}: expected ACTIVE, got {state}"
        else:
            assert state == routine_db.RoutineState.DISMISSED.value, f"Failed for {day_of_week}: expected DISMISSED, got {state}"

    c.execute("DELETE FROM routines WHERE event_name LIKE 'TEST_%'")
    conn.commit()
    conn.close()


def test_decay_routine_is_noop_when_already_decayed(routine_db: ModuleType):
    conn = routine_db.get_connection()
    c = conn.cursor()
    c.execute("DELETE FROM routines WHERE event_name = 'TEST_DECAYED_NOOP'")
    conn.commit()

    routine_db.upsert_routine("Everyday", "10:00", "TEST_DECAYED_NOOP", "general", 0.5)
    c.execute("SELECT id FROM routines WHERE event_name='TEST_DECAYED_NOOP'")
    r_id = c.fetchone()[0]

    c.execute("UPDATE routines SET state='decayed', confidence=0.05, decay_counter=5 WHERE id=?", (r_id,))
    conn.commit()

    routine_db.decay_routine(r_id)

    c.execute("SELECT state, confidence, decay_counter FROM routines WHERE id=?", (r_id,))
    state, conf, decay_c = c.fetchone()

    assert state == routine_db.RoutineState.DECAYED.value
    assert conf == 0.05
    assert decay_c == 5

    c.execute("DELETE FROM routines WHERE event_name = 'TEST_DECAYED_NOOP'")
    conn.commit()
    conn.close()

def test_decay_routine_rounds_confidence_before_threshold(routine_db: ModuleType):
    conn = routine_db.get_connection()
    c = conn.cursor()
    c.execute("DELETE FROM routines WHERE event_name = 'TEST_DECAY_ROUNDING'")
    conn.commit()

    routine_db.upsert_routine("Everyday", "10:00", "TEST_DECAY_ROUNDING", "general", 0.3)
    c.execute("SELECT id FROM routines WHERE event_name='TEST_DECAY_ROUNDING'")
    r_id = c.fetchone()[0]

    c.execute("UPDATE routines SET state='trigger_pending', confidence=0.2999999 WHERE id=?", (r_id,))
    conn.commit()

    routine_db.decay_routine(r_id)

    c.execute("SELECT state, confidence FROM routines WHERE id=?", (r_id,))
    state, conf = c.fetchone()

    assert state == routine_db.RoutineState.ACTIVE.value
    assert conf == 0.1

    c.execute("DELETE FROM routines WHERE event_name = 'TEST_DECAY_ROUNDING'")
    conn.commit()
    conn.close()

def test_decay_everyday_like_routine_stays_active_at_point_one(routine_db: ModuleType):
    conn = routine_db.get_connection()
    c = conn.cursor()
    c.execute("DELETE FROM routines WHERE event_name = 'TEST_DECAY_POINT_ONE'")
    conn.commit()

    routine_db.upsert_routine("Everyday", "10:00", "TEST_DECAY_POINT_ONE", "general", 0.3)
    c.execute("SELECT id FROM routines WHERE event_name='TEST_DECAY_POINT_ONE'")
    r_id = c.fetchone()[0]

    c.execute("UPDATE routines SET state='trigger_pending', confidence=0.3 WHERE id=?", (r_id,))
    conn.commit()

    routine_db.decay_routine(r_id)

    c.execute("SELECT state, confidence FROM routines WHERE id=?", (r_id,))
    state, conf = c.fetchone()

    assert state == routine_db.RoutineState.ACTIVE.value
    assert conf == 0.1

    c.execute("DELETE FROM routines WHERE event_name = 'TEST_DECAY_POINT_ONE'")
    conn.commit()
    conn.close()
