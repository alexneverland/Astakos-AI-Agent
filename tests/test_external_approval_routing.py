"""Offline routing tests for approval notifications across external channels."""

from __future__ import annotations

from langchain_core.messages import AIMessage

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


def test_matrix_selection_routes_critical_approval_without_telegram(
    tmp_path,
    monkeypatch,
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
            {"messages": [message], "channel": "matrix"}
        )
    finally:
        external_delivery_router.unregister("matrix")

    assert result["approval_status"] == "pending"
    assert telegram_calls == []
    assert len(matrix.approvals) == 1
    assert matrix.approvals[0].call_id == "call-matrix"
    assert matrix.approvals[0].tool_name == "mail_manager"


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
