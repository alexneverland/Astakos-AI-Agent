"""Offline contracts for Matrix outbound delivery adapter behavior."""

from __future__ import annotations

import pytest

import core.approval as approval
from clients.matrix_delivery import MatrixExternalTransport
from services.external_delivery import ApprovalDeliveryRequest


@pytest.fixture
def pending_file(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(approval, "PENDING_FILE", str(tmp_path / "pending.json"))


def test_matrix_text_uses_injected_encrypted_room_sender(pending_file) -> None:
    sent: list[str] = []
    transport = MatrixExternalTransport(
        send_text=lambda text: sent.append(text) or "$matrix-text",
        approval_reaction_hint="Αντέδρασε ✅ ή ❌ σε αυτό το μήνυμα.",
    )

    external_id = transport.send_text("Καλημέρα", silent=True)

    assert external_id == "$matrix-text"
    assert sent == ["Καλημέρα"]


def test_matrix_approval_records_exact_sent_event_id(pending_file) -> None:
    approval.save_pending("mail_manager", {}, "call-1", channel="matrix")
    sent: list[str] = []
    transport = MatrixExternalTransport(
        send_text=lambda text: sent.append(text) or "$matrix-approval",
        approval_reaction_hint="Αντέδρασε ✅ ή ❌ σε αυτό το μήνυμα.",
    )
    request = ApprovalDeliveryRequest(
        call_id="call-1",
        tool_name="mail_manager",
        args_preview="action='send'",
        prompt="Απαιτείται έγκριση για mail_manager.",
    )

    external_id = transport.send_approval(request)

    assert external_id == "$matrix-approval"
    assert sent == [
        "Απαιτείται έγκριση για mail_manager.\n\n"
        "Αντέδρασε ✅ ή ❌ σε αυτό το μήνυμα."
    ]
    pending = approval.get_pending("call-1")
    assert pending["delivery_channel"] == "matrix"
    assert pending["external_message_id"] == "$matrix-approval"


def test_matrix_approval_without_confirmed_event_id_does_not_create_mapping(
    pending_file,
) -> None:
    approval.save_pending("mail_manager", {}, "call-1", channel="matrix")
    transport = MatrixExternalTransport(
        send_text=lambda text: None,
        approval_reaction_hint="React.",
    )
    request = ApprovalDeliveryRequest(
        call_id="call-1",
        tool_name="mail_manager",
        args_preview="—",
        prompt="Approve?",
    )

    with pytest.raises(RuntimeError, match="event id"):
        transport.send_approval(request)

    assert "external_message_id" not in approval.get_pending("call-1")
