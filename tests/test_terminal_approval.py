"""
Tests for the terminal approval flow bug fix.
Verifies that run_terminal_command with already_approved=True
bypasses the safe_execute gate and executes the command.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from unittest.mock import patch, MagicMock


def test_warning_command_without_approval_executes():
    """git push is now a WARNING: it runs without an approval gate, under a warning policy."""
    from core.safe_executor import safe_execute

    mock_executor = MagicMock(return_value={"status": "ok", "output": "done"})
    result = safe_execute("git push origin main", mock_executor, confirm_callback=None)

    assert result.get("status") == "ok"
    mock_executor.assert_called_once()


def test_already_approved_bypasses_safe_execute():
    """already_approved=True executes the command even if it is REQUIRE_CONFIRMATION."""
    from tools.system import run_terminal_command

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(
            stdout="pushed successfully", stderr="", returncode=0
        )
        # .func to call the raw function instead of the StructuredTool wrapper
        result = run_terminal_command.func("git push origin main", already_approved=True)

    assert "pushed" in result.lower() or result != ""
    mock_run.assert_called_once()


def test_normal_safe_command_executes_without_flag():
    """SAFE command is executed normally without already_approved."""
    from tools.system import run_terminal_command

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(
            stdout="git status output", stderr="", returncode=0
        )
        result = run_terminal_command.func("git status")

    assert result != ""
    mock_run.assert_called_once()


def test_blocked_command_stays_blocked_even_with_approval():
    """BLOCKED command (rm -rf /) must be blocked even with already_approved=True."""
    from tools.system import run_terminal_command

    with patch("subprocess.run") as mock_run:
        result = run_terminal_command.func("rm -rf /", already_approved=True)

    assert "BLOCKED" in result or "blocked" in result.lower()
    mock_run.assert_not_called()
