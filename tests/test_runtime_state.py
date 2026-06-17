import sqlite3

import memory.runtime_state as rs


def test_set_and_get_runtime_state(tmp_path, monkeypatch):
    db_path = tmp_path / "runtime_state.db"

    def _get_conn(write=False):
        return sqlite3.connect(db_path)

    monkeypatch.setattr(rs, "get_connection", _get_conn)

    rs.ensure_runtime_state_table()
    rs.set_runtime_state("current_shift", "afternoon")

    value = rs.get_runtime_state("current_shift")
    assert value == "afternoon"


def test_missing_runtime_state_returns_default(tmp_path, monkeypatch):
    db_path = tmp_path / "runtime_state.db"

    def _get_conn(write=False):
        return sqlite3.connect(db_path)

    monkeypatch.setattr(rs, "get_connection", _get_conn)

    rs.ensure_runtime_state_table()

    value = rs.get_runtime_state("missing_key", default="fallback")
    assert value == "fallback"


def test_get_all_runtime_state(tmp_path, monkeypatch):
    db_path = tmp_path / "runtime_state.db"

    def _get_conn(write=False):
        return sqlite3.connect(db_path)

    monkeypatch.setattr(rs, "get_connection", _get_conn)

    rs.ensure_runtime_state_table()
    rs.set_runtime_state("current_shift", "morning")
    rs.set_runtime_state("school_mode", "closed")

    data = rs.get_all_runtime_state()

    assert "current_shift" in data
    assert data["current_shift"]["value"] == "morning"
    assert data["school_mode"]["value"] == "closed"
