import sqlite3

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
