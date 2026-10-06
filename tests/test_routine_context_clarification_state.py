"""Offline lifecycle tests for routine context questions."""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from memory.routine_context_clarification import ClarificationStore, QuestionRequest


ATHENS = ZoneInfo("Europe/Athens")
NOW = datetime(2026, 10, 6, 10, 0, tzinfo=ATHENS)


def request(
    identifier: str, *, topic: str = "user_out_of_home", minutes_until_slot: int = 12,
) -> QuestionRequest:
    """Build a question that is due before its routine slot."""
    return QuestionRequest(
        id=identifier,
        topic=topic,
        routine_ids=("routine-1",),
        flags=("user_out_of_home",),
        slot_at=NOW + timedelta(minutes=minutes_until_slot),
        question="Γυρίσατε σπίτι;",
        channel="matrix",
    )


def test_reservation_survives_restart_and_holds_one_pending(tmp_path):
    """A new store instance sees the first pending question."""
    path = tmp_path / "clarification.json"
    assert ClarificationStore(path).reserve(request("one"), now=NOW)
    other = ClarificationStore(path)
    assert not other.reserve(request("two"), now=NOW)
    assert other.snapshot()["pending"]["id"] == "one"
    assert not other.reserve(request("one"), now=NOW)


def test_contending_send_claims_consume_budget_only_once(tmp_path):
    """Budget charging belongs to the winning durable sending transition."""
    path = tmp_path / "state.json"
    store = ClarificationStore(path)
    assert store.reserve(request("one"), now=NOW)
    budgets = []
    def attempt(_):
        return ClarificationStore(path).begin_send("one", now=NOW,
            budget=lambda: budgets.append(True) or True)
    with ThreadPoolExecutor(max_workers=2) as workers:
        results = list(workers.map(attempt, range(2)))
    assert sorted(results) == [False, True]
    assert budgets == [True]


def test_refused_send_budget_preserves_reserved_request(tmp_path):
    """A rejected proactive budget cannot create an uncertain transport send."""
    store = ClarificationStore(tmp_path / "state.json")
    assert store.reserve(request("one"), now=NOW)
    assert not store.begin_send("one", now=NOW, budget=lambda: False)
    assert store.snapshot()["pending"]["status"] == "reserved"


def test_delivery_and_decline_keep_topic_and_daily_budget(tmp_path):
    """Closing a question does not permit the same topic or a third question."""
    store = ClarificationStore(tmp_path / "clarification.json")
    assert store.reserve(request("one"), now=NOW)
    assert store.begin_send("one", now=NOW)
    assert store.mark_sent("one", external_id="$event", now=NOW)
    assert store.close("one", outcome="declined", now=NOW)
    assert not store.reserve(request("repeat"), now=NOW + timedelta(minutes=1))
    assert store.reserve(request("two", topic="partner_with_user"), now=NOW + timedelta(minutes=1))
    assert store.begin_send("two", now=NOW + timedelta(minutes=1))
    assert store.mark_sent("two", external_id="$event-2", now=NOW + timedelta(minutes=1))
    assert store.close("two", outcome="resolved", now=NOW + timedelta(minutes=1))
    assert not store.reserve(request("three", topic="kid1_with_user"), now=NOW + timedelta(minutes=2))


def test_uncertain_send_reserves_budget_across_restart(tmp_path):
    """A sending state is not discarded when no receipt is available."""
    path = tmp_path / "clarification.json"
    store = ClarificationStore(path)
    assert store.reserve(request("one"), now=NOW)
    assert store.begin_send("one", now=NOW)
    assert ClarificationStore(path).snapshot()["pending"]["status"] == "sending"
    assert not ClarificationStore(path).reserve(request("two"), now=NOW)


def test_expiry_closes_pending_without_reusing_same_topic(tmp_path):
    """A missed slot clears pending while retaining the day's reservation."""
    store = ClarificationStore(tmp_path / "clarification.json")
    assert store.reserve(request("one"), now=NOW)
    assert store.expire(now=NOW + timedelta(minutes=12))
    assert store.snapshot()["pending"] is None
    assert not store.reserve(request("repeat"), now=NOW + timedelta(minutes=13))
    assert store.reserve(request("two", topic="partner_with_user", minutes_until_slot=24), now=NOW + timedelta(minutes=13))


def test_concurrent_workers_reserve_once(tmp_path):
    """Two independent store objects cannot both claim the open slot."""
    path = tmp_path / "clarification.json"

    def attempt(identifier: str) -> bool:
        return ClarificationStore(path).reserve(request(identifier), now=NOW)

    with ThreadPoolExecutor(max_workers=2) as pool:
        result = list(pool.map(attempt, ("one", "two")))
    assert sorted(result) == [False, True]
    assert len(ClarificationStore(path).snapshot()["requests"]) == 1


def test_corrupt_ledger_fails_closed_and_preserves_bytes(tmp_path):
    """Invalid state cannot be silently reset to an empty budget."""
    path = tmp_path / "clarification.json"
    path.write_text('{"version": 999}', encoding="utf-8")
    original = path.read_bytes()
    store = ClarificationStore(path)
    with pytest.raises(ValueError):
        store.reserve(request("one"), now=NOW)
    assert path.read_bytes() == original


def test_atomic_write_failure_leaves_previous_ledger(tmp_path, monkeypatch):
    """An interrupted replacement cannot erase the previous reservation."""
    path = tmp_path / "clarification.json"
    store = ClarificationStore(path)
    assert store.reserve(request("one"), now=NOW)
    original = path.read_bytes()

    def fail_replace(*_args):
        raise OSError("simulated interruption")

    monkeypatch.setattr("memory.routine_context_clarification.os.replace", fail_replace)
    with pytest.raises(OSError):
        store.begin_send("one", now=NOW)
    assert path.read_bytes() == original
    assert json.loads(original)["requests"][0]["status"] == "reserved"


def test_rejects_nonlocal_or_late_reservation(tmp_path):
    """The question cannot be reserved at or after its scheduled slot."""
    store = ClarificationStore(tmp_path / "clarification.json")
    with pytest.raises(ValueError):
        store.reserve(request("one"), now=NOW.replace(tzinfo=None))
    assert not store.reserve(request("one"), now=NOW + timedelta(minutes=12))


def test_late_answer_cannot_close_sent_question(tmp_path):
    """A delivered question expires at its routine slot, without replay."""
    store = ClarificationStore(tmp_path / "clarification.json")
    assert store.reserve(request("one"), now=NOW)
    assert store.begin_send("one", now=NOW)
    assert store.mark_sent("one", external_id="$event", now=NOW)
    assert not store.close("one", outcome="resolved", now=NOW + timedelta(minutes=12))
    assert store.expire(now=NOW + timedelta(minutes=12))
    assert store.snapshot()["requests"][0]["status"] == "expired"


def test_corrupt_nested_value_is_rejected_without_reset(tmp_path):
    """Untrusted JSON with an invalid status cannot bypass the ledger."""
    path = tmp_path / "clarification.json"
    store = ClarificationStore(path)
    assert store.reserve(request("one"), now=NOW)
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["requests"][0]["status"] = ["reserved"]
    path.write_text(json.dumps(raw), encoding="utf-8")
    original = path.read_bytes()
    with pytest.raises(ValueError):
        store.reserve(request("two"), now=NOW)
    assert path.read_bytes() == original


def test_repeated_model_snapshot_is_claimed_once_across_restart(tmp_path):
    """Each unchanged snapshot invokes the semantic question model at most once."""
    path = tmp_path / "clarification.json"
    assert ClarificationStore(path).claim_evaluation("snapshot-a", now=NOW)
    assert not ClarificationStore(path).claim_evaluation("snapshot-a", now=NOW)
    assert ClarificationStore(path).claim_evaluation("snapshot-b", now=NOW)
