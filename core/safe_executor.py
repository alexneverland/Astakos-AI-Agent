import re
from enum import Enum

class ExecPolicy(Enum):
    SAFE                = "safe"
    WARNING             = "warning"
    REQUIRE_CONFIRMATION = "require_confirmation"
    BLOCKED             = "blocked"

# ── Patterns (σειρά: πιο επικίνδυνα πρώτα) ──────────────────────
_BLOCKED = [
    r"rm\s+-[rf]{1,2}\s+/",          # rm -rf / (destructive)
    r"del\s+.*\*",                  # del /f /s C:\* (Windows mass delete)
    r"format\s+[a-zA-Z]:", r"diskpart", r"bcdedit",
    r"net\s+user.+/add", r"reg\s+delete",
]
_REQUIRE_CONFIRM = [
    r"Remove-Item.+-Recurse.+-Force",
    r"shutdown", r"restart-computer",
    r"taskkill", r"Stop-Process",
    r"git\s+push",                   # όλα τα pushes — irreversible
    r"DROP\s+TABLE", r"DELETE\s+FROM",
    r"git\s+reset\s+--hard",
    r"Remove-Item\s+.*astakos",      # οτιδήποτε αγγίζει το project root
]
_WARNING = [
    r"Remove-Item",                  # χωρίς -Recurse -Force
    r"pip\s+install",
    r"npm\s+install",                # npm packages
    r"git\s+commit",
    r"Move-Item", r"Rename-Item",
    r"Set-Content", r"Out-File",
]

def classify_command(cmd: str) -> tuple[ExecPolicy, str]:
    for p in _BLOCKED:
        if re.search(p, cmd, re.IGNORECASE):
            return ExecPolicy.BLOCKED, p
    for p in _REQUIRE_CONFIRM:
        if re.search(p, cmd, re.IGNORECASE):
            return ExecPolicy.REQUIRE_CONFIRMATION, p
    for p in _WARNING:
        if re.search(p, cmd, re.IGNORECASE):
            return ExecPolicy.WARNING, p
    return ExecPolicy.SAFE, ""


def safe_execute(cmd: str, executor_func, confirm_callback=None) -> dict:
    """
    Κεντρικό gate για όλες τις εκτελέσεις.
    confirm_callback: async fn που στέλνει Telegram και περιμένει ναι/όχι
    """
    policy, matched = classify_command(cmd)

    if policy == ExecPolicy.BLOCKED:
        from memory.event_log import log_event
        log_event("safe_executor", "blocked", cmd=cmd[:80], pattern=matched)
        return {"status": "blocked", "reason": f"Απαγορευμένη εντολή: `{matched}`"}

    if policy == ExecPolicy.REQUIRE_CONFIRMATION:
        from memory.event_log import log_event
        log_event("safe_executor", "pending_confirmation", cmd=cmd[:80])
        if confirm_callback:
            confirmed = confirm_callback(cmd)  # στέλνει Telegram, περιμένει
            if not confirmed:
                return {"status": "cancelled", "reason": "Ο χρήστης δεν επιβεβαίωσε."}
        else:
            return {"status": "blocked", "reason": "Απαιτεί επιβεβαίωση αλλά δεν υπάρχει callback."}

    if policy == ExecPolicy.WARNING:
        from memory.event_log import log_event
        from tools.telegram import send_telegram_msg
        log_event("safe_executor", "warning_executed", cmd=cmd[:80])
        send_telegram_msg(f"⚠️ SafeExec WARNING: `{cmd[:100]}`")

    # SAFE ή WARNING approved → εκτέλεση
    return executor_func(cmd)