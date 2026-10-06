"""Channel-aware delivery boundary for assistant-authored text."""

from __future__ import annotations

from collections.abc import Callable

from core.messaging_channel import ExternalChannel
from services.external_delivery import (
    DeliveryReceipt,
    ExternalDeliveryRouter,
    external_delivery_router,
)

MessageRecorder = Callable[[ExternalChannel, str, str | None, str], None]


class AssistantHistoryError(RuntimeError):
    """Delivery succeeded; retry only recording, never the external send."""

    def __init__(self, receipt: DeliveryReceipt, repair: Callable[[], None]) -> None:
        super().__init__("Confirmed assistant delivery needs history repair")
        self.receipt = receipt
        self.repair = repair


def _record_confirmed_assistant_message(
    channel: ExternalChannel,
    text: str,
    agent: str | None,
    external_id: str,
) -> None:
    """Persist a confirmed outbound message in its own channel history."""
    from memory.conversation_history import append_message

    append_message(
        role="assistant",
        content=text,
        channel=channel,
        agent=agent,
        metadata={
            "transport": channel,
            "external_message_id": external_id,
        },
    )


def deliver_external_assistant_text(
    text: str,
    *,
    agent: str | None,
    router: ExternalDeliveryRouter = external_delivery_router,
    record_message: MessageRecorder = _record_confirmed_assistant_message,
    silent: bool = False,
) -> DeliveryReceipt:
    """Deliver once, then record only the confirmed selected-channel send."""
    receipt = router.send_text(text, silent=silent)
    def repair() -> None:
        """Record the immutable confirmed delivery without contacting transport."""
        record_message(receipt.channel, text, agent, receipt.external_id)
    try:
        repair()
    except Exception as exc:
        raise AssistantHistoryError(receipt, repair) from exc
    return receipt
