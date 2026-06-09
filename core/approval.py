# ================================================================
# Project: Astakos AI Agent 🦞
# Module:  Action Approval — CRITICAL tool gate
# Αν tool είναι CRITICAL → αποθηκεύει pending, στέλνει Telegram
# Αν SAFE/WARNING → αφήνει το graph να συνεχίσει κανονικά
# ================================================================

import os
import json
from datetime import datetime, timedelta
from core.tool_risk import get_risk as _get_risk

def _effective_risk(tc: dict) -> str:
    """
    Υπολογίζει το πραγματικό risk level ενός tool call.
    Για run_terminal_command: χρησιμοποιεί classify_command() αντί για static registry.
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
        return "WARNING"  # upload/download/rename/create_folder
    if name == "mail_manager":
        action = str(tc.get("args", {}).get("action", "")).lower()
        if action in {"send", "reply", "delete"}:
            return "CRITICAL"
        if action in {"search", "check_emails", "check", "read", "read_full"}:
            return "WARNING"
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

    return _get_risk(name)

def is_critical(tc: dict) -> bool:
    return _effective_risk(tc) == "CRITICAL"

def get_risk(name: str) -> str:
    if name == "edit_project_file":
        # Core files escalate to CRITICAL — everything else stays WARNING
        _CORE = {"agents.py", "brain.py", "graph.py", "approval.py",
                 "tool_risk.py", "prompts.md", "config.py"}
        file_path = tc.get("args", {}).get("file_path", "")
        fname = os.path.basename(file_path.strip().strip("'\""))
        if fname in _CORE:
            return "CRITICAL"
        return "WARNING"

    return _get_risk(name)

PENDING_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "astakos_pending_approval.json"
)

# Pending actions παλαιότερα από αυτό θεωρούνται expired και αφαιρούνται αυτόματα.
PENDING_TTL_SECONDS: int = 3600  # 60 λεπτά

# ────────────────────────────────────────────────────────────────
# Pending approval store
# ────────────────────────────────────────────────────────────────

def save_pending(tool_name: str, tool_args: dict, tool_call_id: str):
    """Αποθηκεύει CRITICAL tool call για αργότερα."""
    pending = _load_pending()
    pending[tool_call_id] = {
        "tool_name":   tool_name,
        "tool_args":   tool_args,
        "tool_call_id": tool_call_id,
        "created_at":  datetime.now().isoformat(timespec="seconds"),
        "status":      "pending",
    }
    _save_pending(pending)


def get_pending(tool_call_id: str) -> dict | None:
    return _load_pending().get(tool_call_id)


def resolve_pending(tool_call_id: str, approved: bool):
    """Σημειώνει ως approved/rejected."""
    pending = _load_pending()
    if tool_call_id in pending:
        pending[tool_call_id]["status"] = "approved" if approved else "rejected"
        pending[tool_call_id]["resolved_at"] = datetime.now().isoformat(timespec="seconds")
        _save_pending(pending)


def pop_pending(tool_call_id: str) -> dict | None:
    """Διαβάζει και αφαιρεί από το pending store."""
    pending = _load_pending()
    item = pending.pop(tool_call_id, None)
    if item:
        _save_pending(pending)
    return item


def list_pending() -> list[dict]:
    return [v for v in _load_pending().values() if v["status"] == "pending"]


def execute_approved_pending(tool_call_id: str, tools: list) -> dict:
    """
    Εκτελεί pending action που έχει εγκριθεί από UI/Telegram.
    Το pending αφαιρείται μόνο μετά από επιτυχημένο tool.invoke().
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
    """Φορτώνει το pending store χωρίς TTL cleanup (χρησιμοποιείται εσωτερικά)."""
    if not os.path.exists(PENDING_FILE):
        return {}
    try:
        with open(PENDING_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return {}


def expire_stale_pending() -> list:
    """
    Αφαιρεί pending actions που έχουν υπερβεί το PENDING_TTL_SECONDS.
    Επιστρέφει λίστα με τα tool_call_ids που έγιναν expired.
    Καλείται αυτόματα σε κάθε _load_pending().
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
    """Φορτώνει μόνο ενεργά (non-expired, non-resolved) pending entries."""
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
    Τρέχει πριν το ToolNode.
    - SAFE / WARNING → state["approval_status"] = "ok" → συνεχίζει στα tools
    - BLOCKED        → κόβεται άμεσα από safe executor, βάζει "blocked"
    - CRITICAL       → αποθηκεύει pending, στέλνει Telegram, βάζει "pending"
    """
    from langchain_core.messages import AIMessage, ToolMessage

    last_msg = state["messages"][-1]
    tool_calls = getattr(last_msg, "tool_calls", [])

    if not tool_calls:
        return {"approval_status": "ok"}

    blocked_calls = [tc for tc in tool_calls if _effective_risk(tc) == "BLOCKED"]
    if blocked_calls:
        tool_messages = []
        for tc in blocked_calls:
            print(f"\033[91m[Approval]: 🛡️ BLOCKED — {tc['name']} rejected by safe executor\033[0m")
            tool_messages.append(ToolMessage(
                content=f"🛡️ Η εντολή `{tc['name']}` μπλοκαρίστηκε από τον safe executor και δεν μπορεί να εγκριθεί.",
                tool_call_id=tc["id"],
                name=tc["name"],
            ))

        return {
            "approval_status": "blocked",
            "messages": tool_messages,
        }

    critical_calls = [tc for tc in tool_calls if is_critical(tc)]

    if not critical_calls:
        # Όλα SAFE/WARNING — πάμε κανονικά
        risk_levels = [_effective_risk(tc) for tc in tool_calls]
        if "WARNING" in risk_levels:
            for tc in tool_calls:
                if _effective_risk(tc) == "WARNING":
                    print(f"\033[93m[Approval]: ⚠️ WARNING tool: {tc['name']}\033[0m")
                    _notify_telegram_warning(tc)
        return {"approval_status": "ok"}

    # Υπάρχουν CRITICAL calls — τα αποθηκεύουμε και ζητάμε approval
    tool_messages = []
    for tc in critical_calls:
        save_pending(tc["name"], tc.get("args", {}), tc["id"])
        print(f"\033[91m[Approval]: 🚨 CRITICAL — {tc['name']} blocked, awaiting approval\033[0m")

        # Στέλνουμε Telegram notification
        _notify_telegram(tc)

        # Επιστρέφουμε ToolMessage ώστε το graph να μην κολλήσει
        tool_messages.append(ToolMessage(
            content=f"⏳ Αναμονή έγκρισης για `{tc['name']}`. Σου έστειλα Telegram για επιβεβαίωση.",
            tool_call_id=tc["id"],
            name=tc["name"],
        ))

    return {
        "approval_status": "pending",
        "messages": tool_messages,
    }


def _notify_telegram_warning(tool_call: dict):
    """Στέλνει απλό Telegram info για WARNING tools (χωρίς approve/reject)."""
    try:
        import requests
        from config import TELEGRAM_TOKEN, TELEGRAM_CHAT_ID

        tool_name = tool_call["name"]
        args = tool_call.get("args", {})
        args_preview = ", ".join(f"{k}={repr(v)[:40]}" for k, v in args.items()) or "—"
        text = (
            f"⚠️ *WARNING Action Executed*

"
            f"Tool: `{tool_name}`
"
            f"Args: `{args_preview}`"
        )
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": text,
                "parse_mode": "Markdown",
            },
            timeout=5,
        )
    except Exception as e:
        print(f"\033[91m[Approval]: Telegram warning notify error: {e}\033[0m")


def _notify_telegram(tool_call: dict):
    """Στέλνει Telegram inline keyboard για approval."""
    try:
        import requests
        from config import TELEGRAM_TOKEN, TELEGRAM_CHAT_ID

        tool_name = tool_call["name"]
        args = tool_call.get("args", {})
        call_id = tool_call["id"]

        args_preview = ", ".join(f"{k}={repr(v)[:40]}" for k, v in args.items()) or "—"
        text = (
            f"🚨 *Action Approval Required*\n\n"
            f"Tool: `{tool_name}`\n"
            f"Args: `{args_preview}`\n\n"
            f"Εκτελώ;"
        )

        keyboard = {
            "inline_keyboard": [[
                {"text": "✅ Ναι", "callback_data": f"approve:{call_id}"},
                {"text": "❌ Όχι", "callback_data": f"reject:{call_id}"},
            ]]
        }

        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": text,
                "parse_mode": "Markdown",
                "reply_markup": keyboard,
            },
            timeout=5,
        )
    except Exception as e:
        print(f"\033[91m[Approval]: Telegram notify error: {e}\033[0m")
