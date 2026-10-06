"""Durable answer correlation and canonical persistence with no live I/O."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from threading import Barrier
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from memory import routine_db
from memory.routine_context_clarification import ClarificationStore, QuestionRequest
from services import context_extractor
from services.routine_context_clarification import process_question_answer

NOW = datetime.now(ZoneInfo("Europe/Athens"))


@pytest.fixture
def delivered(tmp_path, monkeypatch):
    """Use genuine temporary ledgers/DBs and stub only the provider boundary."""
    import socket

    def forbidden(*args, **kwargs):
        raise AssertionError("Unexpected network or second semantic interpretation")

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(routine_db, "DB_PATH", str(tmp_path / "routines.db"))
    routine_db.setup_db()
    monkeypatch.setattr(context_extractor, "load_recent_trusted_user_messages", lambda **_: [])
    monkeypatch.setattr(context_extractor, "infer_routine_reconciliation_directives", forbidden)
    store = ClarificationStore(tmp_path / "astakos_routine_context_questions.json")
    request = QuestionRequest("q1", "presence", ("r1",), ("partner_with_user",),
                              NOW + timedelta(minutes=12), "Είναι μαζί σου τώρα;", "matrix")
    assert store.reserve(request, now=NOW)
    assert store.begin_send("q1", now=NOW)
    assert store.mark_sent("q1", external_id="$q1", now=NOW)
    assert store.mark_recorded("q1")
    monkeypatch.setattr(context_extractor, "safe_gemini_call", lambda _: SimpleNamespace(
        text='{"relation":"related","flags":{"partner_with_user":false}}'))
    return store


@pytest.mark.parametrize("channel", ["web", "telegram", "matrix"])
def test_owner_reply_resolves_once_across_channels(delivered, channel):
    result = process_question_answer(store=delivered, user_text="no", channel=channel,
                                     now=NOW + timedelta(seconds=1), trusted_owner=True)
    assert result.consumed and result.outcome == "resolved"
    assert routine_db.get_context_state("partner_with_user")["value"] == "false"
    assert delivered.snapshot()["requests"][0]["status"] == "resolved"
    second = process_question_answer(store=delivered, user_text="no", channel=channel,
                                     now=NOW + timedelta(seconds=2), trusted_owner=True)
    assert not second.consumed


@pytest.mark.parametrize("extra", [
    {"trusted_owner": False}, {"external_derived": True},
    {"competing_confirmation": True}, {"reply_to_id": "$another"},
])
def test_other_authority_cannot_resolve_question(delivered, monkeypatch, extra):
    def forbidden(*args, **kwargs):
        raise AssertionError("No model call for nonauthoritative reply")

    monkeypatch.setattr(context_extractor, "safe_gemini_call", forbidden)
    args = dict(store=delivered, user_text="ναι", channel="matrix",
                now=NOW + timedelta(seconds=1), trusted_owner=True)
    args.update(extra)
    result = process_question_answer(**args)
    assert not result.consumed
    assert delivered.snapshot()["pending"]["status"] == "sent"
    assert routine_db.get_context_state("partner_with_user") is None


def test_expiry_during_model_call_prevents_write(delivered, monkeypatch):
    clock = [NOW + timedelta(seconds=1)]

    def classify(_):
        clock[0] = NOW + timedelta(minutes=13)
        return SimpleNamespace(text='{"relation":"related","flags":{"partner_with_user":true}}')

    monkeypatch.setattr(context_extractor, "safe_gemini_call", classify)
    result = process_question_answer(store=delivered, user_text="ναι", channel="web",
                                     now=clock[0], current_time=lambda: clock[0], trusted_owner=True)
    assert result.outcome != "resolved"
    assert routine_db.get_context_state("partner_with_user") is None


def test_concurrent_replies_do_not_both_write(delivered, monkeypatch):
    barrier = Barrier(2)
    writes = []
    canonical = routine_db.set_context_state

    def classify(_):
        barrier.wait(timeout=5)
        return SimpleNamespace(text='{"relation":"related","flags":{"partner_with_user":false}}')

    def write(*args, **kwargs):
        writes.append(args)
        canonical(*args, **kwargs)

    monkeypatch.setattr(context_extractor, "safe_gemini_call", classify)
    monkeypatch.setattr(context_extractor, "set_context_state", write)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda channel: process_question_answer(
            store=delivered, user_text="no", channel=channel,
            now=NOW + timedelta(seconds=1), trusted_owner=True), ["web", "matrix"]))
    assert len(writes) == 1
    assert sum(result.outcome == "resolved" for result in results) == 1
    assert all(result.consumed for result in results)


@pytest.mark.parametrize("relation,status,consumed", [
    ("unrelated", "sent", False), ("uncertain", "sent", False),
    ("refused", "declined", True),
])
def test_nonanswer_lifecycle(delivered, monkeypatch, relation, status, consumed):
    monkeypatch.setattr(context_extractor, "safe_gemini_call", lambda _: SimpleNamespace(
        text='{"relation":"' + relation + '","flags":{}}'))
    result = process_question_answer(store=delivered, user_text="άστο", channel="web",
                                     now=NOW + timedelta(seconds=1), trusted_owner=True)
    assert result.consumed is consumed
    assert delivered.snapshot()["requests"][0]["status"] == status
    assert routine_db.get_context_state("partner_with_user") is None


def test_competing_confirmation_appears_during_classification(delivered, monkeypatch):
    authoritative = [True]

    def classify(_):
        authoritative[0] = False
        return SimpleNamespace(text='{"relation":"related","flags":{"partner_with_user":true}}')

    monkeypatch.setattr(context_extractor, "safe_gemini_call", classify)
    result = process_question_answer(
        store=delivered, user_text="ναι", channel="web", now=NOW + timedelta(seconds=1),
        trusted_owner=True, still_authoritative=lambda: authoritative[0],
    )
    assert result.consumed and result.outcome == "deferred"
    assert delivered.snapshot()["pending"]["status"] == "sent"
    assert routine_db.get_context_state("partner_with_user") is None


def test_model_failure_keeps_request_pending(delivered, monkeypatch):
    def fail(_):
        raise TimeoutError("model unavailable")

    monkeypatch.setattr(context_extractor, "safe_gemini_call", fail)
    result = process_question_answer(store=delivered, user_text="ναι", channel="web",
                                     now=NOW + timedelta(seconds=1), trusted_owner=True)
    assert result.outcome == "uncertain"
    assert delivered.snapshot()["pending"]["status"] == "sent"
    assert routine_db.get_context_state("partner_with_user") is None


def test_reply_before_delivery_is_not_correlated(delivered, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("A message predating delivery is not an answer")

    monkeypatch.setattr(context_extractor, "safe_gemini_call", forbidden)
    result = process_question_answer(store=delivered, user_text="ναι", channel="web",
                                     now=NOW - timedelta(seconds=1), trusted_owner=True)
    assert not result.consumed
    assert routine_db.get_context_state("partner_with_user") is None


def test_production_adapter_does_nothing_without_ledger(tmp_path, monkeypatch):
    import config
    from services import routine_context_clarification as clarification

    monkeypatch.setattr(config, "BASE_DIR", str(tmp_path))

    def forbidden(*args, **kwargs):
        raise AssertionError("No database or provider lookup without a question ledger")

    monkeypatch.setattr(clarification, "context_confirmation_conflict", forbidden)
    result = clarification.try_context_question_reply("ναι", "web", trusted_owner=True)
    assert not result.consumed
    assert not list(tmp_path.iterdir())


def test_production_adapter_resolves_real_temporary_ledger(delivered, monkeypatch):
    import config
    from services import routine_context_clarification as clarification

    monkeypatch.setattr(config, "BASE_DIR", str(delivered.path.parent))
    monkeypatch.setattr(clarification, "context_confirmation_conflict", lambda: False)
    result = clarification.try_context_question_reply("no", "web", trusted_owner=True)
    assert result.consumed and result.outcome == "resolved"
    assert delivered.snapshot()["requests"][0]["status"] == "resolved"
    assert routine_db.get_context_state("partner_with_user")["value"] == "false"


@pytest.mark.parametrize("change", ["context", "history", "gps"])
def test_production_reply_rejects_newer_evidence_during_inference(delivered, monkeypatch, change):
    """The old answer cannot overwrite a new canonical flag or GPS/history version."""
    import config
    from memory import conversation_history as history
    from services import routine_context_clarification as clarification
    from services import routine_context
    monkeypatch.setattr(config, "BASE_DIR", str(delivered.path.parent))
    monkeypatch.setattr(clarification, "context_confirmation_conflict", lambda: False)
    marker = [0]
    monkeypatch.setattr(history, "get_max_rowid", lambda: marker[0])
    evidence = [{}]
    monkeypatch.setattr(routine_context, "build_routine_context_evidence", lambda _: evidence[0])
    def classify(_):
        if change == "context":
            routine_db.set_context_state("partner_with_user", "true")
        elif change == "history":
            marker[0] += 1
        else:
            from services.routine_context_evidence import ContextEvidence
            evidence[0] = {"user_out_of_home": ContextEvidence(
                effective_value=False, source="gps", recorded_at=NOW)}
        return SimpleNamespace(text='{"relation":"related","flags":{"partner_with_user":false}}')
    monkeypatch.setattr(context_extractor, "safe_gemini_call", classify)
    result = clarification.try_context_question_reply("no", "web", trusted_owner=True)
    assert result.consumed and result.outcome == "deferred"
    assert delivered.snapshot()["pending"]["status"] == "sent"
    state = routine_db.get_context_state("partner_with_user")
    assert state is None if change != "context" else state["value"] == "true"


def test_resolution_durably_requests_one_timely_dispatch(delivered):
    """A final answer is a durable wakeup, not a wait for the next minute tick."""
    result = process_question_answer(store=delivered, user_text="no", channel="web",
                                    now=NOW + timedelta(seconds=1), trusted_owner=True)
    assert result.outcome == "resolved"
    reloaded = ClarificationStore(delivered.path)
    assert reloaded.claim_dispatch(now=NOW + timedelta(seconds=2))
    assert not reloaded.claim_dispatch(now=NOW + timedelta(seconds=3))


def test_dispatch_request_waits_for_selected_external_runtime(delivered, monkeypatch):
    """Web never dispatches locally; a busy external dispatcher keeps the wakeup."""
    import config
    import threading
    from clients import telegram_bot as bot
    from core import messaging_channel
    from services import routine_context_clarification_scheduler as worker
    process_question_answer(store=delivered, user_text="no", channel="web",
                            now=NOW + timedelta(seconds=1), trusted_owner=True)
    monkeypatch.setattr(config, "BASE_DIR", str(delivered.path.parent))
    monkeypatch.setattr(bot, "shutdown_event", threading.Event())
    monkeypatch.setattr(messaging_channel, "resolve_external_channel", lambda: "matrix")
    monkeypatch.setattr(bot, "_external_background_runtime_channel", None)
    calls = []
    monkeypatch.setattr(bot, "job_check_routines", lambda: calls.append("dispatch"))
    assert not worker.drain_context_answer_dispatch()
    assert delivered.snapshot()["requests"][0]["dispatch_pending"]
    monkeypatch.setattr(bot, "_external_background_runtime_channel", "matrix")
    entered, release = threading.Event(), threading.Event()
    def hold():
        with worker._dispatch_lock:
            entered.set()
            assert release.wait(5)
    thread = threading.Thread(target=hold)
    thread.start()
    assert entered.wait(5)
    try:
        assert not worker.drain_context_answer_dispatch()
        assert delivered.snapshot()["requests"][0]["dispatch_pending"]
    finally:
        release.set()
        thread.join(5)
    assert worker.drain_context_answer_dispatch()
    assert not worker.drain_context_answer_dispatch()
    assert calls == ["dispatch"]


def test_dispatch_request_never_replays_expired_slot(delivered):
    """A delayed worker consumes a wakeup without sending after its deadline."""
    process_question_answer(store=delivered, user_text="no", channel="web",
                            now=NOW + timedelta(seconds=1), trusted_owner=True)
    assert not delivered.claim_dispatch(now=NOW + timedelta(minutes=12))
    assert not delivered.snapshot()["requests"][0]["dispatch_pending"]
