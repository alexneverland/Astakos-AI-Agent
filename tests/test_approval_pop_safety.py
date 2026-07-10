"""
Tests for the pop-before-execute bug fix.
Verifies that the pending action is NOT lost if:
- the tool is not found
- tool.invoke raises an exception
And that it is removed ONLY after successful execution.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from unittest.mock import patch


class DummyTool:
    def __init__(self, name, result="success", error=None):
        self.name = name
        self.result = result
        self.error = error
        self.calls = []

    def invoke(self, args):
        self.calls.append(args)
        if self.error:
            raise self.error
        return self.result


def _setup_pending(tmp_path, tool_call_id="tc-safe-1", tool_name="github_manager", tool_args=None):
    pending_file = str(tmp_path / "pending.json")
    with patch("core.approval.PENDING_FILE", pending_file):
        from core.approval import save_pending, get_pending
        save_pending(tool_name, tool_args or {"repo": "astakos"}, tool_call_id)
        return pending_file


def test_pending_survives_missing_tool(tmp_path):
    """If the tool is not found, the pending action must remain."""
    pending_file = _setup_pending(tmp_path)
    with patch("core.approval.PENDING_FILE", pending_file):
        from core.approval import execute_approved_pending, get_pending

        result = execute_approved_pending("tc-safe-1", [])

        assert result["ok"] is False
        assert result["status"] == "tool_not_found"
        assert get_pending("tc-safe-1") is not None


def test_pending_survives_invoke_exception(tmp_path):
    """If tool.invoke raises an exception, the pending action must remain."""
    pending_file = _setup_pending(tmp_path)
    with patch("core.approval.PENDING_FILE", pending_file):
        from core.approval import execute_approved_pending, get_pending

        tool = DummyTool("github_manager", error=Exception("Network error"))
        result = execute_approved_pending("tc-safe-1", [tool])

        assert result["ok"] is False
        assert result["status"] == "failed"
        assert "Network error" in result["error"]
        assert get_pending("tc-safe-1") is not None


def test_pending_removed_only_after_success(tmp_path):
    """The pending is removed ONLY after a successful invoke."""
    pending_file = _setup_pending(tmp_path)
    with patch("core.approval.PENDING_FILE", pending_file):
        from core.approval import execute_approved_pending, get_pending

        tool = DummyTool("github_manager", result="success")
        result = execute_approved_pending("tc-safe-1", [tool])

        assert result["ok"] is True
        assert result["status"] == "executed"
        assert result["result"] == "success"
        assert tool.calls == [{"repo": "astakos"}]
        assert get_pending("tc-safe-1") is None


def test_terminal_approval_adds_already_approved_flag(tmp_path):
    """run_terminal_command gets already_approved=True from the shared approval helper."""
    pending_file = _setup_pending(
        tmp_path,
        tool_call_id="tc-terminal",
        tool_name="run_terminal_command",
        tool_args={"command": "git push origin main"},
    )
    with patch("core.approval.PENDING_FILE", pending_file):
        from core.approval import execute_approved_pending, get_pending

        tool = DummyTool("run_terminal_command", result="pushed")
        result = execute_approved_pending("tc-terminal", [tool])

        assert result["ok"] is True
        assert tool.calls == [{"command": "git push origin main", "already_approved": True}]
        assert get_pending("tc-terminal") is None


def test_reject_always_pops(tmp_path):
    """Reject always removes the pending — no invoke needed."""
    pending_file = _setup_pending(tmp_path, "tc-reject-1")
    with patch("core.approval.PENDING_FILE", pending_file):
        from core.approval import get_pending, pop_pending

        assert get_pending("tc-reject-1") is not None
        pop_pending("tc-reject-1")
        assert get_pending("tc-reject-1") is None
