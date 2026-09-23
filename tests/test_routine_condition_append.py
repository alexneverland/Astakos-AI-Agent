import json
import sqlite3
from pathlib import Path
from unittest.mock import patch


def _make_db(path: Path) -> None:
    conn = sqlite3.connect(path)
    conn.execute(
        """
        CREATE TABLE routines (
            id INTEGER PRIMARY KEY,
            condition_type TEXT,
            condition_payload TEXT,
            condition_mode TEXT,
            conditions_json TEXT,
            source_memory_ref TEXT
        )
        """
    )
    conn.execute(
        "INSERT INTO routines (id, conditions_json) VALUES (?, ?)",
        (765, None),
    )
    conn.commit()
    conn.close()


def test_append_routine_condition_preserves_existing_conditions(tmp_path):
    import memory.routine_db as rdb

    db_path = tmp_path / "routines.db"
    _make_db(db_path)

    with patch.object(rdb, "get_connection", side_effect=lambda write=False: sqlite3.connect(db_path)):
        added_first = rdb.append_routine_condition(
            765,
            condition_type="context_flag",
            condition_payload='{"flag":"user_at_work","equals":true}',
            condition_mode="allow_when_true",
            source_memory_ref="llm_agent",
        )
        added_second = rdb.append_routine_condition(
            765,
            condition_type="shift_mode",
            condition_payload='{"flag":"current_shift","equals":"morning"}',
            condition_mode="allow_when_true",
            source_memory_ref="llm_agent",
        )

    assert added_first is True
    assert added_second is True

    conn = sqlite3.connect(db_path)
    row = conn.execute("SELECT conditions_json FROM routines WHERE id = 765").fetchone()
    conn.close()

    conditions = json.loads(row[0])
    assert len(conditions) == 2
    assert conditions[0]["condition_type"] == "context_flag"
    assert conditions[0]["condition_payload"]["flag"] == "user_at_work"
    assert conditions[1]["condition_type"] == "shift_mode"
    assert conditions[1]["condition_payload"]["flag"] == "current_shift"


def test_append_rejects_conflicting_shift_rule(tmp_path):
    """An additive rule must not make a routine impossible to trigger."""
    import memory.routine_db as rdb

    db_path = tmp_path / "routines.db"
    _make_db(db_path)
    with patch.object(rdb, "get_connection", side_effect=lambda write=False: sqlite3.connect(db_path)):
        assert rdb.append_routine_condition(
            765,
            condition_type="shift_mode",
            condition_payload={"flag": "current_shift", "equals": "morning"},
            condition_mode="allow_when_true",
        )
        assert not rdb.append_routine_condition(
            765,
            condition_type="shift_mode",
            condition_payload={"flag": "current_shift", "equals": "afternoon"},
            condition_mode="allow_when_true",
        )
        assert not rdb.append_routine_condition(
            765,
            condition_type="shift_mode",
            condition_payload={"flag": "current_shift", "equals": "morning"},
            condition_mode="suppress_when_true",
        )
        assert not rdb.append_routine_condition(
            765,
            condition_type="context_flag",
            condition_payload={"flag": "current_shift", "equals": "morning"},
            condition_mode="suppress_when_true",
        )
        assert rdb.append_routine_condition(
            765,
            condition_type="context_flag",
            condition_payload={"flag": "user_at_work", "equals": True},
            condition_mode="allow_when_true",
        )
        assert len(rdb.get_routine_conditions(765)) == 2


def test_replace_conditions_requires_unchanged_current_list(tmp_path):
    """Repair replaces only the exact list inspected beforehand."""
    import memory.routine_db as rdb

    db_path = tmp_path / "routines.db"
    _make_db(db_path)
    before = [
        {"condition_type": "shift_mode", "condition_payload": {"flag": "current_shift", "equals": "morning"}, "condition_mode": "allow_when_true"},
        {"condition_type": "shift_mode", "condition_payload": {"flag": "current_shift", "equals": "afternoon"}, "condition_mode": "allow_when_true"},
    ]
    with patch.object(rdb, "get_connection", side_effect=lambda write=False: sqlite3.connect(db_path)):
        assert rdb.append_routine_condition(765, **before[0])
        assert not rdb.replace_routine_conditions(765, [], [before[0]])
        assert rdb.get_routine_conditions(765) == [before[0]]
        assert rdb.replace_routine_conditions(765, [before[0]], [
            {"condition_type": "context_flag", "condition_payload": {"flag": "user_at_work", "equals": True}, "condition_mode": "allow_when_true"},
        ])
        assert rdb.get_routine_conditions(765)[0]["condition_type"] == "context_flag"


def test_append_rejects_suppression_of_both_boolean_values(tmp_path):
    """A routine must not be suppressed for every value of one context flag."""
    import memory.routine_db as rdb

    db_path = tmp_path / "routines.db"
    _make_db(db_path)
    with patch.object(rdb, "get_connection", side_effect=lambda write=False: sqlite3.connect(db_path)):
        assert rdb.append_routine_condition(
            765, condition_type="context_flag",
            condition_payload={"flag": "kid1_unavailable_for_routine", "equals": True},
            condition_mode="suppress_when_true",
        )
        assert not rdb.append_routine_condition(
            765, condition_type="context_flag",
            condition_payload={"flag": "kid1_unavailable_for_routine", "equals": False},
            condition_mode="suppress_when_true",
        )
        assert len(rdb.get_routine_conditions(765)) == 1


def test_append_allows_two_shift_suppressions_when_other_shifts_remain(tmp_path):
    """Suppressing morning and afternoon still leaves an off shift eligible."""
    import memory.routine_db as rdb

    db_path = tmp_path / "routines.db"
    _make_db(db_path)
    with patch.object(rdb, "get_connection", side_effect=lambda write=False: sqlite3.connect(db_path)):
        assert rdb.append_routine_condition(
            765, condition_type="shift_mode",
            condition_payload={"flag": "current_shift", "equals": "morning"},
            condition_mode="suppress_when_true",
        )
        assert rdb.append_routine_condition(
            765, condition_type="shift_mode",
            condition_payload={"flag": "current_shift", "equals": "afternoon"},
            condition_mode="suppress_when_true",
        )


def test_replace_rejects_malformed_legacy_payload_without_writing(tmp_path):
    """An invalid legacy condition cannot be silently replaced or crash repair."""
    import memory.routine_db as rdb

    db_path = tmp_path / "routines.db"
    _make_db(db_path)
    conn = sqlite3.connect(db_path)
    conn.execute(
        "UPDATE routines SET condition_type = ?, condition_payload = ?, condition_mode = ? WHERE id = 765",
        ("context_flag", "{invalid", "suppress_when_true"),
    )
    conn.commit()
    conn.close()

    with patch.object(rdb, "get_connection", side_effect=lambda write=False: sqlite3.connect(db_path)):
        assert rdb.replace_routine_conditions(765, [], []) is False

    conn = sqlite3.connect(db_path)
    row = conn.execute("SELECT condition_payload, conditions_json FROM routines WHERE id = 765").fetchone()
    conn.close()
    assert row == ("{invalid", None)


def test_existing_reconciler_absence_condition_uses_confirmed_absence(tmp_path):
    """A condition saved before the flag rename follows the narrowed runtime meaning."""
    import memory.routine_db as rdb
    from services.routine_conditions import evaluate_routine_conditions

    db_path = tmp_path / "routines.db"
    _make_db(db_path)
    with patch.object(rdb, "get_connection", side_effect=lambda write=False: sqlite3.connect(db_path)):
        assert rdb.append_routine_condition(
            765, condition_type="context_flag",
            condition_payload={"flag": "kid1_away_from_home", "equals": True},
            condition_mode="suppress_when_true", source_memory_ref="reconciler",
        )
        persisted = rdb.get_routine_conditions(765)

    school_context = {"kid1_away_from_home": True, "kid1_unavailable_for_routine": False}
    camp_context = {"kid1_away_from_home": True, "kid1_unavailable_for_routine": True}
    assert evaluate_routine_conditions(persisted, school_context)["allowed"] is True
    assert evaluate_routine_conditions(persisted, camp_context)["allowed"] is False


def test_legacy_absence_condition_preserves_row_provenance(tmp_path, monkeypatch):
    """The old single-condition columns retain their source on read."""
    import memory.routine_db as rdb
    from services.routine_conditions import evaluate_routine_conditions

    monkeypatch.setattr(rdb, "DB_PATH", str(tmp_path / "legacy_routines.db"))
    rdb.setup_db()
    conn = rdb.get_connection(write=True)
    conn.execute(
        """INSERT INTO routines
           (id, condition_type, condition_payload, condition_mode, source_memory_ref)
           VALUES (?, ?, ?, ?, ?)""",
        (765, "context_flag", '{"flag":"kid1_away_from_home","equals":true}',
         "suppress_when_true", "reconciler"),
    )
    conn.execute(
        """INSERT INTO routines
           (id, condition_type, condition_payload, condition_mode, source_memory_ref)
           VALUES (?, ?, ?, ?, ?)""",
        (766, "context_flag", '{"flag":"kid1_away_from_home","equals":true}',
         "suppress_when_true", "manual"),
    )
    conn.commit()
    conn.close()

    persisted = rdb.get_routine_conditions(765)
    school_context = {"kid1_away_from_home": True, "kid1_unavailable_for_routine": False}
    camp_context = {"kid1_away_from_home": True, "kid1_unavailable_for_routine": True}

    assert persisted[0]["source_memory_ref"] == "reconciler"
    assert evaluate_routine_conditions(persisted, school_context)["allowed"] is True
    assert evaluate_routine_conditions(persisted, camp_context)["allowed"] is False

    manual_condition = rdb.get_routine_conditions(766)
    assert manual_condition[0]["source_memory_ref"] == "manual"
    assert evaluate_routine_conditions(manual_condition, school_context)["allowed"] is False
