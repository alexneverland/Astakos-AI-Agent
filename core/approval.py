# ================================================================
# Project: Astakos AI Agent 🦞
# Module:  Action Approval — CRITICAL tool gate
# If tool is CRITICAL → saves as pending, sends Telegram message
# If SAFE/WARNING → lets the graph continue normally
# ================================================================

import os
import json
from datetime import datetime, timedelta
from typing import Sequence
from langchain_core.messages import BaseMessage
from langchain_core.messages.tool import ToolCall
from core.tool_risk import get_risk as _get_risk
from core.capability_draft import has_capability_draft_authorization

def _effective_risk(tc: dict) -> str:
    """
    Calculates the actual risk level of a tool call.
    For run_terminal_command: uses classify_command() instead of a static registry.
    """
    name = tc["name"]
    if name == "run_terminal_command":
        from core.safe_executor import classify_command, ExecPolicy
        cmd = tc.get("args", {}).get("command", "")
        policy, _ = classify_command(cmd)
        if policy == ExecPolicy.BLOCKED:
            return "BLOCKED"
        elif policy == ExecPolicy.REQUIRE_CONFIRMATION:
            return "CRITICAL"
        elif policy == ExecPolicy.WARNING:
            return "WARNING"
        else:
            return "SAFE"
    if name == "execute_local_pipeline":
        args = tc.get("args", {})
        if args.get("target_name") or args.get("message"):
            return "CRITICAL"
        from core.messenger_draft import has_active_draft
        return "CRITICAL" if has_active_draft() else "SAFE"
    if name == "drive_manager":
        action = tc.get("args", {}).get("action", "list_files")
        _DRIVE_CRITICAL = {"delete", "share", "move"}
        _DRIVE_WARNING  = {"upload", "download", "rename", "create_folder"}
        _DRIVE_SAFE     = {"list_files", "search", "info"}
        if action in _DRIVE_CRITICAL:
            return "CRITICAL"
        elif action in _DRIVE_SAFE:
            return "SAFE"
        return "NOTIFY"  # upload/download/rename/create_folder → inform but don't block
    if name == "mail_manager":
        action = str(tc.get("args", {}).get("action", "")).lower()
        if action in {"send", "reply", "delete"}:
            return "CRITICAL"
        if action in {"search", "check_emails", "check", "read", "read_full", "read_thread"}:
            return "SAFE"
        return "CRITICAL"
    if name == "github_manager":
        action = str(tc.get("args", {}).get("action", "")).lower()
        if action in {"list_repos", "read_file"}:
            return "SAFE"
        # Unknown actions fail closed because this tool can publish changes.
        return "CRITICAL"
    if name == "google_tasks_tool":
        action = str(tc.get("args", {}).get("action", "list")).lower()
        if action == "delete":
            return "CRITICAL"
        if action == "list":
            return "SAFE"
        if action in {"create", "complete", "update"}:
            return "WARNING"
        return "WARNING"
    if name == "google_calendar_tool":
        action = str(tc.get("args", {}).get("action", "list")).lower()
        if action == "delete":
            return "CRITICAL"
        if action in {"list", "today", "week", "search"}:
            return "SAFE"
        if action in {"create", "update"}:
            return "WARNING"
        return "WARNING"

    if name == "edit_project_file":
        _CORE = {"agents.py", "brain.py", "graph.py", "approval.py",
                 "tool_risk.py", "prompts.md", "config.py"}
        file_path = tc.get("args", {}).get("file_path", "")
        fname = file_path.strip().strip(chr(39)).strip(chr(34)).replace(chr(92), chr(47)).split(chr(47))[-1]
        if fname in _CORE:
            return "CRITICAL"
        return "WARNING"
    if name == "register_tool":
        args = tc.get("args", {})
        if not isinstance(args, dict):
            return "CRITICAL"
        is_dry = args.get("dry_run", False)
        # Convert string representations to boolean if needed
        if isinstance(is_dry, str):
            is_dry = is_dry.lower() in ["true", "1", "yes", "y", "nai"]
        if is_dry:
            return "WARNING"
        return "CRITICAL"

    return _get_risk(name)


def _is_accepted_routine_messenger_draft_creation(
    tool_call: ToolCall,
    prior_messages: Sequence[BaseMessage],
    *,
    routine_draft_offer_authorized: bool | None = None,
) -> bool:
    """Return whether a trusted routine acceptance authorizes a draft write."""
    if tool_call.get("name") != "relay_local_payload":
        return False
    from services.messenger_intent import has_accepted_routine_draft_offer
    return has_accepted_routine_draft_offer(
        prior_messages,
        state_authorized=routine_draft_offer_authorized,
    )


def _is_trusted_active_messenger_draft_edit(
    tool_call: ToolCall,
    prior_messages: Sequence[BaseMessage],
) -> bool:
    """Return whether a clean direct user message requests an active-draft revision."""
    if tool_call.get("name") != "relay_local_payload":
        return False

    from core.messenger_draft import has_active_draft
    from core.untrusted_content import external_content_source_names, is_direct_user_message
    from services.messenger_intent import is_active_draft_edit_intent

    if not has_active_draft():
        return False
    for message in reversed(prior_messages):
        if is_direct_user_message(message):
            if external_content_source_names(getattr(message, "additional_kwargs", {})):
                return False
            return is_active_draft_edit_intent(str(getattr(message, "content", "")))
    return False

def _is_explicit_messenger_draft_creation(
    tool_call: ToolCall,
    prior_messages: Sequence[BaseMessage],
    *,
    routine_draft_offer_authorized: bool | None = None,
) -> bool:
    """Return whether a user explicitly requested the reversible Messenger draft write.

    This only exempts ``relay_local_payload`` from the external-context
    escalation. A trusted active-draft edit is also permitted after an
    incidental read because the user must still review the draft before the
    separate CRITICAL send path can run.
    """
    if tool_call.get("name") != "relay_local_payload":
        return False

    from core.untrusted_content import (
        external_content_source_names,
        is_direct_user_message,
    )
    from services.messenger_intent import is_explicit_draft_creation_request

    if _is_accepted_routine_messenger_draft_creation(
        tool_call,
        prior_messages,
        routine_draft_offer_authorized=routine_draft_offer_authorized,
    ):
        return True

    if _is_trusted_active_messenger_draft_edit(tool_call, prior_messages):
        return True

    for message in reversed(prior_messages):
        if is_direct_user_message(message):
            if external_content_source_names(
                getattr(message, "additional_kwargs", {}),
            ):
                return False
            return is_explicit_draft_creation_request(
                str(getattr(message, "content", "")),
            )
    return False


def _is_direct_user_meal_log(
    tool_call: ToolCall,
    prior_messages: Sequence[BaseMessage],
) -> bool:
    """Allow only a grounded direct meal report to bypass stale provenance."""
    if tool_call.get("name") != "log_meal":
        return False

    from core.untrusted_content import external_content_source_names, is_direct_user_message
    from services.food_intent import is_meal_report

    meal_name = str((tool_call.get("args") or {}).get("meal_name", "")).strip()
    if not meal_name:
        return False

    for message in reversed(prior_messages):
        if not is_direct_user_message(message):
            continue
        if external_content_source_names(getattr(message, "additional_kwargs", {})):
            return False
        user_text = str(getattr(message, "content", ""))
        return is_meal_report(user_text) and meal_name.casefold() in user_text.casefold()
    return False

def is_critical(tc: dict) -> bool:
    return _effective_risk(tc) == "CRITICAL"

def get_risk(name: str) -> str:
    return _get_risk(name)

PENDING_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "astakos_pending_approval.json"
)

# Pending actions older than this are considered expired and are automatically removed.
PENDING_TTL_SECONDS: int = 3600  # 60 minutes

# CRITICAL tools that always require a separate Telegram approval inside an
# approved plan.  The plan approval covers ordinary steps; it must not silently
# cross an external, destructive, permission, or project-write boundary.
#
# Action-aware tools are included here only after _effective_risk() has already
# classified the concrete action as CRITICAL.  For example, reading mail or a
# repository remains smooth, while sending mail or pushing repository changes
# needs a new approval.
PLAN_PER_ACTION_APPROVAL_TOOLS: frozenset[str] = frozenset({
    "run_terminal_command",              # arbitrary OS commands
    "write_custom_tool",                 # generates and tests dynamic skill
    "register_tool",                     # permanent tool registry changes
    "write_project_file",                # full project-file overwrite
    "grant_project_access",              # permission change
    "mail_manager",                      # only send/reply/delete are CRITICAL
    "post_to_linkedin",                  # external publication
    "process_and_clear_linkedin_post",   # external publication/clearing
    "execute_local_pipeline",            # sends an active Messenger draft
    "edit_project_file",                 # only core-file edits are CRITICAL
    "drive_manager",                     # only delete/share/move are CRITICAL
    "github_manager",                    # only create/update/push are CRITICAL
})


def requires_plan_per_action_approval(tool_call: dict) -> bool:
    """Return whether this concrete call crosses a plan approval boundary.

    The explicit risk check makes this safe to reuse outside the current
    ``critical_calls`` path: read-only actions of action-aware tools do not
    become approval boundaries merely because their tool name is listed.
    """
    return (
        _effective_risk(tool_call) == "CRITICAL"
        and tool_call["name"] in PLAN_PER_ACTION_APPROVAL_TOOLS
    )

# ────────────────────────────────────────────────────────────────
# Pending approval store
# ────────────────────────────────────────────────────────────────

def save_pending(tool_name: str, tool_args: dict, tool_call_id: str, channel: str = "telegram"):
    """Saves CRITICAL tool call for later."""
    pending = _load_pending()
    pending[tool_call_id] = {
        "tool_name":   tool_name,
        "tool_args":   tool_args,
        "tool_call_id": tool_call_id,
        "created_at":  datetime.now().isoformat(timespec="seconds"),
        "status":      "pending",
        "channel":     channel,
    }
    _save_pending(pending)


def get_pending(tool_call_id: str) -> dict | None:
    return _load_pending().get(tool_call_id)


def resolve_pending(tool_call_id: str, approved: bool):
    """Marks as approved/rejected."""
    pending = _load_pending()
    if tool_call_id in pending:
        pending[tool_call_id]["status"] = "approved" if approved else "rejected"
        pending[tool_call_id]["resolved_at"] = datetime.now().isoformat(timespec="seconds")
        _save_pending(pending)


def pop_pending(tool_call_id: str) -> dict | None:
    """Reads and removes from the pending store."""
    pending = _load_pending()
    item = pending.pop(tool_call_id, None)
    if item:
        _save_pending(pending)
    return item


def list_pending() -> list[dict]:
    return [v for v in _load_pending().values() if v["status"] == "pending"]


def execute_approved_pending(tool_call_id: str, tools: list) -> dict:
    """
    Executes a pending action that has been approved by the UI/Telegram.
    The pending action is removed only after a successful tool.invoke().
    """
    item = get_pending(tool_call_id)
    if not item:
        return {
            "ok": False,
            "status": "missing",
            "error": "Action not found or already executed",
        }
    if item.get("status") != "pending":
        return {
            "ok": False,
            "status": item.get("status", "not_pending"),
            "tool": item.get("tool_name"),
            "error": "Action is no longer pending and cannot be executed",
        }

    tool_name = item["tool_name"]
    tool_args = item.get("tool_args", {})
    tools_map = {getattr(t, "name", None): t for t in tools}
    tool = tools_map.get(tool_name)
    if not tool:
        return {
            "ok": False,
            "status": "tool_not_found",
            "tool": tool_name,
            "error": f"Tool '{tool_name}' not found",
        }

    invoke_args = dict(tool_args)
    if tool_name == "run_terminal_command":
        invoke_args["already_approved"] = True

    try:
        result = tool.invoke(invoke_args)
    except Exception as e:
        return {
            "ok": False,
            "status": "failed",
            "tool": tool_name,
            "error": str(e),
        }

    pop_pending(tool_call_id)
    return {
        "ok": True,
        "status": "executed",
        "tool": tool_name,
        "result": result,
    }


def _load_pending_raw() -> dict:
    """Loads the pending store without TTL cleanup (used internally)."""
    if not os.path.exists(PENDING_FILE):
        return {}
    try:
        with open(PENDING_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return {}


def expire_stale_pending() -> list:
    """
    Removes pending actions that have exceeded PENDING_TTL_SECONDS.
    Returns a list of the tool_call_ids that expired.
    Called automatically on every _load_pending().
    """
    pending = _load_pending_raw()
    now = datetime.now()
    expired_ids = []
    for call_id, item in list(pending.items()):
        if item.get("status") != "pending":
            continue
        created_raw = item.get("created_at", "")
        try:
            created_at = datetime.fromisoformat(created_raw)
        except (ValueError, TypeError):
            continue
        age = (now - created_at).total_seconds()
        if age > PENDING_TTL_SECONDS:
            item["status"] = "expired"
            item["expired_at"] = now.isoformat(timespec="seconds")
            expired_ids.append(call_id)
            print(f"\033[93m[Approval]: \u23f0 Expired stale pending: {item['tool_name']} (age={int(age)}s)\033[0m")
    if expired_ids:
        _save_pending(pending)
    return expired_ids


def _load_pending() -> dict:
    """Loads only active (non-expired, non-resolved) pending entries."""
    expire_stale_pending()
    return _load_pending_raw()


def _save_pending(data: dict):
    with open(PENDING_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# ────────────────────────────────────────────────────────────────
# LangGraph node
# ────────────────────────────────────────────────────────────────

def approval_check_node(state):
    """
    Runs before the ToolNode.
    - SAFE / WARNING → state["approval_status"] = "ok" → continues to tools
    - BLOCKED        → immediately cut off by safe executor, sets "blocked"
    - CRITICAL       → saves pending, sends Telegram, sets "pending"
    """
    from langchain_core.messages import AIMessage, ToolMessage
    from core.i18n import t

    last_msg = state["messages"][-1]
    tool_calls = getattr(last_msg, "tool_calls", [])
    prior_messages = state["messages"][:-1]
    routine_draft_offer_authorized = state.get("routine_draft_offer_authorized")
    if routine_draft_offer_authorized is not None:
        routine_draft_offer_authorized = routine_draft_offer_authorized is True

    if not tool_calls:
        return {"approval_status": "ok"}

    blocked_entries = [
        (tc, "core.approval.blocked", "rejected by safe executor")
        for tc in tool_calls
        if _effective_risk(tc) == "BLOCKED"
    ]
    blocked_call_ids = {tc["id"] for tc, _, _ in blocked_entries}

    from core.untrusted_content import (
        active_external_content_tool_names,
        has_untrusted_result_in_active_history,
        has_untrusted_result_since_latest_user_message,
        is_read_only_external_followup_tool,
    )
    if has_untrusted_result_since_latest_user_message(state["messages"]):
        for tc in tool_calls:
            if (
                not is_read_only_external_followup_tool(tc["name"], tc.get("args"))
                and not _is_accepted_routine_messenger_draft_creation(
                    tc,
                    prior_messages,
                    routine_draft_offer_authorized=routine_draft_offer_authorized,
                )
                and not _is_trusted_active_messenger_draft_edit(tc, prior_messages)
                and tc["id"] not in blocked_call_ids
            ):
                blocked_entries.append((
                    tc,
                    "core.approval.external_content_action_blocked",
                    "follows untrusted external tool content in the same user turn",
                ))
                blocked_call_ids.add(tc["id"])

    external_content_is_active = has_untrusted_result_in_active_history(state["messages"])
    external_context_approval_ids = {
        tc["id"]
        for tc in tool_calls
        if (
            external_content_is_active
            and not is_read_only_external_followup_tool(tc["name"], tc.get("args"))
            and not _is_explicit_messenger_draft_creation(
                tc,
                prior_messages,
                routine_draft_offer_authorized=routine_draft_offer_authorized,
            )
            and not _is_direct_user_meal_log(tc, prior_messages)
            and tc["id"] not in blocked_call_ids
        )
    }

    # ── Draft Authorization Gate ──────────────────────────────────────
    # write_custom_tool requires explicit newest-message authorization.
    # If lacking, we block it exactly like a BLOCKED tool.
    for tc in tool_calls:
        if tc["name"] == "write_custom_tool" and tc["id"] not in blocked_call_ids:
            if not has_capability_draft_authorization(state):
                blocked_entries.append((
                    tc,
                    "core.approval.unauthorized_draft_error",
                    "lacks explicit draft authorization",
                ))

    if blocked_entries:
        tool_messages = []
        for tc, message_key, reason in blocked_entries:
            print(f"\033[91m[Approval]: 🛡️ BLOCKED — {tc['name']} {reason}\033[0m")
            tool_messages.append(ToolMessage(
                content=t(message_key, name=tc["name"]),
                tool_call_id=tc["id"],
                name=tc["name"],
            ))

        return {
            "approval_status": "blocked",
            "messages": tool_messages,
        }

    critical_calls = [
        tc for tc in tool_calls
        if is_critical(tc) or tc["id"] in external_context_approval_ids
    ]

    # ── Plan mode bypass ───────────────────────────────────────────
    # An approved plan carries ordinary CRITICAL steps, but external,
    # destructive, permission, and project-write boundaries still need a
    # separate Telegram confirmation. External-content escalation is never
    # bypassed by a plan.
    if critical_calls and state.get("plan_active"):
        bypassed = [
            tc for tc in critical_calls
            if (
                not requires_plan_per_action_approval(tc)
                and tc["id"] not in external_context_approval_ids
            )
        ]
        bypassed_ids = {tc["id"] for tc in bypassed}
        still_critical = [tc for tc in critical_calls if tc["id"] not in bypassed_ids]
        if bypassed:
            print(f"\033[93m[Approval]: 📋 Plan mode — bypassing CRITICAL approval for: "
                  f"{[tc['name'] for tc in bypassed]}\033[0m")
        critical_calls = still_critical

    if not critical_calls:
        risk_levels = [_effective_risk(tc) for tc in tool_calls]

        # NOTIFY: executes + Telegram info (without buttons)_
        if "NOTIFY" in risk_levels:
            for tc in tool_calls:
                if _effective_risk(tc) == "NOTIFY":
                    print(f"\033[96m[Approval]: 📣 NOTIFY tool: {tc['name']}\033[0m")
                    _notify_telegram_notify(tc)

        # WARNING: executes + logs only in the console, without Telegram
        elif "WARNING" in risk_levels:
            for tc in tool_calls:
                if _effective_risk(tc) == "WARNING":
                    print(f"\033[93m[Approval]: ⚠️ WARNING tool: {tc['name']}\033[0m")

        approval_update = {"approval_status": "ok"}
        if any(
            _is_accepted_routine_messenger_draft_creation(
                tc,
                prior_messages,
                routine_draft_offer_authorized=routine_draft_offer_authorized,
            )
            for tc in tool_calls
        ):
            # The routine acceptance is a one-shot authority for creating exactly
            # one reviewable draft, not a general write capability for this turn.
            approval_update["routine_draft_offer_authorized"] = False
        return approval_update

    # There are CRITICAL calls — we save them and request approval
    tool_messages = []
    current_channel = state.get("channel", "telegram")
    for tc in critical_calls:
        pending_args = dict(tc.get("args", {}))
        if tc["name"] in {
            "save_to_memory",
            "manage_list",
            "save_goal_tool",
            "update_goal_milestones_tool",
            "learn_routine",
            "recipe_expert",
            "set_local_reminder",
        } and tc["id"] in external_context_approval_ids:
            import json

            pending_args["external_content_sources_json"] = json.dumps(
                sorted(active_external_content_tool_names(state["messages"])),
            )
        save_pending(tc["name"], pending_args, tc["id"], channel=current_channel)
        print(f"\033[91m[Approval]: 🚨 CRITICAL — {tc['name']} blocked, awaiting approval\033[0m")

        # We send a Telegram notification
        _notify_telegram(tc)

        # We return a ToolMessage so that the graph does not get stuck
        tool_messages.append(ToolMessage(
            content=t("core.approval.waiting", name=tc["name"]),
            tool_call_id=tc["id"],
            name=tc["name"],
        ))

    return {
        "approval_status": "pending",
        "messages": tool_messages,
    }


def _args_preview(args: dict) -> str:
    """Creates a safe preview of the args without special chars."""
    import html
    parts = []
    for k, v in args.items():
        val = repr(v)[:60].replace("<", "").replace(">", "")
        parts.append(f"{html.escape(k)}={html.escape(val)}")
    return ", ".join(parts) or "—"


def _notify_telegram_notify(tool_call: dict):
    """Sends Telegram info for NOTIFY tools (executed, without approve/reject)."""
    try:
        from tools.telegram import send_telegram_msg
        tool_name = tool_call["name"]
        args_prev = _args_preview(tool_call.get("args", {}))
        text = (
            f"📣 <b>{tool_name}</b>\n"
            f"<code>{args_prev}</code>"
        )
        send_telegram_msg(text)
    except Exception as e:
        print(f"\033[93m[Approval]: Telegram notify error: {e}\033[0m")


def _notify_telegram(tool_call: dict):
    """Sends a Telegram inline keyboard for CRITICAL approval."""
    try:
        import requests
        from config import TELEGRAM_TOKEN, TELEGRAM_CHAT_ID

        tool_name = tool_call["name"]
        call_id   = tool_call["id"]
        args_prev = _args_preview(tool_call.get("args", {}))

        from core.i18n import t
        text = t("core.approval.req_approval", tool_name=tool_name, args_prev=args_prev)
        if tool_name == "register_tool":
            text += t("core.approval.register_tool_hint")

        keyboard = {
            "inline_keyboard": [[
                {"text": t("clients.telegram_bot.btn_yes"), "callback_data": f"approve:{call_id}"},
                {"text": t("clients.telegram_bot.btn_no"), "callback_data": f"reject:{call_id}"},
            ]]
        }
        resp = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={
                "chat_id":      TELEGRAM_CHAT_ID,
                "text":         text,
                "parse_mode":   "HTML",
                "reply_markup": keyboard,
            },
            timeout=15,
        )
        if resp.status_code != 200:
            print(f"\033[91m[Approval]: Telegram CRITICAL notify failed: {resp.status_code} {resp.text[:80]}\033[0m")
    except Exception as e:
        print(f"\033[91m[Approval]: Telegram notify error: {e}\033[0m")
