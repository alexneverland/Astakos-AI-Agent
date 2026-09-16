"""Synchronous external-delivery adapter for a running Matrix client."""

from __future__ import annotations

from collections.abc import Callable

from core.approval import record_pending_delivery
from services.external_delivery import ApprovalDeliveryRequest

MatrixTextSender = Callable[[str], str | int | None]


class MatrixExternalTransport:
    """Adapt one running encrypted Matrix room to external-delivery contracts."""

    def __init__(
        self,
        *,
        send_text: MatrixTextSender,
        approval_reaction_hint: str,
    ) -> None:
        self._send_text = send_text
        self._approval_reaction_hint = str(approval_reaction_hint or "").strip()
        if not self._approval_reaction_hint:
            raise ValueError("Matrix approval delivery requires a reaction hint")

    def send_text(self, text: str, *, silent: bool = False) -> str | int | None:
        """Send text through the injected encrypted-room sender."""
        del silent  # Matrix has no Telegram-equivalent silent flag in this adapter.
        normalized = str(text or "").strip()
        if not normalized:
            raise ValueError("Matrix delivery requires text")
        return self._send_text(normalized)

    def send_approval(self, request: ApprovalDeliveryRequest) -> str | int:
        """Send and durably correlate one actionable Matrix approval prompt."""
        text = f"{request.prompt.strip()}\n\n{self._approval_reaction_hint}"
        external_id = self.send_text(text)
        if external_id is None or not str(external_id).strip():
            raise RuntimeError("Matrix approval delivery returned no event id")
        record_pending_delivery(
            request.call_id,
            delivery_channel="matrix",
            external_message_id=str(external_id),
        )
        return external_id
