"""Regression coverage for scheduled text crossing the external boundary."""

from __future__ import annotations

from dataclasses import dataclass, field

from services.external_delivery import external_delivery_router


@dataclass
class FakeTransport:
    external_id: str
    texts: list[str] = field(default_factory=list)

    def send_text(self, text: str, *, silent: bool = False) -> str:
        del silent
        self.texts.append(text)
        return self.external_id

    def send_approval(self, request):  # pragma: no cover - outside this slice
        raise AssertionError("approval delivery is outside this test")


def test_scheduled_assistant_text_uses_matrix_history_when_matrix_is_selected(
    monkeypatch,
) -> None:
    import clients.telegram_bot as bot
    import memory.conversation_history as conversation_history

    transport = FakeTransport("$matrix-event")
    stored: list[dict] = []
    monkeypatch.setenv("ASTAKOS_EXTERNAL_CHANNEL", "matrix")
    monkeypatch.setattr(
        conversation_history,
        "append_message",
        lambda **kwargs: stored.append(kwargs) or kwargs,
    )
    external_delivery_router.register("matrix", transport)

    try:
        external_id = bot._send_and_record_assistant(
            "ώρα για ύπνο",
            agent="Routine_Agent",
        )
    finally:
        external_delivery_router.unregister("matrix")

    assert external_id == "$matrix-event"
    assert transport.texts == ["ώρα για ύπνο"]
    assert stored == [
        {
            "role": "assistant",
            "content": "ώρα για ύπνο",
            "channel": "matrix",
            "agent": "Routine_Agent",
            "metadata": {
                "transport": "matrix",
                "external_message_id": "$matrix-event",
            },
        }
    ]


def test_default_scheduled_assistant_text_preserves_telegram_history(
    monkeypatch,
) -> None:
    import clients.telegram_bot as bot

    transport = FakeTransport("73")
    recorded: list[tuple[str, str, str | None, dict | None]] = []
    monkeypatch.delenv("ASTAKOS_EXTERNAL_CHANNEL", raising=False)
    monkeypatch.setattr(
        bot,
        "_append_to_analytics_log",
        lambda role, content, agent=None, metadata=None: recorded.append(
            (role, content, agent, metadata)
        ),
    )
    external_delivery_router.register("telegram", transport)

    try:
        external_id = bot._send_and_record_assistant(
            "καλημέρα",
            agent="Proactive_Agent",
        )
    finally:
        bot._register_telegram_external_transport()

    assert external_id == "73"
    assert transport.texts == ["καλημέρα"]
    assert recorded == [
        (
            "ai",
            "καλημέρα",
            "Proactive_Agent",
            {"transport": "telegram", "external_message_id": "73"},
        )
    ]
