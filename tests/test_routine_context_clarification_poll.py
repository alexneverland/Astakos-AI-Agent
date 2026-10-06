"""Offline scheduler lifecycle using real temporary ledgers and history."""
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from memory.routine_context_clarification import ATHENS, ClarificationStore
from services.routine_context_clarification import RoutineCandidate
from services.routine_context_evidence import ContextEvidence
from services.routine_context_clarification_poll import PollSnapshot, run_clarification_poll

NOW = datetime(2026, 10, 6, 10, tzinfo=ATHENS)


def snapshot(marker="42", value=None, candidates=True):
    """Represent a candidate already filtered by the normal scheduler."""
    condition = {"condition_type": "context_flag", "condition_mode": "suppress_when_true",
                 "condition_payload": {"flag": "user_out_of_home", "equals": True}}
    return PollSnapshot(
        candidates=(RoutineCandidate("1", "Home activity", NOW + timedelta(minutes=12),
                                    (condition,)),) if candidates else (),
        runtime_context={"current_shift": "afternoon"}, history_marker=marker,
        evidence={"user_out_of_home": ContextEvidence(effective_value=value,
            status="unknown" if value is None else "known", recorded_at=NOW + timedelta(minutes=1))})


def harness(tmp_path):
    """Use a real ledger and capture only the outbound boundary."""
    store = ClarificationStore(tmp_path / "state.json")
    sends, records, budgets = [], [], []
    def sender(channel, text, identity):
        sends.append(identity)
        return SimpleNamespace(channel=channel, external_id="$question")
    return store, sends, records, budgets, dict(store=store, clock=lambda: NOW,
        selected_channel=lambda: "matrix", snapshot_loader=lambda _: snapshot(),
        unavailable=lambda: False,
        classify=lambda _: {"routine_ids": ["1"], "flags": ["user_out_of_home"],
                            "question": "Γυρίσατε σπίτι;"},
        budget=lambda: budgets.append(True) or True, sender=sender,
        record=lambda **row: records.append(row))


def test_poll_delivers_once_then_waits_without_model_or_budget(tmp_path):
    store, sends, records, budgets, args = harness(tmp_path)
    assert run_clarification_poll(**args) == "delivered"
    args["classify"] = lambda _: pytest.fail("pending question must not reclassify")
    assert run_clarification_poll(**args) == "waiting_answer"
    assert len(sends) == len(records) == len(budgets) == 1
    assert store.snapshot()["pending"]["history_recorded"]


@pytest.mark.parametrize("change", ["history", "evidence", "candidate", "channel", "quiet", "deadline"])
def test_slow_classification_cannot_send_obsolete_question(tmp_path, change):
    store, sends, _, budgets, args = harness(tmp_path)
    state = {"snapshot": snapshot(), "channel": "matrix", "quiet": False, "now": NOW}
    args.update(snapshot_loader=lambda _: state["snapshot"],
                selected_channel=lambda: state["channel"],
                unavailable=lambda: state["quiet"], clock=lambda: state["now"])
    def classify(_):
        if change == "history": state["snapshot"] = snapshot(marker="43")
        if change == "evidence": state["snapshot"] = snapshot(value=False)
        if change == "candidate": state["snapshot"] = snapshot(candidates=False)
        if change == "channel": state["channel"] = "telegram"
        if change == "quiet": state["quiet"] = True
        if change == "deadline": state["now"] += timedelta(minutes=12)
        return {"routine_ids": ["1"], "flags": ["user_out_of_home"], "question": "Σπίτι;"}
    args["classify"] = classify
    assert run_clarification_poll(**args) == "deferred"
    assert not sends and not budgets and store.snapshot()["pending"] is None


@pytest.mark.parametrize("reason", ["quiet", "muted", "recent_activity", "recent_reminder", "confirmation"])
def test_interrupt_gate_runs_before_classification_or_reservation(tmp_path, reason):
    store, sends, _, budgets, args = harness(tmp_path)
    args.update(unavailable=lambda: reason, classify=lambda _: pytest.fail("guard before model"))
    assert run_clarification_poll(**args) == reason
    assert not store.path.exists() and not sends and not budgets


def test_new_evidence_resolves_question_without_another_send(tmp_path):
    store, sends, _, budgets, args = harness(tmp_path)
    assert run_clarification_poll(**args) == "delivered"
    args.update(clock=lambda: NOW + timedelta(minutes=2),
                snapshot_loader=lambda _: snapshot(value=False),
                classify=lambda _: pytest.fail("evidence already sufficient"))
    assert run_clarification_poll(**args) == "resolved"
    assert store.snapshot()["pending"] is None
    assert len(sends) == len(budgets) == 1
    reloaded = ClarificationStore(store.path)
    assert reloaded.claim_dispatch(now=NOW + timedelta(minutes=2))
    assert run_clarification_poll(**args) == "not_due"
    assert not reloaded.claim_dispatch(now=NOW + timedelta(minutes=2))


def test_slot_expiry_never_replays_question(tmp_path):
    store, sends, _, budgets, args = harness(tmp_path)
    assert run_clarification_poll(**args) == "delivered"
    args.update(clock=lambda: NOW + timedelta(minutes=12),
                snapshot_loader=lambda _: snapshot(value=False),
                classify=lambda _: pytest.fail("expired candidate must not classify"))
    assert run_clarification_poll(**args) == "not_due"
    assert store.snapshot()["pending"] is None
    assert store.snapshot()["requests"][0]["status"] == "expired"
    assert len(sends) == len(budgets) == 1
    assert not store.claim_dispatch(now=NOW + timedelta(minutes=12))


def test_declined_question_does_not_request_dispatch(tmp_path):
    """Declining a question is not permission to resume its reminder."""
    store, sends, _, _, args = harness(tmp_path)
    assert run_clarification_poll(**args) == "delivered"
    assert store.close(store.snapshot()["pending"]["id"], outcome="declined",
                       now=NOW + timedelta(minutes=1))
    assert not store.claim_dispatch(now=NOW + timedelta(minutes=1))
    assert len(sends) == 1


def test_receipt_history_repair_after_expiry_uses_real_shared_store(tmp_path):
    """Crash after history commit is recovered idempotently without another send."""
    from memory.conversation_history import append_message, load_messages

    store, sends, _, budgets, args = harness(tmp_path)
    db_path = str(tmp_path / "history.db")
    def interrupted_record(**row):
        append_message(**row, db_path=db_path)
        raise OSError("crash after committed history")
    args["record"] = interrupted_record
    assert run_clarification_poll(**args) == "held"
    assert not store.snapshot()["pending"]["history_recorded"]
    args.update(clock=lambda: NOW + timedelta(minutes=20), unavailable=lambda: "quiet",
                record=lambda **row: append_message(**row, db_path=db_path),
                classify=lambda _: pytest.fail("repair is not a model decision"))
    assert run_clarification_poll(**args) == "quiet"
    rows = load_messages(db_path=db_path)
    assert len(rows) == 1 and rows[0]["agent"] == "Routine_Context"
    assert store.snapshot()["requests"][0]["history_recorded"]
    assert len(sends) == len(budgets) == 1


def test_corrupt_ledger_is_held_unchanged(tmp_path):
    """Malformed durable state never resets a question budget or dispatches."""
    store, sends, _, budgets, args = harness(tmp_path)
    # Simulate a damaged ledger through the filesystem fixture only.
    store.path.write_bytes(b"broken")
    assert run_clarification_poll(**args) == "error"
    assert store.path.read_bytes() == b"broken"
    assert not sends and not budgets
