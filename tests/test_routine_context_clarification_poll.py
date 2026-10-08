"""Offline scheduler lifecycle using real temporary ledgers and history."""
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from memory.routine_context_clarification import ATHENS, ClarificationStore
from services.routine_context_clarification import RoutineCandidate
from services.routine_context_evidence import ContextEvidence
from services.routine_context_clarification_poll import PollSnapshot, run_clarification_poll

NOW = datetime(2026, 10, 6, 10, tzinfo=ATHENS)


@pytest.mark.parametrize("legacy", [False, True])
def test_grouped_midnight_question_resolves_each_occurrence_on_its_own_date(tmp_path, legacy):
    """Yesterday's completion cannot close tomorrow's member of a shared question."""
    from dataclasses import replace
    store, sends, _, _, args = harness(tmp_path)
    now = NOW.replace(hour=23, minute=50)
    first = replace(snapshot().candidates[0], slot_at=now.replace(minute=58))
    second = replace(first, id="2", name="Tomorrow activity",
                     slot_at=(now + timedelta(days=1)).replace(hour=0, minute=2))
    args.update(clock=lambda: now,
                snapshot_loader=lambda _: replace(snapshot(), candidates=(first, second)),
                classify=lambda _: {"routine_ids": ["1", "2"],
                                    "flags": ["user_out_of_home"], "question": "Home now?"})
    assert run_clarification_poll(**args) == "delivered"
    if legacy:
        import json
        saved = json.loads(store.path.read_text(encoding="utf-8"))
        del saved["requests"][0]["routine_slots"]
        store.path.write_text(json.dumps(saved), encoding="utf-8")
    # Both IDs have completion today, but ID 2's questioned occurrence is tomorrow.
    args["closed_routine_ids"] = lambda slot: {1, 2} if slot.date() == now.date() else set()
    assert run_clarification_poll(**args) == "waiting_answer"
    assert store.snapshot()["pending"] is not None
    args["closed_routine_ids"] = lambda slot: {1, 2}
    assert run_clarification_poll(**args) == ("waiting_answer" if legacy else "resolved")
    assert (store.snapshot()["pending"] is not None) is legacy
    assert len(sends) == 1


@pytest.mark.parametrize("slots", [{"other": "2026-10-06T10:12:00+03:00"},
                                   {"1": "not-a-date"},
                                   {"1": "2026-10-06T10:13:00+03:00"}])
def test_malformed_occurrence_mapping_cannot_close_question(tmp_path, slots):
    """Corrupt persisted dates are rejected, not used as completion evidence."""
    import json
    store, sends, _, _, args = harness(tmp_path)
    assert run_clarification_poll(**args) == "delivered"
    saved = json.loads(store.path.read_text(encoding="utf-8"))
    saved["requests"][0]["routine_slots"] = slots
    store.path.write_text(json.dumps(saved), encoding="utf-8")
    before = store.path.read_bytes()
    args["closed_routine_ids"] = lambda slot: {1}
    assert run_clarification_poll(**args) == "error"
    assert store.path.read_bytes() == before and len(sends) == 1


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


@pytest.mark.parametrize("channel", ["matrix", "telegram"])
def test_later_market_reasks_after_spacing_without_poisoning_model_claim(tmp_path, channel):
    """A too-early poll must not consume the unchanged candidate's semantic attempt."""
    from dataclasses import replace
    from services.routine_context_evidence import evaluate_stored_evidence
    store, sends, _, _, args = harness(tmp_path)
    first = NOW.replace(hour=8)
    clock = {"now": first}
    rabbit = replace(snapshot().candidates[0], id="96", name="Rabbit cleaning",
                     slot_at=first.replace(minute=15))
    market = replace(rabbit, id="1", name="Market shopping", slot_at=first.replace(minute=35))
    # A previously stored home observation is stale; no current GPS exists.
    evidence = evaluate_stored_evidence(
        {"value": "false", "updated_at": "2026-10-06T01:22:00", "expires_at": "2026-10-06"},
        now=first)
    current = {"candidate": rabbit}
    model_calls = []
    def classify(packet):
        model_calls.append(packet)
        return {"routine_ids": [current["candidate"].id], "flags": ["user_out_of_home"],
                "question": "Home now?"}
    args.update(clock=lambda: clock["now"], selected_channel=lambda: channel,
                snapshot_loader=lambda _: replace(snapshot(), candidates=(current["candidate"],),
                    evidence={"user_out_of_home": evidence}), classify=classify)
    assert run_clarification_poll(**args) == "delivered"
    clock["now"] = first.replace(minute=29)
    current["candidate"] = market
    assert run_clarification_poll(**args) in {"held", "deferred"}
    assert len(model_calls) == 1
    clock["now"] = first.replace(minute=30)
    assert run_clarification_poll(**args) == "delivered"
    assert len(sends) == len(model_calls) == 2
    assert store.snapshot()["pending"]["routine_ids"] == ["1"]


@pytest.mark.parametrize("fresh_gps", [False, True])
def test_rabbit_at_eight_does_not_block_market_at_nine_when_gps_stops(tmp_path, fresh_gps):
    """Reproduce the owner's timestamps; an expired GPS share cannot imply home."""
    from dataclasses import replace
    from services.routine_context_evidence import evaluate_context_evidence
    store, sends, _, _, args = harness(tmp_path)
    first = NOW.replace(hour=8, second=38)
    rabbit = replace(snapshot().candidates[0], id="96", slot_at=first.replace(minute=15, second=0))
    args.update(clock=lambda: first,
                snapshot_loader=lambda _: replace(snapshot(), candidates=(rabbit,)),
                classify=lambda _: {"routine_ids": ["96"], "flags": ["user_out_of_home"],
                                    "question": "Home for the rabbit?"})
    assert run_clarification_poll(**args) == "delivered"
    later = first.replace(minute=56, second=22)
    point_at = later if fresh_gps else later - timedelta(hours=8)
    evidence = evaluate_context_evidence({},
        {"lat": 1.0, "lon": 1.0, "timestamp": point_at.timestamp()},
        now=later, location_resolver=lambda *_: True)
    market = replace(rabbit, id="1", name="Market shopping",
                     slot_at=later.replace(hour=9, minute=0, second=0))
    args.update(clock=lambda: later,
                snapshot_loader=lambda _: replace(snapshot(), candidates=(market,), evidence=evidence),
                classify=lambda _: {"routine_ids": ["1"], "flags": ["user_out_of_home"],
                                    "question": "Home before the market?"})
    assert run_clarification_poll(**args) == ("not_due" if fresh_gps else "delivered")
    assert len(sends) == (1 if fresh_gps else 2)
    assert store.snapshot()["requests"][0]["status"] == "expired"


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
