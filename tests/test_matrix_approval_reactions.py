"""Offline security contracts for Matrix approval reactions."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

import core.approval as approval
from services.matrix_approval import MatrixApprovalReactionService


@dataclass
class FakeTool:
    name: str = "mail_manager"
    calls: int = 0

    def invoke(self, args: dict) -> str:
        self.calls += 1
        return f"sent:{args.get('action')}"


@pytest.fixture
def approval_state(tmp_path, monkeypatch):
    monkeypatch.setattr(approval, "PENDING_FILE", str(tmp_path / "pending.json"))
    tool = FakeTool()
    service = MatrixApprovalReactionService(
        allowed_user_id="@owner:example.test",
        allowed_room_id="!private-room:example.test",
        tools_provider=lambda: [tool],
    )
    approval.save_pending(
        "mail_manager",
        {"action": "send"},
        "call-1",
        channel="matrix",
    )
    approval.record_pending_delivery(
        "call-1",
        delivery_channel="matrix",
        external_message_id="$approval-event",
    )
    return service, tool


@pytest.mark.parametrize("approval_key", ["👍", "👍️", "👍🏽", "✅"])
def test_trusted_approve_reaction_executes_exact_pending_action_once(
    approval_state,
    approval_key: str,
) -> None:
    service, tool = approval_state

    result = service.handle_reaction(
        room_id="!private-room:example.test",
        sender_id="@owner:example.test",
        authenticated=True,
        reacts_to="$approval-event",
        key=approval_key,
    )
    duplicate = service.handle_reaction(
        room_id="!private-room:example.test",
        sender_id="@owner:example.test",
        authenticated=True,
        reacts_to="$approval-event",
        key=approval_key,
    )

    assert result is not None
    assert result.status == "executed"
    assert result.tool_name == "mail_manager"
    assert result.origin_channel == "matrix"
    assert result.execution_result == "sent:send"
    assert tool.calls == 1
    assert duplicate is None


@pytest.mark.parametrize(
    ("room_id", "sender_id", "authenticated"),
    [
        ("!other:example.test", "@owner:example.test", True),
        ("!private-room:example.test", "@other:example.test", True),
        ("!private-room:example.test", "@owner:example.test", False),
    ],
)
def test_untrusted_reaction_is_inert(
    approval_state,
    room_id: str,
    sender_id: str,
    authenticated: bool,
) -> None:
    service, tool = approval_state

    result = service.handle_reaction(
        room_id=room_id,
        sender_id=sender_id,
        authenticated=authenticated,
        reacts_to="$approval-event",
        key="✅",
    )

    assert result is None
    assert tool.calls == 0
    assert approval.get_pending("call-1") is not None


def test_unrelated_reaction_or_message_is_inert(approval_state) -> None:
    service, tool = approval_state

    assert service.handle_reaction(
        room_id="!private-room:example.test",
        sender_id="@owner:example.test",
        authenticated=True,
        reacts_to="$unrelated",
        key="✅",
    ) is None
    assert service.handle_reaction(
        room_id="!private-room:example.test",
        sender_id="@owner:example.test",
        authenticated=True,
        reacts_to="$approval-event",
        key="🙂",
    ) is None
    assert service.handle_reaction(
        room_id="!private-room:example.test",
        sender_id="@owner:example.test",
        authenticated=True,
        reacts_to="$approval-event",
        key="ναι",
    ) is None

    assert tool.calls == 0
    assert approval.get_pending("call-1") is not None


def test_messenger_tool_error_is_not_treated_as_sent(tmp_path, monkeypatch) -> None:
    """An approved Messenger tool can return failure text without raising."""
    monkeypatch.setattr(approval, "PENDING_FILE", str(tmp_path / "pending.json"))

    @dataclass
    class FailingMessengerTool:
        name: str = "execute_local_pipeline"

        def invoke(self, args: dict) -> str:
            return "❌ Error Messenger: unavailable"

    service = MatrixApprovalReactionService(
        allowed_user_id="@owner:example.test",
        allowed_room_id="!private-room:example.test",
        tools_provider=lambda: [FailingMessengerTool()],
    )
    approval.save_pending("execute_local_pipeline", {}, "call-send", channel="matrix")
    approval.record_pending_delivery(
        "call-send", delivery_channel="matrix", external_message_id="$send",
    )

    result = service.handle_reaction(
        room_id="!private-room:example.test",
        sender_id="@owner:example.test",
        authenticated=True,
        reacts_to="$send",
        key="👍",
    )

    assert result is not None
    assert result.status == "failed"
    assert "unavailable" in (result.error or "")


def test_messenger_tool_success_is_reported_as_sent(tmp_path, monkeypatch) -> None:
    """Only the actual success result produces a completed-send outcome."""
    monkeypatch.setattr(approval, "PENDING_FILE", str(tmp_path / "pending.json"))

    @dataclass
    class SuccessfulMessengerTool:
        name: str = "execute_local_pipeline"

        def invoke(self, args: dict) -> str:
            return "✅ Το μήνυμα στάλθηκε στη Σοφία!"

    service = MatrixApprovalReactionService(
        allowed_user_id="@owner:example.test",
        allowed_room_id="!private-room:example.test",
        tools_provider=lambda: [SuccessfulMessengerTool()],
    )
    approval.save_pending("execute_local_pipeline", {}, "call-send", channel="web")
    approval.record_pending_delivery(
        "call-send", delivery_channel="matrix", external_message_id="$send",
    )

    result = service.handle_reaction(
        room_id="!private-room:example.test",
        sender_id="@owner:example.test",
        authenticated=True,
        reacts_to="$send",
        key="👍",
    )

    assert result is not None
    assert result.status == "executed"
    assert result.origin_channel == "web"
    assert approval.get_pending("call-send") is None


@pytest.mark.parametrize("rejection_key", ["👎", "👎️", "👎🏻", "❌"])
def test_trusted_reject_reaction_removes_pending_without_execution(
    approval_state,
    rejection_key: str,
) -> None:
    service, tool = approval_state

    result = service.handle_reaction(
        room_id="!private-room:example.test",
        sender_id="@owner:example.test",
        authenticated=True,
        reacts_to="$approval-event",
        key=rejection_key,
    )

    assert result is not None
    assert result.status == "rejected"
    assert result.tool_name == "mail_manager"
    assert tool.calls == 0
    assert approval.get_pending("call-1") is None
