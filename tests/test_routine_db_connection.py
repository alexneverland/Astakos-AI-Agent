import sqlite3
from pathlib import Path

import pytest
import memory.routine_db as routine_db


class _FakeCursor:
    def __init__(self, row=None):
        self.row = row

    def fetchone(self):
        return self.row


class _FakeConnection:
    def __init__(self, fail_wal: bool = False):
        self.fail_wal = fail_wal
        self.statements = []

    def execute(self, statement: str):
        self.statements.append(statement)
        if self.fail_wal and statement == "PRAGMA journal_mode=WAL":
            raise sqlite3.OperationalError("database is locked")
        if statement == "PRAGMA journal_mode=WAL":
            return _FakeCursor(("wal",))
        return _FakeCursor()


def test_get_connection_uses_bounded_busy_timeout_without_repeating_wal(monkeypatch):
    fake_connection = _FakeConnection()
    connect_kwargs = {}
    monkeypatch.setattr(routine_db, "_wal_enabled", True)
    monkeypatch.setattr(routine_db, "_wal_enabled_path", routine_db.DB_PATH)

    def fake_connect(*args, **kwargs):
        connect_kwargs.update(kwargs)
        return fake_connection

    monkeypatch.setattr(routine_db.sqlite3, "connect", fake_connect)

    result = routine_db.get_connection()

    assert result is fake_connection
    assert connect_kwargs["timeout"] == 5
    assert connect_kwargs["check_same_thread"] is False
    assert fake_connection.statements == ["PRAGMA busy_timeout=5000"]


def test_enable_wal_retries_after_transient_startup_lock(monkeypatch):
    monkeypatch.setattr(routine_db, "_wal_enabled", False)
    monkeypatch.setattr(routine_db, "_wal_enabled_path", None)
    locked_connection = _FakeConnection(fail_wal=True)
    working_connection = _FakeConnection()

    assert routine_db._enable_wal(locked_connection) is False
    assert routine_db._enable_wal(working_connection) is True
    assert routine_db._wal_enabled is True
    assert routine_db._wal_enabled_path == routine_db.DB_PATH


def test_enable_wal_remains_best_effort_when_database_is_locked(monkeypatch):
    monkeypatch.setattr(routine_db, "_wal_enabled", False)
    monkeypatch.setattr(routine_db, "_wal_enabled_path", None)
    fake_connection = _FakeConnection(fail_wal=True)

    assert routine_db._enable_wal(fake_connection) is False
    assert fake_connection.statements == ["PRAGMA journal_mode=WAL"]


def test_skip_streak_migration_applies_cooldown_only_on_third_refusal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The isolated migration preserves two skips and escalates the third one only."""
    db_path = tmp_path / "routines.db"
    monkeypatch.setattr(routine_db, "DB_PATH", str(db_path))
    monkeypatch.setattr(routine_db, "_wal_enabled", False)
    monkeypatch.setattr(routine_db, "_wal_enabled_path", None)
    routine_db.setup_db()

    connection = routine_db.get_connection()
    connection.execute(
        """
        INSERT INTO routines (day_of_week, time_str, event_name, event_type, confidence, state, is_active)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        ("Thursday", "09:00", "Dynamic routine", "general", 0.9, "active", 1),
    )
    routine_id = connection.execute("SELECT last_insert_rowid()").fetchone()[0]
    connection.commit()
    connection.close()

    first = routine_db.record_routine_skip_today(routine_id)
    second = routine_db.record_routine_skip_today(routine_id)
    third = routine_db.record_routine_skip_today(routine_id)

    assert first == {"skip_streak": 1, "cooldown_applied": False, "cooldown_hours": None}
    assert second == {"skip_streak": 2, "cooldown_applied": False, "cooldown_hours": None}
    assert third["skip_streak"] == 3
    assert third["cooldown_applied"] is True
    assert third["cooldown_hours"] == 40.0


def test_indefinite_pause_migration_blocks_scheduler_without_deleting_routine(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An indefinite user pause is persisted separately from routine lifecycle state."""
    db_path = tmp_path / "routines.db"
    monkeypatch.setattr(routine_db, "DB_PATH", str(db_path))
    monkeypatch.setattr(routine_db, "_wal_enabled", False)
    monkeypatch.setattr(routine_db, "_wal_enabled_path", None)
    routine_db.setup_db()

    connection = routine_db.get_connection()
    connection.execute(
        """
        INSERT INTO routines (day_of_week, time_str, event_name, event_type, confidence, state, is_active)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        ("Thursday", "09:00", "Dynamic routine", "general", 0.9, "active", 1),
    )
    routine_id = connection.execute("SELECT last_insert_rowid()").fetchone()[0]
    connection.commit()
    connection.close()

    routine_db.pause_routine_indefinitely(routine_id)
    metadata = routine_db.get_routine_schedule_meta(routine_id)

    assert metadata["paused_indefinitely"] is True
    assert routine_db.is_routine_temporarily_inactive_meta(metadata)[0] is True
    assert routine_db.get_routine_state(routine_id).value == "active"
