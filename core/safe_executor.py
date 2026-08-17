from core.i18n import t
import re
import shlex
from enum import Enum

class ExecPolicy(Enum):
    SAFE                = "safe"
    WARNING             = "warning"
    REQUIRE_CONFIRMATION = "require_confirmation"
    BLOCKED             = "blocked"


def _normalize_command(cmd: str) -> str:
    """Normalize command for security inspection by stripping PowerShell backtick obfuscation."""
    # Strip inline backtick escapes (including punctuation in protected paths).
    # Preserve a trailing backtick because it is PowerShell line continuation.
    return re.sub(r"`(?=[^\r\n])", "", str(cmd or ""))


# ── Patterns (order: most dangerous first) ──────────────────────
_BLOCKED = [
    # ── Direct web-download-to-shell pipelines ─────────────────
    r"\b(?:curl|wget|Invoke-WebRequest|iwr|Invoke-RestMethod|irm)\b.*\|\s*(?:&\s*)?['\"]?(?:(?:ba|z|da)?sh|powershell|pwsh|iex|Invoke-Expression)\b",
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
    # ── Mutating file operations ──────────────────────────────
    r"\b(?:Set-Content|sc|Out-File|Add-Content|ac|Clear-Content|clc|New-Item|ni)\b",
    r"\b(?:Move-Item|mi|mv|Rename-Item|rni|ren)\b",
    r"\b(?:Copy-Item|cpi|cp)\b",
    r"\b(?:Remove-Item|ri)\b",
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
    r"\bpip\s+install\b",
    r"\bnpm\s+install\b",                # npm packages
    r"\bgit\s+commit\b",
    r"\bgit\s+push\b",
]

_PROTECTED_WRITE_PATHS = (
    r"(?:^|[/\s'\";])config\.py\b",
    r"(?:^|[/\s'\";])\.env\b",
    r"(?:^|[/\s'\";])credentials\.json\b",
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

_SENSITIVE_PROTECTED_PATHS = (
    r"(?:^|[/\s'\";])\.env\b",
    r"(?:^|[/\s'\";])credentials\.json\b",
    r"(?:^|[/\s'\";])\.[eE][^\s'\";*?\[\]]*[*?\[\]]",                # .e*, .e??, .e[n]v, .env*
    r"(?:^|[/\s'\";])\.[^\s'\";*?\[\]]*[*?\[\]][^\s'\";]*nv\b",      # .?nv, .*nv
    r"(?:^|[/\s'\";])[^\s'\";*?\[\]]*[*?\[\]][^\s'\";]*\.env\b",      # *.env
    r"(?:^|[/\s'\";])cred[a-zA-Z0-9_\-]*[*?\[\]]",                   # cred*, cred[e]ntials.json
    r"(?:^|[/\s'\";])c[^\s'\";*?\[\]]*[*?\[\]][^\s'\";]*json\b",     # c*s.json
    r"(?:^|[/\s'\";])[^\s'\";*?\[\]]*[*?\[\]][^\s'\";]*credentials\.json\b",
    r"(?:^|[/\s'\";])token[a-zA-Z0-9_\-]*[*?\[\]]",                  # token*.json
)

_SAFE_READ_COMMAND = re.compile(
    r"^\s*(?:"
    r"Get-Content|gc|type|cat|Select-String|sls|"
    r"Get-ChildItem|gci|dir|ls|Test-Path|Resolve-Path|Get-Item|gi"
    r")\b[^;&|><\r\n\(\)\$]*$",
    re.IGNORECASE,
)

_SAFE_COMMAND = re.compile(
    r"^\s*(?:"
    r"pytest|"
    r"(?:python(?:w|\d+(?:\.\d+)*)?|py)(?:\.exe)?\s+-m\s+pytest"
    r")\b[^;&|><\r\n]*$",
    re.IGNORECASE,
)


def _is_safe_git_command(tokens: list[str]) -> bool:
    """Return whether a git command invocation is strictly read-only."""
    if not tokens or tokens[0].lower() != "git":
        return False
    if len(tokens) == 1:
        return False

    subcmd = tokens[1].lower()
    # Simple safe subcommands that only inspect state
    if subcmd in {"status", "log", "show"}:
        return True

    if subcmd == "diff":
        # Disallow --output / -o which writes diff output to a file
        return not any(
            arg.lower().startswith("--output") or arg.lower() == "-o"
            for arg in tokens[2:]
        )

    if subcmd == "branch":
        branch_args = tokens[2:]
        if not branch_args:
            return True  # plain 'git branch' lists branches

        safe_branch_options = {
            "-a", "--all", "-r", "--remotes", "-v", "-vv", "--verbose",
            "--list", "-l", "--show-current", "--merged", "--no-merged",
            "--contains", "--no-contains",
        }
        for arg in branch_args:
            lowered = arg.lower()
            if lowered in safe_branch_options or lowered.startswith("--sort=") or lowered.startswith("--format="):
                continue
            if "--list" in branch_args or "-l" in branch_args:
                if not lowered.startswith("-"):
                    continue
            # Any delete (-d, -D, --delete), move (-m, -M, --move), copy (-c, -C), or branch creation
            return False
        return True

    return False


def _canonicalize_path_syntax(command: str) -> str:
    """Normalize separators, strip inline quotes, and resolve dot segments for protected-path matching only."""
    unquoted = command.replace("'", "").replace('"', "")
    canonical = unquoted.replace("\\", "/")
    previous = ""
    while canonical != previous:
        previous = canonical
        canonical = re.sub(r"/{2,}", "/", canonical)
        canonical = re.sub(r"/\./", "/", canonical)
        canonical = re.sub(r"/[^/;]+/\.\./", "/", canonical)
    return canonical


def _protected_file_write_policy(normalized_cmd: str) -> tuple[ExecPolicy | None, str]:
    """Fail closed for terminal operations that touch protected repository files."""
    normalized_path_cmd = _canonicalize_path_syntax(normalized_cmd)

    if re.search(
        "|".join(_SENSITIVE_PROTECTED_PATHS),
        normalized_path_cmd,
        re.IGNORECASE,
    ):
        return ExecPolicy.REQUIRE_CONFIRMATION, "sensitive protected file via terminal"

    protected = "|".join(_PROTECTED_WRITE_PATHS)
    if not re.search(protected, normalized_path_cmd, re.IGNORECASE):
        return None, ""

    if not re.search(r"(\$[\(\{]|`|\(|\))", normalized_path_cmd) and _SAFE_READ_COMMAND.fullmatch(normalized_path_cmd):
        return None, ""
    return ExecPolicy.REQUIRE_CONFIRMATION, "protected file operation via terminal"


_PYTHON_INTERPRETER = r"(?:python(?:w|\d+(?:\.\d+)*)?|py)(?:\.exe)?"


def _shell_tokens(command: str) -> list[str]:
    """Return shell-like tokens without executing the command."""
    try:
        return shlex.split(command, posix=False)
    except ValueError:
        return []


def _is_python_interpreter(token: str) -> bool:
    """Return whether a token names a supported Python interpreter executable."""
    executable = token.strip("'\"")
    pattern = rf"(?:^|[\\/]){_PYTHON_INTERPRETER}$"
    return bool(re.search(pattern, executable, re.IGNORECASE))


def _python_direct_policy(tokens: list[str]) -> tuple[ExecPolicy | None, str]:
    """Inspect interpreter options until Python selects a module or script."""
    option_index = 0
    while option_index < len(tokens):
        token = tokens[option_index].strip("'\"")
        lowered = token.lower()
        if token == "-":
            return ExecPolicy.REQUIRE_CONFIRMATION, "python program from stdin"
        if lowered.startswith("-c") and not lowered.startswith("--"):
            return ExecPolicy.REQUIRE_CONFIRMATION, "python inline command (-c)"
        if lowered == "-m" or lowered.startswith("-m"):
            return None, ""
        if lowered == "--check-hash-based-pycs":
            option_index += 2
            continue
        if token.startswith("-X") or token.startswith("-W"):
            option_index += 1 if len(token) > 2 else 2
            continue
        if re.fullmatch(r"-[A-Za-z]+", token) and "c" in lowered[1:]:
            return ExecPolicy.REQUIRE_CONFIRMATION, "python inline command (-c)"
        if token.startswith("-"):
            option_index += 1
            continue
        return None, ""
    return None, ""


def _unwrap_command_wrapper(normalized_cmd: str) -> str | None:
    """Extract a recognized shell wrapper payload without executing it."""
    tokens = _shell_tokens(normalized_cmd)
    if not tokens:
        return None

    if tokens[0] == "&":
        tokens = tokens[1:]
    if not tokens:
        return None

    executable = re.split(r"[\\/]", tokens[0].strip("'\"").lower())[-1]
    if executable in {"cmd", "cmd.exe"}:
        for index, token in enumerate(tokens[1:], start=1):
            if token.lower() in {"/c", "/k"} and index + 1 < len(tokens):
                payload = " ".join(tokens[index + 1:]).strip()
                if len(payload) >= 2 and payload[0] == payload[-1] and payload[0] in "'\"":
                    return payload[1:-1].strip()
                return payload
        return None

    if executable in {"powershell", "powershell.exe", "pwsh", "pwsh.exe"}:
        for index, token in enumerate(tokens[1:], start=1):
            if token.lower() in {"-command", "-c"} and index + 1 < len(tokens):
                payload = " ".join(tokens[index + 1:]).strip()
                if len(payload) >= 2 and payload[0] == payload[-1] and payload[0] in "'\"":
                    return payload[1:-1].strip()
                return payload
    return None


def _python_inline_policy(normalized_cmd: str) -> tuple[ExecPolicy | None, str]:
    """Require approval for direct or piped Python execution."""
    tokens = _shell_tokens(normalized_cmd)

    if tokens and tokens[0] == "&":
        tokens = tokens[1:]
    if tokens and _is_python_interpreter(tokens[0]):
        return _python_direct_policy(tokens[1:])

    pipeline_tail = normalized_cmd.rsplit("|", maxsplit=1)[-1]
    pipeline_tokens = _shell_tokens(pipeline_tail)
    if pipeline_tokens and pipeline_tokens[0] == "&":
        pipeline_tokens = pipeline_tokens[1:]
    if pipeline_tokens and _is_python_interpreter(pipeline_tokens[0]):
        return ExecPolicy.REQUIRE_CONFIRMATION, "python execution from pipeline"
    return None, ""


def _register_tool_terminal_policy(normalized_cmd: str) -> tuple[ExecPolicy | None, str]:
    """Detect register_tool apply attempts hidden inside terminal commands."""
    lowered = normalized_cmd.lower().replace("\\", "/")
    if "register_tool" not in lowered:
        return None, ""

    if "register_tool.py" in lowered:
        if "--help" in lowered or re.search(r"(?:^|\s)-h(?:\s|$)", lowered):
            if re.search(r"(&&|\|\||;|\||&|\n|\r)", normalized_cmd):
                return None, ""
            return ExecPolicy.SAFE, "register_tool.py help"
        if re.search(t("prompts.ext_true_1_yes_y_nai_s_s"), lowered):
            if re.search(r"(&&|\|\||;|\||&|\n|\r)", normalized_cmd):
                return None, ""
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


def classify_command(cmd: str, _wrapper_depth: int = 0) -> tuple[ExecPolicy, str]:
    normalized_cmd = _normalize_command(cmd)

    # 1. BLOCKED patterns (most dangerous first)
    for p in _BLOCKED:
        if re.search(p, normalized_cmd, re.IGNORECASE):
            return ExecPolicy.BLOCKED, p

    # Inspect the payload of common wrappers before classifying the wrapper itself.
    if _wrapper_depth < 2:
        wrapper_payload = _unwrap_command_wrapper(normalized_cmd)
        if wrapper_payload:
            return classify_command(wrapper_payload, _wrapper_depth + 1)

    # 2. Register tool terminal policy
    register_policy, register_reason = _register_tool_terminal_policy(normalized_cmd)
    if register_policy is not None:
        return register_policy, register_reason

    # 3. Protected file operations
    protected_policy, protected_reason = _protected_file_write_policy(normalized_cmd)
    if protected_policy is not None:
        return protected_policy, protected_reason

    # 4. Conservative compound-command fallback (&&, ||, ;, |, &, \n)
    if re.search(r"(&&|\|\||;|\||&|\n|\r)", normalized_cmd):
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

    # 8. Explicitly allow only known read/test commands without evaluative subexpressions.
    # Unknown, evaluative, or mutating commands require approval instead of being treated as safe by default.
    if not re.search(r"(\$[\(\{]|`|\(|\))", normalized_cmd):
        if _SAFE_READ_COMMAND.fullmatch(normalized_cmd):
            return ExecPolicy.SAFE, "known safe terminal command"
        tokens = _shell_tokens(normalized_cmd)
        if _is_safe_git_command(tokens):
            return ExecPolicy.SAFE, "known safe terminal command"
        if _SAFE_COMMAND.fullmatch(normalized_cmd):
            return ExecPolicy.SAFE, "known safe terminal command"

    return ExecPolicy.REQUIRE_CONFIRMATION, "unknown terminal command"


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
