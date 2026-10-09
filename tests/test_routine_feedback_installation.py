"""Fresh setup and upgrade contracts using real isolated routine databases."""
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sqlite3
from types import ModuleType

import pytest

from memory.routine_feedback import RoutineFeedbackStore, load_initialized_feedback_store
from services.routine_feedback import ATHENS


def _setup_path(monkeypatch: pytest.MonkeyPatch, path: Path) -> ModuleType:
    """Select a temporary canonical database without importing live storage."""
    from memory import routine_db
    monkeypatch.setattr(routine_db, "DB_PATH", str(path))
    return routine_db


def test_fresh_normal_setup_provisions_dated_feedback(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Setup without declarations must prepare the ledger for later learned routines."""
    path = tmp_path / "fresh.db"
    routine_db = _setup_path(monkeypatch, path)
    routine_db.setup_db()
    store = load_initialized_feedback_store(path, connection_factory=routine_db.get_connection)
    assert store is not None
    assert store.tracked_routine_ids() == ()


def test_upgrade_adds_ledger_without_resetting_routines(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The supported legacy table keeps owner state while gaining the missing ledger."""
    path = tmp_path / "legacy.db"
    routine_db = _setup_path(monkeypatch, path)
    routine_db.setup_db()
    with sqlite3.connect(path) as connection:
        connection.execute("DROP TABLE IF EXISTS routine_occurrences")
        connection.execute("""INSERT INTO routines
            (id, day_of_week, time_str, event_name, confidence, state, is_active,
             fingerprint, paused_indefinitely, notify_cooldown_hours,
             explicit_skip_streak, unanswered_reminder_streak)
             VALUES (1,'Everyday','18:00','Walk',0.42,'active',1,'fixture',1,40,2,1)""")
        before = connection.execute("SELECT * FROM routines").fetchall()
    routine_db.setup_db()
    store = load_initialized_feedback_store(path, connection_factory=routine_db.get_connection)
    assert store is not None
    assert store.occurrences(1) == []
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT * FROM routines").fetchall() == before


def test_repeat_setup_preserves_feedback_and_baseline(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Provisioning must never call the separate owner-only feedback reset."""
    path = tmp_path / "existing.db"
    routine_db = _setup_path(monkeypatch, path)
    routine_db.setup_db()
    routine_db.import_declared_routines([{"day": "Everyday", "time": "18:00", "event": "Walk", "type": "hobby"}])
    store = RoutineFeedbackStore(routine_db.get_connection)
    store.initialize()
    now = datetime(2026, 10, 9, 12, tzinfo=ATHENS)
    store.record_baseline(1, at=now)
    with sqlite3.connect(path) as connection:
        before = connection.execute("SELECT * FROM routine_occurrences").fetchall()
        routines_before = connection.execute("SELECT * FROM routines").fetchall()
    monkeypatch.setattr(RoutineFeedbackStore, "reset_feedback_baseline", lambda *a, **k: pytest.fail("Startup reset owner feedback"))
    routine_db.setup_db()
    routine_db.setup_db()
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT * FROM routine_occurrences").fetchall() == before
        assert connection.execute("SELECT * FROM routines").fetchall() == routines_before


def test_concurrent_normal_starters_share_complete_schema(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Parallel Web/transport startup must not race additive ledger columns."""
    path = tmp_path / "concurrent.db"
    routine_db = _setup_path(monkeypatch, path)
    with ThreadPoolExecutor(max_workers=3) as workers:
        for future in [workers.submit(routine_db.setup_db) for _ in range(3)]:
            future.result(timeout=15)
    store = load_initialized_feedback_store(path, connection_factory=routine_db.get_connection)
    assert store is not None
    assert store.tracked_routine_ids() == ()


def test_failed_ledger_migration_rolls_back_entire_setup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """No partial canonical schema may survive a failed fresh installation."""
    path = tmp_path / "failed.db"
    routine_db = _setup_path(monkeypatch, path)
    initialize = RoutineFeedbackStore.initialize_schema

    def fail_after_creation(connection: sqlite3.Connection) -> None:
        """Exercise real schema work before a simulated migration interruption."""
        initialize(connection)
        raise sqlite3.OperationalError("fixture migration failure")

    monkeypatch.setattr(RoutineFeedbackStore, "initialize_schema", staticmethod(fail_after_creation))
    with pytest.raises(sqlite3.OperationalError, match="fixture migration failure"):
        routine_db.setup_db()
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall() == []
    monkeypatch.setattr(RoutineFeedbackStore, "initialize_schema", staticmethod(initialize))
    routine_db.setup_db()
    assert load_initialized_feedback_store(path, connection_factory=routine_db.get_connection) is not None


@pytest.mark.parametrize("channel", ["web", "telegram", "matrix"])
def test_fresh_declaration_delivers_and_completes_through_runtime(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, channel: str) -> None:
    """Real fresh storage supports a confirmed injected send and saved-owner feedback."""
    from memory.conversation_history import append_message
    from memory.routine_importer import import_validated_routines
    from services.routine_feedback_runtime import RoutineFeedbackRuntime
    from services.routine_completion_helper import DatedRoutineSelection
    from services.external_delivery import DeliveryReceipt
    path = tmp_path / "paired.db"
    routine_db = _setup_path(monkeypatch, path)
    routine_db.setup_db()
    assert import_validated_routines([{"day": "Everyday", "time": "18:00", "event": "Walk", "type": "hobby"}])["count"] == 1
    store = load_initialized_feedback_store(path, connection_factory=routine_db.get_connection)
    assert store is not None
    now = datetime(2026, 10, 9, 18, tzinfo=ATHENS)
    history = str(tmp_path / "history.db")
    delivered = []

    def deliver(text: str) -> DeliveryReceipt:
        """Return a real protocol receipt while forbidding external transport I/O."""
        delivered.append(text)
        return DeliveryReceipt("matrix" if channel == "web" else channel, "fixture-receipt")

    runtime = RoutineFeedbackRuntime(store=store, clock=lambda: now, deliver=deliver,
        record=lambda **kwargs: append_message(db_path=history, **kwargs),
        selector=lambda *args, **kwargs: DatedRoutineSelection("complete", 1, now.date()),
        draft_loader=lambda: {}, draft_selector=lambda *args, **kwargs: None)
    outcome = runtime.sender.send(routine_id=1, occurrence_date=now.date(), text="Walk reminder",
        expected_revision=store.revision(1), eligible=lambda: True)
    assert outcome.status == "sent"
    assert delivered == ["Walk reminder"]
    saved = append_message(role="user", content="I did the walk", channel=channel, db_path=history)
    handler = runtime.handler(channel=channel, conversation_db_path=history)
    assert handler("I did the walk", saved) is not None
    assert store.occurrences(1)[0].feedback == "complete"
    routine_db.setup_db()
    assert store.occurrences(1)[0].feedback == "complete"
