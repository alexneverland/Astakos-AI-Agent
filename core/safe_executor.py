import re
from enum import Enum

class ExecPolicy(Enum):
    SAFE                = "safe"
    WARNING             = "warning"
    REQUIRE_CONFIRMATION = "require_confirmation"
    BLOCKED             = "blocked"

# ── Patterns (σειρά: πιο επικίνδυνα πρώτα) ──────────────────────
_BLOCKED = [
    # ── Unix destructive ───────────────────────────────────────
    r"rm\s+-[rf]{1,2}\s+/",              # rm -rf /
    # ── Windows CMD destructive ────────────────────────────────
    r"del\s+.*\*",                       # del /f /s C:\*
    r"del\s+/[fFsS].*\s+/[sS]",         # del /f /s <path> (subtree)
    r"rd\s+/[sS]",                        # rd /s (rmdir subtree)
    r"rmdir\s+/[sS]",                     # rmdir /s
    r"erase\s+.*\*",                     # erase *.* (mass delete)
    r"format\s+[a-zA-Z]:",               # format C:
    r"diskpart",                           # disk partitioning
    r"bcdedit",                            # boot config editor
    # ── Windows user/registry ──────────────────────────────────
    r"net\s+user.+/add",                  # add user
    r"net\s+localgroup.+/add",            # add to admin group
    r"reg\s+delete",                      # delete registry key
    r"reg\s+add",                         # add/modify registry key
    r"reg\s+import",                      # import registry file
    # ── PowerShell execution bypass ────────────────────────────
    r"powershell.*-[eE]ncodedCommand",     # encoded PS command
    r"powershell.*-[eE]xec.*[bB]ypass",   # execution policy bypass
    r"Invoke-Expression",                  # PS eval equivalent
    r"iex\s*\(",                         # PS iex() shorthand
    r"IEX\s*\(",
    # ── Dangerous system tools ─────────────────────────────────
    r"wmic",                               # WMI — can execute code remotely
    r"schtasks.*(/create|/change)",        # create/modify scheduled tasks
    r"icacls.*grant.*Everyone",            # grant Everyone access
    r"takeown\s+/f.*\s+/r",             # recursive ownership takeover
    r"cipher\s+/w",                       # wipe free space (slow+destructive)
]
_REQUIRE_CONFIRM = [
    # ── PowerShell file ops ────────────────────────────────────
    r"Remove-Item.+-Recurse.+-Force",      # rm -rf equivalent
    r"Remove-Item\s+.*astakos",           # project root protection
    # ── System state ──────────────────────────────────────────
    r"shutdown", r"restart-computer",
    r"taskkill", r"Stop-Process",
    r"Start-Process",                      # spawn arbitrary process
    r"net\s+stop\s+\w+",               # stop Windows service
    r"sc\s+(stop|delete|create)\s+",    # service control
    r"Set-ExecutionPolicy",               # PS execution policy change
    # ── Git destructive ────────────────────────────────────────
    r"git\s+push",                        # irreversible remote push
    r"git\s+reset\s+--hard",            # lose local changes
    r"git\s+clean\s+-[fd]",             # delete untracked files
    # ── SQL destructive ────────────────────────────────────────
    r"DROP\s+TABLE", r"DROP\s+DATABASE",
    r"DELETE\s+FROM",
    r"TRUNCATE\s+TABLE",
    # ── Network config ─────────────────────────────────────────
    r"netsh",                              # network configuration
    # ── Capability registry direct write ─────────────────────
    r"open\s*\([^)]*capability_registry\.json[^)]*[\x27\x22][wa]",  # write/append open
]
_WARNING = [
    r"Remove-Item",                  # χωρίς -Recurse -Force
    r"pip\s+install",
    r"npm\s+install",                # npm packages
    r"git\s+commit",
    r"git\s+push",
    r"Move-Item", r"Rename-Item",
    r"Set-Content", r"Out-File",
]

_PROTECTED_WRITE_PATHS = (
    r"astakos_skills[/][^/\s'\";]+\.py",
    r"tools[/]system\.py",
    r"core[/]tool_risk\.py",
    r"core[/]capability_registry\.json",
    r"core[/]safe_executor\.py",
    r"core[/]graph\.py",
    r"core[/]prompts\.md",
)


def _protected_file_write_policy(cmd: str) -> tuple[ExecPolicy | None, str]:
    """Require approval for terminal writes to skill/registry/core files."""
    normalized = cmd.replace("\\", "/")
    protected = "|".join(_PROTECTED_WRITE_PATHS)
    if not re.search(protected, normalized, re.IGNORECASE):
        return None, ""

    write_patterns = (
        r"\bopen\s*\([^)]*,\s*['\"][wax+]",
        r"\b(Set-Content|Out-File|Add-Content)\b",
        r">\s*[^&|]+",
        r">>\s*[^&|]+",
        r"\.write\s*\(",
        r"\.write_text\s*\(",
    )
    if any(re.search(pattern, cmd, re.IGNORECASE) for pattern in write_patterns):
        return ExecPolicy.REQUIRE_CONFIRMATION, "protected file write via terminal"

    return None, ""

def _register_tool_terminal_policy(cmd: str) -> tuple[ExecPolicy | None, str]:
    """Detect register_tool apply attempts hidden inside terminal commands."""
    lowered = cmd.lower().replace("\\", "/")
    if "register_tool" not in lowered:
        return None, ""

    if "register_tool.py" in lowered:
        if "--help" in lowered or re.search(r"(?:^|\s)-h(?:\s|$)", lowered):
            return ExecPolicy.SAFE, "register_tool.py help"
        if re.search(r"(?:true|1|yes|y|nai|ναι)\s*['\"]?\s*$", lowered):
            return ExecPolicy.WARNING, "register_tool.py dry-run via terminal"
        return ExecPolicy.REQUIRE_CONFIRMATION, "register_tool.py apply via terminal"

    if re.search(r"register_tool\s*(?:\.func)?\s*\(", cmd, re.IGNORECASE):
        if re.search(
            r"dry_run\s*=\s*(?:true|1|['\"](?:true|yes|y|nai|ναι)['\"])",
            cmd,
            re.IGNORECASE,
        ):
            return ExecPolicy.WARNING, "register_tool dry-run via terminal"
        return ExecPolicy.REQUIRE_CONFIRMATION, "register_tool apply via terminal"

    # ── alias import: "import register_tool as rt; rt(...)" ──
    alias_match = re.search(r"import\s+register_tool\s+as\s+(\w+)", cmd, re.IGNORECASE)
    if alias_match:
        alias = re.escape(alias_match.group(1))
        if re.search(rf"\b{alias}\s*\(", cmd):
            if re.search(
                r"dry_run\s*=\s*(?:true|1|['\"](?:true|yes|y|nai|\u03bd\u03b1\u03b9)['\"])",
                cmd, re.IGNORECASE,
            ):
                return ExecPolicy.WARNING, "register_tool alias dry-run via terminal"
            return ExecPolicy.REQUIRE_CONFIRMATION, "register_tool alias apply via terminal"

    return None, ""

def classify_command(cmd: str) -> tuple[ExecPolicy, str]:
    for p in _BLOCKED:
        if re.search(p, cmd, re.IGNORECASE):
            return ExecPolicy.BLOCKED, p
    protected_policy, protected_reason = _protected_file_write_policy(cmd)
    if protected_policy is not None:
        return protected_policy, protected_reason
    register_policy, register_reason = _register_tool_terminal_policy(cmd)
    if register_policy is not None:
        return register_policy, register_reason
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
