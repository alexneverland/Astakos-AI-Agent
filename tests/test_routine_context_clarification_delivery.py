"""Offline, persisted delivery lifecycle for one routine clarification."""

from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from memory.routine_context_clarification import ClarificationStore, QuestionRequest
from services.routine_context_clarification import deliver_question


NOW = datetime(2026, 10, 6, 10, 0, tzinfo=ZoneInfo("Europe/Athens"))


def question(channel: str = "matrix") -> QuestionRequest:
    """Construct one bounded question without touching production data."""
    return QuestionRequest(
        id="question-1", topic="location", routine_ids=("routine-1",),
        flags=("user_out_of_home",), slot_at=NOW + timedelta(minutes=12),
        question="Γυρίσατε σπίτι;", channel=channel,
    )


def test_delivered_question_records_once_and_does_not_resend(tmp_path):
    """A second worker repairs/checks history but never delivers again."""
    store = ClarificationStore(tmp_path / "state.json")
    sent, recorded, budgets = [], [], []

    def sender(channel, text, identity):
        sent.append((channel, text, identity))
        return SimpleNamespace(channel=channel, external_id="$one")

    def budget():
        budgets.append(True)
        return True

    kwargs = dict(store=store, question=question(), now=NOW,
                  selected_channel=lambda: "matrix", still_current=lambda: True,
                  budget=budget, sender=sender,
                  record=lambda **data: recorded.append(data))
    assert deliver_question(**kwargs) == "delivered"
    assert deliver_question(**kwargs) == "recorded"
    assert len(sent) == len(budgets) == len(recorded) == 1
    assert recorded[0]["message_id"] == "routine-clarification-question-1"
    assert store.snapshot()["pending"]["status"] == "sent"


def test_matrix_uncertain_send_uses_same_transaction_on_recovery(tmp_path):
    """An unknown first Matrix result can retry with its stable identity."""
    path = tmp_path / "state.json"
    calls = []

    def sender(channel, text, identity):
        calls.append(identity)
        if len(calls) == 1:
            raise TimeoutError("receipt lost")
        return SimpleNamespace(channel=channel, external_id="$one")

    args = dict(question=question(), now=NOW, selected_channel=lambda: "matrix",
                still_current=lambda: True, budget=lambda: True,
                sender=sender, record=lambda **_: None)
    assert deliver_question(store=ClarificationStore(path), **args) == "held"
    assert ClarificationStore(path).snapshot()["pending"]["status"] == "sending"
    assert deliver_question(store=ClarificationStore(path), **args) == "delivered"
    assert calls == ["astakos-routine-question-question-1"] * 2


def test_telegram_uncertain_send_is_held(tmp_path):
    """A Telegram timeout cannot authorize another outbound attempt."""
    path = tmp_path / "state.json"
    calls = []

    def sender(channel, text, identity):
        calls.append(identity)
        raise TimeoutError("uncertain")

    args = dict(question=question("telegram"), now=NOW,
                selected_channel=lambda: "telegram", still_current=lambda: True,
                budget=lambda: True, sender=sender, record=lambda **_: None)
    assert deliver_question(store=ClarificationStore(path), **args) == "held"
    assert deliver_question(store=ClarificationStore(path), **args) == "held"
    assert len(calls) == 1


def test_history_failure_repairs_from_receipt_without_resending(tmp_path):
    """Durable receipt survives a failed local history write."""
    path = tmp_path / "state.json"
    sends, writes = [], []

    def sender(channel, text, identity):
        sends.append(identity)
        return SimpleNamespace(channel=channel, external_id="$one")

    def record(**data):
        writes.append(data)
        if len(writes) == 1:
            raise OSError("history unavailable")

    args = dict(question=question(), now=NOW,
                selected_channel=lambda: "matrix", still_current=lambda: True,
                budget=lambda: True, sender=sender, record=record)
    assert deliver_question(store=ClarificationStore(path), **args) == "held"
    assert ClarificationStore(path).snapshot()["pending"]["external_id"] == "$one"
    assert deliver_question(store=ClarificationStore(path), **args) == "recorded"
    assert len(sends) == 1
    assert writes[0]["message_id"] == writes[1]["message_id"]


def test_stale_generation_and_wrong_channel_do_not_consume_budget(tmp_path):
    """Rechecked eligibility precedes reservation, budget and outbound I/O."""
    path = tmp_path / "state.json"

    def forbidden(*_args, **_kwargs):
        raise AssertionError("No budget or delivery call")

    args = dict(store=ClarificationStore(path), question=question(), now=NOW,
                budget=forbidden, sender=forbidden, record=forbidden)
    assert deliver_question(**args, selected_channel=lambda: "matrix",
                            still_current=lambda: False) == "stale"
    assert deliver_question(**args, selected_channel=lambda: "telegram",
                            still_current=lambda: True) == "stale"
    assert not path.exists()


def test_confirmed_history_repairs_after_deadline_and_channel_change(tmp_path):
    """Receipt repair is local bookkeeping, not a new late outbound question."""
    store = ClarificationStore(tmp_path / "state.json")
    request = question()
    assert store.reserve(request, now=NOW)
    assert store.begin_send(request.id, now=NOW)
    assert store.mark_sent(request.id, external_id="$one", now=NOW)
    recorded = []

    def forbidden(*args, **kwargs):
        raise AssertionError("No outbound action or budget during receipt repair")

    assert deliver_question(
        store=store, question=request, now=NOW + timedelta(minutes=20),
        selected_channel=lambda: "telegram", still_current=lambda: False,
        budget=forbidden, sender=forbidden, record=lambda **data: recorded.append(data),
    ) == "recorded"
    assert recorded[0]["timestamp"] == NOW


def test_delivery_receipt_uses_actual_clock_after_slow_send(tmp_path):
    """The recorded timestamp is acknowledgement time, not worker entry time."""
    store = ClarificationStore(tmp_path / "state.json")
    clock = [NOW]

    def sender(channel, text, identity):
        clock[0] += timedelta(minutes=2)
        return SimpleNamespace(channel=channel, external_id="$one")

    recorded = []
    assert deliver_question(
        store=store, question=question(), now=NOW,
        current_time=lambda: clock[0], selected_channel=lambda: "matrix",
        still_current=lambda: True, budget=lambda: True, sender=sender,
        record=lambda **data: recorded.append(data),
    ) == "delivered"
    assert recorded[0]["timestamp"] == NOW + timedelta(minutes=2)


def test_clock_crosses_deadline_before_send(tmp_path):
    """Budget bookkeeping cannot permit an already expired question to be sent."""
    store = ClarificationStore(tmp_path / "state.json")
    clock = [NOW]

    def budget():
        clock[0] += timedelta(minutes=13)
        return True

    def forbidden(*args, **kwargs):
        raise AssertionError("No send after deadline")

    assert deliver_question(
        store=store, question=question(), now=NOW,
        current_time=lambda: clock[0], selected_channel=lambda: "matrix",
        still_current=lambda: True, budget=budget, sender=forbidden, record=forbidden,
    ) == "held"


def test_expired_receipt_still_repairs_history(tmp_path):
    """Expiry cannot erase bookkeeping for a question already delivered."""
    store = ClarificationStore(tmp_path / "state.json")
    request = question()
    assert store.reserve(request, now=NOW)
    assert store.begin_send(request.id, now=NOW)
    assert store.mark_sent(request.id, external_id="$one", now=NOW)
    later = NOW + timedelta(minutes=20)
    store.expire(now=later)
    writes = []

    def forbidden(*args, **kwargs):
        raise AssertionError("No late outbound action")

    assert deliver_question(
        store=store, question=request, now=later,
        selected_channel=lambda: "telegram", still_current=lambda: False,
        budget=forbidden, sender=forbidden, record=lambda **data: writes.append(data),
    ) == "recorded"
    assert len(writes) == 1
    assert store.snapshot()["requests"][0]["status"] == "expired"
    assert store.snapshot()["requests"][0]["history_recorded"] is True
