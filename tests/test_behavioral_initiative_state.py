"""Offline durable send-intent and exactly-once history contracts."""
from datetime import datetime
import pytest

from memory.behavioral_initiative_state import InitiativeStore
from memory.conversation_history import append_message, load_messages


def test_missing_state_is_read_only_and_atomic_restart(tmp_path):
    store = InitiativeStore(tmp_path / "state.json")
    assert store.load() == {"version": 1, "delivered": [], "pending": None, "evaluated": None}
    assert not store.path.exists()
    with store.lock():
        state = store.load()
        store.save(state)
    assert InitiativeStore(store.path).load() == state


def test_corruption_is_not_reset(tmp_path):
    store = InitiativeStore(tmp_path / "state.json")
    store.path.write_text('{"version":1,"delivered":"bad","pending":null}')
    with pytest.raises(ValueError):
        store.load()
    assert '"bad"' in store.path.read_text()


def test_failed_replace_preserves_state_and_cleans_temporary(tmp_path, monkeypatch):
    import memory.behavioral_initiative_state as module
    store = InitiativeStore(tmp_path / "state.json")
    state = store.load()
    store.save(state)
    monkeypatch.setattr(module.os, "replace", lambda *args: (_ for _ in ()).throw(OSError()))
    with pytest.raises(OSError):
        store.save(state)
    assert store.load() == state
    assert not list(tmp_path.glob(".behavioral-initiative-*.tmp"))


def test_stable_history_identity_survives_repeat_and_restart(tmp_path):
    path = str(tmp_path / "conversation.db")
    for _ in range(2):
        append_message(role="assistant", content="A considerate opener", channel="matrix",
                       message_id="behavioral-123", timestamp=datetime(2026, 10, 2, 12), db_path=path)
    rows = load_messages(db_path=path)
    assert len(rows) == 1
    assert rows[0]["id"] == "behavioral-123"


def test_optional_diagnostics_do_not_initialize_or_modify_delivery_state(tmp_path):
    store = InitiativeStore(tmp_path / "state.json")
    assert store.load_diagnostics() == {"last_check": None, "last_decision": None}
    assert not list(tmp_path.iterdir())
    event = {"reason": "model_no_topic", "model_evaluated": True}
    store.record_diagnostic(event)
    store.record_diagnostic({"reason": "already_evaluated", "model_evaluated": False})
    assert store.load_diagnostics()["last_decision"] == event
    assert not store.path.exists()


def test_corrupt_telemetry_is_not_a_delivery_failure_or_exposed_payload(tmp_path):
    store = InitiativeStore(tmp_path / "state.json")
    store.diagnostic_path.write_text('{"version":1,"last_check":{"private_text":"secret"}}')
    assert store.load_diagnostics()["error"] == "diagnostics_unavailable"
    assert "secret" not in str(store.load_diagnostics())
    assert store.load()["pending"] is None
