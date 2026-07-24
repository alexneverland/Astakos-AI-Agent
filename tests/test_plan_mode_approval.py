"""
Tests for plan-mode approval policy in core/approval.py.

Verifies that PLAN_PER_ACTION_APPROVAL_TOOLS (run_terminal_command, register_tool)
always require per-action Telegram approval even when plan_active=True,
while other CRITICAL tools (e.g. github_manager) are bypassed in plan mode.

No live Telegram, real files, .env, credentials, databases, or network access.
"""
from unittest.mock import patch, MagicMock


def _make_state(tool_calls: list[dict], plan_active: bool = False) -> dict:
    """Build a minimal LangGraph state for approval_check_node."""
    ai_msg = MagicMock()
    ai_msg.tool_calls = tool_calls
    state = {"messages": [ai_msg]}
    if plan_active:
        state["plan_active"] = True
    return state


# ── A. register_tool with plan_active=True → pending (not bypassed) ──

def test_register_tool_plan_active_requires_approval():
    """register_tool(apply) must NOT be bypassed in plan mode."""
    from core.approval import approval_check_node

    state = _make_state(
        [{"name": "register_tool", "args": {"tool_name": "my_skill", "dry_run": False}, "id": "rt-1"}],
        plan_active=True,
    )

    with patch("core.approval.save_pending") as mock_save, \
         patch("core.approval._notify_telegram") as mock_notify:
        result = approval_check_node(state)

    assert result["approval_status"] == "pending", (
        "register_tool must block for approval even when plan_active=True"
    )
    mock_save.assert_called_once()
    mock_notify.assert_called_once()


# ── B. github_manager with plan_active=True → bypassed (ok) ──

def test_github_manager_plan_active_is_bypassed():
    """Other CRITICAL tools (github_manager) are still bypassed in plan mode."""
    from core.approval import approval_check_node

    state = _make_state(
        [{"name": "github_manager", "args": {"action": "create_issue"}, "id": "gh-1"}],
        plan_active=True,
    )

    with patch("core.approval.save_pending") as mock_save, \
         patch("core.approval._notify_telegram") as mock_notify:
        result = approval_check_node(state)

    assert result["approval_status"] == "ok", (
        "github_manager should be bypassed in plan mode"
    )
    mock_save.assert_not_called()
    mock_notify.assert_not_called()


# ── C. run_terminal_command behavior unchanged ──

def test_run_terminal_command_plan_active_requires_approval():
    """run_terminal_command still requires per-action approval in plan mode.

    run_terminal_command has DYNAMIC risk (depends on classify_command).
    We mock is_critical to return True so the test exercises the plan-mode
    bypass policy, not classify_command heuristics.
    """
    from core.approval import approval_check_node

    state = _make_state(
        [{"name": "run_terminal_command", "args": {"command": "test-command"}, "id": "tc-1"}],
        plan_active=True,
    )

    with (
        patch("core.approval.is_critical", return_value=True),
        patch("core.approval.save_pending") as mock_save,
        patch("core.approval._notify_telegram") as mock_notify,
    ):
        result = approval_check_node(state)

    assert result["approval_status"] == "pending", (
        "run_terminal_command must still block in plan mode"
    )
    mock_save.assert_called_once()
    mock_notify.assert_called_once()


# ── D. register_tool outside plan mode → still requires approval ──

def test_register_tool_outside_plan_requires_approval():
    """register_tool without plan_active must still require approval (baseline)."""
    from core.approval import approval_check_node

    state = _make_state(
        [{"name": "register_tool", "args": {"tool_name": "my_skill", "dry_run": False}, "id": "rt-2"}],
        plan_active=False,
    )

    with patch("core.approval.save_pending") as mock_save, \
         patch("core.approval._notify_telegram") as mock_notify:
        result = approval_check_node(state)

    assert result["approval_status"] == "pending", (
        "register_tool must block for approval outside plan mode"
    )
    mock_save.assert_called_once()
    mock_notify.assert_called_once()


# ── Mixed batch: register_tool + github_manager in plan mode ──

def test_mixed_batch_plan_active_splits_correctly():
    """In plan mode, register_tool blocks while github_manager is bypassed."""
    from core.approval import approval_check_node

    state = _make_state(
        [
            {"name": "github_manager", "args": {"action": "create_pr"}, "id": "gh-2"},
            {"name": "register_tool", "args": {"tool_name": "new_tool", "dry_run": False}, "id": "rt-3"},
        ],
        plan_active=True,
    )

    with patch("core.approval.save_pending") as mock_save, \
         patch("core.approval._notify_telegram") as mock_notify:
        result = approval_check_node(state)

    assert result["approval_status"] == "pending", (
        "Batch with register_tool must still block"
    )
    # Only register_tool should be saved as pending, not github_manager
    saved_names = [call.args[0] for call in mock_save.call_args_list]
    assert "register_tool" in saved_names
    assert "github_manager" not in saved_names
