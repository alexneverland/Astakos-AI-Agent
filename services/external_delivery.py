"""Canonical one-channel delivery boundary for external messaging."""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from core.messaging_channel import ExternalChannel, resolve_external_channel


class ExternalDeliveryError(RuntimeError):
    """Raised when the selected external transport cannot deliver a message."""


@dataclass(frozen=True)
class ApprovalDeliveryRequest:
    """Channel-neutral content required to render one approval request."""

    call_id: str
    tool_name: str
    args_preview: str
    prompt: str

    def __post_init__(self) -> None:
        for field_name in ("call_id", "tool_name", "prompt"):
            if not str(getattr(self, field_name) or "").strip():
                raise ValueError(f"Approval delivery requires {field_name}")


@dataclass(frozen=True)
class DeliveryReceipt:
    """Minimal transport-neutral proof of one successful delivery."""

    channel: ExternalChannel
    external_id: str


class ExternalTransport(Protocol):
    """Synchronous adapter contract used by background and graph workers."""

    def send_text(self, text: str, *, silent: bool = False) -> str | int | None:
        """Send one text message and return its external identifier."""

    def send_approval(
        self,
        request: ApprovalDeliveryRequest,
    ) -> str | int | None:
        """Send one actionable approval request and return its identifier."""


class ExternalDeliveryRouter:
    """Route each outbound item to exactly one configured external channel."""

    def __init__(
        self,
        *,
        channel_selector: Callable[[], ExternalChannel] = resolve_external_channel,
    ) -> None:
        self._channel_selector = channel_selector
        self._transports: dict[ExternalChannel, ExternalTransport] = {}
        self._lock = threading.RLock()

    def register(
        self,
        channel: ExternalChannel,
        transport: ExternalTransport,
    ) -> None:
        """Register or replace the adapter for one supported channel."""
        if channel not in {"telegram", "matrix"}:
            raise ValueError("External delivery requires a supported channel")
        if transport is None:
            raise ValueError("External delivery requires a transport")
        with self._lock:
            self._transports[channel] = transport

    def unregister(self, channel: ExternalChannel) -> None:
        """Remove one adapter without affecting the other channel."""
        with self._lock:
            self._transports.pop(channel, None)

    def _selected_transport(self) -> tuple[ExternalChannel, ExternalTransport]:
        channel = self._channel_selector()
        with self._lock:
            transport = self._transports.get(channel)
        if transport is None:
            raise ExternalDeliveryError(
                f"Selected external transport '{channel}' is not available"
            )
        return channel, transport

    @staticmethod
    def _receipt(channel: ExternalChannel, external_id: str | int | None) -> DeliveryReceipt:
        if external_id is None or not str(external_id).strip():
            raise ExternalDeliveryError(
                f"Selected external transport '{channel}' did not confirm delivery"
            )
        return DeliveryReceipt(channel=channel, external_id=str(external_id))

    def send_text(self, text: str, *, silent: bool = False) -> DeliveryReceipt:
        """Send text only through the selected channel, never a fallback."""
        normalized = str(text or "").strip()
        if not normalized:
            raise ValueError("External delivery requires text")
        channel, transport = self._selected_transport()
        try:
            external_id = transport.send_text(normalized, silent=silent)
        except Exception as exc:
            raise ExternalDeliveryError(
                f"Selected external transport '{channel}' failed"
            ) from exc
        return self._receipt(channel, external_id)

    def send_text_to(
        self, channel: ExternalChannel, text: str, *, silent: bool = False
    ) -> DeliveryReceipt:
        """Send only if a queued item's original channel is still selected."""
        selected, transport = self._selected_transport()
        if channel != selected:
            raise ExternalDeliveryError("Queued external channel is not selected")
        normalized = str(text or "").strip()
        if not normalized:
            raise ValueError("External delivery requires text")
        try:
            external_id = transport.send_text(normalized, silent=silent)
        except Exception as exc:
            raise ExternalDeliveryError(
                f"Selected external transport '{channel}' failed"
            ) from exc
        return self._receipt(channel, external_id)

    def send_matrix_mirror_chunk_to(
        self, text: str, *, transaction_id: str
    ) -> DeliveryReceipt:
        """Send a retriable Matrix mirror chunk with a stable transaction ID."""
        selected, transport = self._selected_transport()
        if selected != "matrix":
            raise ExternalDeliveryError("Matrix mirror target is not selected")
        sender = getattr(transport, "send_mirror_chunk", None)
        if not callable(sender):
            raise ExternalDeliveryError("Selected Matrix transport cannot send mirror chunks")
        try:
            external_id = sender(text, transaction_id=transaction_id)
        except Exception as exc:
            raise ExternalDeliveryError("Selected Matrix mirror chunk failed") from exc
        return self._receipt("matrix", external_id)

    def send_approval(self, request: ApprovalDeliveryRequest) -> DeliveryReceipt:
        """Send an approval only through the selected channel."""
        channel, transport = self._selected_transport()
        try:
            external_id = transport.send_approval(request)
        except Exception as exc:
            raise ExternalDeliveryError(
                f"Selected external transport '{channel}' failed"
            ) from exc
        return self._receipt(channel, external_id)


external_delivery_router = ExternalDeliveryRouter()
