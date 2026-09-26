"""Offline contracts for exact, recoverable cleanup of capability memories."""

import sqlite3

import pytest


@pytest.fixture
def capability_db(tmp_path, monkeypatch):
    """Create a disposable capability store, never the user's live database."""
    import memory.working_memory as working_memory

    db_path = tmp_path / "capabilities.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "CREATE TABLE capabilities (id INTEGER PRIMARY KEY, type TEXT NOT NULL, "
            "description TEXT NOT NULL UNIQUE, created_at TEXT DEFAULT CURRENT_TIMESTAMP)"
        )
        conn.executemany(
            "INSERT INTO capabilities (id, type, description) VALUES (?, ?, ?)",
            [
                (1, "can_do", "Astakos can send approvals"),
                (2, "can_do", "Astakos can request approvals"),
                (3, "cannot_do", "Astakos cannot generate videos"),
            ],
        )
    monkeypatch.setattr(working_memory, "STATE_DB", str(db_path))
    return working_memory


def test_capability_cleanup_lists_all_records_without_recent_limit(capability_db):
    """Maintenance audit must see exact IDs and both capability types."""
    records = capability_db.list_capability_records()

    assert [(item["id"], item["type"], item["description"]) for item in records] == [
        (1, "can_do", "Astakos can send approvals"),
        (2, "can_do", "Astakos can request approvals"),
        (3, "cannot_do", "Astakos cannot generate videos"),
    ]


def test_capability_cleanup_removes_only_exact_rows_and_writes_backup(
    capability_db, tmp_path
):
    """A selected duplicate is archived and removed; the distinct gap survives."""
    records = capability_db.list_capability_records()
    backup_path = tmp_path / "removed.json"

    removed = capability_db.remove_capability_records([records[1]], backup_path)

    assert removed == 1
    assert [item["id"] for item in capability_db.list_capability_records()] == [1, 3]
    assert "Astakos can request approvals" in backup_path.read_text(encoding="utf-8")


def test_capability_cleanup_refuses_stale_row_without_deleting(capability_db, tmp_path):
    """An ID with a changed description must abort the transaction safely."""
    stale = {"id": 2, "type": "can_do", "description": "not the stored text"}
    backup_path = tmp_path / "should-not-exist.json"

    with pytest.raises(ValueError, match="stale"):
        capability_db.remove_capability_records([stale], backup_path)

    assert [item["id"] for item in capability_db.list_capability_records()] == [1, 2, 3]
    assert not backup_path.exists()
