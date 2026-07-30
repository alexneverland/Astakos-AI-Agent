import sqlite3
from datetime import datetime
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
    assert routine_db.get_routine_notify_info(routine_id)["last_notified_ts"] is not None


def test_unanswered_reminder_streak_migrates_existing_database(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The migration adds the unanswered counter to an existing routines table without rewriting rows."""
    db_path = tmp_path / "routines.db"
    connection = sqlite3.connect(db_path)
    connection.execute(
        """
        CREATE TABLE routines (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            day_of_week TEXT,
            time_str TEXT,
            event_name TEXT,
            event_type TEXT,
            confidence REAL,
            last_triggered TEXT,
            decay_counter INTEGER,
            is_active BOOLEAN DEFAULT 1,
            fingerprint TEXT,
            mention_count INTEGER DEFAULT 1,
            ignore_count INTEGER DEFAULT 0,
            notify_cooldown_hours REAL DEFAULT 20.0,
            last_notified_ts TEXT,
            explicit_skip_streak INTEGER DEFAULT 0,
            paused_indefinitely BOOLEAN DEFAULT 0
        )
        """
    )
    connection.execute(
        "INSERT INTO routines (day_of_week, time_str, event_name, confidence) VALUES (?, ?, ?, ?)",
        ("Thursday", "09:00", "Existing routine", 0.9),
    )
    connection.commit()
    connection.close()

    monkeypatch.setattr(routine_db, "DB_PATH", str(db_path))
    monkeypatch.setattr(routine_db, "_wal_enabled", False)
    monkeypatch.setattr(routine_db, "_wal_enabled_path", None)
    routine_db.setup_db()

    connection = routine_db.get_connection()
    columns = {row[1] for row in connection.execute("PRAGMA table_info(routines)").fetchall()}
    migrated_row = connection.execute(
        "SELECT event_name, unanswered_reminder_streak FROM routines"
    ).fetchone()
    connection.close()

    assert "unanswered_reminder_streak" in columns
    assert migrated_row == ("Existing routine", 0)


def test_unanswered_reminder_decay_requires_three_delivered_expiries(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Only three separate unanswered delivered reminders reduce confidence or decay a routine."""
    db_path = tmp_path / "routines.db"
    monkeypatch.setattr(routine_db, "DB_PATH", str(db_path))
    monkeypatch.setattr(routine_db, "_wal_enabled", False)
    monkeypatch.setattr(routine_db, "_wal_enabled_path", None)
    routine_db.setup_db()

    connection = routine_db.get_connection()
    connection.execute(
        """
        INSERT INTO routines (
            day_of_week, time_str, event_name, event_type, confidence,
            state, is_active, unanswered_reminder_streak
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        ("Thursday", "09:00", "Dynamic routine", "general", 0.4, "trigger_pending", 0, 0),
    )
    routine_id = connection.execute("SELECT last_insert_rowid()").fetchone()[0]
    connection.commit()
    connection.close()

    def expire_next_delivery() -> dict[str, int | float | bool | str]:
        """Put the routine into the sent state to simulate its next delivered reminder."""
        connection = routine_db.get_connection()
        connection.execute(
            "UPDATE routines SET state='trigger_pending', is_active=0 WHERE id=?",
            (routine_id,),
        )
        connection.commit()
        connection.close()
        return routine_db.record_unanswered_routine_expiry(routine_id)

    first = routine_db.record_unanswered_routine_expiry(routine_id)
    second = expire_next_delivery()
    third = expire_next_delivery()

    assert first["unanswered_streak"] == 1
    assert first["confidence_reduced"] is False
    assert second["unanswered_streak"] == 2
    assert second["confidence_reduced"] is False
    assert third == {
        "unanswered_streak": 3,
        "confidence_reduced": True,
        "confidence": 0.2,
        "state": "active",
    }
    assert routine_db.get_routine_notify_info(routine_id)["cooldown_hours"] == 20.0

    fourth = expire_next_delivery()
    fifth = expire_next_delivery()
    sixth = expire_next_delivery()

    assert fourth["confidence_reduced"] is False
    assert fifth["confidence_reduced"] is False
    assert sixth == {
        "unanswered_streak": 3,
        "confidence_reduced": True,
        "confidence": 0.0,
        "state": "decayed",
    }
    assert routine_db.get_routine_state(routine_id).value == "decayed"


def test_routine_response_resets_unanswered_reminder_streak(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An acknowledgement clears the unanswered reminder streak without completing the routine."""
    db_path = tmp_path / "routines.db"
    monkeypatch.setattr(routine_db, "DB_PATH", str(db_path))
    monkeypatch.setattr(routine_db, "_wal_enabled", False)
    monkeypatch.setattr(routine_db, "_wal_enabled_path", None)
    routine_db.setup_db()

    connection = routine_db.get_connection()
    connection.execute(
        """
        INSERT INTO routines (
            day_of_week, time_str, event_name, event_type, confidence,
            state, is_active, unanswered_reminder_streak
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        ("Thursday", "09:00", "Dynamic routine", "general", 0.9, "trigger_pending", 0, 2),
    )
    routine_id = connection.execute("SELECT last_insert_rowid()").fetchone()[0]
    connection.commit()
    connection.close()

    routine_db.mark_routine_acknowledged(routine_id)

    connection = routine_db.get_connection()
    streak = connection.execute(
        "SELECT unanswered_reminder_streak FROM routines WHERE id=?",
        (routine_id,),
    ).fetchone()[0]
    connection.close()
    assert streak == 0


def test_indefinite_pause_migration_blocks_scheduler_without_deleting_routine(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An indefinite pause restores pending state and remains reversible without deletion."""
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
        (datetime.now().strftime("%A"), "09:00", "Dynamic routine", "general", 0.9, "trigger_pending", 1),
    )
    routine_id = connection.execute("SELECT last_insert_rowid()").fetchone()[0]
    connection.commit()
    connection.close()

    monkeypatch.setattr("memory.event_log.log_event", lambda *args, **kwargs: None)
    routine_db.pause_routine_indefinitely(routine_id)
    metadata = routine_db.get_routine_schedule_meta(routine_id)

    assert metadata["paused_indefinitely"] is True
    assert routine_db.is_routine_temporarily_inactive_meta(metadata)[0] is True
    assert routine_db.get_routine_state(routine_id).value == "active"

    routine_db.clear_routine_paused_until(routine_id)

    assert routine_db.get_routine_state(routine_id).value == "active"


def test_indefinite_pause_excludes_routine_from_preemptive_candidates(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An indefinitely paused routine is absent from the shared Web and Telegram candidate query."""
    db_path = tmp_path / "routines.db"
    monkeypatch.setattr(routine_db, "DB_PATH", str(db_path))
    monkeypatch.setattr(routine_db, "_wal_enabled", False)
    monkeypatch.setattr(routine_db, "_wal_enabled_path", None)
    monkeypatch.setattr("memory.event_log.log_event", lambda *args, **kwargs: None)
    routine_db.setup_db()

    day = datetime.now().strftime("%A")
    connection = routine_db.get_connection()
    connection.execute(
        """
        INSERT INTO routines (day_of_week, time_str, event_name, event_type, confidence, state, is_active)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (day, "09:00", "Dynamic routine", "general", 0.9, "active", 1),
    )
    routine_id = connection.execute("SELECT last_insert_rowid()").fetchone()[0]
    connection.commit()
    connection.close()

    assert [row["id"] for row in routine_db.get_eligible_preemptive_routines_for_day(day)] == [routine_id]

    routine_db.pause_routine_indefinitely(routine_id)

    assert routine_db.get_eligible_preemptive_routines_for_day(day) == []
