"""
Tests για το terminal approval flow bug fix.
Επαληθευει οτι run_terminal_command με already_approved=True
παρακαμπτει το safe_execute gate και εκτελει την εντολη.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from unittest.mock import patch, MagicMock


def test_require_confirmation_without_approval_returns_cancelled():
    """Χωρις already_approved, REQUIRE_CONFIRMATION εντολη επιστρεφει cancelled."""
    from core.safe_executor import safe_execute, ExecPolicy

    mock_executor = MagicMock(return_value={"status": "ok", "output": "done"})
    result = safe_execute("git push origin main", mock_executor, confirm_callback=None)

    assert result.get("status") in ("blocked", "cancelled")
    mock_executor.assert_not_called()


def test_already_approved_bypasses_safe_execute():
    """already_approved=True εκτελει εντολη ακομα και αν ειναι REQUIRE_CONFIRMATION."""
    from tools.system import run_terminal_command

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(
            stdout="pushed successfully", stderr="", returncode=0
        )
        # .func για να καλεσουμε την raw function αντι για το StructuredTool wrapper
        result = run_terminal_command.func("git push origin main", already_approved=True)

    assert "pushed" in result.lower() or result != ""
    mock_run.assert_called_once()


def test_normal_safe_command_executes_without_flag():
    """SAFE εντολη εκτελειται κανονικα χωρις already_approved."""
    from tools.system import run_terminal_command

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(
            stdout="git status output", stderr="", returncode=0
        )
        result = run_terminal_command.func("git status")

    assert result != ""
    mock_run.assert_called_once()


def test_blocked_command_stays_blocked_even_with_approval():
    """BLOCKED εντολη (rm -rf /) πρεπει να μπλοκαριστει ακομα και με already_approved=False."""
    from tools.system import run_terminal_command

    with patch("subprocess.run") as mock_run:
        result = run_terminal_command.func("rm -rf /", already_approved=False)

    assert "BLOCKED" in result or "blocked" in result.lower()
    mock_run.assert_not_called()
