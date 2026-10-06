"""Offline contracts for channel-aware assistant text delivery."""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from services.external_delivery import ExternalDeliveryError, ExternalDeliveryRouter


@dataclass
class FakeTransport:
    texts: list[tuple[str, bool]] = field(default_factory=list)

    def send_text(self, text: str, *, silent: bool = False) -> str:
        self.texts.append((text, silent))
        return "event-42"

    def send_approval(self, request):  # pragma: no cover - irrelevant boundary
        raise AssertionError("approval delivery is outside this test")


def test_assistant_delivery_records_the_selected_channel_only() -> None:
    from services.external_assistant_delivery import deliver_external_assistant_text

    matrix = FakeTransport()
    router = ExternalDeliveryRouter(channel_selector=lambda: "matrix")
    router.register("matrix", matrix)
    recorded: list[tuple[str, str, str | None, str]] = []

    receipt = deliver_external_assistant_text(
        "υπενθύμιση",
        agent="Routine_Agent",
        router=router,
        record_message=lambda channel, text, agent, external_id: recorded.append(
            (channel, text, agent, external_id)
        ),
    )

    assert receipt.channel == "matrix"
    assert receipt.external_id == "event-42"
    assert matrix.texts == [("υπενθύμιση", False)]
    assert recorded == [
        ("matrix", "υπενθύμιση", "Routine_Agent", "event-42")
    ]


def test_assistant_delivery_does_not_record_a_failed_send() -> None:
    from services.external_assistant_delivery import deliver_external_assistant_text

    router = ExternalDeliveryRouter(channel_selector=lambda: "matrix")
    recorded: list[tuple[str, str, str | None, str]] = []

    with pytest.raises(ExternalDeliveryError, match="matrix"):
        deliver_external_assistant_text(
            "δεν στάλθηκε",
            agent="FollowUp_Agent",
            router=router,
            record_message=lambda channel, text, agent, external_id: recorded.append(
                (channel, text, agent, external_id)
            ),
        )

    assert recorded == []


def test_bot_retains_confirmed_receipt_when_history_fails(monkeypatch, tmp_path):
    """History failure must not make a successful Matrix send look retryable."""
    from clients import telegram_bot as bot
    from services.external_delivery import external_delivery_router
    from memory import conversation_history
    matrix = FakeTransport()
    monkeypatch.setattr(external_delivery_router, "_channel_selector", lambda: "matrix")
    monkeypatch.setattr(external_delivery_router, "_transports", {"matrix": matrix})
    tasks = []
    monkeypatch.setattr(bot, "enqueue_fast_task", lambda *args: tasks.append(args))
    original_append = conversation_history.append_message
    history_path = str(tmp_path / "history.db")
    failed_once = [True]
    def failed(**kwargs):
        if failed_once[0]:
            failed_once[0] = False
            raise OSError("history temporarily unavailable")
        return original_append(db_path=history_path, **kwargs)
    monkeypatch.setattr(conversation_history, "append_message", failed)
    assert bot._send_and_record_assistant("Reminder", agent="Routine_Agent") == "event-42"
    assert matrix.texts == [("Reminder", False)]
    assert len(tasks) == 1
    tasks[0][0]()
    tasks[0][0]()  # An uncertain history commit is idempotent by delivery ID.
    assert len(conversation_history.load_messages(db_path=history_path)) == 1
    assert matrix.texts == [("Reminder", False)]
