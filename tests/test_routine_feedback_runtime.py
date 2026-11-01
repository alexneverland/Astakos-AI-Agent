"""Offline paired runtime composition; transport and inference are injected."""
from datetime import datetime
from types import SimpleNamespace
import sqlite3

import pytest

from memory.routine_feedback import RoutineFeedbackStore
from memory.conversation_history import append_message
from services.routine_feedback import ATHENS
from services.external_delivery import DeliveryReceipt
from services.routine_completion_helper import DatedRoutineSelection

NOW = datetime(2026, 10, 7, 10, tzinfo=ATHENS)


@pytest.mark.parametrize("value,expected", [(0, 0.0), (20, 20.0), (-1, 4.0), (100, 72.0), (None, 20.0)])
def test_notification_reader_preserves_zero_without_relaxing_legacy_bounds(value, expected):
    """The explicit no-backoff baseline must survive the canonical reader."""
    from memory.routine_db import clamp_cooldown_hours
    assert clamp_cooldown_hours(value) == expected


def test_real_notification_reader_preserves_reset_zero(store, monkeypatch):
    """Exercise the actual scheduler reader against the temporary reset baseline."""
    from memory import routine_db
    monkeypatch.setattr(routine_db, "get_connection", store.connection_factory)
    assert routine_db.get_routine_notify_info(1)["cooldown_hours"] == 0.0


@pytest.mark.parametrize("action", ["increase_cooldown", "reduce_frequency"])
def test_legacy_reflection_cannot_replace_dated_pressure(store, monkeypatch, action):
    """Nightly reflection must not become a second backoff policy writer."""
    from memory import routine_db
    from services import reflection_engine
    connection = store.connection_factory()
    path = connection.execute("PRAGMA database_list").fetchone()[2]
    connection.close()
    monkeypatch.setattr(reflection_engine.config, "ROUTINES_DB", path)
    monkeypatch.setattr(routine_db, "get_connection", store.connection_factory)
    assert reflection_engine._apply_action({"action": action, "routine_id": 1, "action_value": 40}) is False
    assert routine_db.get_routine_notify_info(1)["cooldown_hours"] == 0.0


@pytest.fixture
def store(tmp_path, monkeypatch):
    """Create only a disposable routine catalogue and occurrence ledger."""
    path = tmp_path / "routines.db"
    from core import messenger_draft
    monkeypatch.setattr(messenger_draft, "_settings",
                        lambda: (str(tmp_path / "draft.json"), 1800))
    def connect():
        return sqlite3.connect(path)
    with connect() as connection:
        connection.execute("""CREATE TABLE routines (id INTEGER PRIMARY KEY,
            event_name TEXT, notify_cooldown_hours REAL, explicit_skip_streak INTEGER,
            unanswered_reminder_streak INTEGER, confidence REAL, state TEXT,
            is_active INTEGER, last_triggered TEXT, last_notified_ts TEXT,
            paused_indefinitely INTEGER DEFAULT 0, day_of_week TEXT, time_str TEXT)""")
        connection.execute("INSERT INTO routines VALUES (1,'Home activity',0,0,0,1,'active',1,NULL,NULL,0,'Everyday','10:30')")
    result = RoutineFeedbackStore(connect)
    result.initialize()
    return result


@pytest.mark.parametrize("channel", ["web", "matrix", "telegram"])
def test_paired_runtime_delivery_feedback_and_no_second_send(store, tmp_path, channel):
    """One real receipt and saved owner turn complete one occurrence across adapters."""
    from services.routine_feedback_runtime import RoutineFeedbackRuntime
    history = str(tmp_path / "history.db")
    sends = []
    external_channel = "matrix" if channel == "web" else channel
    def deliver(text):
        sends.append(text)
        return DeliveryReceipt(external_channel, "exact-question")
    runtime = RoutineFeedbackRuntime(
        store=store, clock=lambda: NOW, deliver=deliver,
        record=lambda **kwargs: append_message(db_path=history, **kwargs),
        selector=lambda *args, **kwargs: DatedRoutineSelection("complete", 1, NOW.date()),
        draft_loader=lambda: {}, draft_selector=lambda *args, **kwargs: None)
    handler = runtime.handler(channel=channel, conversation_db_path=history)
    bot = SimpleNamespace()
    memory_api = SimpleNamespace()
    runtime.install_scheduler(bot, handler=runtime.handler(
        channel=external_channel, conversation_db_path=history), routine_db=memory_api)
    assert memory_api._dated_draft_feedback_recorder == store.record_draft_acknowledgement
    assert bot._dated_single_routine_sender is bot._dated_batch_routine_sender
    assert bot._dated_deferred_routine_sender is bot._dated_single_routine_sender
    assert bot._dated_routine_feedback_tick(NOW)
    sender = bot._dated_single_routine_sender
    assert sender.send(routine_id=1, occurrence_date=NOW.date(), text="Did you do it?",
        expected_revision=sender.revision(1), eligible=lambda: True).status == "sent"
    saved = append_message(role="user", content="I completed it", channel=channel, db_path=history)
    reply = "exact-question" if channel != "web" else None
    context = handler("I completed it", saved, reply_event_id=reply)
    assert context is not None
    assert store.occurrences(1)[0].feedback == "complete"
    assert sender.send(routine_id=1, occurrence_date=NOW.date(), text="Repeat?",
        expected_revision=sender.revision(1), eligible=lambda: True).status == "blocked"
    assert sends == ["Did you do it?"]


def test_runtime_preflight_rejects_uninitialized_store_without_mutation(store):
    """Composition does not quietly perform a migration or install half the hooks."""
    from services.routine_feedback_runtime import RoutineFeedbackRuntime
    with store.connection_factory() as connection:
        connection.execute("DROP TABLE routine_occurrences")
    with pytest.raises(sqlite3.OperationalError):
        RoutineFeedbackRuntime(store=store, clock=lambda: NOW, deliver=lambda text: None,
            record=lambda **kwargs: None, selector=lambda *args, **kwargs: None,
            draft_loader=lambda: {}, draft_selector=lambda *args, **kwargs: None)
    with store.connection_factory() as connection:
        assert connection.execute("SELECT name FROM sqlite_master WHERE name='routine_occurrences'").fetchone() is None


@pytest.mark.parametrize("failure", [False, True])
def test_recoverable_reset_preserves_receipts_and_protected_state(store, tmp_path, failure):
    """Baseline reset is atomic, backed up, and cannot replay today's receipt."""
    from datetime import timedelta
    before_time = NOW - timedelta(days=3)
    store.record_delivery(1, NOW.date(), at=NOW, receipt_id="preserved")
    store.record_feedback(1, before_time.date(), "complete", at=NOW)
    with store.connection_factory() as connection:
        connection.execute("UPDATE routines SET notify_cooldown_hours=72, confidence=0.2, explicit_skip_streak=2, unanswered_reminder_streak=2, state='paused', is_active=0, last_triggered='2026-10-07'")
        before = connection.execute("SELECT * FROM routines").fetchall()
        occurrences = connection.execute("SELECT * FROM routine_occurrences").fetchall()
        if failure:
            connection.execute("""CREATE TRIGGER reject_reset BEFORE UPDATE OF confidence
                ON routines BEGIN SELECT RAISE(ABORT, 'offline reset'); END""")
    snapshot = tmp_path / "reset.sqlite3"
    if failure:
        with pytest.raises(sqlite3.IntegrityError):
            store.reset_feedback_baseline(at=NOW, snapshot_path=snapshot)
        assert not snapshot.exists()
    else:
        assert store.reset_feedback_baseline(at=NOW, snapshot_path=snapshot) == (1,)
        with sqlite3.connect(snapshot) as backup:
            assert backup.execute("SELECT * FROM routines").fetchall() == before
            assert backup.execute("SELECT * FROM routine_occurrences").fetchall() == occurrences
        store.reconcile(1, now=NOW + timedelta(days=1))
    with store.connection_factory() as connection:
        after = connection.execute("SELECT * FROM routines").fetchall()
    if failure:
        assert after == before
    else:
        assert after[0][2:6] == (0, 0, 0, 1)
        assert after[0][6:] == before[0][6:]
        with store.connection_factory() as connection:
            assert connection.execute("SELECT receipt_id FROM routine_occurrences WHERE routine_id=1 AND occurrence_date=?",
                                      (NOW.date().isoformat(),)).fetchone() == ("preserved",)
        assert not store.claim_dispatch(1, NOW.date(), at=NOW,
            expected_revision=store.revision(1), is_eligible=lambda: True)
        assert store.occurrences(1)[0].feedback == "complete"


def test_reset_never_overwrites_existing_snapshot(store, tmp_path):
    """Existing recovery artifacts are not replaced, even on an operator retry."""
    snapshot = tmp_path / "already.sqlite3"
    snapshot.touch()
    with pytest.raises(FileExistsError):
        store.reset_feedback_baseline(at=NOW, snapshot_path=snapshot)
    assert snapshot.stat().st_size == 0


def test_existing_store_detection_is_read_only_and_never_creates_database(tmp_path):
    """Normal startup cannot perform the owner-gated schema migration."""
    from memory.routine_feedback import load_initialized_feedback_store
    path = tmp_path / "not-created.db"
    def forbidden():
        pytest.fail("An uninitialized database must not be opened for writing")
    assert load_initialized_feedback_store(path, connection_factory=forbidden) is None
    assert not path.exists()
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE routines (id INTEGER PRIMARY KEY)")
    assert load_initialized_feedback_store(path, connection_factory=forbidden) is None
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT name FROM sqlite_master WHERE name='routine_occurrences'").fetchone() is None


def test_external_preparation_installs_the_complete_bundle_before_workers(store, tmp_path, monkeypatch):
    """Matrix factory and scheduler share the same prepared handler/ledger."""
    from clients import telegram_bot as bot
    from memory import routine_db
    from services import routine_feedback_runtime as composition
    history = str(tmp_path / "history.db")
    runtime = composition.RoutineFeedbackRuntime(store=store, clock=lambda: NOW,
        deliver=lambda text: DeliveryReceipt("matrix", "event"),
        record=lambda **kwargs: append_message(db_path=history, **kwargs),
        selector=lambda *args, **kwargs: DatedRoutineSelection("none"),
        draft_loader=lambda: {}, draft_selector=lambda *args, **kwargs: None)
    monkeypatch.setattr(composition, "build_existing_routine_feedback_runtime", lambda: runtime)
    monkeypatch.setattr(bot, "_external_background_runtime_channel", None)
    monkeypatch.setattr(bot, "_dated_feedback_runtime", None, raising=False)
    for name in ("_persisted_routine_feedback_handler", "_dated_routine_feedback_tick",
                 "_dated_single_routine_sender", "_dated_deferred_routine_sender",
                 "_dated_batch_routine_sender", "_dated_pending_expiry_handler"):
        monkeypatch.setattr(bot, name, None)
    monkeypatch.setattr(routine_db, "_dated_draft_feedback_recorder", None)
    handler = bot.prepare_dated_feedback_runtime("matrix")
    assert bot.prepare_dated_feedback_runtime("matrix") is handler
    assert handler is bot._persisted_routine_feedback_handler
    assert bot._dated_single_routine_sender is runtime.sender
    assert bot._dated_deferred_routine_sender is runtime.sender
    assert bot._dated_batch_routine_sender is runtime.sender
    assert bot._dated_pending_expiry_handler == store.close_response_window
    assert routine_db._dated_draft_feedback_recorder == store.record_draft_acknowledgement


def test_web_startup_preparation_uses_canonical_history_and_draft_callback(store, tmp_path, monkeypatch):
    """Verify the actual Web setup without launching background threads or providers."""
    import config
    from api import server as api
    from memory import routine_db
    from services import routine_feedback_runtime as composition
    history = str(tmp_path / "web-history.db")
    monkeypatch.setattr(config, "CONVERSATION_DB_FILE", history)
    runtime = composition.RoutineFeedbackRuntime(store=store, clock=lambda: NOW,
        deliver=lambda text: pytest.fail("Web startup must not send"),
        record=lambda **kwargs: append_message(db_path=history, **kwargs),
        selector=lambda *args, **kwargs: DatedRoutineSelection("complete", 1, NOW.date()),
        draft_loader=lambda: {}, draft_selector=lambda *args, **kwargs: None)
    monkeypatch.setattr(composition, "build_existing_routine_feedback_runtime", lambda: runtime)
    monkeypatch.setattr(routine_db, "_dated_draft_feedback_recorder", None)
    app = SimpleNamespace(state=SimpleNamespace())
    api.prepare_web_routine_feedback(app)
    saved = append_message(role="user", content="done", channel="web", db_path=history)
    assert app.state.persisted_routine_feedback_handler("done", saved) is not None
    assert store.occurrences(1)[0].feedback == "complete"
    assert routine_db._dated_draft_feedback_recorder == store.record_draft_acknowledgement
