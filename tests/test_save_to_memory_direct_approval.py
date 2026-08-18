"""
Tests for save_to_memory parameter compatibility (fact vs content)
and execution of approved pending save_to_memory actions.
"""
import pytest
from unittest.mock import patch, MagicMock
from langchain_core.messages import HumanMessage, AIMessage, ToolMessage

from tools.system import save_to_memory
from core.approval import execute_approved_pending, save_pending


def test_save_to_memory_accepts_fact_parameter():
    with patch("threading.Thread") as mock_thread:
        mock_thread.return_value.start = MagicMock()
        res = save_to_memory.invoke({"fact": "Lazaros travels on Saturday", "category": "family"})
        assert "Saving in background" in res
        mock_thread.assert_called_once()


def test_save_to_memory_accepts_content_parameter_alias():
    with patch("threading.Thread") as mock_thread:
        mock_thread.return_value.start = MagicMock()
        res = save_to_memory.invoke({"content": "Lazaros travels on Saturday", "category": "family"})
        assert "Saving in background" in res
        mock_thread.assert_called_once()


def test_save_to_memory_returns_error_when_both_fact_and_content_empty():
    res = save_to_memory.invoke({"category": "family"})
    assert "No fact or content provided" in res


def test_execute_approved_pending_save_to_memory_with_content_arg():
    call_id = "test_call_123"
    save_pending("save_to_memory", {"content": "Trip to Kutaisi planned", "category": "family"}, call_id, channel="web")
    with patch("threading.Thread") as mock_thread:
        mock_thread.return_value.start = MagicMock()
        result = execute_approved_pending(call_id, [save_to_memory])
        assert result["ok"] is True
        assert result["status"] == "executed"
        assert "Saving in background" in result["result"]
