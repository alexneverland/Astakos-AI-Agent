"""Offline review regressions for mixed-answer durable reconciliation."""

from types import SimpleNamespace
from datetime import datetime, timedelta

import pytest

from memory import routine_db
from services import context_extractor as extractor


@pytest.fixture
def isolated_context(tmp_path, monkeypatch):
    """Use canonical temporary persistence and forbid provider/network leakage."""
    import socket
    from memory import event_log

    def forbidden(*args, **kwargs):
        raise AssertionError("Unexpected live network/provider operation")

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(routine_db, "DB_PATH", str(tmp_path / "routines.db"))
    routine_db.setup_db()
    monkeypatch.setattr(event_log, "log_event", lambda *args, **kwargs: None)
    monkeypatch.setattr(extractor, "load_recent_state_messages", lambda **kwargs: [])
    monkeypatch.setattr(extractor, "safe_gemini_call", forbidden)
    monkeypatch.setattr(extractor, "infer_routine_reconciliation_directives", lambda *args, **kwargs: [])
    return {"question": "Είναι η Σοφία μαζί σου;", "flags": ["partner_with_user"]}


def _durable_shift_and_stale_presence():
    """Model durable schedule output must not reopen already-resolved live state."""
    until = (datetime.now() + timedelta(days=7)).strftime("%Y-%m-%d")
    return [
        {"kind": "context_state_set", "key": "current_shift", "value": "morning", "until_date": until},
        {"kind": "context_state_set", "key": "partner_with_user", "value": True, "until_date": until},
    ]


def test_matrix_mixed_answer_keeps_durable_reconciliation_without_repeating_live_flags(
    isolated_context, monkeypatch,
):
    """The real Matrix background path must preserve a future shift update."""
    from services import matrix_background as background

    message = "Όχι, δεν είμαστε μαζί. Από αύριο δουλεύω πρωί όλη την εβδομάδα."
    monkeypatch.setattr(extractor, "safe_gemini_call", lambda prompt: SimpleNamespace(text=
        '{"relation":"related","flags":{"partner_with_user":false},"continue_conversation":true}'))
    result = extractor.extract_and_update_context_flags(
        message, channel="matrix", clarification_context=isolated_context)
    assert result.continue_conversation
    assert routine_db.get_context_state("partner_with_user")["value"] == "false"

    def forbidden(*args, **kwargs):
        raise AssertionError("A consumed context answer must not repeat live flag inference")

    monkeypatch.setattr(extractor, "safe_gemini_call", forbidden)
    monkeypatch.setattr(extractor, "infer_routine_reconciliation_directives",
                        lambda *args, **kwargs: _durable_shift_and_stale_presence())
    queued = []
    hooks = background.MatrixBackgroundHooks(
        enqueue_fast_task=lambda *args: None,
        enqueue_slow_task=lambda fn, *args: queued.append((fn, args)),
    )
    hooks.on_exchange_completed(message, "Σημειώθηκε.", "Chat_Agent", "matrix",
                                context_flags_processed=True, context_reconciliation_pending=True)
    # Execute only the context job; memory/followup/provider work is out of scope.
    for fn, args in queued:
        if "context" in fn.__name__ or "reconcil" in fn.__name__:
            fn(*args)
    shift = routine_db.get_context_state("current_shift")
    assert shift is not None, "Consuming context must not drop durable shift reconciliation"
    assert shift["value"] == "morning"
    assert routine_db.get_context_state("partner_with_user")["value"] == "false"


def test_reconcile_only_preserves_schedule_without_model_or_live_writes(
    isolated_context, monkeypatch,
):
    """A separate mode can retain durable reconciliation after a guarded answer."""
    routine_db.set_context_state("partner_with_user", "false")
    monkeypatch.setattr(extractor, "infer_routine_reconciliation_directives",
                        lambda *args, **kwargs: _durable_shift_and_stale_presence())
    extractor.reconcile_context_message(
        "Όχι, δεν είμαστε μαζί. Από αύριο δουλεύω πρωί όλη την εβδομάδα.")
    assert routine_db.get_context_state("current_shift")["value"] == "morning"
    assert routine_db.get_context_state("partner_with_user")["value"] == "false"


def test_legacy_missing_continuation_decision_does_not_swallow_reminder(
    isolated_context, monkeypatch,
):
    """Missing model routing metadata must not silently erase another request."""
    monkeypatch.setattr(extractor, "safe_gemini_call", lambda prompt: SimpleNamespace(text=
        '{"relation":"related","flags":{"partner_with_user":false}}'))
    result = extractor.extract_and_update_context_flags(
        "Όχι, και βάλε υπενθύμιση στις έξι να πάρω τηλέφωνο.",
        clarification_context=isolated_context)
    assert result.continue_conversation is True
    assert routine_db.get_context_state("partner_with_user")["value"] == "false"


def test_explicit_standalone_decision_still_closes_context_only(isolated_context, monkeypatch):
    """An explicit false remains the safe fast path for a pure answer."""
    monkeypatch.setattr(extractor, "safe_gemini_call", lambda prompt: SimpleNamespace(text=
        '{"relation":"related","flags":{"partner_with_user":false},"continue_conversation":false}'))
    result = extractor.extract_and_update_context_flags("Όχι", clarification_context=isolated_context)
    assert result.continue_conversation is False
    assert routine_db.get_context_state("partner_with_user")["value"] == "false"
