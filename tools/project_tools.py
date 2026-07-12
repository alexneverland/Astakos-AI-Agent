# ================================================================
# Project: Astakos AI Agent 🦞
# Module:  Project Tools — Code Navigation & Editing
# Allows the Lobster to read and process
# code files from approved project folders.
#
# Permission model (project_access.json):
#   { "C:\\my_project": {"read": true, "edit": true, "label": "MyApp"} }
#
# Tools:
#   grant_project_access  — grants/removes permission to a folder (CRITICAL)
#   list_project_files    — glob inside permitted folder (SAFE)
#   read_project_file     — reads file with line numbers (SAFE)
#   edit_project_file     — Python batch patch: old→new + syntax check (WARNING/CRITICAL)
#   write_project_file    — full rewrite with syntax check (CRITICAL)
#   list_recent_files     — bounded mtime scan, BASE_DIR without permission (SAFE)
# ================================================================

import os
from core.i18n import t
import ast
import json
import fnmatch
import difflib
import threading
from datetime import datetime

from langchain_core.tools import tool
from config import BASE_DIR

# ── Permission file ──────────────────────────────────────────────
PROJECT_ACCESS_FILE = os.path.join(BASE_DIR, "project_access.json")
_access_lock = threading.Lock()

# Core files that escalate edit_project_file to CRITICAL
CORE_FILES = {
    "agents.py", "brain.py", "graph.py", "approval.py",
    "tool_risk.py", "prompts.md", "config.py",
}


# ── Helpers ──────────────────────────────────────────────────────

def _load_access() -> dict:
    try:
        if os.path.exists(PROJECT_ACCESS_FILE):
            with open(PROJECT_ACCESS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return {}


def _save_access(data: dict) -> None:
    with open(PROJECT_ACCESS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _normalize(path: str) -> str:
    return os.path.normcase(os.path.realpath(path.strip().strip("'\"")))


def _check_permission(file_path: str, need_edit: bool = False) -> tuple[bool, str]:
    """
    Checks if the file_path is within a permitted project.
    Returns (ok, error_message).
    """
    real = _normalize(file_path)
    access = _load_access()
    for folder, perms in access.items():
        norm_folder = _normalize(folder)
        if real.startswith(norm_folder + os.sep) or real == norm_folder:
            if not perms.get("read", False):
                return False, t("tools.project_tools.no_read_perm", label=perms.get('label', folder))
            if need_edit and not perms.get("edit", False):
                return False, t("tools.project_tools.no_edit_perm", label=perms.get('label', folder))
            return True, ""
    return False, t("tools.project_tools.no_project")


def _syntax_check(content: str, filename: str) -> tuple[bool, str]:
    """Checks Python syntax. Returns (ok, error_msg)."""
    if not filename.endswith(".py"):
        return True, ""
    try:
        ast.parse(content, filename=filename)
        return True, ""
    except SyntaxError as e:
        return False, f"SyntaxError L{e.lineno}: {e.msg}"


def _mini_diff(old: str, new: str, filename: str) -> str:
    """Returns a compact diff summary."""
    old_lines = old.splitlines()
    new_lines = new.splitlines()
    diff = list(difflib.unified_diff(
        old_lines, new_lines,
        fromfile=f"a/{filename}", tofile=f"b/{filename}",
        lineterm="", n=2
    ))
    if not diff:
        return t("tools.project_tools.no_changes")
    # Keep up to 40 diff lines to avoid overwhelming the context
    summary = "\n".join(diff[:40])
    if len(diff) > 40:
        summary += t("tools.project_tools.more_lines", count=len(diff)-40)
    return summary


# ── Tools ────────────────────────────────────────────────────────

@tool
def grant_project_access(folder_path: str, mode: str = "read") -> str:
    """
    Grants or revokes permission for Astakos to read/edit a project folder.

    folder_path: The project folder (e.g., C:\\mastroapp)
    mode: "read"   → read-only
          "edit"   → read + edit
          "revoke" → revoke permission
    """
    mode = mode.strip().lower()
    if mode not in ("read", "edit", "revoke"):
        return t("tools.project_tools.invalid_mode")

    folder_path = folder_path.strip().strip("'\"")
    if mode != "revoke" and not os.path.isdir(folder_path):
        return t("tools.project_tools.folder_not_found", folder_path=folder_path)

    label = os.path.basename(folder_path.rstrip("/\\")) or folder_path
    norm = os.path.normcase(os.path.realpath(folder_path))

    with _access_lock:
        access = _load_access()

        if mode == "revoke":
            # We find and remove (case-insensitive)
            to_del = [k for k in access if _normalize(k) == norm]
            if not to_del:
                return t("tools.project_tools.no_record", folder_path=folder_path)
            for k in to_del:
                del access[k]
            _save_access(access)
            return t("tools.project_tools.access_removed", label=label)

        # read or edit
        access[folder_path] = {
            "read":       True,
            "edit":       (mode == "edit"),
            "label":      label,
            "granted_at": datetime.now().isoformat(timespec="seconds"),
        }
        _save_access(access)
        mode_str = "read+edit" if mode == "edit" else "read-only"
        return t("tools.project_tools.access_granted", mode_str=mode_str, label=label, folder_path=folder_path)


@tool
def list_project_files(folder_path: str, pattern: str = "**/*.py") -> str:
    """
    Returns a list of files from an approved project folder.

    folder_path: The folder (or subfolder) of the project
    pattern:     Glob pattern (default: **/*.py). Examples:
                 "*.py", "**/*.py", "core/*.py", "**/*.md"
    """
    folder_path = folder_path.strip().strip("'\"")

    # Permission check (read is sufficient)
    ok, err = _check_permission(os.path.join(folder_path, "_"))
    if not ok:
        # We also test the folder itself
        ok, err = _check_permission(folder_path + os.sep + "x")
        if not ok:
            return err

    if not os.path.isdir(folder_path):
        return t("tools.project_tools.folder_not_found", folder_path=folder_path)

    _SKIP_DIRS = {
        "venv", ".venv", "__pycache__", ".git", "node_modules",
        "dist", "build", ".tox", ".mypy_cache", "migrations",
        "chroma_db", "telegram_photos", "telegram_uploads",
        "outputs", "avatars", ".ruff_cache",
    }

    matches = []
    # We support ** with os.walk
    for root, dirs, files in os.walk(folder_path):
        dirs[:] = [d for d in dirs if d not in _SKIP_DIRS and not d.startswith(".")]
        for fname in files:
            full = os.path.join(root, fname)
            rel  = os.path.relpath(full, folder_path)
            # fnmatch with ** emulation: if pattern has **, we simply check fname and rel
            flat_pattern = pattern.replace("**/", "").replace("**\\", "")
            if fnmatch.fnmatch(rel, pattern) or fnmatch.fnmatch(fname, flat_pattern):
                size = os.path.getsize(full)
                matches.append((rel, size))

    if not matches:
        return t("tools.project_tools.no_files_pattern", pattern=pattern, folder_path=folder_path)

    matches.sort(key=lambda x: x[0])
    lines = [t("tools.project_tools.list_header", folder_path=folder_path, count=len(matches), pattern=pattern)]
    for rel, size in matches:
        kb = size / 1024
        lines.append(f"  {rel}  ({kb:.1f} KB)")

    return "\n".join(lines)


@tool
def read_project_file(file_path: str, start_line: int = 1, end_line: int = 0) -> str:
    """
    Reads a file from an approved project folder with line numbers.

    file_path:  Full file path (e.g., C:\\mastroapp\\core\\views.py)
    start_line: Start line (default: 1)
    end_line:   End line (default: 0 = until the end, max 500 lines)
    """
    file_path = file_path.strip().strip("'\"")

    ok, err = _check_permission(file_path)
    if not ok:
        return err

    if not os.path.isfile(file_path):
        return t("tools.project_tools.file_not_found", file_path=file_path)

    size = os.path.getsize(file_path)
    if size > 500_000:  # 500 KB limit
        return t("tools.project_tools.file_too_large", size=f"{size/1024:.0f}")

    try:
        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            all_lines = f.readlines()
    except Exception as e:
        return t("tools.project_tools.read_error", e=str(e))

    total = len(all_lines)
    s = max(1, start_line) - 1
    e_line = end_line if end_line > 0 else total
    e_line = min(e_line, s + 500)  # max 500 lines per call`
    e_line = min(e_line, total)

    selected = all_lines[s:e_line]
    numbered = "".join(f"{s+i+1:4d}\t{line}" for i, line in enumerate(selected))

    fname = os.path.basename(file_path)
    header = t("tools.project_tools.read_header", fname=fname, start=s+1, end=s+len(selected), total=total)
    return header + numbered


@tool
def edit_project_file(file_path: str, old_str: str, new_str: str) -> str:
    """
    Processes a file in an approved project folder.
    Python batch approach: read → replace → syntax check → write.

    file_path: Full file path
    old_str:   The exact text you want to change (must be unique)
    new_str:   The new text that will replace old_str

    RULES:
    - If old_str is not found → error (writes nothing)
    - If old_str is found >1 time → error (ambiguous — provide larger context)
    - If .py and new code has a SyntaxError → abort (writes nothing)
    """
    file_path = file_path.strip().strip("'\"")

    ok, err = _check_permission(file_path, need_edit=True)
    if not ok:
        return err

    if not os.path.isfile(file_path):
        return t("tools.project_tools.file_not_found", file_path=file_path)

    fname = os.path.basename(file_path)

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            original = f.read()
    except Exception as e:
        return t("tools.project_tools.read_error", e=str(e))

    # No-op guard
    if old_str == new_str:
        return t("tools.project_tools.no_change_made")

    # Count occurrences
    count = original.count(old_str)
    if count == 0:
        return (
            t("tools.project_tools.old_str_not_found", fname=fname)
        )
    if count > 1:
        return (
            t("tools.project_tools.old_str_ambiguous", count=count, fname=fname)
        )

    # Apply replace
    patched = original.replace(old_str, new_str, 1)

    # Syntax check for .py
    ok_syn, syn_err = _syntax_check(patched, fname)
    if not ok_syn:
        return (
            t("tools.project_tools.syntax_error_patch", syn_err=syn_err)
        )

    # Writing
    try:
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(patched)
    except Exception as e:
        return t("tools.project_tools.write_error", e=str(e))

    diff = _mini_diff(original, patched, fname)
    old_lines = len(original.splitlines())
    new_lines = len(patched.splitlines())
    delta = new_lines - old_lines
    delta_str = f"+{delta}" if delta >= 0 else str(delta)

    # Find in which line the change occurred
    for i, (a, b) in enumerate(zip(original.splitlines(), patched.splitlines()), 1):
        if a != b:
            change_line = i
            break
    else:
        change_line = old_lines  # append to the end

    syn_msg = f"✅ Syntax check: OK" if fname.endswith(".py") else "➖ Syntax check: N/A (non-python)"

    return (
        t("tools.project_tools.edit_success", fname=fname, file_path=file_path, old_lines=old_lines, new_lines=new_lines, delta_str=delta_str, change_line=change_line, syn_msg=syn_msg, diff=diff)
    )


@tool
def grep_project_files(folder_path: str, pattern: str, file_pattern: str = "*.py", context_lines: int = 2) -> str:
    """
    Searches for a pattern within the files of an approved project folder.
    Returns file + line + content (similar to ripgrep).

    folder_path:   The project folder (e.g., C:\\mastro_app)
    pattern:       Regex pattern (e.g., "CustomerSerializer", "def create", "temp_id=None")
    file_pattern:  Glob for file types (default: *.py). Examples: "*.js", "*.py", "*"
    context_lines: Lines of context before/after each match (default: 2, max: 5)
    """
    import re

    folder_path = folder_path.strip().strip("'\"")

    ok, err = _check_permission(os.path.join(folder_path, "_"))
    if not ok:
        ok, err = _check_permission(folder_path + os.sep + "x")
        if not ok:
            return err

    if not os.path.isdir(folder_path):
        return t("tools.project_tools.folder_not_found", folder_path=folder_path)

    context_lines = max(0, min(context_lines, 5))

    _SKIP_DIRS = {
        "venv", ".venv", "__pycache__", ".git", "node_modules",
        "dist", "build", ".tox", ".mypy_cache", "migrations",
        "chroma_db", "telegram_photos", "telegram_uploads",
        "outputs", "avatars", ".ruff_cache",
    }

    try:
        regex = re.compile(pattern, re.IGNORECASE)
    except re.error as e:
        return t("tools.project_tools.invalid_regex", e=str(e))

    flat_pattern = file_pattern.replace("**/", "").replace("**\\", "")
    matches_by_file: list[tuple[str, list]] = []
    total_matches = 0

    for root, dirs, files in os.walk(folder_path):
        dirs[:] = [d for d in dirs if d not in _SKIP_DIRS and not d.startswith(".")]
        for fname in sorted(files):
            if not fnmatch.fnmatch(fname, flat_pattern):
                continue
            full = os.path.join(root, fname)
            rel  = os.path.relpath(full, folder_path)
            try:
                with open(full, "r", encoding="utf-8", errors="replace") as f:
                    lines = f.readlines()
            except Exception:
                continue

            file_matches = []
            for i, line in enumerate(lines):
                if regex.search(line):
                    start = max(0, i - context_lines)
                    end   = min(len(lines), i + context_lines + 1)
                    file_matches.append({
                        "match_line": i + 1,
                        "start":      start + 1,
                        "lines":      lines[start:end],
                    })
                    total_matches += 1
                    if total_matches >= 200:  # safety cap
                        break

            if file_matches:
                matches_by_file.append((rel, file_matches))

            if total_matches >= 200:
                break

    if not matches_by_file:
        return (
            t("tools.project_tools.grep_no_results", pattern=pattern, file_pattern=file_pattern, folder_path=folder_path)
        )

    lines_out = [
        t("tools.project_tools.grep_header", pattern=pattern, total_matches=total_matches, files_count=len(matches_by_file), folder_name=os.path.basename(folder_path)), ""
    ]

    for rel, file_matches in matches_by_file:
        lines_out.append(f"📄 **{rel}** ({len(file_matches)} matches)")
        for m in file_matches:
            for j, line in enumerate(m["lines"]):
                lineno = m["start"] + j
                marker = "▶" if lineno == m["match_line"] else " "
                lines_out.append(f"  {marker} {lineno:4d} │ {line.rstrip()}")
            lines_out.append("")

    if total_matches >= 200:
        lines_out.append(t("tools.project_tools.grep_truncated"))

    return "\n".join(lines_out)


# Same noisy folders as list_project_files/grep_project_files,
# + credentials (sensitive) — reused from list_recent_files.
_RECENT_SKIP_DIRS = {
    "venv", ".venv", "__pycache__", ".git", "node_modules",
    "dist", "build", ".tox", ".mypy_cache", "migrations",
    "chroma_db", "telegram_photos", "telegram_uploads",
    "outputs", "avatars", ".ruff_cache", "credentials",
}
_RECENT_SKIP_FILES = {".env", "secrets.py"}


@tool
def list_recent_files(folder_path: str = "", top_n: int = 15) -> str:
    """
    Finds the most recently modified files in a folder — fast,
    bounded os.walk (NOT subprocess/PowerShell), ignores venv/.git/__pycache__/
    node_modules and other noisy folders.

    USEFUL FOR: "what did I change recently", "which files did I touch", "what have I changed
    but not committed yet" — ESPECIALLY for untracked/uncommitted files
    that git log/git status doesn't show easily.
    For committed git history prefer git (run_terminal_command).
    DO NOT write ad-hoc PowerShell (Get-ChildItem -Recurse) for this purpose
    — it is slow on large trees and hangs on the 30s subprocess timeout.

    folder_path: Folder to scan. Empty = the entire Astakos repo
                 (BASE_DIR) — does not require grant_project_access, it is the
                 Astakos code itself.
                 For external projects (outside C:\\astakos_v2) it requires
                 grant_project_access first.
    top_n: How many of the most recent files to return (default 15, max 50).
    """
    folder_path = (folder_path or "").strip().strip("'\"")
    top_n = max(1, min(int(top_n), 50))

    target = folder_path or BASE_DIR
    real_target = os.path.realpath(target)
    real_base = os.path.realpath(BASE_DIR)
    is_internal = real_target == real_base or real_target.startswith(real_base + os.sep)

    if not is_internal:
        ok, err = _check_permission(os.path.join(target, "_"))
        if not ok:
            ok, err = _check_permission(target + os.sep + "x")
            if not ok:
                return err

    if not os.path.isdir(target):
        return t("tools.project_tools.target_folder_not_found", target=target)

    entries: list[tuple[float, str]] = []
    scanned = 0
    SAFETY_CAP = 8000  # bounded — no subprocess timeout needed
    stopped_early = False

    for root, dirs, files in os.walk(target):
        dirs[:] = [d for d in dirs if d not in _RECENT_SKIP_DIRS and not d.startswith(".")]
        for fname in files:
            if fname in _RECENT_SKIP_FILES:
                continue
            scanned += 1
            if scanned > SAFETY_CAP:
                stopped_early = True
                break
            full = os.path.join(root, fname)
            try:
                mtime = os.path.getmtime(full)
            except OSError:
                continue
            entries.append((mtime, os.path.relpath(full, target)))
        if stopped_early:
            break

    if not entries:
        return t("tools.project_tools.no_recent_files", target=target)

    entries.sort(key=lambda x: x[0], reverse=True)
    top = entries[:top_n]

    label = "Astakos repo (C:\\astakos_v2)" if is_internal else (os.path.basename(target.rstrip("/\\")) or target)
    lines = [t("tools.project_tools.recent_header", label=label, top_count=len(top), total_count=len(entries))]
    now = datetime.now()
    for mtime, rel in top:
        dt = datetime.fromtimestamp(mtime)
        delta = now - dt
        if delta.days > 0:
            age = t("tools.project_tools.days_ago", days=delta.days)
        elif delta.seconds >= 3600:
            age = t("tools.project_tools.hours_ago", hours=delta.seconds // 3600)
        else:
            age = t("tools.project_tools.mins_ago", mins=max(1, delta.seconds // 60))
        lines.append(f"  {rel}  ({dt.strftime('%Y-%m-%d %H:%M')}, {age})")

    if stopped_early:
        lines.append(
            t("tools.project_tools.recent_truncated", safety_cap=SAFETY_CAP)
        )

    return "\n".join(lines)


@tool
def write_project_file(file_path: str, content: str) -> str:
    """
    Writes an entire file to an approved project folder (full rewrite).
    Use ONLY for new files or when edit_project_file is not sufficient.
    For existing files, prefer edit_project_file.

    file_path: Full file path
    content:   Full content of the new file
    """
    file_path = file_path.strip().strip("'\"")

    ok, err = _check_permission(file_path, need_edit=True)
    if not ok:
        return err

    fname = os.path.basename(file_path)

    # Syntax check before writing
    ok_syn, syn_err = _syntax_check(content, fname)
    if not ok_syn:
        return (
            t("tools.project_tools.syntax_error_content", syn_err=syn_err)
        )

    is_new = not os.path.exists(file_path)

    try:
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(content)
    except Exception as e:
        return t("tools.project_tools.write_error", e=str(e))

    lines = len(content.splitlines())
    action = t("tools.project_tools.created") if is_new else t("tools.project_tools.replaced")
    return t("tools.project_tools.write_success", fname=fname, action=action, lines=lines, size=f"{len(content.encode())/1024:.1f}")
