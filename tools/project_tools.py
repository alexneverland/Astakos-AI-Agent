# ================================================================
# Project: Astakos AI Agent 🦞
# Module:  Project Tools — Code Navigation & Editing
# Επιτρέπει στον Αστακό να διαβάζει και να επεξεργάζεται
# αρχεία κώδικα από εγκεκριμένα project folders.
#
# Permission model (project_access.json):
#   { "C:\\my_project": {"read": true, "edit": true, "label": "MyApp"} }
#
# Tools:
#   grant_project_access  — δίνει/αφαιρεί δικαίωμα σε folder (CRITICAL)
#   list_project_files    — glob μέσα σε permitted folder (SAFE)
#   read_project_file     — διαβάζει αρχείο με line numbers (SAFE)
#   edit_project_file     — Python batch patch: old→new + syntax check (WARNING/CRITICAL)
#   write_project_file    — full rewrite με syntax check (CRITICAL)
# ================================================================

import os
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
    Ελέγχει αν το file_path βρίσκεται εντός κάποιου permitted project.
    Επιστρέφει (ok, error_message).
    """
    real = _normalize(file_path)
    access = _load_access()
    for folder, perms in access.items():
        norm_folder = _normalize(folder)
        if real.startswith(norm_folder + os.sep) or real == norm_folder:
            if not perms.get("read", False):
                return False, f"❌ Το project '{perms.get('label', folder)}' δεν έχει read permission."
            if need_edit and not perms.get("edit", False):
                return False, f"❌ Το project '{perms.get('label', folder)}' έχει μόνο read — δεν επιτρέπεται edit."
            return True, ""
    return False, f"❌ Το path δεν ανήκει σε κανένα εγκεκριμένο project. Ζήτα από τον Λάζαρο να τρέξει grant_project_access."


def _syntax_check(content: str, filename: str) -> tuple[bool, str]:
    """Ελέγχει Python syntax. Επιστρέφει (ok, error_msg)."""
    if not filename.endswith(".py"):
        return True, ""
    try:
        ast.parse(content, filename=filename)
        return True, ""
    except SyntaxError as e:
        return False, f"SyntaxError L{e.lineno}: {e.msg}"


def _mini_diff(old: str, new: str, filename: str) -> str:
    """Επιστρέφει compact diff summary."""
    old_lines = old.splitlines()
    new_lines = new.splitlines()
    diff = list(difflib.unified_diff(
        old_lines, new_lines,
        fromfile=f"a/{filename}", tofile=f"b/{filename}",
        lineterm="", n=2
    ))
    if not diff:
        return "(χωρίς αλλαγές)"
    # Κρατάμε μέχρι 40 γραμμές diff για να μην πνίξουμε το context
    summary = "\n".join(diff[:40])
    if len(diff) > 40:
        summary += f"\n... (+{len(diff)-40} γραμμές)"
    return summary


# ── Tools ────────────────────────────────────────────────────────

@tool
def grant_project_access(folder_path: str, mode: str = "read") -> str:
    """
    Δίνει ή αφαιρεί δικαίωμα στον Αστακό να διαβάζει/επεξεργάζεται ένα project folder.

    folder_path: Ο φάκελος του project (π.χ. C:\\mastroapp)
    mode: "read"   → μόνο ανάγνωση
          "edit"   → ανάγνωση + επεξεργασία
          "revoke" → αφαίρεση δικαιώματος
    """
    mode = mode.strip().lower()
    if mode not in ("read", "edit", "revoke"):
        return "❌ Μη έγκυρο mode. Χρησιμοποίησε: read | edit | revoke"

    folder_path = folder_path.strip().strip("'\"")
    if mode != "revoke" and not os.path.isdir(folder_path):
        return f"❌ Ο φάκελος '{folder_path}' δεν υπάρχει."

    label = os.path.basename(folder_path.rstrip("/\\")) or folder_path
    norm = os.path.normcase(os.path.realpath(folder_path))

    with _access_lock:
        access = _load_access()

        if mode == "revoke":
            # Βρίσκουμε και αφαιρούμε (case-insensitive)
            to_del = [k for k in access if _normalize(k) == norm]
            if not to_del:
                return f"⚠️ Δεν βρέθηκε εγγραφή για '{folder_path}'."
            for k in to_del:
                del access[k]
            _save_access(access)
            return f"✅ Αφαιρέθηκε η πρόσβαση για '{label}'."

        # read ή edit
        access[folder_path] = {
            "read":       True,
            "edit":       (mode == "edit"),
            "label":      label,
            "granted_at": datetime.now().isoformat(timespec="seconds"),
        }
        _save_access(access)
        mode_str = "read+edit" if mode == "edit" else "read-only"
        return f"✅ Πρόσβαση '{mode_str}' δόθηκε για '{label}' ({folder_path})."


@tool
def list_project_files(folder_path: str, pattern: str = "**/*.py") -> str:
    """
    Επιστρέφει λίστα αρχείων από εγκεκριμένο project folder.

    folder_path: Ο φάκελος (ή subfolder) του project
    pattern:     Glob pattern (default: **/*.py). Παραδείγματα:
                 "*.py", "**/*.py", "core/*.py", "**/*.md"
    """
    folder_path = folder_path.strip().strip("'\"")

    # Permission check (read αρκεί)
    ok, err = _check_permission(os.path.join(folder_path, "_"))
    if not ok:
        # Δοκιμάζουμε και το ίδιο το folder
        ok, err = _check_permission(folder_path + os.sep + "x")
        if not ok:
            return err

    if not os.path.isdir(folder_path):
        return f"❌ Ο φάκελος '{folder_path}' δεν υπάρχει."

    _SKIP_DIRS = {
        "venv", ".venv", "__pycache__", ".git", "node_modules",
        "dist", "build", ".tox", ".mypy_cache", "migrations",
        "chroma_db", "telegram_photos", "telegram_uploads",
        "outputs", "avatars", ".ruff_cache",
    }

    matches = []
    # Υποστηρίζουμε ** με os.walk
    for root, dirs, files in os.walk(folder_path):
        dirs[:] = [d for d in dirs if d not in _SKIP_DIRS and not d.startswith(".")]
        for fname in files:
            full = os.path.join(root, fname)
            rel  = os.path.relpath(full, folder_path)
            # fnmatch με ** emulation: αν pattern έχει **, ελέγχουμε απλά το fname και το rel
            flat_pattern = pattern.replace("**/", "").replace("**\\", "")
            if fnmatch.fnmatch(rel, pattern) or fnmatch.fnmatch(fname, flat_pattern):
                size = os.path.getsize(full)
                matches.append((rel, size))

    if not matches:
        return f"⚠️ Δεν βρέθηκαν αρχεία με pattern '{pattern}' στο '{folder_path}'."

    matches.sort(key=lambda x: x[0])
    lines = [f"📁 {folder_path} — {len(matches)} αρχεία (pattern: {pattern})\n"]
    for rel, size in matches:
        kb = size / 1024
        lines.append(f"  {rel}  ({kb:.1f} KB)")

    return "\n".join(lines)


@tool
def read_project_file(file_path: str, start_line: int = 1, end_line: int = 0) -> str:
    """
    Διαβάζει αρχείο από εγκεκριμένο project folder με line numbers.

    file_path:  Πλήρες path αρχείου (π.χ. C:\\mastroapp\\core\\views.py)
    start_line: Γραμμή έναρξης (default: 1)
    end_line:   Γραμμή λήξης (default: 0 = μέχρι τέλος, max 500 γραμμές)
    """
    file_path = file_path.strip().strip("'\"")

    ok, err = _check_permission(file_path)
    if not ok:
        return err

    if not os.path.isfile(file_path):
        return f"❌ Το αρχείο δεν υπάρχει: {file_path}"

    size = os.path.getsize(file_path)
    if size > 500_000:  # 500 KB limit
        return f"❌ Το αρχείο είναι πολύ μεγάλο ({size/1024:.0f} KB). Χρησιμοποίησε start_line/end_line."

    try:
        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            all_lines = f.readlines()
    except Exception as e:
        return f"❌ Σφάλμα ανάγνωσης: {e}"

    total = len(all_lines)
    s = max(1, start_line) - 1
    e_line = end_line if end_line > 0 else total
    e_line = min(e_line, s + 500)  # max 500 γραμμές ανά κλήση
    e_line = min(e_line, total)

    selected = all_lines[s:e_line]
    numbered = "".join(f"{s+i+1:4d}\t{line}" for i, line in enumerate(selected))

    fname = os.path.basename(file_path)
    header = f"📄 {fname} — γραμμές {s+1}–{s+len(selected)} / {total} total\n"
    return header + numbered


@tool
def edit_project_file(file_path: str, old_str: str, new_str: str) -> str:
    """
    Επεξεργάζεται αρχείο σε εγκεκριμένο project folder.
    Python batch approach: διαβάζει → replace → syntax check → γράφει.

    file_path: Πλήρες path αρχείου
    old_str:   Το ακριβές κείμενο που θέλεις να αλλάξεις (πρέπει να είναι μοναδικό)
    new_str:   Το νέο κείμενο που θα αντικαταστήσει το old_str

    ΚΑΝΟΝΕΣ:
    - Αν old_str δεν βρεθεί → σφάλμα (δεν γράφει τίποτα)
    - Αν old_str βρεθεί >1 φορά → σφάλμα (ambiguous — δώσε πιο μεγάλο context)
    - Αν .py και νέος κώδικας έχει SyntaxError → abort (δεν γράφει τίποτα)
    """
    file_path = file_path.strip().strip("'\"")

    ok, err = _check_permission(file_path, need_edit=True)
    if not ok:
        return err

    if not os.path.isfile(file_path):
        return f"❌ Το αρχείο δεν υπάρχει: {file_path}"

    fname = os.path.basename(file_path)

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            original = f.read()
    except Exception as e:
        return f"❌ Σφάλμα ανάγνωσης: {e}"

    # No-op guard
    if old_str == new_str:
        return "⚠️ old_str και new_str είναι πανομοιότυπα — καμία αλλαγή έγινε."

    # Μέτρηση εμφανίσεων
    count = original.count(old_str)
    if count == 0:
        return (
            f"❌ old_str δεν βρέθηκε στο {fname}.\n"
            f"Tip: Χρησιμοποίησε read_project_file για να δεις το ακριβές κείμενο."
        )
    if count > 1:
        return (
            f"❌ old_str βρέθηκε {count} φορές στο {fname} — ambiguous.\n"
            f"Δώσε πιο πολύ context στο old_str ώστε να είναι μοναδικό."
        )

    # Εφαρμογή replace
    patched = original.replace(old_str, new_str, 1)

    # Syntax check για .py
    ok_syn, syn_err = _syntax_check(patched, fname)
    if not ok_syn:
        return (
            f"❌ Syntax error στο patched αρχείο — ΤΙΠΟΤΑ ΔΕΝ ΓΡΑΦΤΗΚΕ.\n"
            f"{syn_err}\n"
            f"Διόρθωσε το new_str και ξαναπροσπάθησε."
        )

    # Γράψιμο
    try:
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(patched)
    except Exception as e:
        return f"❌ Σφάλμα γραψίματος: {e}"

    diff = _mini_diff(original, patched, fname)
    old_lines = len(original.splitlines())
    new_lines = len(patched.splitlines())
    delta = new_lines - old_lines
    delta_str = f"+{delta}" if delta >= 0 else str(delta)

    # Βρίσκουμε σε ποια γραμμή έγινε η αλλαγή
    for i, (a, b) in enumerate(zip(original.splitlines(), patched.splitlines()), 1):
        if a != b:
            change_line = i
            break
    else:
        change_line = old_lines  # προσθήκη στο τέλος

    syn_msg = f"✅ Syntax check: OK" if fname.endswith(".py") else "➖ Syntax check: N/A (non-python)"

    return (
        f"✅ **{fname}** ενημερώθηκε επιτυχώς.\n\n"
        f"📋 **Σύνοψη αλλαγών:**\n"
        f"• Αρχείο: `{file_path}`\n"
        f"• Γραμμές: {old_lines} → {new_lines} ({delta_str})\n"
        f"• Περιοχή αλλαγής: ~γραμμή {change_line}\n"
        f"• Εμφανίσεις old_str: 1 (μοναδικό ✅)\n"
        f"• {syn_msg}\n\n"
        f"```diff\n{diff}\n```"
    )


@tool
def grep_project_files(folder_path: str, pattern: str, file_pattern: str = "*.py", context_lines: int = 2) -> str:
    """
    Ψάχνει για pattern μέσα στα αρχεία ενός εγκεκριμένου project folder.
    Επιστρέφει αρχείο + γραμμή + περιεχόμενο (σαν ripgrep).

    folder_path:   Ο φάκελος του project (π.χ. C:\mastro_app)
    pattern:       Regex pattern (π.χ. "CustomerSerializer", "def create", "temp_id=None")
    file_pattern:  Glob για τύπο αρχείων (default: *.py). Παραδείγματα: "*.js", "*.py", "*"
    context_lines: Γραμμές context πριν/μετά από κάθε match (default: 2, max: 5)
    """
    import re

    folder_path = folder_path.strip().strip("'\"")

    ok, err = _check_permission(os.path.join(folder_path, "_"))
    if not ok:
        ok, err = _check_permission(folder_path + os.sep + "x")
        if not ok:
            return err

    if not os.path.isdir(folder_path):
        return f"❌ Ο φάκελος '{folder_path}' δεν υπάρχει."

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
        return f"❌ Μη έγκυρο regex pattern: {e}"

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
            f"🔍 Κανένα αποτέλεσμα για `{pattern}` "
            f"(pattern: {file_pattern}) στο '{folder_path}'."
        )

    lines_out = [
        f"🔍 **grep** `{pattern}` — {total_matches} αποτελέσματα "
        f"σε {len(matches_by_file)} αρχεία (folder: {os.path.basename(folder_path)}/)",
        ""
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
        lines_out.append("⚠️ Αποτελέσματα περικόπηκαν στα 200. Χρησιμοποίησε πιο συγκεκριμένο pattern.")

    return "\n".join(lines_out)


@tool
def write_project_file(file_path: str, content: str) -> str:
    """
    Γράφει ολόκληρο αρχείο σε εγκεκριμένο project folder (full rewrite).
    Χρησιμοποίησε ΜΟΝΟ για νέα αρχεία ή όταν το edit_project_file δεν αρκεί.
    Για υπάρχοντα αρχεία, προτίμησε edit_project_file.

    file_path: Πλήρες path αρχείου
    content:   Πλήρες περιεχόμενο νέου αρχείου
    """
    file_path = file_path.strip().strip("'\"")

    ok, err = _check_permission(file_path, need_edit=True)
    if not ok:
        return err

    fname = os.path.basename(file_path)

    # Syntax check πριν γράψουμε
    ok_syn, syn_err = _syntax_check(content, fname)
    if not ok_syn:
        return (
            f"❌ Syntax error στο περιεχόμενο — ΤΙΠΟΤΑ ΔΕΝ ΓΡΑΦΤΗΚΕ.\n"
            f"{syn_err}"
        )

    is_new = not os.path.exists(file_path)

    try:
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(content)
    except Exception as e:
        return f"❌ Σφάλμα γραψίματος: {e}"

    lines = len(content.splitlines())
    action = "δημιουργήθηκε" if is_new else "αντικαταστάθηκε"
    return f"✅ {fname} {action} ({lines} γραμμές, {len(content.encode())/1024:.1f} KB)."
