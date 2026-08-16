from core.i18n import t
import re
from enum import Enum

class ExecPolicy(Enum):
    SAFE                = "safe"
    WARNING             = "warning"
    REQUIRE_CONFIRMATION = "require_confirmation"
    BLOCKED             = "blocked"


def _normalize_command(cmd: str) -> str:
    """Normalize command for security inspection by stripping PowerShell backtick obfuscation."""
    # Strip backticks within tokens (e.g. R`e`m`o`v`e`-`I`t`e`m -> Remove-Item, I`E`X -> IEX)
    return re.sub(r"`(?=[a-zA-Z0-9_\-])", "", str(cmd or ""))


# ── Patterns (order: most dangerous first) ──────────────────────
_BLOCKED = [
    # ── Direct web-download-to-shell pipelines ─────────────────
    r"\b(?:curl|wget|Invoke-WebRequest|iwr)\b.*\|\s*(?:&\s*)?(?:(?:ba|z|da)?sh|powershell|pwsh|iex|Invoke-Expression)\b",
    # ── Unix destructive ───────────────────────────────────────
    r"\brm\s+(?:.*-(?:[a-zA-Z]*r[a-zA-Z]*f|[a-zA-Z]*f[a-zA-Z]*r)|.*-[a-zA-Z]*r\b.*-[a-zA-Z]*f\b|.*-[a-zA-Z]*f\b.*-[a-zA-Z]*r\b).*\s+/(?:$|\s|\*)",  # rm -rf /, rm -r -f /, rm -rf /*
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
    # ── PowerShell execution bypass & encoded commands ─────────
    r"(?:powershell|pwsh).*\s+-(?:e|enc|encoded|encodedcommand)(?:\s+|:)",                 # encoded PS command (whitespace or colon)
    r"(?:powershell|pwsh).*\s+-(?:ep|exec|executionpolicy)(?:\s+|:)(?:bypass|unrestricted)\b",  # execution policy bypass (whitespace or colon)
    r"\bInvoke-Expression\b",            # PS eval equivalent
    r"\biex\s*[\(\s]",                   # PS iex shorthand
    # ── Dangerous system tools ─────────────────────────────────
    r"\bwmic\b",                         # WMI — can execute code remotely
    r"schtasks.*(/create|/change)",        # create/modify scheduled tasks
    r"icacls.*grant.*Everyone",            # grant Everyone access
    r"takeown\s+/f.*\s+/r",             # recursive ownership takeover
    r"cipher\s+/w",                       # wipe free space (slow+destructive)
]

_REQUIRE_CONFIRM = [
    # ── PowerShell file ops (full and shorthand flags/aliases) ──
    r"\b(?:Remove-Item|ri|rm|erase|rd|rmdir|del)\b.*-(?:r|rec|recurse)\b.*-(?:f|fo|force)\b",
    r"\b(?:Remove-Item|ri|rm|erase|rd|rmdir|del)\b.*-(?:f|fo|force)\b.*-(?:r|rec|recurse)\b",
    r"\b(?:Remove-Item|ri)\b.*astakos",           # project root protection
    # ── System state ──────────────────────────────────────────
    r"shutdown", r"restart-computer",
    r"taskkill", r"Stop-Process",
    r"Start-Process",                      # spawn arbitrary process
    r"net\s+stop\s+\w+",               # stop Windows service
    r"sc\s+(stop|delete|create)\s+",    # service control
    r"Set-ExecutionPolicy",               # PS execution policy change
    # ── Git destructive ────────────────────────────────────────
    r"git\s+reset\s+--hard",            # lose local changes
    r"git\s+clean\s+-[fd]",             # delete untracked files
    # ── SQL destructive ────────────────────────────────────────
    r"DROP\s+TABLE", r"DROP\s+DATABASE", r"DROP\s+VIEW", r"DROP\s+SCHEMA",
    r"DELETE\s+FROM",
    r"TRUNCATE\s+TABLE",
    # ── Network config ─────────────────────────────────────────
    r"netsh",                              # network configuration
    # ── Capability registry direct write ─────────────────────
    r"open\s*\([^)]*capability_registry\.json[^)]*[\x27\x22][wa]",  # write/append open
]

_WARNING = [
    r"\bRemove-Item\b",                  # without -Recurse -Force
    r"\bpip\s+install\b",
    r"\bnpm\s+install\b",                # npm packages
    r"\bgit\s+commit\b",
    r"\bgit\s+push\b",
    r"\bMove-Item\b", r"\bRename-Item\b",
    r"\bSet-Content\b", r"\bOut-File\b",
]

_PROTECTED_WRITE_PATHS = (
    r"(?:^|[/\s'\";])config\.py\b",
    r"astakos_skills[/][^/\s'\";]+\.py",
    r"tools[/]system\.py",
    r"core[/]approval\.py",
    r"core[/]agents\.py",
    r"core[/]brain\.py",
    r"core[/]safe_executor\.py",
    r"core[/]graph\.py",
    r"core[/]tool_risk\.py",
    r"core[/]capability_registry\.json",
    r"core[/]prompts\.md",
    r"core[/][^/\s'\";]+\.py",
)


def _canonicalize_path_syntax(command: str) -> str:
    """Normalize separators and dot segments for protected-path matching only."""
    canonical = command.replace("\\", "/")
    previous = ""
    while canonical != previous:
        previous = canonical
        canonical = re.sub(r"/{2,}", "/", canonical)
        canonical = re.sub(r"/\./", "/", canonical)
        canonical = re.sub(r"/[^/\s'\";]+/\.\./", "/", canonical)
    return canonical


def _protected_file_write_policy(normalized_cmd: str) -> tuple[ExecPolicy | None, str]:
    """Require approval for terminal writes to skill/registry/core files."""
    normalized_path_cmd = _canonicalize_path_syntax(normalized_cmd)
    protected = "|".join(_PROTECTED_WRITE_PATHS)
    if not re.search(protected, normalized_path_cmd, re.IGNORECASE):
        return None, ""

    write_patterns = (
        r"\bopen\s*\([^)]*,\s*['\"][wax+]",
        r"\bopen\s*\([^)]*['\"][wax+]",
        r"\b(Set-Content|Out-File|Add-Content|Clear-Content|clc)\b",
        r"\b(?:Remove-Item|ri|rm|erase|rd|rmdir|del)\b",
        r">\s*[^&|]+",
        r">>\s*[^&|]+",
        r"\.(?:write_text|write_bytes|write)\s*\(",
        r"\btee\b",
        r"\btruncate\b",
        r"\bsed\s+.*-i",
        # Conservative: copy/move commands touching protected paths require
        # approval because PowerShell/CMD destination parsing is not reliable.
        r"\b(?:Copy-Item|cp|Move-Item|mv)\b",
    )
    if any(
        re.search(pattern, normalized_path_cmd, re.IGNORECASE)
        for pattern in write_patterns
    ):
        return ExecPolicy.REQUIRE_CONFIRMATION, "protected file write via terminal"

    return None, ""


def _python_inline_policy(normalized_cmd: str) -> tuple[ExecPolicy | None, str]:
    """Require approval for inline Python code passed by option or standard input."""
    interpreter = r"(?:python(?:w|\d+(?:\.\d+)*)?|py)(?:\.exe)?"
    inline_python = (
        rf"(?:^|[\s\\/]){interpreter}[\"']?"
        r"(?:\s+[^\s]+)*?\s+-[A-Za-z]*c\S*"
    )
    if re.search(inline_python, normalized_cmd, re.IGNORECASE):
        return ExecPolicy.REQUIRE_CONFIRMATION, "python inline command (-c)"

    piped_python = (
        rf"\|\s*(?:&\s*)?{interpreter}[\"']?"
        r"(?:\s+[^|;&\r\n]+)*\s*$"
    )
    if re.search(piped_python, normalized_cmd, re.IGNORECASE):
        return ExecPolicy.REQUIRE_CONFIRMATION, "python execution from pipeline"
    return None, ""


def _register_tool_terminal_policy(normalized_cmd: str) -> tuple[ExecPolicy | None, str]:
    """Detect register_tool apply attempts hidden inside terminal commands."""
    lowered = normalized_cmd.lower().replace("\\", "/")
    if "register_tool" not in lowered:
        return None, ""

    if "register_tool.py" in lowered:
        if "--help" in lowered or re.search(r"(?:^|\s)-h(?:\s|$)", lowered):
            return ExecPolicy.SAFE, "register_tool.py help"
        if re.search(t("prompts.ext_true_1_yes_y_nai_s_s"), lowered):
            return ExecPolicy.WARNING, "register_tool.py dry-run via terminal"
        return ExecPolicy.REQUIRE_CONFIRMATION, "register_tool.py apply via terminal"

    if re.search(r"register_tool\s*(?:\.func)?\s*\(", normalized_cmd, re.IGNORECASE):
        if re.search(
            t("prompts.ext_dry_run_s_s_true_1_true_yes_y_"),
            normalized_cmd,
            re.IGNORECASE,
        ):
            return ExecPolicy.WARNING, "register_tool dry-run via terminal"
        return ExecPolicy.REQUIRE_CONFIRMATION, "register_tool apply via terminal"

    # ── alias import: "import register_tool as rt; rt(...)" ──
    alias_match = re.search(
        r"import\s+register_tool\s+as\s+(\w+)",
        normalized_cmd,
        re.IGNORECASE,
    )
    if alias_match:
        alias = re.escape(alias_match.group(1))
        if re.search(rf"\b{alias}\s*\(", normalized_cmd):
            if re.search(
                r"dry_run\s*=\s*(?:true|1|['\"](?:true|yes|y|nai|\u03bd\u03b1\u03b9)['\"])",
                normalized_cmd, re.IGNORECASE,
            ):
                return ExecPolicy.WARNING, "register_tool alias dry-run via terminal"
            return ExecPolicy.REQUIRE_CONFIRMATION, "register_tool alias apply via terminal"

    return None, ""


def classify_command(cmd: str) -> tuple[ExecPolicy, str]:
    normalized_cmd = _normalize_command(cmd)

    # 1. BLOCKED patterns (most dangerous first)
    for p in _BLOCKED:
        if re.search(p, normalized_cmd, re.IGNORECASE):
            return ExecPolicy.BLOCKED, p

    # 2. Protected file writes
    protected_policy, protected_reason = _protected_file_write_policy(normalized_cmd)
    if protected_policy is not None:
        return protected_policy, protected_reason

    # 3. Register tool terminal policy
    register_policy, register_reason = _register_tool_terminal_policy(normalized_cmd)
    if register_policy is not None:
        return register_policy, register_reason

    # 4. Conservative compound-command fallback (&&, ||, ;, \n)
    if re.search(r"(&&|\|\||;|\n|\r)", normalized_cmd):
        return ExecPolicy.REQUIRE_CONFIRMATION, "compound command"

    # 5. Require confirmation patterns
    for p in _REQUIRE_CONFIRM:
        if re.search(p, normalized_cmd, re.IGNORECASE):
            return ExecPolicy.REQUIRE_CONFIRMATION, p

    # 6. Python inline (-c) commands
    python_policy, python_reason = _python_inline_policy(normalized_cmd)
    if python_policy is not None:
        return python_policy, python_reason

    # 7. WARNING patterns
    for p in _WARNING:
        if re.search(p, normalized_cmd, re.IGNORECASE):
            return ExecPolicy.WARNING, p

    # 8. SAFE
    return ExecPolicy.SAFE, ""


def safe_execute(cmd: str, executor_func, confirm_callback=None) -> dict:
    """
    Central gate for all executions.
    confirm_callback: async fn that sends a Telegram message and waits for yes/no
    """
    policy, matched = classify_command(cmd)

    if policy == ExecPolicy.BLOCKED:
        from memory.event_log import log_event
        log_event("safe_executor", "blocked", cmd=cmd[:80], pattern=matched)
        return {"status": "blocked", "reason": t("core.safe_executor.forbidden_command", matched=matched)}

    if policy == ExecPolicy.REQUIRE_CONFIRMATION:
        from memory.event_log import log_event
        log_event("safe_executor", "pending_confirmation", cmd=cmd[:80])
        if confirm_callback:
            confirmed = confirm_callback(cmd)  # sends Telegram, waits
            if not confirmed:
                return {"status": "cancelled", "reason": t("prompts.ext_str_32")}
        else:
            return {"status": "blocked", "reason": t("prompts.ext_callback")}

    if policy == ExecPolicy.WARNING:
        from memory.event_log import log_event
        from tools.telegram import send_telegram_msg
        log_event("safe_executor", "warning_executed", cmd=cmd[:80])
        send_telegram_msg(f"⚠️ SafeExec WARNING: `{cmd[:100]}`")

    # SAFE or WARNING approved → execution
    return executor_func(cmd)
