"""
Tests για το approval flow — save/get/resolve/pop pending + is_critical routing.
Δεν χρειάζεται live Telegram.
"""
import sys, os, json, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from unittest.mock import patch, MagicMock
import pytest


# -- Pending store (save/get/pop/list) ----------------------------

def _make_approval_with_tmp():
    """Επιστρέφει το approval module με temp file αντί για το real pending file."""
    import core.approval as ap
    return ap

def test_save_and_get_pending(tmp_path):
    pending_file = str(tmp_path / "pending.json")
    with patch("core.approval.PENDING_FILE", pending_file):
        from core.approval import save_pending, get_pending
        save_pending("github_manager", {"repo": "astakos"}, "call-123")
        item = get_pending("call-123")
        assert item is not None
        assert item["tool_name"] == "github_manager"
        assert item["status"] == "pending"

def test_resolve_pending_approved(tmp_path):
    pending_file = str(tmp_path / "pending.json")
    with patch("core.approval.PENDING_FILE", pending_file):
        from core.approval import save_pending, resolve_pending, get_pending
        save_pending("mail_manager", {}, "call-456")
        resolve_pending("call-456", approved=True)
        item = get_pending("call-456")
        assert item["status"] == "approved"

def test_resolve_pending_rejected(tmp_path):
    pending_file = str(tmp_path / "pending.json")
    with patch("core.approval.PENDING_FILE", pending_file):
        from core.approval import save_pending, resolve_pending, get_pending
        save_pending("mail_manager", {}, "call-789")
        resolve_pending("call-789", approved=False)
        item = get_pending("call-789")
        assert item["status"] == "rejected"

def test_pop_pending_removes_item(tmp_path):
    pending_file = str(tmp_path / "pending.json")
    with patch("core.approval.PENDING_FILE", pending_file):
        from core.approval import save_pending, pop_pending, get_pending
        save_pending("github_manager", {}, "call-pop")
        item = pop_pending("call-pop")
        assert item is not None
        assert get_pending("call-pop") is None

def test_list_pending_only_returns_pending_status(tmp_path):
    pending_file = str(tmp_path / "pending.json")
    with patch("core.approval.PENDING_FILE", pending_file):
        from core.approval import save_pending, resolve_pending, list_pending
        save_pending("github_manager", {}, "p1")
        save_pending("mail_manager", {}, "p2")
        resolve_pending("p2", approved=True)
        pending = list_pending()
        ids = [p["tool_call_id"] for p in pending]
        assert "p1" in ids
        assert "p2" not in ids  # approved — δεν εμφανίζεται


# -- is_critical routing ------------------------------------------

def test_critical_tool_blocked_in_node():
    """approval_check_node με CRITICAL tool → approval_status=pending."""
    from core.approval import approval_check_node
    from langchain_core.messages import AIMessage

    ai_msg = MagicMock()
    ai_msg.tool_calls = [{"name": "github_manager", "args": {}, "id": "tc-1"}]

    with patch("core.approval.save_pending"), \
         patch("core.approval._notify_telegram"):
        result = approval_check_node({"messages": [ai_msg]})
        assert result["approval_status"] == "pending"

def test_safe_tool_passes_through():
    """approval_check_node με SAFE tool → approval_status=ok."""
    from core.approval import approval_check_node

    ai_msg = MagicMock()
    ai_msg.tool_calls = [{"name": "search_memory", "args": {}, "id": "tc-2"}]

    result = approval_check_node({"messages": [ai_msg]})
    assert result["approval_status"] == "ok"

def test_blocked_terminal_command_is_not_saved_for_approval():
    """BLOCKED terminal command → approval_status=blocked και δεν αποθηκεύεται pending."""
    from core.approval import approval_check_node

    ai_msg = MagicMock()
    ai_msg.tool_calls = [{
        "name": "run_terminal_command",
        "args": {"command": "rm -rf /"},
        "id": "tc-blocked",
    }]

    with patch("core.approval.save_pending") as save_pending, \
         patch("core.approval._notify_telegram") as notify:
        result = approval_check_node({"messages": [ai_msg]})

    assert result["approval_status"] == "blocked"
    save_pending.assert_not_called()
    notify.assert_not_called()

def test_no_tool_calls_passes_through():
    """approval_check_node χωρίς tool calls → approval_status=ok."""
    from core.approval import approval_check_node

    ai_msg = MagicMock()
    ai_msg.tool_calls = []

    result = approval_check_node({"messages": [ai_msg]})
    assert result["approval_status"] == "ok"
