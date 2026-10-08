"""Offline production-worker wiring with real temporary routine/history stores."""
from datetime import datetime, timedelta
import socket

import pytest

from memory.routine_context_clarification import ATHENS, ClarificationStore
from services.routine_context_evidence import ContextEvidence

NOW = datetime(2026, 10, 6, 10, tzinfo=ATHENS)


def test_today_completion_keeps_tomorrows_midnight_candidate(environment):
    """A daily routine has independent occurrences on either side of midnight."""
    from memory.routine_feedback import RoutineFeedbackStore
    worker, db, rid, state, _, _, _, root = environment
    state["now"] = NOW.replace(hour=23, minute=50)
    db.update_routine_db(rid, new_time="00:02")
    ledger = RoutineFeedbackStore(db.get_connection)
    ledger.initialize()
    ledger.record_feedback(rid, NOW.date(), "complete", at=state["now"])
    candidates = worker.load_poll_snapshot(state["now"], ClarificationStore(root / "state.json")).candidates
    assert len(candidates) == 1
    assert candidates[0].slot_at.date() == (NOW + timedelta(days=1)).date()


@pytest.mark.parametrize("feedback", ["complete", "skip_today", "defer", "acknowledge"])
def test_dated_feedback_filters_context_questions_before_generation(environment, feedback):
    """An already cleaned rabbit needs no location question for that day's slot."""
    from memory.routine_feedback import RoutineFeedbackStore
    worker, db, rid, _, sends, _, _, root = environment
    ledger = RoutineFeedbackStore(db.get_connection)
    ledger.initialize()
    ledger.record_feedback(rid, NOW.date(), feedback, at=NOW - timedelta(minutes=25))
    candidates = worker.load_poll_snapshot(NOW, ClarificationStore(root / "state.json")).candidates
    assert bool(candidates) is (feedback == "acknowledge")
    worker.run_context_clarification_job()
    assert bool(sends) is (feedback == "acknowledge")


@pytest.mark.parametrize("other_day", [False, True])
def test_completed_routine_closes_only_its_current_question_even_during_activity(environment, monkeypatch, other_day):
    """Completion retires an obsolete question, without inventing location evidence."""
    from memory.routine_feedback import RoutineFeedbackStore
    worker, db, rid, state, sends, _, _, root = environment
    ledger = RoutineFeedbackStore(db.get_connection)
    ledger.initialize()
    worker.run_context_clarification_job()
    questions = ClarificationStore(root / "astakos_routine_context_questions.json")
    assert questions.snapshot()["pending"] is not None
    at = NOW - timedelta(days=1) if other_day else NOW + timedelta(seconds=1)
    ledger.record_feedback(rid, at.date(), "complete", at=at)
    state["now"] = NOW + timedelta(minutes=1)
    monkeypatch.setattr(worker, "clarification_unavailable", lambda: "recent_activity")
    worker.run_context_clarification_job()
    assert (questions.snapshot()["pending"] is not None) is other_day
    assert len(sends) == 1
    assert state["evidence"]["user_out_of_home"].effective_value is None


def test_completion_during_question_generation_prevents_stale_delivery(environment, monkeypatch):
    """A different channel can finish the routine while the wording model is busy."""
    from memory.routine_feedback import RoutineFeedbackStore
    worker, db, rid, _, sends, _, _, root = environment
    ledger = RoutineFeedbackStore(db.get_connection)
    ledger.initialize()

    def classify(packet, **kwargs):
        """Simulate a committed owner completion at the inference boundary."""
        ledger.record_feedback(rid, NOW.date(), "complete", at=NOW)
        return {"routine_ids": [str(rid)], "flags": ["user_out_of_home"], "question": "Home now?"}

    monkeypatch.setattr(worker, "classify_packet", classify)
    worker.run_context_clarification_job()
    assert not sends
    assert ClarificationStore(root / "astakos_routine_context_questions.json").snapshot()["pending"] is None


@pytest.mark.parametrize("installed", [
    "_dated_routine_feedback_tick", "_dated_single_routine_sender",
    "_dated_deferred_routine_sender", "_dated_batch_routine_sender",
    "_persisted_routine_feedback_handler",
])
def test_partial_dated_wiring_cannot_fall_back_to_legacy_pressure(environment, monkeypatch, installed):
    """Missing cleanup wiring must retain pending state, not write legacy penalties."""
    from clients import telegram_bot as bot
    _, db, rid, _, _, _, _, _ = environment
    offered = NOW - timedelta(minutes=31)
    db.save_pending_confirmation(rid, "Home activity", offered)
    db.transition_routine(rid, db.RoutineState.TRIGGER_PENDING)
    for name in (
        "_dated_routine_feedback_tick", "_dated_single_routine_sender",
        "_dated_deferred_routine_sender", "_dated_batch_routine_sender",
        "_persisted_routine_feedback_handler", "_dated_pending_expiry_handler",
    ):
        monkeypatch.setattr(bot, name, None)
    monkeypatch.setattr(bot, installed, object())
    before = db.get_routine_notify_info(rid)
    result = bot._expire_pending_routine_response(rid, sent_at=offered, now=NOW)
    assert result is None
    assert db.get_routine_notify_info(rid) == before
    assert rid in db.load_pending_confirmations()


def test_unconfigured_dated_flow_preserves_legacy_expiry(environment, monkeypatch):
    """The default inactive rollout must not disable the existing expiry policy."""
    from clients import telegram_bot as bot
    _, db, rid, _, _, _, _, _ = environment
    for name in (
        "_dated_routine_feedback_tick", "_dated_single_routine_sender",
        "_dated_deferred_routine_sender", "_dated_batch_routine_sender",
        "_persisted_routine_feedback_handler", "_dated_pending_expiry_handler",
    ):
        monkeypatch.setattr(bot, name, None)
    calls = []
    result = {"confidence_reduced": False}
    def legacy(routine_id):
        calls.append(routine_id)
        return result
    monkeypatch.setattr(db, "record_unanswered_routine_expiry", legacy)
    assert bot._expire_pending_routine_response(
        rid, sent_at=NOW - timedelta(minutes=31), now=NOW) is result
    assert calls == [rid]


@pytest.mark.parametrize("quiet", [False, True])
@pytest.mark.parametrize("failure", [False, True])
def test_dated_response_window_expiry_never_calls_legacy_decay(environment, monkeypatch, quiet, failure):
    """Both scheduler expiry branches retain daily evidence and retry failed cleanup."""
    import sqlite3
    from clients import telegram_bot as bot
    from memory.routine_feedback import RoutineFeedbackStore
    _, db, rid, state, _, _, _, _ = environment
    offered = NOW - timedelta(minutes=31)
    store = RoutineFeedbackStore(lambda: sqlite3.connect(db.DB_PATH))
    store.initialize()
    store.record_delivery(rid, offered.date(), at=offered, receipt_id="draft-offer")
    db.save_pending_confirmation(rid, "Home activity", offered, draft_offer=True)
    with store.connection_factory() as connection:
        connection.execute("UPDATE routines SET state='trigger_pending' WHERE id=?", (rid,))
        if failure:
            connection.execute("""CREATE TRIGGER reject_window_cleanup BEFORE DELETE ON pending_confirmations
                BEGIN SELECT RAISE(ABORT, 'offline cleanup'); END""")
    monkeypatch.setattr(bot, "datetime", db.datetime)
    monkeypatch.setattr(bot, "pending_routine_confirmations", {
        rid: {"event": "Home activity", "sent_at": offered, "draft_offer": True}})
    monkeypatch.setattr(bot, "_dated_pending_expiry_handler", store.close_response_window)
    monkeypatch.setattr(bot, "is_quiet_hours", lambda: quiet)
    monkeypatch.setattr(bot, "is_proactive_muted", lambda: False)
    monkeypatch.setattr(bot, "can_send_proactive", lambda: False)
    def forbidden(*args, **kwargs):
        pytest.fail("30-minute expiry must not mutate old pressure/confidence")
    monkeypatch.setattr(db, "record_unanswered_routine_expiry", forbidden)
    before = db.get_routine_notify_info(rid)
    bot.job_check_routines()
    assert (rid in bot.pending_routine_confirmations) == failure
    with store.connection_factory() as connection:
        assert bool(connection.execute("SELECT 1 FROM pending_confirmations WHERE routine_id=?", (rid,)).fetchone()) == failure
        assert connection.execute("SELECT state FROM routines WHERE id=?", (rid,)).fetchone()[0] == (
            "trigger_pending" if failure else "active")
    assert db.get_routine_notify_info(rid) == before
    row = store.occurrences(rid)[0]
    assert row.feedback is None and row.delivered_at == offered


@pytest.mark.parametrize("minutes,replaced,expected", [(30, False, False), (31, True, False), (31, False, True)])
def test_response_window_cleanup_requires_exact_expired_offer(environment, minutes, replaced, expected):
    """Cleanup cannot consume a newer offer or invent delivery evidence."""
    import sqlite3
    from memory.routine_feedback import RoutineFeedbackStore
    _, db, rid, _, _, _, _, _ = environment
    offered = (NOW - timedelta(minutes=minutes)).replace(tzinfo=None)
    stored = offered + timedelta(minutes=1) if replaced else offered
    store = RoutineFeedbackStore(lambda: sqlite3.connect(db.DB_PATH))
    store.initialize()
    db.save_pending_confirmation(rid, "Home activity", stored, draft_offer=True)
    with store.connection_factory() as connection:
        connection.execute("UPDATE routines SET state='trigger_pending' WHERE id=?", (rid,))
    before = db.get_routine_notify_info(rid)
    assert store.close_response_window(rid, sent_at=offered, now=NOW) is expected
    assert store.occurrences(rid) == []
    assert db.get_routine_notify_info(rid) == before
    with store.connection_factory() as connection:
        assert bool(connection.execute("SELECT 1 FROM pending_confirmations WHERE routine_id=?", (rid,)).fetchone()) is not expected


@pytest.fixture
def environment(monkeypatch, tmp_path, request):
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
    declared = [{"day": "Everyday", "time": "10:12", "event": "Home activity", "type": "daily"}]
    if getattr(request.node, "callspec", None) and request.node.callspec.params.get("batch"):
        declared.append({"day": "Everyday", "time": "10:12", "event": "School preparation", "type": "daily"})
    db.import_declared_routines(declared)
    rid = db.get_routines_for_day("Tuesday")[0]["id"]
    for routine in db.get_routines_for_day("Tuesday"):
        db.set_routine_condition(routine["id"], condition_type="context_flag",
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
@pytest.mark.parametrize("failure", [None, "pending", "transport", "late_repair"])
def test_dated_draft_offer_retains_receipt_and_separate_pending_window(environment, channel, failure):
    """Draft offers recover receipt and authorization context without another send."""
    import sqlite3
    from memory.routine_feedback import RoutineFeedbackStore
    from services.routine_feedback_dispatch import DatedRoutineSender, repair_staged_deliveries
    from services.external_delivery import DeliveryReceipt
    _, db, rid, state, _, _, _, _ = environment
    store = RoutineFeedbackStore(lambda: sqlite3.connect(db.DB_PATH))
    store.initialize()
    if failure in ("pending", "late_repair"):
        with store.connection_factory() as connection:
            connection.execute("""CREATE TRIGGER reject_offer BEFORE INSERT ON pending_confirmations
                BEGIN SELECT RAISE(ABORT, 'offline pending failure'); END""")
    calls = []
    def deliver(text):
        calls.append(text)
        if failure == "transport":
            raise TimeoutError("unknown delivery")
        return DeliveryReceipt(channel, "$draft-offer")
    sender = DatedRoutineSender(store, lambda: state["now"], deliver)
    result = sender.send(routine_id=rid, occurrence_date=NOW.date(), text="Prepare a local draft?",
        expected_revision=sender.revision(rid), eligible=lambda: True, draft_event="Home activity")
    assert result.status == {None: "sent", "pending": "recording_pending",
                             "transport": "uncertain", "late_repair": "recording_pending"}[failure]
    if failure in ("pending", "late_repair"):
        assert store.occurrences(rid)[0].delivered_at is None
        assert not db.load_pending_confirmations()
        reopened = RoutineFeedbackStore(store.connection_factory)
        assert reopened.pending_delivery_proofs()[0].draft_event == "Home activity"
        with store.connection_factory() as connection:
            connection.execute("DROP TRIGGER reject_offer")
        if failure == "late_repair":
            state["now"] += timedelta(minutes=31)
        assert repair_staged_deliveries(store=reopened, now=state["now"]) == 1
    pending = db.load_pending_confirmations()
    assert bool(pending) == (failure in (None, "pending"))
    if pending:
        assert pending[rid]["draft_offer"] is True and pending[rid]["sent_at"] == NOW
        assert db.get_routine_state(rid).value == "trigger_pending"
    row = store.occurrences(rid)[0]
    assert row.feedback is None
    assert (row.delivered_at is None) == (failure == "transport")
    assert store.pending_question(now=state["now"]) is None
    assert sender.send(routine_id=rid, occurrence_date=NOW.date(), text="Prepare a local draft?",
        expected_revision=sender.revision(rid), eligible=lambda: True,
        draft_event="Home activity").status == "blocked"
    assert calls == ["Prepare a local draft?"]


@pytest.mark.parametrize("channel", ["matrix", "telegram"])
@pytest.mark.parametrize("failure", [False, True])
def test_scheduler_routes_draft_offer_through_dated_delivery(environment, monkeypatch, channel, failure):
    """Real scheduler and canonical pending storage share one confirmed send."""
    import sqlite3
    from clients import telegram_bot as bot
    from memory.routine_feedback import RoutineFeedbackStore
    from services.routine_feedback_dispatch import DatedRoutineSender
    from services.external_delivery import DeliveryReceipt
    worker, db, rid, state, _, _, _, _ = environment
    state["channel"] = channel
    state["evidence"] = {"user_out_of_home": ContextEvidence(effective_value=False, status="known")}
    monkeypatch.setattr(bot, "datetime", db.datetime)
    monkeypatch.setattr(bot, "is_quiet_hours", lambda: False)
    monkeypatch.setattr(bot, "is_proactive_muted", lambda: False)
    monkeypatch.setattr(bot, "_active_routine_pause_until", lambda: None)
    monkeypatch.setattr(bot, "pending_routine_confirmations", {})
    monkeypatch.setattr(bot, "_external_background_runtime_channel", channel)
    monkeypatch.setattr(bot, "resolve_external_channel", lambda: state["channel"])
    monkeypatch.setattr(worker, "schedule_context_clarification", lambda _: None)
    monkeypatch.setattr(bot, "_is_partner_messenger_routine", lambda _: True)
    monkeypatch.setattr(bot, "_craft_proactive_msg", lambda *a, **k: ("Prepare a local draft?", True))
    store = RoutineFeedbackStore(lambda: sqlite3.connect(db.DB_PATH))
    store.initialize()
    if failure:
        with store.connection_factory() as connection:
            connection.execute("""CREATE TRIGGER reject_offer BEFORE INSERT ON pending_confirmations
                BEGIN SELECT RAISE(ABORT, 'offline pending failure'); END""")
    calls, repairs = [], []
    def deliver(text):
        calls.append(text)
        return DeliveryReceipt(channel, "$scheduler-offer")
    monkeypatch.setattr(bot, "_dated_single_routine_sender", DatedRoutineSender(store, lambda: NOW, deliver))
    monkeypatch.setattr(bot, "enqueue_fast_task", lambda *args: repairs.append(args))
    monkeypatch.setattr(bot, "_send_and_record_assistant", lambda *a, **k: pytest.fail("legacy draft delivery"))
    bot.job_check_routines()
    assert calls == ["Prepare a local draft?"]
    if failure:
        assert not db.load_pending_confirmations()
        assert repairs and store.pending_delivery_proofs()
        with store.connection_factory() as connection:
            connection.execute("DROP TRIGGER reject_offer")
        assert repairs[0][0]()
    assert db.load_pending_confirmations()[rid]["draft_offer"] is True
    assert bot.pending_routine_confirmations[rid]["sent_at"] == NOW
    assert store.occurrences(rid)[0].delivered_at == NOW
    assert store.pending_question(now=NOW) is None
    bot.job_check_routines()
    assert calls == ["Prepare a local draft?"]


@pytest.mark.parametrize("change", ["complete", "newer_offer", "consumed"])
def test_draft_receipt_recovery_never_resurrects_old_offer(environment, change):
    """Delayed recording cannot replace new pending context or newer feedback."""
    import sqlite3
    from memory.routine_feedback import RoutineFeedbackStore
    from services.routine_feedback_dispatch import DatedRoutineSender, repair_staged_deliveries
    from services.external_delivery import DeliveryReceipt
    _, db, rid, state, _, _, _, _ = environment
    store = RoutineFeedbackStore(lambda: sqlite3.connect(db.DB_PATH))
    store.initialize()
    with store.connection_factory() as connection:
        connection.execute("""CREATE TRIGGER reject_offer BEFORE INSERT ON pending_confirmations
            BEGIN SELECT RAISE(ABORT, 'offline pending failure'); END""")
    sender = DatedRoutineSender(store, lambda: state["now"], lambda _: DeliveryReceipt("matrix", "$old"))
    result = sender.send(routine_id=rid, occurrence_date=NOW.date(), text="Prepare draft?",
        expected_revision=sender.revision(rid), eligible=lambda: True, draft_event="Home activity")
    assert result.status == "recording_pending"
    with store.connection_factory() as connection:
        connection.execute("DROP TRIGGER reject_offer")
    state["now"] += timedelta(minutes=1)
    if change == "newer_offer":
        db.mark_routine_notified(rid)
        db.save_pending_confirmation(rid, "Home activity", state["now"], draft_offer=True)
    else:
        store.record_feedback(rid, NOW.date(), "complete" if change == "complete" else "acknowledge", at=state["now"])
    assert repair_staged_deliveries(store=store, now=state["now"]) == 1
    pending = db.load_pending_confirmations()
    if change == "newer_offer":
        assert pending[rid]["sent_at"] == state["now"]
    else:
        assert not pending
    row = store.occurrences(rid)[0]
    assert row.delivered_at == NOW
    assert row.feedback == {"complete": "complete", "consumed": "acknowledge", "newer_offer": None}[change]


def test_draft_offer_history_repair_preserves_separate_scope(environment):
    """Restart history repair retains draft identity without becoming a completion question."""
    import sqlite3
    from memory.routine_feedback import RoutineFeedbackStore
    from services.routine_feedback_dispatch import DatedRoutineSender, repair_pending_history
    from services.external_assistant_delivery import AssistantHistoryError
    from services.external_delivery import DeliveryReceipt
    from memory.conversation_history import append_message, load_messages
    _, db, rid, _, _, _, history_path, _ = environment
    store = RoutineFeedbackStore(lambda: sqlite3.connect(db.DB_PATH))
    store.initialize()
    def deliver(text):
        raise AssistantHistoryError(DeliveryReceipt("matrix", "$history-offer"), lambda: None)
    sender = DatedRoutineSender(store, lambda: NOW, deliver)
    result = sender.send(routine_id=rid, occurrence_date=NOW.date(), text="Prepare draft?",
        expected_revision=sender.revision(rid), eligible=lambda: True, draft_event="Home activity")
    assert result.status == "sent" and result.history_repair is not None
    reopened = RoutineFeedbackStore(store.connection_factory)
    assert reopened.pending_history_repairs()[0].proof.draft_event == "Home activity"
    assert repair_pending_history(store=reopened, record=append_message) == 1
    assert repair_pending_history(store=reopened, record=append_message) == 0
    assert len(load_messages(db_path=history_path)) == 1
    assert reopened.pending_question(now=NOW) is None
    assert db.load_pending_confirmations()[rid]["draft_offer"] is True


def test_scheduler_reload_observes_draft_window_repaired_after_restart(environment, monkeypatch):
    """The existing tick sees canonical repair even if startup loaded no pending offer."""
    import sqlite3
    from clients import telegram_bot as bot
    from memory.routine_feedback import RoutineFeedbackStore, PendingDeliveryProof
    from services.routine_feedback_dispatch import repair_staged_deliveries
    _, db, rid, _, _, _, _, _ = environment
    store = RoutineFeedbackStore(lambda: sqlite3.connect(db.DB_PATH))
    store.initialize()
    assert store.claim_dispatch(rid, NOW.date(), at=NOW, expected_revision=store.revision(rid), is_eligible=lambda: True)
    assert store.stage_delivery(PendingDeliveryProof(rid, NOW.date(), NOW, "$restarted", "matrix", None, "Home activity"))
    monkeypatch.setattr(bot, "datetime", db.datetime)
    monkeypatch.setattr(bot, "pending_routine_confirmations", {})
    monkeypatch.setattr(bot, "_dated_pending_expiry_handler", store.close_response_window)
    def maintenance(now):
        repair_staged_deliveries(store=store, now=now)
        return True
    monkeypatch.setattr(bot, "_dated_routine_feedback_tick", maintenance)
    monkeypatch.setattr(bot, "is_quiet_hours", lambda: True)
    monkeypatch.setattr(bot, "is_proactive_muted", lambda: False)
    monkeypatch.setattr(bot, "can_send_proactive", lambda: False)
    bot.job_check_routines()
    assert bot.pending_routine_confirmations[rid]["sent_at"] == NOW
    assert store.occurrences(rid)[0].delivered_at == NOW


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


@pytest.mark.parametrize("channel", ["matrix", "telegram"])
@pytest.mark.parametrize("failure", [None, "history", "transport", "ledger"])
@pytest.mark.parametrize("batch", [False, True])
def test_scheduler_uses_real_dated_receipt_without_legacy_timeout(
        environment, monkeypatch, channel, failure, batch):
    """Exercise scheduler, transport boundary and persisted occurrence together."""
    import sqlite3
    from clients import telegram_bot as bot
    from memory import conversation_history as history
    from memory.routine_feedback import RoutineFeedbackStore
    from services.routine_feedback_dispatch import DatedRoutineSender
    from services.external_assistant_delivery import deliver_external_assistant_text
    from services.external_delivery import DeliveryReceipt, external_delivery_router as router
    worker, db, rid, state, _, _, history_path, root = environment
    state["channel"] = channel
    state["evidence"] = {"user_out_of_home": ContextEvidence(effective_value=False, status="known")}
    monkeypatch.setattr(bot, "datetime", db.datetime)
    monkeypatch.setattr(bot, "is_quiet_hours", lambda: False)
    monkeypatch.setattr(bot, "is_proactive_muted", lambda: False)
    monkeypatch.setattr(bot, "_active_routine_pause_until", lambda: None)
    monkeypatch.setattr(bot, "pending_routine_confirmations", {})
    monkeypatch.setattr(bot, "_external_background_runtime_channel", channel)
    monkeypatch.setattr(bot, "resolve_external_channel", lambda: state["channel"])
    monkeypatch.setattr(worker, "schedule_context_clarification", lambda _: None)
    monkeypatch.setattr(bot, "_craft_proactive_msg", lambda *a, **k: ("Dated reminder", False))
    store = RoutineFeedbackStore(lambda: sqlite3.connect(db.DB_PATH))
    store.initialize()
    if failure == "ledger":
        # Force the actual projection transaction to abort after proof staging.
        with sqlite3.connect(db.DB_PATH) as connection:
            connection.execute("""CREATE TRIGGER reject_dated_delivery BEFORE UPDATE OF delivered_at
                ON routine_occurrences WHEN NEW.delivered_at IS NOT NULL
                BEGIN SELECT RAISE(ABORT, 'offline receipt failure'); END""")
    calls, repairs = [], []
    def send(text, **kwargs):
        calls.append(text)
        if failure == "transport":
            raise TimeoutError("unknown delivery")
        return DeliveryReceipt(channel, "$dated")
    monkeypatch.setattr(router, "send_text", send)
    monkeypatch.setattr(bot, "enqueue_fast_task", lambda *args: repairs.append(args))
    if failure == "history":
        monkeypatch.setattr(history, "append_message", lambda **kw: (_ for _ in ()).throw(OSError("history offline")))
    sender = DatedRoutineSender(store=store, now=lambda: state["now"],
        deliver=lambda text: deliver_external_assistant_text(text, agent="Routine_Agent"))
    monkeypatch.setattr(bot, "_dated_batch_routine_sender" if batch else "_dated_single_routine_sender", sender)
    bot.job_check_routines()
    bot.job_check_routines()
    assert calls == ["Dated reminder"]
    rows = store.occurrences(rid)
    assert len(rows) == 1
    assert (rows[0].delivered_at is None) == (failure in ("transport", "ledger"))
    assert not bot.pending_routine_confirmations and not db.load_pending_confirmations()
    if batch:
        ids = tuple(sorted(item["id"] for item in db.get_routines_for_day("Tuesday")))
        assert len(ids) == 2
        assert all(len(store.occurrences(member)) == 1 for member in ids)
    if failure != "transport" and failure != "ledger":
        question = store.pending_question(now=state["now"], reply_channel=channel, reply_event_id="$dated")
        assert question is not None and question.occurrence_date == state["now"].date()
        if batch:
            assert question.routine_ids == ids
    if failure == "history":
        assert len(store.pending_history_repairs()) == (2 if batch else 1)
        assert len(repairs) == 1
    elif failure == "ledger":
        assert len(store.pending_delivery_proofs()) == (2 if batch else 1)
        assert len(repairs) == 1
        with sqlite3.connect(db.DB_PATH) as connection:
            connection.execute("DROP TRIGGER reject_dated_delivery")
        assert repairs[0][0]()
        assert store.occurrences(rid)[0].delivered_at == state["now"]
        assert not store.pending_delivery_proofs()
        bot.job_check_routines()
        assert calls == ["Dated reminder"]
    elif failure is None:
        assert len(history.load_messages(db_path=history_path)) == 1
    # Dated receipts own daily deduplication, not the legacy inactive lifecycle.
    assert db.get_routine_state(rid).value == "active"
    if batch:
        assert all(db.get_routine_state(member).value == "active" for member in ids)


@pytest.mark.parametrize("change", ["completion", "channel", "ledger_feedback"])
@pytest.mark.parametrize("batch", [False, True])
def test_dated_scheduler_rechecks_changes_during_generation(environment, monkeypatch, change, batch):
    """No transport for obsolete completion or switched selected channel."""
    import sqlite3
    from clients import telegram_bot as bot
    from memory.routine_feedback import RoutineFeedbackStore
    from services.routine_feedback_dispatch import DatedRoutineSender
    worker, db, rid, state, _, _, _, _ = environment
    state["evidence"] = {"user_out_of_home": ContextEvidence(effective_value=False, status="known")}
    monkeypatch.setattr(bot, "datetime", db.datetime)
    monkeypatch.setattr(bot, "is_quiet_hours", lambda: False)
    monkeypatch.setattr(bot, "is_proactive_muted", lambda: False)
    monkeypatch.setattr(bot, "_active_routine_pause_until", lambda: None)
    monkeypatch.setattr(bot, "pending_routine_confirmations", {})
    monkeypatch.setattr(bot, "_external_background_runtime_channel", None)
    monkeypatch.setattr(bot, "resolve_external_channel", lambda: state["channel"])
    monkeypatch.setattr(worker, "schedule_context_clarification", lambda _: None)
    store = RoutineFeedbackStore(lambda: sqlite3.connect(db.DB_PATH))
    store.initialize()
    def craft(*args, **kwargs):
        if change == "completion":
            db.mark_routine_triggered_today(rid)
        elif change == "ledger_feedback":
            # Acknowledgement leaves canonical schedule eligibility unchanged;
            # only the pre-inference ledger revision detects this new evidence.
            store.record_feedback(rid, NOW.date(), "acknowledge", at=NOW)
        else:
            state["channel"] = "telegram"
        return "Obsolete reminder", False
    monkeypatch.setattr(bot, "_craft_proactive_msg", craft)
    def forbidden(text):
        pytest.fail("obsolete reminder reached transport")
    monkeypatch.setattr(bot, "_dated_batch_routine_sender" if batch else "_dated_single_routine_sender", DatedRoutineSender(
        store=store, now=lambda: state["now"], deliver=forbidden))
    bot.job_check_routines()
    assert len(store.occurrences(rid)) == (1 if change == "ledger_feedback" else 0)
    assert all(row.delivered_at is None for row in store.occurrences(rid))
    if batch:
        assert all(not store.occurrences(item["id"])
                   for item in db.get_routines_for_day("Tuesday") if item["id"] != rid)


@pytest.mark.parametrize("channel", ["matrix", "telegram"])
@pytest.mark.parametrize("scenario", ["sent", "history", "ledger", "transport",
                                     "completed", "expired", "context", "channel"])
def test_restart_followup_uses_dated_delivery_and_fresh_grace(environment, monkeypatch, channel, scenario):
    """Real missed-slot lifecycle shares confirmed proof and rejects obsolete generation."""
    import sqlite3
    import config
    from clients import telegram_bot as bot
    from memory import conversation_history as history
    from memory.routine_feedback import RoutineFeedbackStore
    from services.routine_feedback_dispatch import DatedRoutineSender
    from services.external_assistant_delivery import deliver_external_assistant_text
    from services.external_delivery import DeliveryReceipt, external_delivery_router as router
    _, db, rid, state, _, _, history_path, _ = environment
    db.update_routine_db(rid, new_time="09:55")
    state.update(channel=channel, evidence={"user_out_of_home": ContextEvidence(effective_value=False, status="known")})
    monkeypatch.setattr(config, "ROUTINE_MISS_GRACE_MINUTES", 15)
    monkeypatch.setattr(bot, "datetime", db.datetime)
    monkeypatch.setattr(bot, "is_quiet_hours", lambda: False)
    monkeypatch.setattr(bot, "is_proactive_muted", lambda: False)
    monkeypatch.setattr(bot, "is_routines_paused", lambda: False)
    monkeypatch.setattr(bot, "_active_routine_pause_until", lambda: None)
    monkeypatch.setattr(bot, "pending_routine_confirmations", {})
    monkeypatch.setattr(bot, "_external_background_runtime_channel", channel)
    monkeypatch.setattr(bot, "resolve_external_channel", lambda: state["channel"])
    store = RoutineFeedbackStore(lambda: sqlite3.connect(db.DB_PATH))
    store.initialize()
    if scenario == "ledger":
        with sqlite3.connect(db.DB_PATH) as connection:
            connection.execute("""CREATE TRIGGER reject_late_receipt BEFORE UPDATE OF delivered_at
                ON routine_occurrences WHEN NEW.delivered_at IS NOT NULL
                BEGIN SELECT RAISE(ABORT, 'offline projection'); END""")
    crafted = []
    def craft(*args):
        crafted.append(args)
        if scenario == "completed": db.mark_routine_triggered_today(rid)
        elif scenario == "expired": state["now"] += timedelta(minutes=16)
        elif scenario == "context":
            state["evidence"] = {"user_out_of_home": ContextEvidence(effective_value=True, status="known")}
        elif scenario == "channel": state["channel"] = "telegram" if channel == "matrix" else "matrix"
        return "Late reminder"
    monkeypatch.setattr(bot, "_craft_deferred_msg", craft)
    calls, repairs = [], []
    def send(text, **kwargs):
        calls.append(text)
        if scenario == "transport": raise TimeoutError("unknown send")
        return DeliveryReceipt(channel, "$late")
    monkeypatch.setattr(router, "send_text", send)
    monkeypatch.setattr(bot, "enqueue_fast_task", lambda *args: repairs.append(args))
    if scenario == "history":
        monkeypatch.setattr(history, "append_message", lambda **kw: (_ for _ in ()).throw(OSError("history offline")))
    monkeypatch.setattr(bot, "_dated_deferred_routine_sender", DatedRoutineSender(
        store, lambda: state["now"], lambda text: deliver_external_assistant_text(text, agent="Routine_Agent")))
    bot.startup_check_missed_routines()
    bot.startup_check_missed_routines()
    assert crafted
    blocked = scenario in {"completed", "expired", "context", "channel"}
    assert calls == ([] if blocked else ["Late reminder"])
    assert not bot.pending_routine_confirmations and not db.load_pending_confirmations()
    rows = store.occurrences(rid)
    assert len(rows) == (0 if blocked else 1)
    if not blocked:
        assert (rows[0].delivered_at is None) == (scenario in {"transport", "ledger"})
        assert len(repairs) == int(scenario in {"history", "ledger"})
    if scenario == "sent":
        assert len(history.load_messages(db_path=history_path)) == 1
        assert store.pending_question(now=state["now"]).event_id == "$late"
        assert db.get_routine_state(rid).value == "active"
