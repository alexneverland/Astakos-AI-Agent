"""
Tests for plan-mode approval policy in core/approval.py.

Verifies that approved plans keep ordinary reads smooth while meaningful risk
boundaries still require a separate approval.

No live Telegram, real files, .env, credentials, databases, or network access.
"""
from unittest.mock import MagicMock, patch

import pytest


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


# ── B. benign GitHub read with plan_active=True → bypassed (ok) ──

def test_github_manager_read_plan_active_is_bypassed():
    """Repository listing stays smooth after the user approves a plan."""
    from core.approval import approval_check_node

    state = _make_state(
        [{"name": "github_manager", "args": {"action": "list_repos"}, "id": "gh-1"}],
        plan_active=True,
    )

    with patch("core.approval.save_pending") as mock_save, \
         patch("core.approval._notify_telegram") as mock_notify:
        result = approval_check_node(state)

    assert result["approval_status"] == "ok", (
        "github_manager reads should be bypassed in plan mode"
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


# ── Risk boundaries: each still requires approval in plan mode ──

@pytest.mark.parametrize(
    ("tool_name", "args"),
    [
        ("write_project_file", {"file_path": "notes.txt", "content": "new content"}),
        ("grant_project_access", {"folder_path": "C:/safe-folder", "mode": "write"}),
        ("mail_manager", {"action": "send", "to_email": "person@example.com", "subject": "Hi", "body": "Hello"}),
        ("mail_manager", {"action": "reply", "email_id": "mail-1", "body": "Hello"}),
        ("mail_manager", {"action": "delete", "email_id": "mail-1"}),
        ("post_to_linkedin", {"text": "Public update"}),
        ("process_and_clear_linkedin_post", {}),
        ("execute_local_pipeline", {"target_name": "Sofia", "message": "Hello"}),
        ("edit_project_file", {"file_path": "core/approval.py", "old_str": "old", "new_str": "new"}),
        ("drive_manager", {"action": "delete", "file_id": "drive-1"}),
        ("drive_manager", {"action": "share", "file_id": "drive-1", "share_email": "person@example.com"}),
        ("drive_manager", {"action": "move", "file_id": "drive-1", "folder_id": "folder-1"}),
        ("github_manager", {"action": "create_file", "repo_name": "repo", "target_files": "notes.txt", "content": "new"}),
        ("github_manager", {"action": "update_file", "repo_name": "repo", "target_files": "notes.txt", "content": "new"}),
        ("github_manager", {"action": "push_local_commits", "target_files": "notes.txt", "commit_message": "Update notes"}),
    ],
)
def test_plan_risk_boundary_requires_per_action_approval(
    tool_name: str,
    args: dict,
) -> None:
    """Approved plans cannot silently cross external, destructive, or system-write boundaries."""
    from core.approval import approval_check_node

    state = _make_state(
        [{"name": tool_name, "args": args, "id": f"boundary-{tool_name}"}],
        plan_active=True,
    )

    with patch("core.approval.save_pending") as mock_save, \
         patch("core.approval._notify_telegram") as mock_notify:
        result = approval_check_node(state)

    assert result["approval_status"] == "pending"
    mock_save.assert_called_once()
    mock_notify.assert_called_once()


@pytest.mark.parametrize(
    ("tool_name", "args"),
    [
        ("mail_manager", {"action": "read_full", "email_id": "mail-1"}),
        ("drive_manager", {"action": "list_files"}),
        ("edit_project_file", {"file_path": "notes.txt", "old_str": "old", "new_str": "new"}),
        ("github_manager", {"action": "read_file", "repo_name": "repo", "target_files": "README.md"}),
    ],
)
def test_plan_safe_actions_remain_smooth(tool_name: str, args: dict) -> None:
    """Reads and non-core edits do not create an approval prompt after plan approval."""
    from core.approval import approval_check_node

    state = _make_state(
        [{"name": tool_name, "args": args, "id": f"safe-{tool_name}"}],
        plan_active=True,
    )

    with patch("core.approval.save_pending") as mock_save, \
         patch("core.approval._notify_telegram") as mock_notify:
        result = approval_check_node(state)

    assert result["approval_status"] == "ok"
    mock_save.assert_not_called()
    mock_notify.assert_not_called()


def test_plan_does_not_bypass_external_context_escalation() -> None:
    """Plan approval never authorizes an action derived from stale external content."""
    from langchain_core.messages import AIMessage, HumanMessage
    from core.approval import approval_check_node
    from core.untrusted_content import external_content_history_metadata

    external_reply = AIMessage(
        content="A prior external result.",
        additional_kwargs=external_content_history_metadata(["get_news"]),
    )
    user_message = HumanMessage(content="Συνέχισε")
    tool_call = AIMessage(
        content="",
        tool_calls=[{
            "name": "set_local_reminder",
            "args": {"action": "add", "task": "Act on external result"},
            "id": "external-plan-1",
        }],
    )

    with patch("core.approval.save_pending") as mock_save, \
         patch("core.approval._notify_telegram") as mock_notify:
        result = approval_check_node({
            "messages": [external_reply, user_message, tool_call],
            "plan_active": True,
        })

    assert result["approval_status"] == "pending"
    mock_save.assert_called_once()
    mock_notify.assert_called_once()


# ── Mixed batch: register_tool + GitHub read in plan mode ──

def test_mixed_batch_plan_active_splits_correctly():
    """In plan mode, register_tool blocks while github_manager is bypassed."""
    from core.approval import approval_check_node

    state = _make_state(
        [
            {"name": "github_manager", "args": {"action": "list_repos"}, "id": "gh-2"},
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
