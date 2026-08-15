"""Tests for Telegram callback query authorization and pending action approval security."""

from typing import Any, Dict
from unittest.mock import patch
import pytest
import requests

import clients.telegram_bot as bot


@pytest.fixture(autouse=True)
def _reset_bot_chat_id(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensures TELEGRAM_CHAT_ID is reset to a predictable test value for each test."""
    monkeypatch.setattr(bot, "TELEGRAM_CHAT_ID", "12345678")
    monkeypatch.setattr(bot, "TELEGRAM_TOKEN", "fake_bot_token")


def _build_callback_query(
    action: str,
    tool_call_id: str,
    from_id: str,
    chat_id: str,
    cq_id: str = "cq_999",
    msg_id: int = 42,
) -> Dict[str, Any]:
    """Helper to construct a mock Telegram callback_query payload."""
    return {
        "id": cq_id,
        "from": {"id": int(from_id) if from_id.isdigit() else from_id, "is_bot": False},
        "message": {
            "message_id": msg_id,
            "chat": {"id": int(chat_id) if chat_id.isdigit() else chat_id, "type": "private"},
        },
        "data": f"{action}:{tool_call_id}",
    }


def test_unauthorized_user_approve_callback_blocked_without_execution() -> None:
    """Proves that a callback query from an unauthorized user ID cannot approve or execute pending tools."""
    cq = _build_callback_query(
        action="approve",
        tool_call_id="call-sec-1",
        from_id="99999999",  # Attacker user ID
        chat_id="99999999",  # Attacker chat ID
    )

    with patch("core.approval.execute_approved_pending") as mock_exec, \
         patch("core.approval.get_pending") as mock_get, \
         patch("core.approval.pop_pending") as mock_pop, \
         patch("requests.post") as mock_post:

        mock_get.return_value = {"tool_name": "run_terminal_command", "channel": "telegram"}

        bot._handle_approval_callback(cq)

        # Critical assertions: tool must NOT be executed or retrieved
        assert not mock_exec.called, "execute_approved_pending must never be called for unauthorized user"
        assert not mock_get.called, "get_pending must not be processed for unauthorized user"
        assert not mock_pop.called, "pop_pending must not be processed for unauthorized user"

        # Verify answerCallbackQuery was called with unauthorized notice
        answer_calls = [
            call for call in mock_post.call_args_list
            if "answerCallbackQuery" in call.args[0]
        ]
        assert len(answer_calls) >= 1
        assert answer_calls[0].kwargs["json"]["callback_query_id"] == "cq_999"


def test_authorized_chat_with_unauthorized_from_id_rejected() -> None:
    """Proves that a callback matching chat_id but sent by a different from_id is rejected."""
    cq = _build_callback_query(
        action="approve",
        tool_call_id="call-sec-split-1",
        from_id="99999999",  # Unauthorized sender
        chat_id="12345678",  # Authorized chat
    )

    with patch("core.approval.execute_approved_pending") as mock_exec, \
         patch("core.approval.get_pending") as mock_get, \
         patch("core.approval.pop_pending") as mock_pop, \
         patch("requests.post") as mock_post:

        mock_get.return_value = {"tool_name": "run_terminal_command", "channel": "telegram"}

        bot._handle_approval_callback(cq)

        assert not mock_exec.called
        assert not mock_get.called
        assert not mock_pop.called

        answer_calls = [
            call for call in mock_post.call_args_list
            if "answerCallbackQuery" in call.args[0]
        ]
        assert len(answer_calls) >= 1
        assert answer_calls[0].kwargs["json"]["text"] == bot.UNAUTHORIZED_CALLBACK_ALERT_TEXT


def test_authorized_from_id_with_unauthorized_chat_id_rejected() -> None:
    """Proves that a callback matching from_id but with a different chat_id is rejected."""
    cq = _build_callback_query(
        action="approve",
        tool_call_id="call-sec-split-2",
        from_id="12345678",  # Authorized user
        chat_id="99999999",  # Unauthorized chat
    )

    with patch("core.approval.execute_approved_pending") as mock_exec, \
         patch("core.approval.get_pending") as mock_get, \
         patch("core.approval.pop_pending") as mock_pop, \
         patch("requests.post") as mock_post:

        mock_get.return_value = {"tool_name": "run_terminal_command", "channel": "telegram"}

        bot._handle_approval_callback(cq)

        assert not mock_exec.called
        assert not mock_get.called
        assert not mock_pop.called

        answer_calls = [
            call for call in mock_post.call_args_list
            if "answerCallbackQuery" in call.args[0]
        ]
        assert len(answer_calls) >= 1
        assert answer_calls[0].kwargs["json"]["text"] == bot.UNAUTHORIZED_CALLBACK_ALERT_TEXT


def test_unauthorized_user_reject_callback_blocked() -> None:
    """Proves that a callback query from an unauthorized user ID cannot reject or pop pending tools."""
    cq = _build_callback_query(
        action="reject",
        tool_call_id="call-sec-2",
        from_id="99999999",
        chat_id="99999999",
    )

    with patch("core.approval.execute_approved_pending") as mock_exec, \
         patch("core.approval.pop_pending") as mock_pop, \
         patch("requests.post"):

        bot._handle_approval_callback(cq)

        assert not mock_exec.called
        assert not mock_pop.called, "pop_pending must never be called for unauthorized user"


def test_unauthorized_callback_transport_failure_is_logged(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Keeps Telegram callback transport failures observable without executing a tool."""
    cq = _build_callback_query(
        action="approve",
        tool_call_id="call-sec-network",
        from_id="99999999",
        chat_id="99999999",
    )

    with patch(
        "requests.post",
        side_effect=requests.RequestException("network unavailable"),
    ), patch("core.approval.execute_approved_pending") as mock_exec:
        bot._handle_approval_callback(cq)

    assert not mock_exec.called
    assert "Failed to answer unauthorized callback cq_999" in caplog.text


def test_unconfigured_telegram_chat_id_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    """Proves that when TELEGRAM_CHAT_ID is empty/unconfigured, all callback queries are rejected."""
    monkeypatch.setattr(bot, "TELEGRAM_CHAT_ID", "")

    cq = _build_callback_query(
        action="approve",
        tool_call_id="call-sec-3",
        from_id="12345678",
        chat_id="12345678",
    )

    with patch("core.approval.execute_approved_pending") as mock_exec, \
         patch("core.approval.get_pending") as mock_get, \
         patch("requests.post") as mock_post:

        bot._handle_approval_callback(cq)

        assert not mock_exec.called
        assert not mock_get.called
        assert mock_post.called


def test_authorized_user_approve_callback_executes_tool() -> None:
    """Proves that a callback query from the authorized user/chat executes the approved tool."""
    cq = _build_callback_query(
        action="approve",
        tool_call_id="call-valid-1",
        from_id="12345678",  # Authorized user ID
        chat_id="12345678",  # Authorized chat ID
    )

    with patch("core.approval.get_pending") as mock_get, \
         patch("core.approval.execute_approved_pending") as mock_exec, \
         patch("clients.telegram_bot.send_telegram_msg"), \
         patch("clients.telegram_bot.send_telegram_msg_full"), \
         patch("requests.post"):

        mock_get.return_value = {"tool_name": "mail_manager", "channel": "telegram"}
        mock_exec.return_value = {"ok": True, "result": "Success"}

        bot._handle_approval_callback(cq)

        assert mock_get.called
        assert mock_exec.called
        assert mock_exec.call_args.args[0] == "call-valid-1"


def test_authorized_user_reject_callback_pops_pending() -> None:
    """Proves that a callback query from the authorized user/chat pops and rejects the pending tool."""
    cq = _build_callback_query(
        action="reject",
        tool_call_id="call-valid-2",
        from_id="12345678",
        chat_id="12345678",
    )

    with patch("core.approval.get_pending") as mock_get, \
         patch("core.approval.pop_pending") as mock_pop, \
         patch("clients.telegram_bot.send_telegram_msg"), \
         patch("requests.post"):

        mock_get.return_value = {"tool_name": "mail_manager", "channel": "telegram"}

        bot._handle_approval_callback(cq)

        assert mock_pop.called
        assert mock_pop.call_args.args[0] == "call-valid-2"
