"""Slow semantic inference cannot overwrite newer canonical context evidence."""

from types import SimpleNamespace

import pytest

from memory import routine_db
from services import context_extractor as extractor


@pytest.fixture
def isolated_context(tmp_path, monkeypatch):
    """Use canonical writers on a temporary DB and forbid outbound providers."""
    import socket

    def forbidden(*args, **kwargs):
        raise AssertionError("Unexpected outbound network call")

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(routine_db, "DB_PATH", str(tmp_path / "routines.db"))
    routine_db.setup_db()
    monkeypatch.setattr(extractor, "load_recent_trusted_user_messages", lambda **_: [])
    monkeypatch.setattr(extractor, "infer_routine_reconciliation_directives", lambda *a, **k: [])
    monkeypatch.setattr(extractor, "apply_routine_reconciliation_directives", forbidden)
    monkeypatch.setattr(extractor, "safe_gemini_call", forbidden)


def test_ordinary_inference_cannot_overwrite_newer_context_batch(isolated_context, monkeypatch):
    """A newer work update holds the entire older home/presence payload."""
    routine_db.set_context_state("user_at_work", "false")

    def slow_model(prompt):
        routine_db.set_context_state("user_at_work", "true")
        return SimpleNamespace(text='{"user_at_work":false,"partner_with_user":true}')

    monkeypatch.setattr(extractor, "safe_gemini_call", slow_model)
    extractor.extract_and_update_context_flags("Είμαι σπίτι μαζί με τη Σοφία.")

    assert routine_db.get_context_state("user_at_work")["value"] == "true"
    assert routine_db.get_context_state("partner_with_user") is None


def test_mixed_extra_flag_newer_write_holds_entire_answer(isolated_context, monkeypatch):
    """Extra nonvolatile facts are freshness-protected too; requests still continue."""
    routine_db.set_context_state("partner_at_work", "true")

    def slow_model(prompt):
        routine_db.set_context_state("partner_at_work", "false")
        return SimpleNamespace(text=(
            '{"relation":"related","flags":{"partner_with_user":false,'
            '"partner_at_work":true},"continue_conversation":true}'
        ))

    monkeypatch.setattr(extractor, "safe_gemini_call", slow_model)
    result = extractor.extract_and_update_context_flags(
        "Όχι, η Σοφία είναι δουλειά. Βάλε υπενθύμιση για τις έξι.",
        clarification_context={"question": "Είναι η Σοφία μαζί σου;", "flags": ["partner_with_user"]},
        clarification_still_current=lambda: True,
        clarification_commit=lambda persist: persist(),
    )

    assert routine_db.get_context_state("partner_at_work")["value"] == "false"
    assert routine_db.get_context_state("partner_with_user") is None
    assert routine_db.get_context_state("partner_work_mode") is None
    assert result.continue_conversation is True
    assert not result.applied_flags


def test_context_batch_compare_and_set_rejects_stale_all_or_none(isolated_context):
    """No second key is written when any expected context row has changed."""
    routine_db.set_context_state("partner_at_work", "true")
    expected = {"partner_at_work": routine_db.get_context_state("partner_at_work"),
                "partner_with_user": None}
    routine_db.set_context_state("partner_at_work", "false")

    accepted = routine_db.set_context_states_if_unchanged(
        {"partner_at_work": ("true", None), "partner_with_user": ("false", None)}, expected
    )

    assert accepted is False
    assert routine_db.get_context_state("partner_at_work")["value"] == "false"
    assert routine_db.get_context_state("partner_with_user") is None


def test_context_batch_compare_and_set_accepts_current_snapshot(isolated_context):
    """Current expected rows authorize one atomic bounded update batch."""
    routine_db.set_context_state("partner_at_work", "false")
    expected = {"partner_at_work": routine_db.get_context_state("partner_at_work"),
                "partner_with_user": None}

    accepted = routine_db.set_context_states_if_unchanged(
        {"partner_at_work": ("true", "2099-01-01"), "partner_with_user": ("false", None)}, expected
    )

    assert accepted is True
    assert routine_db.get_context_state("partner_at_work")["value"] == "true"
    assert routine_db.get_context_state("partner_at_work")["expires_at"] == "2099-01-01"
    assert routine_db.get_context_state("partner_with_user")["value"] == "false"


def test_context_batch_compare_and_set_detects_same_value_new_evidence(isolated_context):
    """Reaffirming an equal value still supersedes an older evidence version."""
    routine_db.set_context_state("partner_at_work", "false")
    expected = {"partner_at_work": routine_db.get_context_state("partner_at_work")}
    routine_db.set_context_state("partner_at_work", "false", expires_at="2099-01-01")

    accepted = routine_db.set_context_states_if_unchanged(
        {"partner_at_work": ("true", None)}, expected
    )

    assert accepted is False
    assert routine_db.get_context_state("partner_at_work")["value"] == "false"
    assert routine_db.get_context_state("partner_at_work")["expires_at"] == "2099-01-01"


def test_context_batch_commit_failure_rolls_back_every_key(isolated_context, monkeypatch):
    """No partial context survives an exception at the transaction commit boundary."""
    connect = routine_db.get_connection

    class FailingCommit:
        """Delegate actual temp SQLite operations, fail only the commit boundary."""
        def __init__(self):
            self.connection = connect()

        def __getattr__(self, name):
            return getattr(self.connection, name)

        def commit(self):
            raise OSError("commit unavailable")

    monkeypatch.setattr(routine_db, "get_connection", FailingCommit)
    with pytest.raises(OSError):
        routine_db.set_context_states_if_unchanged(
            {"partner_at_work": ("true", None), "partner_with_user": ("false", None)},
            {"partner_at_work": None, "partner_with_user": None})
    monkeypatch.setattr(routine_db, "get_connection", connect)
    assert routine_db.get_context_state("partner_at_work") is None
    assert routine_db.get_context_state("partner_with_user") is None
