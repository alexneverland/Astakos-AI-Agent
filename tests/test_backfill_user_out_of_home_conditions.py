import json
import sqlite3
from pathlib import Path

from scripts import backfill_user_out_of_home_conditions as script


def _make_db(path: Path):
    conn = sqlite3.connect(path)
    conn.execute(
        """
        CREATE TABLE routines (
            id INTEGER PRIMARY KEY,
            event_name TEXT,
            conditions_json TEXT
        )
        """
    )

    rows = [
        (
            2,
            "Ύπνος Αλέξανδρου",
            json.dumps(
                [
                    {
                        "condition_type": "context_flag",
                        "condition_payload": {"flag": "alexandros_away_from_home", "equals": False},
                        "condition_mode": "allow_when_true",
                        "source_memory_ref": "manual_cleanup",
                    },
                    {
                        "condition_type": "context_flag",
                        "condition_payload": {"flag": "family_outside_activity", "equals": True},
                        "condition_mode": "suppress_when_true",
                        "source_memory_ref": "manual_cleanup",
                    },
                ],
                ensure_ascii=False,
            ),
        ),
        (
            3,
            "Πάρκο με τον Αλέξανδρο",
            json.dumps(
                [
                    {
                        "condition_type": "context_flag",
                        "condition_payload": {"flag": "alexandros_away_from_home", "equals": True},
                        "condition_mode": "suppress_when_true",
                    }
                ],
                ensure_ascii=False,
            ),
        ),
        (
            10,
            "επίσκεψη στο πάρκο",
            json.dumps(
                [
                    {
                        "condition_type": "context_flag",
                        "condition_payload": {"flag": "state:alexandros:outing", "equals": "in_progress"},
                        "condition_mode": "suppress_when_true",
                    }
                ],
                ensure_ascii=False,
            ),
        ),
        (
            15,
            "μαγείρεμα",
            json.dumps(
                [
                    {
                        "condition_type": "context_flag",
                        "condition_payload": {"flag": "user_out_of_home", "equals": True},
                        "condition_mode": "suppress_when_true",
                    }
                ],
                ensure_ascii=False,
            ),
        ),
    ]

    conn.executemany(
        "INSERT INTO routines (id, event_name, conditions_json) VALUES (?, ?, ?)",
        rows,
    )
    conn.commit()
    conn.close()


def test_backfill_user_out_of_home_conditions(tmp_path, monkeypatch):
    db_path = tmp_path / "routines.db"
    _make_db(db_path)
    monkeypatch.setattr(script, "DB_PATH", str(db_path))

    result = script.run_backfill()
    assert result["updated_count"] == 3

    conn = sqlite3.connect(db_path)
    rows = conn.execute(
        "SELECT id, event_name, conditions_json FROM routines ORDER BY id"
    ).fetchall()
    conn.close()

    by_id = {r[0]: json.loads(r[2]) for r in rows}

    # #2: old family_outside_activity removed, user_out_of_home added
    conds2 = by_id[2]
    assert not any(
        (c.get("condition_payload") or {}).get("flag") == "family_outside_activity"
        for c in conds2
    )
    assert any(
        (c.get("condition_payload") or {}).get("flag") == "user_out_of_home"
        and c.get("condition_mode") == "suppress_when_true"
        and (c.get("condition_payload") or {}).get("equals") is True
        for c in conds2
    )

    # #3: generalized out-of-home suppress added
    conds3 = by_id[3]
    assert any(
        (c.get("condition_payload") or {}).get("flag") == "user_out_of_home"
        for c in conds3
    )

    # #10: generalized out-of-home suppress added
    conds10 = by_id[10]
    assert any(
        (c.get("condition_payload") or {}).get("flag") == "state:alexandros:outing"
        for c in conds10
    )
    assert any(
        (c.get("condition_payload") or {}).get("flag") == "user_out_of_home"
        for c in conds10
    )

    # #15: already okay, no duplicate user_out_of_home
    conds15 = by_id[15]
    matches15 = [
        c for c in conds15
        if (c.get("condition_payload") or {}).get("flag") == "user_out_of_home"
    ]
    assert len(matches15) == 1
