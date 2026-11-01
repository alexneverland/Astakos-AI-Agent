"""Offline contracts for one-channel external delivery routing."""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from services.external_delivery import (
    ApprovalDeliveryRequest,
    ExternalDeliveryError,
    ExternalDeliveryRouter,
)


@dataclass
class FakeTransport:
    texts: list[tuple[str, bool]] = field(default_factory=list)
    approvals: list[ApprovalDeliveryRequest] = field(default_factory=list)

    def send_text(self, text: str, *, silent: bool = False) -> str:
        self.texts.append((text, silent))
        return f"text-{len(self.texts)}"

    def send_approval(self, request: ApprovalDeliveryRequest) -> str:
        self.approvals.append(request)
        return f"approval-{len(self.approvals)}"


def test_text_goes_only_to_selected_external_channel() -> None:
    telegram = FakeTransport()
    matrix = FakeTransport()
    router = ExternalDeliveryRouter(channel_selector=lambda: "matrix")
    router.register("telegram", telegram)
    router.register("matrix", matrix)

    receipt = router.send_text("μόνο Matrix", silent=True)

    assert receipt.channel == "matrix"
    assert receipt.external_id == "text-1"
    assert matrix.texts == [("μόνο Matrix", True)]
    assert telegram.texts == []


def test_approval_goes_only_to_selected_external_channel() -> None:
    telegram = FakeTransport()
    matrix = FakeTransport()
    router = ExternalDeliveryRouter(channel_selector=lambda: "telegram")
    router.register("telegram", telegram)
    router.register("matrix", matrix)
    request = ApprovalDeliveryRequest(
        call_id="call-1",
        tool_name="mail_manager",
        args_preview="action='send'",
        prompt="Να σταλεί;",
    )

    receipt = router.send_approval(request)

    assert receipt.channel == "telegram"
    assert receipt.external_id == "approval-1"
    assert telegram.approvals == [request]
    assert matrix.approvals == []


def test_missing_selected_transport_fails_without_fallback() -> None:
    telegram = FakeTransport()
    router = ExternalDeliveryRouter(channel_selector=lambda: "matrix")
    router.register("telegram", telegram)

    with pytest.raises(ExternalDeliveryError, match="matrix"):
        router.send_text("δεν πρέπει να πάει Telegram")

    assert telegram.texts == []


def test_transport_failure_is_not_retried_on_other_channel() -> None:
    class FailingTransport(FakeTransport):
        def send_text(self, text: str, *, silent: bool = False) -> str:
            raise RuntimeError("offline")

    telegram = FakeTransport()
    router = ExternalDeliveryRouter(channel_selector=lambda: "matrix")
    router.register("telegram", telegram)
    router.register("matrix", FailingTransport())

    with pytest.raises(ExternalDeliveryError, match="matrix"):
        router.send_text("μία προσπάθεια")

    assert telegram.texts == []


def test_registration_rejects_unknown_channel_and_blank_payload() -> None:
    router = ExternalDeliveryRouter(channel_selector=lambda: "matrix")
    transport = FakeTransport()

    with pytest.raises(ValueError, match="channel"):
        router.register("email", transport)  # type: ignore[arg-type]

    router.register("matrix", transport)
    with pytest.raises(ValueError, match="text"):
        router.send_text("   ")
