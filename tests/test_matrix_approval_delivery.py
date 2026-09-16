"""Offline persistence contracts for Matrix approval delivery correlation."""

from __future__ import annotations

import pytest

import core.approval as approval


@pytest.fixture
def pending_file(tmp_path, monkeypatch) -> str:
    path = str(tmp_path / "pending.json")
    monkeypatch.setattr(approval, "PENDING_FILE", path)
    return path


def test_matrix_delivery_id_is_attached_to_one_pending_call(pending_file) -> None:
    approval.save_pending("mail_manager", {"action": "send"}, "call-1", channel="matrix")

    saved = approval.record_pending_delivery(
        "call-1",
        delivery_channel="matrix",
        external_message_id="$approval-event",
    )

    assert saved["tool_call_id"] == "call-1"
    assert saved["delivery_channel"] == "matrix"
    assert saved["external_message_id"] == "$approval-event"
    assert approval.find_pending_by_delivery(
        delivery_channel="matrix",
        external_message_id="$approval-event",
    )["tool_call_id"] == "call-1"


def test_delivery_lookup_does_not_cross_channels(pending_file) -> None:
    approval.save_pending("mail_manager", {}, "call-1", channel="web")
    approval.record_pending_delivery(
        "call-1",
        delivery_channel="matrix",
        external_message_id="$approval-event",
    )

    assert approval.find_pending_by_delivery(
        delivery_channel="telegram",
        external_message_id="$approval-event",
    ) is None


def test_external_delivery_id_cannot_be_reused_by_another_pending_call(pending_file) -> None:
    approval.save_pending("mail_manager", {}, "call-1", channel="matrix")
    approval.save_pending("drive_manager", {}, "call-2", channel="matrix")
    approval.record_pending_delivery(
        "call-1",
        delivery_channel="matrix",
        external_message_id="$approval-event",
    )

    with pytest.raises(ValueError, match="already mapped"):
        approval.record_pending_delivery(
            "call-2",
            delivery_channel="matrix",
            external_message_id="$approval-event",
        )


def test_unknown_or_resolved_call_cannot_receive_delivery_mapping(pending_file) -> None:
    with pytest.raises(KeyError, match="pending"):
        approval.record_pending_delivery(
            "missing",
            delivery_channel="matrix",
            external_message_id="$event",
        )

    approval.save_pending("mail_manager", {}, "call-1", channel="matrix")
    approval.pop_pending("call-1")
    with pytest.raises(KeyError, match="pending"):
        approval.record_pending_delivery(
            "call-1",
            delivery_channel="matrix",
            external_message_id="$event",
        )


@pytest.mark.parametrize("channel", ["", "web", "email"])
def test_delivery_mapping_accepts_only_external_channels(pending_file, channel: str) -> None:
    approval.save_pending("mail_manager", {}, "call-1", channel="matrix")

    with pytest.raises(ValueError, match="delivery_channel"):
        approval.record_pending_delivery(
            "call-1",
            delivery_channel=channel,
            external_message_id="$event",
        )
