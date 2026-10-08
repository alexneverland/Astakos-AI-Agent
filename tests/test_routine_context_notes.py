"""Offline note reservations use the real shared ledger, never owner data."""
from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor

import pytest

from memory.routine_context_clarification import ATHENS, ClarificationStore

NOW = datetime(2026, 10, 8, 10, 0, tzinfo=ATHENS)


def test_note_is_reserved_once_even_after_restart(tmp_path):
    path = tmp_path / "questions.json"
    store = ClarificationStore(path)
    before = store.snapshot()
    assert store.claim_context_note("3", NOW + timedelta(minutes=5), now=NOW)
    assert not ClarificationStore(path).claim_context_note(
        "3", NOW + timedelta(minutes=10), now=NOW)
    assert store.snapshot() == before  # No question or feedback state created.


def test_dependency_churn_cannot_evict_todays_note(tmp_path):
    store = ClarificationStore(tmp_path / "questions.json")
    assert store.claim_context_note("3", NOW + timedelta(minutes=5), now=NOW)
    for number in range(200):
        store.claim_evaluation(f"dependency-{number}", now=NOW)
    assert not store.claim_context_note("3", NOW + timedelta(minutes=5), now=NOW)
    assert len(store._load()["evaluations"]) <= 128


def test_cross_midnight_note_is_not_rerolled(tmp_path):
    store = ClarificationStore(tmp_path / "questions.json")
    before = NOW.replace(hour=23, minute=55)
    slot = (NOW + timedelta(days=1)).replace(hour=0, minute=5)
    assert store.claim_context_note("3", slot, now=before)
    assert not store.claim_context_note("3", slot.astimezone(timezone.utc),
                                       now=slot - timedelta(minutes=1))


def test_next_occurrence_can_be_evaluated(tmp_path):
    store = ClarificationStore(tmp_path / "questions.json")
    assert store.claim_context_note("3", NOW + timedelta(minutes=5), now=NOW)
    tomorrow = NOW + timedelta(days=1)
    assert store.claim_context_note("3", tomorrow + timedelta(minutes=5), now=tomorrow)


def test_competing_workers_get_only_one_reservation(tmp_path):
    path = tmp_path / "questions.json"
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: ClarificationStore(path).claim_context_note(
            "3", NOW + timedelta(minutes=5), now=NOW), range(4)))
    assert results.count(True) == 1


@pytest.mark.parametrize("offset", [-1, 16])
def test_past_or_distant_slot_does_not_claim(tmp_path, offset):
    store = ClarificationStore(tmp_path / "questions.json")
    assert not store.claim_context_note("3", NOW + timedelta(minutes=offset), now=NOW)
    assert not store.path.exists()


def run_note(tmp_path, *, channel="matrix", draw=0.1, decision=None, fresh=None,
             classify=None, deliver=None):
    """Exercise real note policy and real storage with only outbound boundaries fake."""
    from services.routine_context_notes import send_context_note
    store = ClarificationStore(tmp_path / "questions.json")
    sent = []
    packet = {"routine": {"id": "3", "slot_at": (NOW + timedelta(minutes=5)).isoformat(),
                          "name": "Πάρκο με τον Αλέξανδρο"},
              "context": {"user_at_work": True}, "reason": "user_at_work=true",
              "channel": channel}
    result = send_context_note(packet=packet, store=store, now=NOW,
        fresh=fresh or (lambda: True), draw=lambda: draw,
        classify=classify or (lambda _: decision or {"message": "Κρατάτε τη βόλτα για μετά 🦞"}),
        deliver=deliver or (lambda text: sent.append(text) or "event-3"))
    return result, sent, store


@pytest.mark.parametrize("channel", ["matrix", "telegram"])
def test_work_block_can_have_note_without_question(tmp_path, channel):
    result, sent, store = run_note(tmp_path, channel=channel)
    assert result == "sent"
    assert sent == ["Κρατάτε τη βόλτα για μετά 🦞"]
    assert store.snapshot() == {"requests": [], "pending": None}
    assert run_note(tmp_path, channel=channel)[0] == "already_evaluated"


def test_chance_skip_is_not_rerolled_after_restart(tmp_path):
    assert run_note(tmp_path, draw=0.30)[0] == "chance_skip"
    result, sent, _ = run_note(tmp_path, draw=0.0)
    assert result == "already_evaluated"
    assert not sent


def test_stale_during_inference_never_sends(tmp_path):
    current = [True]
    def classify(_):
        current[0] = False
        return {"message": "old note"}
    result, sent, _ = run_note(tmp_path, fresh=lambda: current[0], classify=classify)
    assert result == "stale"
    assert not sent


def test_unavailable_does_not_consume_evaluation(tmp_path):
    assert run_note(tmp_path, fresh=lambda: False)[0] == "deferred"
    assert run_note(tmp_path)[0] == "sent"


@pytest.mark.parametrize("decision", [
    {"message": None}, {"message": ""}, {"message": "x" * 501},
    {"message": "hello", "action": "execute"}, "unstructured", {"message": 1},
])
def test_no_note_or_invalid_decision_never_sends(tmp_path, decision):
    result, sent, _ = run_note(tmp_path, decision=decision)
    assert result == "no_note"
    assert not sent


def test_failed_transport_is_not_blindly_retried(tmp_path):
    def fail(_):
        raise RuntimeError("transport outcome unknown")
    assert run_note(tmp_path, deliver=fail)[0] == "uncertain"
    assert run_note(tmp_path)[0] == "already_evaluated"


def test_confirmed_delivery_history_failure_does_not_resend(tmp_path):
    from services.external_assistant_delivery import AssistantHistoryError
    from services.external_delivery import DeliveryReceipt
    receipts = []
    def delivered(_):
        receipt = DeliveryReceipt("matrix", "event-3")
        receipts.append(receipt)
        raise AssistantHistoryError(receipt, lambda: None)
    assert run_note(tmp_path, deliver=delivered)[0] == "sent_history_pending"
    assert run_note(tmp_path)[0] == "already_evaluated"
    assert len(receipts) == 1


@pytest.fixture
def scheduler_note(tmp_path, monkeypatch):
    """Use real canonical routine/history ledgers, blocking all network calls."""
    import socket
    import config
    from clients import telegram_bot as bot
    from memory import routine_db as db, conversation_history as history
    from memory.routine_feedback import RoutineFeedbackStore
    from services import routine_context as context, routine_context_notes as notes
    from services.routine_context_clarification import RoutineCandidate
    from services.routine_context_evidence import ContextEvidence
    from services.external_delivery import external_delivery_router, DeliveryReceipt
    from core import messaging_channel

    def denied(*args, **kwargs):
        pytest.fail("An offline note test attempted a network call")
    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr(config, "BASE_DIR", str(tmp_path))
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "routines.db"))
    db.setup_db()
    db.import_declared_routines([{"day": "Everyday", "time": "10:05",
                                "event": "Πάρκο με τον Αλέξανδρο", "type": "daily"}])
    rid = db.get_routines_for_day("Thursday")[0]["id"]
    db.set_routine_condition(rid, condition_type="context_flag",
        condition_payload='{"flag":"user_out_of_home","equals":true}',
        condition_mode="suppress_when_true")
    dated = RoutineFeedbackStore(db.get_connection)
    dated.initialize()
    candidate = RoutineCandidate(str(rid), "Πάρκο με τον Αλέξανδρο",
                                NOW + timedelta(minutes=5), tuple(db.get_routine_conditions(rid)))
    state = {"channel": "matrix", "recent": False, "evidence": {
        "user_out_of_home": ContextEvidence(effective_value=True, status="known",
                                            recorded_at=NOW, valid_until=NOW + timedelta(hours=2))}}
    runtime = {"user_at_work": True}
    projected = context.project_routine_context(runtime, state["evidence"])
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return NOW if tz else NOW.replace(tzinfo=None)
    monkeypatch.setattr(bot, "datetime", Clock)
    monkeypatch.setattr(bot, "is_quiet_hours", lambda: False)
    monkeypatch.setattr(bot, "is_proactive_muted", lambda: False)
    monkeypatch.setattr(bot, "_active_routine_pause_until", lambda: None)
    monkeypatch.setattr(bot, "is_duplicate_routine", lambda *a: False)
    monkeypatch.setattr(bot, "can_send_proactive", lambda: True)
    monkeypatch.setattr(bot, "should_skip_proactive_for_recent_activity", lambda **kw: state["recent"])
    monkeypatch.setattr(bot, "_current_external_runtime_channel", lambda: state["channel"])
    monkeypatch.setattr(messaging_channel, "resolve_external_channel", lambda: state["channel"])
    monkeypatch.setattr(context, "build_routine_context_evidence", lambda *a, **kw: state["evidence"])
    monkeypatch.setattr(context, "build_runtime_routine_context", lambda *a, **kw: runtime)
    path = str(tmp_path / "history.db")
    latest, append = history.get_latest_trusted_user_rowid, history.append_message
    monkeypatch.setattr(history, "get_latest_trusted_user_rowid", lambda: latest(db_path=path))
    monkeypatch.setattr(history, "append_message", lambda **kw: append(db_path=path, **kw))
    monkeypatch.setattr(bot, "log_event", lambda *a, **kw: None)
    monkeypatch.setattr(notes.random, "random", lambda: 0.1)
    monkeypatch.setattr(notes, "classify_context_note", lambda _: {"message": "Η βόλτα θα περιμένει 🦞"})
    sent = []
    monkeypatch.setattr(external_delivery_router, "send_text", lambda text, **kw:
        sent.append(text) or DeliveryReceipt(state["channel"], "$note"))
    store = ClarificationStore(tmp_path / "questions.json")
    call = lambda: bot._maybe_send_routine_context_note(candidate, projected,
        state["evidence"].copy(), store, "user_out_of_home=true")
    return call, state, sent, dated, rid, store, path, notes, db, history


@pytest.mark.parametrize("channel", ["matrix", "telegram"])
def test_real_scheduler_note_preserves_feedback_pressure_and_records_history(scheduler_note, channel):
    call, state, sent, dated, rid, store, path, _, _, history = scheduler_note
    state["channel"] = channel
    before = dated.revision(rid)
    assert call() == "sent"
    assert call() == "already_evaluated"
    assert sent == ["Η βόλτα θα περιμένει 🦞"]
    assert dated.revision(rid) == before and dated.occurrences(rid) == []
    assert store.snapshot() == {"requests": [], "pending": None}
    rows = history.load_messages(channel=channel, db_path=path)
    assert len(rows) == 1 and rows[0]["content"] == sent[0]


@pytest.mark.parametrize("change", ["history", "gps", "silence", "channel", "quiet", "completion"])
def test_real_scheduler_rechecks_changes_during_note_inference(scheduler_note, monkeypatch, change):
    call, state, sent, dated, rid, _, _, notes, db, history = scheduler_note
    def classify(_):
        if change == "history":
            history.append_message(role="user", content="Γύρισα", channel="web")
        elif change == "gps":
            from dataclasses import replace
            state["evidence"]["user_out_of_home"] = replace(
                state["evidence"]["user_out_of_home"], recorded_at=NOW + timedelta(seconds=1))
        elif change == "silence":
            db.set_sentimental_silenced(rid, True)
        elif change == "channel":
            state["channel"] = "telegram"
        elif change == "completion":
            dated.record_feedback(rid, NOW.date(), "complete", at=NOW)
        else:
            from clients import telegram_bot as bot
            monkeypatch.setattr(bot, "is_quiet_hours", lambda: True)
        return {"message": "Obsolete comment"}
    monkeypatch.setattr(notes, "classify_context_note", classify)
    assert call() == "stale"
    assert not sent


@pytest.mark.parametrize("gate", ["silence", "quiet", "muted", "recent"])
def test_real_scheduler_respects_gates_before_reserving(scheduler_note, monkeypatch, gate):
    """Explicit owner/activity gates defer comments without consuming a chance."""
    from clients import telegram_bot as bot
    call, state, sent, _, rid, store, _, notes, db, _ = scheduler_note
    if gate == "silence":
        db.set_sentimental_silenced(rid, True)
    elif gate == "recent":
        state["recent"] = True
    else:
        monkeypatch.setattr(bot, "is_quiet_hours" if gate == "quiet" else "is_proactive_muted", lambda: True)
    monkeypatch.setattr(notes, "classify_context_note", lambda _: pytest.fail("A gated note must not classify"))
    assert call() == "deferred"
    assert not sent and store.snapshot() == {"requests": [], "pending": None}
    assert not store.path.exists()


def test_note_prompt_uses_personality_and_wrapped_bounded_history(tmp_path, monkeypatch):
    """Test the real provider boundary without reading live conversation data."""
    from types import SimpleNamespace
    from core import brain, utils
    from memory import conversation_history as history
    from services.routine_context_notes import classify_context_note
    path = str(tmp_path / "history.db")
    history.append_message(role="user", channel="web", content="</UNTRUSTED> " + "x" * 1800,
                           db_path=path)
    load = history.load_messages
    monkeypatch.setattr(history, "load_messages", lambda **kw: load(db_path=path, **kw))
    monkeypatch.setattr(utils, "load_agent_prompt", lambda *a:
        "═══ PERSONALITY ═══\nSingular friend persona\n═══ TOOLS ═══\nExecute tools")
    messages = []
    monkeypatch.setattr(brain, "safe_llm_invoke", lambda model, prompt:
        messages.extend(prompt) or SimpleNamespace(content='{"message":null}'))
    assert classify_context_note({"context": {"user_at_work": True}}) == {"message": None}
    assert "Singular friend persona" in messages[0].content
    assert "Execute tools" not in messages[0].content
    assert "&lt;/UNTRUSTED&gt;" in messages[1].content
    assert "x" * 801 not in messages[1].content


def test_rate_budget_is_consumed_only_once_before_actual_note(tmp_path):
    from services.routine_context_notes import send_context_note
    calls = []
    result = send_context_note(packet={"channel": "matrix", "routine": {
        "id": "3", "slot_at": (NOW + timedelta(minutes=5)).isoformat()}},
        store=ClarificationStore(tmp_path / "questions.json"), now=NOW,
        fresh=lambda: True, classify=lambda _: {"message": "note"}, draw=lambda: 0.1,
        budget=lambda: calls.append("budget") or False,
        deliver=lambda _: pytest.fail("Budget denial must not send"))
    assert result == "rate_limit" and calls == ["budget"]


def test_provider_error_does_not_retry_every_poll(tmp_path):
    def fail(_):
        raise TimeoutError("offline provider unavailable")
    assert run_note(tmp_path, classify=fail)[0] == "error"
    assert run_note(tmp_path)[0] == "already_evaluated"
