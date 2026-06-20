from unittest.mock import patch


def test_control_routine_notifications_mutes_all_exact_name_matches(monkeypatch):
    import tools.system as system
    import memory.routine_db as rdb

    monkeypatch.setattr(
        rdb,
        "find_routines_for_schedule_control",
        lambda event_name: [
            {"id": 13, "event": "ποδόσφαιρο Αλέξανδρου", "day": "Monday"},
            {"id": 14, "event": "ποδόσφαιρο Αλέξανδρου", "day": "Thursday"},
        ],
    )
    muted = []
    monkeypatch.setattr(rdb, "get_routine_muted_until", lambda routine_id: None)
    monkeypatch.setattr(rdb, "set_routine_muted_until", lambda routine_id, until: muted.append((routine_id, until)))

    result = system.control_routine_notifications.func(
        event_name="ποδόσφαιρο Αλέξανδρου",
        action="mute",
        until_date="2026-06-25",
    )

    assert muted == [(13, "2026-06-25"), (14, "2026-06-25")]
    assert "[Monday]" in result
    assert "[Thursday]" in result


def test_control_routine_notifications_mute_is_idempotent_per_match(monkeypatch):
    import tools.system as system
    import memory.routine_db as rdb

    monkeypatch.setattr(
        rdb,
        "find_routines_for_schedule_control",
        lambda event_name: [
            {"id": 13, "event": "ποδόσφαιρο Αλέξανδρου", "day": "Monday"},
            {"id": 14, "event": "ποδόσφαιρο Αλέξανδρου", "day": "Thursday"},
        ],
    )
    monkeypatch.setattr(rdb, "get_routine_muted_until", lambda routine_id: "2026-06-25")
    called = []
    monkeypatch.setattr(rdb, "set_routine_muted_until", lambda routine_id, until: called.append((routine_id, until)))

    result = system.control_routine_notifications.func(
        event_name="ποδόσφαιρο Αλέξανδρου",
        action="mute",
        until_date="2026-06-25",
    )

    assert called == []
    assert "ήδη στην επιθυμητή κατάσταση" in result
    assert "ποδόσφαιρο Αλέξανδρου" in result


def test_find_routines_for_schedule_control_returns_all_exact_duplicates(tmp_path):
    import importlib
    import sqlite3
    import memory.routine_db as rdb

    db_path = tmp_path / "routines.db"
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        CREATE TABLE routines ( priority INTEGER DEFAULT 0, conflict_group TEXT, condition_type TEXT, condition_payload TEXT, condition_mode TEXT,
            id INTEGER PRIMARY KEY,
            day_of_week TEXT,
            time_str TEXT,
            event_name TEXT,
            event_type TEXT,
            confidence REAL,
            state TEXT
        )
        """
    )
    conn.executemany(
        "INSERT INTO routines (id, day_of_week, time_str, event_name, event_type, confidence, state) VALUES (?, ?, ?, ?, ?, ?, ?)",
        [
            (13, "Monday", "17:00", "ποδόσφαιρο Αλέξανδρου", "event", 0.9, "active"),
            (14, "Thursday", "17:00", "ποδόσφαιρο Αλέξανδρου", "event", 0.9, "active"),
            (15, "Sunday", "12:00", "μαγείρεμα", "event", 0.8, "active"),
        ],
    )
    conn.commit()
    conn.close()

    with patch.object(rdb, "get_connection", side_effect=lambda: sqlite3.connect(db_path)):
        matches = rdb.find_routines_for_schedule_control("ποδόσφαιρο Αλέξανδρου")

    assert [m["id"] for m in matches] == [13, 14]

