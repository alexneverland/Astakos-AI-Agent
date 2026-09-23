"""Offline routing tests for approval notifications across external channels."""

from __future__ import annotations

from langchain_core.messages import AIMessage
import pytest

import core.approval as approval
from services.external_delivery import external_delivery_router


class FakeMatrixDelivery:
    def __init__(self) -> None:
        self.approvals = []
        self.texts = []

    def send_text(self, text: str, *, silent: bool = False) -> str:
        self.texts.append((text, silent))
        return "$notice"

    def send_approval(self, request) -> str:
        self.approvals.append(request)
        return "$approval"


@pytest.mark.parametrize("origin_channel", ["web", "matrix"])
def test_matrix_selection_routes_critical_approval_without_telegram(
    tmp_path,
    monkeypatch,
    origin_channel: str,
) -> None:
    monkeypatch.setenv("ASTAKOS_EXTERNAL_CHANNEL", "matrix")
    monkeypatch.setattr(approval, "PENDING_FILE", str(tmp_path / "pending.json"))
    telegram_calls = []
    monkeypatch.setattr(
        approval,
        "_notify_telegram",
        lambda tool_call: telegram_calls.append(tool_call),
    )
    matrix = FakeMatrixDelivery()
    external_delivery_router.register("matrix", matrix)
    tool_call = {
        "name": "mail_manager",
        "args": {"action": "send"},
        "id": "call-matrix",
        "type": "tool_call",
    }
    message = AIMessage(content="", tool_calls=[tool_call])

    try:
        result = approval.approval_check_node(
            {"messages": [message], "channel": origin_channel}
        )
    finally:
        external_delivery_router.unregister("matrix")

    assert result["approval_status"] == "pending"
    assert telegram_calls == []
    assert len(matrix.approvals) == (0 if origin_channel == "web" else 1)
    if origin_channel == "matrix":
        assert matrix.approvals[0].call_id == "call-matrix"
        assert matrix.approvals[0].tool_name == "mail_manager"
    waiting = result["messages"][0].content
    assert "Element" in waiting
    assert "Telegram" not in waiting
    if origin_channel == "web":
        assert "ουρά" in waiting.lower()
        assert approval.get_pending("call-matrix")["delivery_status"] == "queued"


def test_default_selection_preserves_existing_telegram_approval(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.delenv("ASTAKOS_EXTERNAL_CHANNEL", raising=False)
    monkeypatch.setattr(approval, "PENDING_FILE", str(tmp_path / "pending.json"))
    telegram_calls = []
    monkeypatch.setattr(
        approval,
        "_notify_telegram",
        lambda tool_call: telegram_calls.append(tool_call),
    )
    tool_call = {
        "name": "mail_manager",
        "args": {"action": "send"},
        "id": "call-telegram",
        "type": "tool_call",
    }
    message = AIMessage(content="", tool_calls=[tool_call])

    result = approval.approval_check_node(
        {"messages": [message], "channel": "web"}
    )

    assert result["approval_status"] == "pending"
    assert telegram_calls == [tool_call]
    assert "Telegram" in result["messages"][0].content


def test_web_matrix_approval_without_matrix_transport_is_queued_for_delivery(
    tmp_path, monkeypatch,
) -> None:
    """The Web process must queue, not pretend Element received approval."""
    monkeypatch.setenv("ASTAKOS_EXTERNAL_CHANNEL", "matrix")
    monkeypatch.setattr(approval, "PENDING_FILE", str(tmp_path / "pending.json"))
    external_delivery_router.unregister("matrix")
    tool_call = {
        "name": "mail_manager", "args": {"action": "send"},
        "id": "call-undelivered", "type": "tool_call",
    }

    result = approval.approval_check_node({
        "messages": [AIMessage(content="", tool_calls=[tool_call])],
        "channel": "web",
    })

    assert result["approval_status"] == "pending"
    assert "Element" in result["messages"][0].content
    assert "έγκριση" in result["messages"][0].content.lower()
    assert "Έλεγξε" not in result["messages"][0].content
    assert approval.get_pending("call-undelivered")["delivery_status"] == "queued"


def test_matrix_worker_delivers_queued_web_approval_once(tmp_path, monkeypatch) -> None:
    """The Matrix process confirms delivery before a reply can resolve the call."""
    from services.pending_approval_delivery import drain_queued_matrix_approvals

    monkeypatch.setenv("ASTAKOS_EXTERNAL_CHANNEL", "matrix")
    monkeypatch.setattr(approval, "PENDING_FILE", str(tmp_path / "pending.json"))
    external_delivery_router.unregister("matrix")
    tool_call = {
        "name": "mail_manager", "args": {"action": "send"},
        "id": "call-cross-process", "type": "tool_call",
    }
    result = approval.approval_check_node({
        "messages": [AIMessage(content="", tool_calls=[tool_call])],
        "channel": "web",
    })
    assert result["approval_status"] == "pending"
    assert approval.find_pending_by_delivery(
        delivery_channel="matrix", external_message_id="$approval"
    ) is None
    assert drain_queued_matrix_approvals() == 0
    assert approval.get_pending("call-cross-process")["delivery_status"] == "queued"

    matrix = FakeMatrixDelivery()
    external_delivery_router.register("matrix", matrix)
    try:
        assert drain_queued_matrix_approvals() == 1
        assert drain_queued_matrix_approvals() == 0
    finally:
        external_delivery_router.unregister("matrix")

    assert len(matrix.approvals) == 1
    assert matrix.approvals[0].call_id == "call-cross-process"
    assert approval.find_pending_by_delivery(
        delivery_channel="matrix", external_message_id="$approval"
    )["tool_call_id"] == "call-cross-process"


def test_queued_web_approval_requires_trusted_matrix_reaction(tmp_path, monkeypatch) -> None:
    """A Web-origin action executes only after the matching trusted reaction."""
    from services.matrix_approval import MatrixApprovalReactionService
    from services.pending_approval_delivery import drain_queued_matrix_approvals

    class FakeTool:
        name = "mail_manager"

        def __init__(self) -> None:
            self.calls = 0

        def invoke(self, args: dict) -> str:
            self.calls += 1
            return "sent"

    monkeypatch.setenv("ASTAKOS_EXTERNAL_CHANNEL", "matrix")
    monkeypatch.setattr(approval, "PENDING_FILE", str(tmp_path / "pending.json"))
    tool_call = {
        "name": "mail_manager", "args": {"action": "send"},
        "id": "call-web-reaction", "type": "tool_call",
    }
    approval.approval_check_node({
        "messages": [AIMessage(content="", tool_calls=[tool_call])],
        "channel": "web",
    })
    matrix = FakeMatrixDelivery()
    external_delivery_router.register("matrix", matrix)
    try:
        assert drain_queued_matrix_approvals() == 1
    finally:
        external_delivery_router.unregister("matrix")

    tool = FakeTool()
    service = MatrixApprovalReactionService(
        allowed_user_id="@owner:example.test",
        allowed_room_id="!private:example.test",
        tools_provider=lambda: [tool],
    )
    reaction = dict(
        room_id="!private:example.test", sender_id="@owner:example.test",
        reacts_to="$approval", key="👍",
    )
    assert service.handle_reaction(**reaction, authenticated=False) is None
    assert tool.calls == 0
    result = service.handle_reaction(**reaction, authenticated=True)
    assert result is not None and result.status == "executed"
    assert result.origin_channel == "web"
    assert tool.calls == 1
    assert service.handle_reaction(**reaction, authenticated=True) is None


def test_matrix_selection_routes_notify_without_telegram(monkeypatch) -> None:
    """NOTIFY-risk arguments stay on the selected Matrix channel."""
    monkeypatch.setenv("ASTAKOS_EXTERNAL_CHANNEL", "matrix")
    telegram_calls = []
    monkeypatch.setattr(
        approval,
        "_notify_telegram_notify",
        lambda tool_call: telegram_calls.append(tool_call),
    )
    matrix = FakeMatrixDelivery()
    external_delivery_router.register("matrix", matrix)
    tool_call = {
        "name": "drive_manager",
        "args": {"action": "upload", "path": "private.txt"},
        "id": "call-notify",
        "type": "tool_call",
    }
    message = AIMessage(content="", tool_calls=[tool_call])

    try:
        result = approval.approval_check_node(
            {"messages": [message], "channel": "matrix"}
        )
    finally:
        external_delivery_router.unregister("matrix")

    assert result["approval_status"] == "ok"
    assert telegram_calls == []
    assert len(matrix.texts) == 1
    assert "drive_manager" in matrix.texts[0][0]
    assert "private.txt" in matrix.texts[0][0]
