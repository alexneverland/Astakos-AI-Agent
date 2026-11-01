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


@pytest.mark.parametrize("channel", ["web", "telegram", "matrix"])
def test_mixed_owner_reply_commits_all_current_facts_then_continues(delivered, monkeypatch, channel):
    """Closing the question keeps extra facts and does not execute a request."""
    monkeypatch.setattr(context_extractor, "safe_gemini_call", lambda _: SimpleNamespace(text=
        '{"relation":"related","flags":{"partner_with_user":false,'
        '"partner_at_work":true},"continue_conversation":true}'))
    result = process_question_answer(
        store=delivered, user_text="Όχι, η Σοφία δουλεύει. Θυμήσου το ρεπό και βάλε reminder στις έξι.",
        channel=channel, now=NOW + timedelta(seconds=1), trusted_owner=True)
    assert result.consumed and result.outcome == "resolved"
    assert result.continue_conversation and result.context_flags_processed
    assert routine_db.get_context_state("partner_at_work")["value"] == "true"
    assert delivered.snapshot()["requests"][0]["status"] == "resolved"


def test_refusal_with_another_request_continues_without_claiming_flag_extraction(delivered, monkeypatch):
    """Declining the question is not declining a separate reminder request."""
    monkeypatch.setattr(context_extractor, "safe_gemini_call", lambda _: SimpleNamespace(text=
        '{"relation":"refused","flags":{},"continue_conversation":true}'))
    result = process_question_answer(
        store=delivered, user_text="Δεν θέλω να απαντήσω. Η Σοφία δουλεύει, βάλε reminder στις έξι.",
        channel="matrix", now=NOW + timedelta(seconds=1), trusted_owner=True)
    assert result.outcome == "declined" and result.continue_conversation
    assert not result.context_flags_processed
    assert delivered.snapshot()["requests"][0]["status"] == "declined"
    assert routine_db.get_context_state("partner_with_user") is None


def test_mixed_answer_batch_conflict_keeps_real_ledger_pending(delivered, monkeypatch):
    """CAS rejection is a held answer, not a failed parser or a resolved ledger."""
    def model(prompt):
        routine_db.set_context_state("partner_at_work", "false")
        return SimpleNamespace(text='{"relation":"related","flags":{"partner_with_user":false,'
                                    '"partner_at_work":true},"continue_conversation":true}')

    monkeypatch.setattr(context_extractor, "safe_gemini_call", model)
    result = process_question_answer(
        store=delivered, user_text="Όχι, είναι δουλειά. Βάλε reminder.",
        channel="matrix", now=NOW + timedelta(seconds=1), trusted_owner=True)
    assert result.outcome == "deferred" and result.continue_conversation
    assert delivered.snapshot()["pending"]["status"] == "sent"
    assert routine_db.get_context_state("partner_at_work")["value"] == "false"
    assert routine_db.get_context_state("partner_with_user") is None


def test_real_matrix_answer_persists_facts_and_continues_original_turn(delivered, monkeypatch):
    """Exercise provider interpretation, ledger, canonical flags and turn history together."""
    import config
    from langchain_core.messages import AIMessage, HumanMessage
    from memory import conversation_history as history
    from services import routine_context_clarification as clarification, routine_context
    from services.matrix_turn import MatrixTurnService
    from core import messenger_draft
    from services import messenger_intent

    path = str(delivered.path.parent / "conversation.db")
    monkeypatch.setattr(config, "BASE_DIR", str(delivered.path.parent))
    monkeypatch.setattr(clarification, "context_confirmation_conflict", lambda: False)
    monkeypatch.setattr(history, "get_max_rowid", lambda: 0)
    monkeypatch.setattr(routine_context, "build_routine_context_evidence", lambda _: {})
    monkeypatch.setattr(messenger_draft, "active_draft_status", lambda: (False, "none", None))
    monkeypatch.setattr(messenger_intent, "classify_messenger_intent",
                        lambda *a, **k: SimpleNamespace(intent="unrelated"))
    monkeypatch.setattr(context_extractor, "safe_gemini_call", lambda _: SimpleNamespace(text=
        '{"relation":"related","flags":{"partner_with_user":false,'
        '"partner_at_work":true},"continue_conversation":true}'))
    text = "Όχι, η Σοφία δουλεύει. Θυμήσου το αυριανό ρεπό και βάλε reminder στις έξι."
    inputs, exchanges = [], []

    def stream(state, options):
        """Stub the graph provider boundary, never real tools or transport."""
        inputs.append(state)
        yield {"Chat_Agent": {"messages": [AIMessage(content="Πάμε να το οργανώσουμε.")]}}

    service = MatrixTurnService(
        graph=SimpleNamespace(stream=stream), conversation_db_path=path,
        select_tool_channel=lambda _: None,
        on_exchange_completed=lambda *a, **k: exchanges.append((a, k)))
    reply = service._run_sync(text, "$mixed-real-answer")
    assert len(inputs) == 1
    assert sum(text in message.content for message in inputs[0]["messages"]
               if isinstance(message, HumanMessage)) == 1
    assert routine_db.get_context_state("partner_at_work")["value"] == "true"
    assert delivered.snapshot()["requests"][0]["status"] == "resolved"
    assert [row["content"] for row in history.load_messages(db_path=path)] == [text, reply]
    assert len(exchanges) == 1 and exchanges[0][1]["context_flags_processed"] is True


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
    canonical = routine_db.set_context_states_if_unchanged

    def classify(_):
        barrier.wait(timeout=5)
        return SimpleNamespace(text='{"relation":"related","flags":{"partner_with_user":false}}')

    def write(*args, **kwargs):
        writes.append(args)
        return canonical(*args, **kwargs)

    monkeypatch.setattr(context_extractor, "safe_gemini_call", classify)
    monkeypatch.setattr(context_extractor, "set_context_states_if_unchanged", write)
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


@pytest.mark.parametrize("relation", ["related", "refused"])
def test_live_gps_resolves_question_during_owner_answer(delivered, monkeypatch, relation):
    """A real GPS/poll resolution must not become a failed answer or overwrite."""
    from services.location_update import record_location_update
    from services import location_update
    from services.routine_context_evidence import evaluate_context_evidence, load_gps_point
    from services.routine_context_clarification_poll import PollSnapshot, run_clarification_poll

    store = ClarificationStore(delivered.path.parent / "gps-question.json")
    request = QuestionRequest("gps", "home", ("100",), ("user_out_of_home",),
                              NOW + timedelta(minutes=12),
                              "Βρίσκεστε στο σπίτι αυτή τη στιγμή;", "matrix")
    assert store.reserve(request, now=NOW)
    assert store.begin_send("gps", now=NOW)
    assert store.mark_sent("gps", external_id="$gps", now=NOW)
    assert store.mark_recorded("gps")
    gps_path = delivered.path.parent / "location.json"
    clock = NOW + timedelta(seconds=3)
    monkeypatch.setattr(location_update, "location_is_home", lambda *_: False)

    def forbidden(*args, **kwargs):
        raise AssertionError("No second send or stale context write")

    def classify(_):
        record_location_update(1, 2, live_update=True, storage_file=gps_path,
                               now_ts=(NOW + timedelta(seconds=2)).timestamp())
        evidence = evaluate_context_evidence({}, load_gps_point(gps_path), now=clock,
                                             location_resolver=lambda *_: False)
        outcome = run_clarification_poll(
            store=store, clock=lambda: clock, selected_channel=lambda: "matrix",
            snapshot_loader=lambda _: PollSnapshot((), {}, evidence, "1"),
            unavailable=lambda: False, classify=forbidden, budget=forbidden,
            sender=forbidden, record=forbidden)
        assert outcome == "resolved"
        return SimpleNamespace(text='{"relation":"' + relation + '","flags":{"user_out_of_home":true}}')

    monkeypatch.setattr(context_extractor, "safe_gemini_call", classify)
    monkeypatch.setattr(context_extractor, "_persist_context_payload", forbidden)
    result = process_question_answer(
        store=store, user_text="Όχι φίλε στην δουλειά είμαι", channel="matrix",
        now=NOW + timedelta(seconds=1), current_time=lambda: clock, trusted_owner=True)
    assert result.consumed and result.outcome == "already_resolved"
    assert routine_db.get_context_state("user_out_of_home")["value"] == "true"
    assert store.snapshot()["requests"][0]["status"] == "resolved"
    assert "έγκρι" not in result.reply.casefold()


@pytest.mark.parametrize("outcome", ["declined", "expired"])
@pytest.mark.parametrize("relation", ["related", "refused"])
def test_nonresolution_during_answer_is_not_acknowledged_as_resolved(delivered, monkeypatch, outcome, relation):
    """Only the exact resolved request can receive the already-resolved reply."""
    clock = [NOW + timedelta(seconds=2)]

    def classify(_):
        if outcome == "declined":
            delivered.close("q1", outcome="declined", now=clock[0])
        else:
            clock[0] = NOW + timedelta(minutes=13)
            delivered.expire(now=clock[0])
        return SimpleNamespace(text='{"relation":"' + relation + '","flags":{"partner_with_user":false}}')

    monkeypatch.setattr(context_extractor, "safe_gemini_call", classify)
    result = process_question_answer(store=delivered, user_text="no", channel="matrix",
        now=NOW + timedelta(seconds=1), current_time=lambda: clock[0], trusted_owner=True)
    assert result.outcome == ("deferred" if relation == "related" else "uncertain")
    assert result.consumed == (relation == "related")
    assert routine_db.get_context_state("partner_with_user") is None


@pytest.mark.parametrize("resolved_by_poll", [True, False])
def test_partial_answer_uses_current_terminal_ledger(delivered, monkeypatch, resolved_by_poll):
    """A partial canonical commit followed by resolution gets a complete acknowledgement."""
    store = ClarificationStore(delivered.path.parent / "multi-flag.json")
    request = QuestionRequest("multi", "presence", ("r1",),
        ("partner_with_user", "user_out_of_home"), NOW + timedelta(minutes=12),
        "Are you home together?", "matrix")
    assert store.reserve(request, now=NOW)
    assert store.begin_send("multi", now=NOW)
    assert store.mark_sent("multi", external_id="$multi", now=NOW)
    assert store.mark_recorded("multi")
    original_commit = store.commit_answer

    def commit_then_resolve(*args, **kwargs):
        applied = original_commit(*args, **kwargs)
        assert applied == frozenset({"partner_with_user"})
        if resolved_by_poll:
            routine_db.set_context_state("user_out_of_home", "false")
            assert store.close("multi", outcome="resolved", now=NOW + timedelta(seconds=2))
        return applied

    monkeypatch.setattr(store, "commit_answer", commit_then_resolve)
    answer = process_question_answer(store=store, user_text="yes", channel="matrix",
        now=NOW + timedelta(seconds=1), trusted_owner=True)
    assert answer.consumed
    assert answer.outcome == ("already_resolved" if resolved_by_poll else "partial")
    assert routine_db.get_context_state("partner_with_user")["value"] == "false"
    assert store.snapshot()["requests"][0]["status"] == ("resolved" if resolved_by_poll else "sent")
