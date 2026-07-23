import sqlite3

import memory.routine_db as routine_db


class _FakeConnection:
    def __init__(self, fail_wal: bool = False):
        self.fail_wal = fail_wal
        self.statements = []

    def execute(self, statement: str):
        self.statements.append(statement)
        if self.fail_wal and statement == "PRAGMA journal_mode=WAL":
            raise sqlite3.OperationalError("database is locked")


def test_get_connection_uses_bounded_busy_timeout_without_wal_per_connection(monkeypatch):
    fake_connection = _FakeConnection()
    connect_kwargs = {}

    def fake_connect(*args, **kwargs):
        connect_kwargs.update(kwargs)
        return fake_connection

    monkeypatch.setattr(routine_db.sqlite3, "connect", fake_connect)

    result = routine_db.get_connection()

    assert result is fake_connection
    assert connect_kwargs["timeout"] == 5
    assert connect_kwargs["check_same_thread"] is False
    assert fake_connection.statements == ["PRAGMA busy_timeout=5000"]


def test_enable_wal_remains_best_effort_when_database_is_locked():
    fake_connection = _FakeConnection(fail_wal=True)

    routine_db._enable_wal(fake_connection)

    assert fake_connection.statements == ["PRAGMA journal_mode=WAL"]
