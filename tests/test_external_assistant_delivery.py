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
