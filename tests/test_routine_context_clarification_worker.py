"""Offline production-worker wiring with real temporary routine/history stores."""
from datetime import datetime, timedelta
import socket

import pytest

from memory.routine_context_clarification import ATHENS, ClarificationStore
from services.routine_context_evidence import ContextEvidence

NOW = datetime(2026, 10, 6, 10, tzinfo=ATHENS)


@pytest.fixture
def environment(monkeypatch, tmp_path):
    """Isolate all storage and reject accidental provider/transport connections."""
    import config
    from clients import telegram_bot as bot
    from memory import routine_db as db, conversation_history as history
    from services import routine_context as context
    from services import routine_context_clarification_scheduler as worker
    from services.external_delivery import external_delivery_router as router, DeliveryReceipt
    from core import messaging_channel
    def denied(*args, **kwargs):
        pytest.fail("offline worker attempted network access")
    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr(config, "BASE_DIR", str(tmp_path))
    monkeypatch.setattr(config, "ROUTINES_DB", str(tmp_path / "routines.db"))
    monkeypatch.setattr(db, "DB_PATH", config.ROUTINES_DB)
    db.setup_db()
    db._setup_pending_table()
    db.import_declared_routines([{"day": "Everyday", "time": "10:12",
                                 "event": "Home activity", "type": "daily"}])
    rid = db.get_routines_for_day("Tuesday")[0]["id"]
    db.set_routine_condition(rid, condition_type="context_flag",
        condition_payload='{"flag":"user_out_of_home","equals":true}', condition_mode="suppress_when_true")
    state = {"evidence": {"user_out_of_home": ContextEvidence(reason="stale")},
             "channel": "matrix", "now": NOW, "gate": False, "failed": False}
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return state["now"] if tz else state["now"].replace(tzinfo=None)
    monkeypatch.setattr(worker, "datetime", Clock)
    monkeypatch.setattr(db, "datetime", Clock)
    monkeypatch.setattr(worker, "clarification_unavailable", lambda: state["gate"])
    monkeypatch.setattr(context, "build_routine_context_evidence", lambda *a, **k: state["evidence"])
    monkeypatch.setattr(context, "build_runtime_routine_context", lambda *a, **k: {"current_shift": "afternoon"})
    monkeypatch.setattr(bot, "is_duplicate_routine", lambda *a: False)
    monkeypatch.setattr(bot, "can_send_proactive", lambda: True)
    monkeypatch.setattr(messaging_channel, "resolve_external_channel", lambda: state["channel"])
    history_path = str(tmp_path / "history.db")
    history_append = history.append_message
    history_cursor = history.get_max_rowid
    monkeypatch.setattr(history, "append_message", lambda **kw: history_append(db_path=history_path, **kw))
    monkeypatch.setattr(history, "get_max_rowid", lambda: history_cursor(db_path=history_path))
    calls, packets = [], []
    def classify(packet, *, dependencies=False):
        packets.append(packet)
        assert not dependencies  # Explicit condition needs no semantic fallback.
        return {"routine_ids": [str(rid)], "flags": ["user_out_of_home"], "question": "Home now?"}
    monkeypatch.setattr(worker, "classify_packet", classify)
    def send(text, *, transaction_id=None):
        calls.append((text, transaction_id))
        if state["failed"]:
            raise RuntimeError("uncertain transport")
        return DeliveryReceipt(state["channel"], "$q")
    monkeypatch.setattr(router, "send_idempotent_matrix_text", send)
    monkeypatch.setattr(router, "send_text_to", lambda channel, text: send(text))
    return worker, db, rid, state, calls, packets, history_path, tmp_path


@pytest.mark.parametrize("channel", ["matrix", "telegram"])
def test_worker_dispatches_one_question_and_one_shared_history_entry(environment, channel):
    from memory.conversation_history import load_messages
    worker, _, rid, state, calls, packets, history_path, root = environment
    state["channel"] = channel
    worker.run_context_clarification_job()
    worker.run_context_clarification_job()
    assert len(calls) == len(packets) == 1
    assert len(load_messages(db_path=history_path)) == 1
    store = ClarificationStore(root / "astakos_routine_context_questions.json")
    assert store.snapshot()["pending"]["routine_ids"] == [str(rid)]
    assert store.snapshot()["pending"]["history_recorded"]


@pytest.mark.parametrize("block", ["paused", "muted", "outside_window", "known_false_condition", "quiet"])
def test_real_candidate_filter_never_asks_for_ineligible_routine(environment, block):
    worker, db, rid, state, calls, packets, _, _ = environment
    if block == "paused": db.pause_routine_indefinitely(rid)
    if block == "muted": db.set_routine_muted_until(rid, "2099-01-01")
    if block == "outside_window": state["now"] = NOW - timedelta(minutes=20)
    if block == "known_false_condition":
        state["evidence"] = {"user_out_of_home": ContextEvidence(effective_value=True, status="known")}
    if block == "quiet": state["gate"] = "quiet"
    worker.run_context_clarification_job()
    assert not calls and not packets


@pytest.mark.parametrize("channel", ["matrix", "telegram"])
def test_worker_retry_preserves_identity_and_holds_uncertain_telegram(environment, channel):
    from memory.conversation_history import load_messages
    worker, _, _, state, calls, _, history_path, _ = environment
    state.update(channel=channel, failed=True)
    worker.run_context_clarification_job()
    state["failed"] = False
    worker.run_context_clarification_job()
    if channel == "matrix":
        assert len(calls) == 2 and calls[0][1] == calls[1][1]
        assert len(load_messages(db_path=history_path)) == 1
    else:
        assert len(calls) == 1 and not load_messages(db_path=history_path)


@pytest.mark.parametrize("history_failure", [False, True])
@pytest.mark.parametrize("resolution", ["answer", "evidence"])
def test_web_answer_persists_then_normal_scheduler_sends_once(environment, monkeypatch, history_failure, resolution):
    """The real ledger/writer/scheduler lifecycle resumes only a timely slot."""
    from clients import telegram_bot as bot
    from services import context_extractor as extractor
    from services.routine_context_clarification import process_question_answer
    from services.routine_context_evidence import evaluate_stored_evidence
    worker, db, rid, state, calls, _, history_path, root = environment
    # Canonical set_context_state timestamps use the local wall clock internally.
    # Use that clock for this persisted end-to-end path; separate tests freeze
    # deadline/expiry boundaries without substituting the database writer.
    state["now"] = datetime.now(ATHENS)
    db.update_routine_db(rid, new_time=(state["now"] + timedelta(minutes=12)).strftime("%H:%M"))
    worker.run_context_clarification_job()
    # Simulate the reply arriving with less than one periodic interval left.
    state["now"] = state["now"].replace(second=45, microsecond=0) + timedelta(minutes=11)
    before_answer = state["now"]
    monkeypatch.setattr(extractor, "datetime", db.datetime)
    monkeypatch.setattr(extractor, "safe_gemini_call", lambda _: '{"relation":"related","flags":{"user_out_of_home":false}}')
    monkeypatch.setattr(extractor, "_recent_user_context_hint", lambda _: "")
    if resolution == "answer":
        answer = process_question_answer(store=ClarificationStore(root / "astakos_routine_context_questions.json"),
            user_text="Ναι, γύρισα σπίτι", channel="web", now=state["now"], trusted_owner=True)
        assert answer.consumed and answer.outcome == "resolved"
    else:
        # New canonical evidence arrives after the periodic tick held the question.
        db.set_context_state("user_out_of_home", "false")
    stored = db.get_context_state("user_out_of_home")
    assert stored["value"] == "false"
    state["now"] = before_answer
    state["evidence"] = {"user_out_of_home": evaluate_stored_evidence(stored, now=state["now"])}
    if resolution == "evidence":
        worker.run_context_clarification_job()
        ledger = ClarificationStore(root / "astakos_routine_context_questions.json")
        assert ledger.snapshot()["pending"] is None
        assert ledger.snapshot()["requests"][0]["status"] == "resolved"
    monkeypatch.setattr(bot, "datetime", db.datetime)
    monkeypatch.setattr(bot, "is_quiet_hours", lambda: False)
    monkeypatch.setattr(bot, "is_proactive_muted", lambda: False)
    monkeypatch.setattr(bot, "_active_routine_pause_until", lambda: None)
    monkeypatch.setattr(bot, "pending_routine_confirmations", {})
    monkeypatch.setattr(bot, "_external_background_runtime_channel", "matrix")
    monkeypatch.setattr(worker, "schedule_context_clarification", lambda _: None)
    monkeypatch.setattr(bot, "_craft_proactive_msg", lambda *a, **k: ("Timely reminder", False))
    notifications = []
    if history_failure:
        from memory import conversation_history as history
        from services.external_delivery import DeliveryReceipt, external_delivery_router as router
        repairs = []
        monkeypatch.setattr(bot, "enqueue_fast_task", lambda *args: repairs.append(args))
        monkeypatch.setattr(router, "send_text", lambda text, **k: (
            notifications.append(text) or DeliveryReceipt("matrix", "$routine")))
        monkeypatch.setattr(history, "append_message", lambda **k: (_ for _ in ()).throw(OSError("history unavailable")))
    else:
        monkeypatch.setattr(bot, "_send_and_record_assistant", lambda text, **k: notifications.append(text) or "$routine")
    assert worker.drain_context_answer_dispatch()
    assert not worker.drain_context_answer_dispatch()
    bot.job_check_routines()
    assert notifications == ["Timely reminder"] and len(calls) == 1
    assert str(rid) in {str(key) for key in db.load_pending_confirmations()}
    if history_failure:
        assert len(repairs) == 1


@pytest.mark.parametrize("change", ["complete", "skip", "pause", "reschedule"])
def test_dispatch_rejects_routine_changed_during_generation(environment, monkeypatch, change):
    """The canonical eligibility reader excludes a now-obsolete reminder."""
    from clients import telegram_bot as bot
    from services.routine_context_clarification import RoutineCandidate
    worker, db, rid, state, _, _, _, root = environment
    monkeypatch.setattr(bot, "is_quiet_hours", lambda: False)
    monkeypatch.setattr(bot, "is_proactive_muted", lambda: False)
    monkeypatch.setattr(bot, "_active_routine_pause_until", lambda: None)
    state["evidence"] = {"user_out_of_home": ContextEvidence(effective_value=False, status="known")}
    snapshot = worker.load_poll_snapshot(NOW, ClarificationStore(root / "state.json"))
    candidate = snapshot.candidates[0]
    if change == "complete":
        db.mark_routine_triggered_today(rid)
    elif change == "skip":
        db.record_routine_skip_today(rid)
    elif change == "pause":
        db.pause_routine_indefinitely(rid)
    else:
        db.update_routine_db(rid, new_time="11:00")
    assert not worker.dispatch_context_current((candidate,), snapshot.runtime_context,
                                               ClarificationStore(root / "state.json"), NOW)
