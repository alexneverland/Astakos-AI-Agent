import pytest
from memory.routine_db import (
    upsert_routine,
    decay_routine,
    get_connection,
    RoutineState
)

def test_decay_everyday_like():
    conn = get_connection()
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
        upsert_routine(day_of_week, "10:00", event_name, "general", 1.0)

        c.execute("SELECT id FROM routines WHERE event_name=?", (event_name,))
        r_id = c.fetchone()[0]

        c.execute("UPDATE routines SET state='trigger_pending', confidence=1.0 WHERE id=?", (r_id,))
        conn.commit()

        decay_routine(r_id)

        c.execute("SELECT state FROM routines WHERE id=?", (r_id,))
        state = c.fetchone()[0]

        if should_be_active:
            assert state == RoutineState.ACTIVE.value, f"Failed for {day_of_week}: expected ACTIVE, got {state}"
        else:
            assert state == RoutineState.DISMISSED.value, f"Failed for {day_of_week}: expected DISMISSED, got {state}"

    c.execute("DELETE FROM routines WHERE event_name LIKE 'TEST_%'")
    conn.commit()
    conn.close()

