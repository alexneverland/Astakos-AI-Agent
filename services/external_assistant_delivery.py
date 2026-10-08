"""Channel-aware delivery boundary for assistant-authored text."""

from __future__ import annotations

from collections.abc import Callable
from hashlib import sha256

from core.messaging_channel import ExternalChannel
from services.external_delivery import (
    DeliveryReceipt,
    ExternalDeliveryRouter,
    external_delivery_router,
)

MessageRecorder = Callable[[ExternalChannel, str, str | None, str], None]


def assistant_delivery_message_id(channel: str, external_id: str) -> str:
    """Stable bounded history identity shared by confirmed delivery and recovery."""
    identity = f"assistant-delivery-{channel}-{external_id}"
    return identity if len(identity) <= 100 else "assistant-delivery-" + sha256(identity.encode()).hexdigest()


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
        message_id=assistant_delivery_message_id(channel, external_id),
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
    target_channel: ExternalChannel | None = None,
) -> DeliveryReceipt:
    """Deliver once, optionally pinning the selection, then record confirmation."""
    receipt = (router.send_text(text, silent=silent) if target_channel is None
               else router.send_text_to(target_channel, text, silent=silent))
    def repair() -> None:
        """Record the immutable confirmed delivery without contacting transport."""
        record_message(receipt.channel, text, agent, receipt.external_id)
    try:
        repair()
    except Exception as exc:
        raise AssistantHistoryError(receipt, repair) from exc
    return receipt
