"""Telegram adapter for the canonical external-delivery router."""

from __future__ import annotations

from collections.abc import Callable

from services.external_delivery import ApprovalDeliveryRequest

TelegramSender = Callable[[str, bool], str | int | None]


def _send_message(text: str, silent: bool) -> str | int | None:
    from tools.telegram import send_telegram_msg

    return send_telegram_msg(text, disable_notification=silent)


def _send_full_message(text: str, silent: bool) -> str | int | None:
    from tools.telegram import send_telegram_msg_full

    return send_telegram_msg_full(text, disable_notification=silent)


class TelegramExternalTransport:
    """Adapt the existing Telegram text senders to the shared router."""

    def __init__(
        self,
        *,
        send_message: TelegramSender = _send_message,
        send_full_message: TelegramSender = _send_full_message,
    ) -> None:
        self._send_message = send_message
        self._send_full_message = send_full_message

    def send_text(self, text: str, *, silent: bool = False) -> str | int | None:
        """Send one text, preserving the existing Telegram chunking threshold."""
        normalized = str(text or "").strip()
        if not normalized:
            raise ValueError("Telegram delivery requires text")
        if len(normalized) <= 3500:
            return self._send_message(normalized, silent)
        return self._send_full_message(normalized, silent)

    def send_approval(self, request: ApprovalDeliveryRequest) -> str | int | None:
        """Keep approvals on their existing Telegram callback implementation."""
        del request
        raise RuntimeError("Telegram approvals use the dedicated callback flow")
