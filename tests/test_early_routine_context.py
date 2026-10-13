"""Early scheduled questions and dispatch use real isolated canonical stores."""
from datetime import timedelta
from types import SimpleNamespace

import pytest

from tests.test_routine_context_clarification_worker import environment
from services.routine_context_clarification_scheduler import clarification_unavailable as real_unavailable
from services.routine_context_evidence import ContextEvidence


@pytest.mark.parametrize("channel", ["matrix", "telegram"])
@pytest.mark.parametrize("quiet_at_dispatch", [None, "before", "during_model"])
@pytest.mark.parametrize("routine_name", ["Αναχώρηση για δουλειά (Πρωινή Βάρδια)"])
def test_default_quiet_window_allows_due_question_then_guarded_reminder(environment, monkeypatch, channel, quiet_at_dispatch, routine_name):
    """06:15 required context can unblock the explicit 06:30 work departure."""
    from clients import telegram_bot as bot
    from memory.routine_context_clarification import ClarificationStore
    from memory.routine_feedback import RoutineFeedbackStore
    from services import routine_context as context
    from services.routine_feedback_dispatch import DatedRoutineSender
    from services.external_delivery import DeliveryReceipt
    worker, db, rid, state, questions, _, _, root = environment
    state["now"] = state["now"].replace(hour=6, minute=15)
    state["channel"] = channel
    db.update_routine_db(rid, new_time="06:30")
    _real_gates(worker, bot, monkeypatch, state, db)
    assert context.resolve_quiet_hours(state["now"]) is True
    assert context.resolve_quiet_hours(state["now"], scheduled=True) is False
    monkeypatch.setattr(context, "build_runtime_routine_context", lambda *a, **k: {"current_shift": "morning"})
    # Actual morning conditions contain no volatile flag, so semantic dependency
    # resolution must run before the required home/away question can be asked.
    assert db.replace_routine_conditions(rid, db.get_routine_conditions(rid), [
        {"condition_type": "shift_mode", "condition_payload": {"flag": "current_shift", "equals": "morning"}, "condition_mode": "allow_when_true"},
        {"condition_type": "context_flag", "condition_payload": {"flag": "user_at_work", "equals": True}, "condition_mode": "suppress_when_true"}])
    def classify(packet, *, dependencies=False):
        if dependencies:
            return {"flags": ["user_out_of_home"]}
        return {"routine_ids": [str(rid)], "flags": ["user_out_of_home"], "question": "Έχεις φύγει ήδη;"}
    monkeypatch.setattr(worker, "classify_packet", classify)
    worker.run_context_clarification_job()
    assert len(questions) == 1
    worker.run_context_clarification_job()
    assert len(questions) == 1
    state["now"] += timedelta(minutes=5)
    state["evidence"] = {"user_out_of_home": ContextEvidence(effective_value=False,
        status="known", recorded_at=state["now"])}
    worker.run_context_clarification_job()  # The existing question resolves.
    assert ClarificationStore(root / "astakos_routine_context_questions.json").snapshot()["pending"] is None
    monkeypatch.setattr(bot, "datetime", db.datetime)
    monkeypatch.setattr(bot, "pending_routine_confirmations", {})
    monkeypatch.setattr(bot, "resolve_external_channel", lambda: channel)
    monkeypatch.setattr(worker, "schedule_context_clarification", lambda _: None)
    monkeypatch.setattr(bot, "_is_partner_messenger_routine", lambda _: False)
    def craft(*a, **k):
        if quiet_at_dispatch == "during_model":
            db.set_context_state("quiet_hours", "true", state["now"].date().isoformat())
        return "Σε δέκα λεπτά αναχώρηση", False
    monkeypatch.setattr(bot, "_craft_proactive_msg", craft)
    if quiet_at_dispatch == "before":
        db.set_context_state("quiet_hours", "true", state["now"].date().isoformat())
    store = RoutineFeedbackStore(db.get_connection)
    delivered = []
    sender = DatedRoutineSender(store, lambda: state["now"],
        lambda text: delivered.append(text) or DeliveryReceipt(channel, "$departure"))
    monkeypatch.setattr(bot, "_dated_single_routine_sender", sender)
    monkeypatch.setattr(bot, "_dated_batch_routine_sender", sender)
    bot.job_check_routines()
    if quiet_at_dispatch:
        assert not delivered and all(row.delivered_at is None for row in store.occurrences(rid))
        return
    assert delivered == ["Σε δέκα λεπτά αναχώρηση"]
    assert store.occurrences(rid)[0].delivered_at == state["now"]
    bot.job_check_routines()
    assert len(delivered) == 1


@pytest.mark.parametrize("block", ["explicit_quiet", "malformed_quiet", "muted", "paused", "routine_muted",
    "routine_paused", "recent_activity", "recent_reminder", "confirmation", "inactive", "budget",
    "outside_window", "deadline", "known_away", "quiet_during_model", "mute_during_model"])
def test_early_question_preserves_other_gates(environment, monkeypatch, block):
    """A schedule overrides only default hours, never explicit safety/currentness."""
    from clients import telegram_bot as bot
    from memory import event_log
    from services import routine_context_clarification as clarification
    worker, db, rid, state, sends, packets, _, _ = environment
    state["now"] = state["now"].replace(hour=6, minute=15)
    db.update_routine_db(rid, new_time="06:30")
    _real_gates(worker, bot, monkeypatch, state, db)
    if block in {"explicit_quiet", "malformed_quiet"}:
        db.set_context_state("quiet_hours", "true" if block == "explicit_quiet" else "invalid", state["now"].date().isoformat())
    if block == "muted": monkeypatch.setattr(bot, "is_proactive_muted", lambda: True)
    if block == "paused": monkeypatch.setattr(bot, "_active_routine_pause_until", lambda: state["now"]+timedelta(hours=1))
    if block == "routine_muted": db.set_routine_muted_until(rid, "2099-01-01")
    if block == "routine_paused": db.pause_routine_indefinitely(rid)
    if block == "recent_activity": monkeypatch.setattr(bot, "should_skip_proactive_for_recent_activity", lambda **k: True)
    if block == "recent_reminder": monkeypatch.setattr(event_log, "has_recent_reminder_delivery", lambda _: True)
    if block == "confirmation": monkeypatch.setattr(clarification, "context_confirmation_conflict", lambda: True)
    if block == "inactive": monkeypatch.setattr(bot, "shutdown_event", SimpleNamespace(is_set=lambda: True))
    if block == "budget": monkeypatch.setattr(bot, "can_send_proactive", lambda: False)
    if block == "outside_window": state["now"] -= timedelta(minutes=1)
    if block == "deadline": state["now"] += timedelta(minutes=15)
    if block == "known_away": state["evidence"] = {"user_out_of_home": ContextEvidence(effective_value=True, status="known")}
    original = worker.classify_packet
    def classify(packet, **kwargs):
        if block == "quiet_during_model": db.set_context_state("quiet_hours", "true", state["now"].date().isoformat())
        if block == "mute_during_model": db.set_routine_muted_until(rid, "2099-01-01")
        return original(packet, **kwargs)
    monkeypatch.setattr(worker, "classify_packet", classify)
    worker.run_context_clarification_job()
    assert not sends
    if block not in {"budget", "quiet_during_model", "mute_during_model"}:
        assert not packets


@pytest.mark.parametrize("stored,expiry,ordinary,scheduled", [
    ("true", "2026-10-05", True, False), ("true", "2026-10-06", True, True),
    ("false", "2026-10-06", False, False)])
def test_scheduled_quiet_policy_retains_explicit_state(environment, stored, expiry, ordinary, scheduled):
    """An expired request falls back to default hours; active requests win."""
    from services.routine_context import resolve_quiet_hours
    _, db, _, state, _, _, _, _ = environment
    state["now"] = state["now"].replace(hour=6, minute=15)
    db.set_context_state("quiet_hours", stored, expiry)
    assert resolve_quiet_hours(state["now"]) is ordinary
    assert resolve_quiet_hours(state["now"], scheduled=True) is scheduled


def _real_gates(worker, bot, monkeypatch, state, db):
    """Restore production gating while isolating transport/history-only checks."""
    from memory import event_log
    from services import routine_context_clarification as clarification
    monkeypatch.setattr(worker, "clarification_unavailable", real_unavailable)
    monkeypatch.setattr(bot, "is_quiet_hours", lambda: True)
    monkeypatch.setattr(bot, "is_proactive_muted", lambda: False)
    monkeypatch.setattr(bot, "_active_routine_pause_until", lambda: None)
    monkeypatch.setattr(bot, "should_skip_proactive_for_recent_activity", lambda **k: False)
    monkeypatch.setattr(bot, "_external_background_runtime_channel", state["channel"])
    monkeypatch.setattr(bot, "shutdown_event", SimpleNamespace(is_set=lambda: False))
    monkeypatch.setattr(event_log, "has_recent_reminder_delivery", lambda _: False)
    monkeypatch.setattr(clarification, "context_confirmation_conflict", lambda: False)
