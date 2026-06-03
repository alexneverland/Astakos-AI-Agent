# ================================================================
# Project: Astakos AI Agent 🦞
# Module:  Action Approval — CRITICAL tool gate
# Αν tool είναι CRITICAL → αποθηκεύει pending, στέλνει Telegram
# Αν SAFE/WARNING → αφήνει το graph να συνεχίσει κανονικά
# ================================================================

import os
import json
from datetime import datetime
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
            return "CRITICAL"
        elif policy == ExecPolicy.REQUIRE_CONFIRMATION:
            return "CRITICAL"
        elif policy == ExecPolicy.WARNING:
            return "WARNING"
        else:
            return "SAFE"
    return _get_risk(name)

def is_critical(tc: dict) -> bool:
    return _effective_risk(tc) == "CRITICAL"

def get_risk(name: str) -> str:
    return _get_risk(name)

PENDING_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "astakos_pending_approval.json"
)

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


def _load_pending() -> dict:
    if not os.path.exists(PENDING_FILE):
        return {}
    try:
        with open(PENDING_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return {}


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
    - CRITICAL       → αποθηκεύει pending, στέλνει Telegram, βάζει "pending"
    """
    from langchain_core.messages import AIMessage, ToolMessage

    last_msg = state["messages"][-1]
    tool_calls = getattr(last_msg, "tool_calls", [])

    if not tool_calls:
        return {"approval_status": "ok"}

    critical_calls = [tc for tc in tool_calls if is_critical(tc)]

    if not critical_calls:
        # Όλα SAFE/WARNING — πάμε κανονικά
        risk_levels = [_effective_risk(tc) for tc in tool_calls]
        if "WARNING" in risk_levels:
            names = [tc["name"] for tc in tool_calls if _effective_risk(tc) == "WARNING"]
            print(f"\033[93m[Approval]: ⚠️ WARNING tools: {names}\033[0m")
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
