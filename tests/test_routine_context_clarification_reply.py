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
