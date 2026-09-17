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
    record_message(receipt.channel, text, agent, receipt.external_id)
    return receipt
