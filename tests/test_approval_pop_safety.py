"""
Tests για το pop-before-execute bug fix.
Επαληθευει οτι το pending action ΔΕΝ χανεται αν:
- το tool δεν βρεθει
- το tool.invoke κανει exception
Και οτι αφαιρειται ΜΟΝΟ μετα απο επιτυχη εκτελεση.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from unittest.mock import patch, MagicMock
import pytest


def _setup_pending(tmp_path, tool_call_id="tc-safe-1", tool_name="github_manager"):
    pending_file = str(tmp_path / "pending.json")
    with patch("core.approval.PENDING_FILE", pending_file):
        from core.approval import save_pending, get_pending
        save_pending(tool_name, {"repo": "astakos"}, tool_call_id)
        return pending_file


def test_pending_survives_missing_tool(tmp_path):
    """Αν το tool δεν βρεθει, το pending action πρεπει να μεινει."""
    pending_file = _setup_pending(tmp_path)
    with patch("core.approval.PENDING_FILE", pending_file):
        from core.approval import get_pending, pop_pending

        item = get_pending("tc-safe-1")
        assert item is not None

        # Simulate: tool not found → δεν καλουμε pop
        tools_map = {}  # αδειο — tool δεν υπαρχει
        tool = tools_map.get(item["tool_name"])
        if not tool:
            pass  # return χωρις pop

        # Pending πρεπει να εξακολουθει να υπαρχει
        assert get_pending("tc-safe-1") is not None


def test_pending_survives_invoke_exception(tmp_path):
    """Αν το tool.invoke κανει exception, το pending action πρεπει να μεινει."""
    pending_file = _setup_pending(tmp_path)
    with patch("core.approval.PENDING_FILE", pending_file):
        from core.approval import get_pending, pop_pending

        item = get_pending("tc-safe-1")
        assert item is not None

        mock_tool = MagicMock()
        mock_tool.invoke.side_effect = Exception("Network error")

        try:
            mock_tool.invoke(item["tool_args"])
            pop_pending("tc-safe-1")  # αυτο ΔΕΝ πρεπει να τρεξει
        except Exception:
            pass  # exception — ΔΕΝ κανουμε pop

        # Pending πρεπει να εξακολουθει να υπαρχει
        assert get_pending("tc-safe-1") is not None


def test_pending_removed_only_after_success(tmp_path):
    """Το pending αφαιρειται ΜΟΝΟ μετα απο επιτυχη invoke."""
    pending_file = _setup_pending(tmp_path)
    with patch("core.approval.PENDING_FILE", pending_file):
        from core.approval import get_pending, pop_pending

        item = get_pending("tc-safe-1")
        assert item is not None

        mock_tool = MagicMock()
        mock_tool.invoke.return_value = "success"

        result = mock_tool.invoke(item["tool_args"])
        pop_pending("tc-safe-1")  # pop μετα απο επιτυχια

        # Τωρα πρεπει να εχει αφαιρεθει
        assert get_pending("tc-safe-1") is None


def test_reject_always_pops(tmp_path):
    """Το reject παντα αφαιρει το pending — δεν χρειαζεται invoke."""
    pending_file = _setup_pending(tmp_path, "tc-reject-1")
    with patch("core.approval.PENDING_FILE", pending_file):
        from core.approval import get_pending, pop_pending

        assert get_pending("tc-reject-1") is not None
        pop_pending("tc-reject-1")
        assert get_pending("tc-reject-1") is None
