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
            conditions_json TEXT
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
