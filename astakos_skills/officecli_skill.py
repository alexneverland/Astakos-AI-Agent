import os
import shlex
import subprocess
from pathlib import Path
from langchain_core.tools import tool
from config import BASE_DIR


_OFFICE_OUTPUT_SUFFIXES = {".docx", ".xlsx", ".pptx", ".pdf", ".html", ".png", ".jpg", ".jpeg"}


def _snapshot_outputs(outputs_dir: str) -> dict[str, float]:
    """Capture output file mtimes before running OfficeCLI."""
    root = Path(outputs_dir)
    if not root.exists():
        return {}
    return {
        str(path.resolve()): path.stat().st_mtime
        for path in root.rglob("*")
        if path.is_file() and path.suffix.lower() in _OFFICE_OUTPUT_SUFFIXES
    }


def _created_file_tags(outputs_dir: str, before: dict[str, float]) -> str:
    """Return CREATED_FILE tags for files created or modified by OfficeCLI."""
    root = Path(outputs_dir)
    changed: list[str] = []
    for path in root.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in _OFFICE_OUTPUT_SUFFIXES:
            continue
        resolved = str(path.resolve())
        previous_mtime = before.get(resolved)
        current_mtime = path.stat().st_mtime
        if previous_mtime is None or current_mtime > previous_mtime + 0.001:
            changed.append(resolved)

    if not changed:
        return ""

    tags = "\n".join(f"[CREATED_FILE: {path}]" for path in sorted(changed)[:5])
    if len(changed) > 5:
        tags += f"\n...και {len(changed) - 5} ακόμα αρχεία στο outputs."
    return tags

@tool
def run_officecli(command: str) -> str:
    """
    Executes commands in OfficeCLI to create and edit Word (.docx), Excel (.xlsx), and PowerPoint (.pptx) files.
    OfficeCLI supports templates, HTML to docx rendering, Excel formulas, etc.

    FORBIDDEN: Do not use the old create_file_tool or generate_word_doc for Office files. 
    Use this tool for simple conversions or templates. HOWEVER, IF a complex structure is needed (e.g., custom calendars, specific cells using openpyxl/python-docx), you ARE ALLOWED to use python (run_terminal_command or run_code), bypassing this tool.
    ALWAYS create or save files inside the folder:
    C:/astakos_v2/outputs/
    So that drive_manager and the Web UIs can find them!
    
    Examples:
    - officecli add deck.pptx / --type slide --title "Intro"
    - officecli render template.docx data.json --out C:/astakos_v2/outputs/report.docx
    - officecli formula calc C:/astakos_v2/outputs/data.xlsx
    
    If the command starts with 'officecli ', it will be replaced with the full path of the executable.
    """
    officecli_path = os.path.join(BASE_DIR, "vendor", "officecli", "officecli.exe")
    outputs_dir = os.path.join(BASE_DIR, "outputs")
    os.makedirs(outputs_dir, exist_ok=True)
    
    if not os.path.exists(officecli_path):
        return f"❌ Το OfficeCLI δεν βρέθηκε στο {officecli_path}. Παρακαλώ κατεβάστε το πρώτα."
    
    # Remove 'officecli ' from the beginning if it exists, in order to insert our own path
    if command.startswith("officecli "):
        command = command[10:]
        
    if any(token in command for token in ["&", "|", ";", ">", "<", "\n", "\r"]):
        return "❌ Μη ασφαλής OfficeCLI εντολή: περιέχει shell metacharacters."
    
    try:
        # We execute the command inside the outputs folder for greater security
        before_outputs = _snapshot_outputs(outputs_dir)
        args = shlex.split(command, posix=False)
        args = [arg.strip('"') for arg in args]
        result = subprocess.run(
            [officecli_path, *args],
            shell=False,
            cwd=outputs_dir, 
            capture_output=True, 
            text=True, 
            encoding='utf-8', 
            errors='replace',
            timeout=120,
        )
        if result.returncode == 0:
            file_tags = _created_file_tags(outputs_dir, before_outputs)
            output = result.stdout.strip()
            response = f"✅ OfficeCLI Εκτελέστηκε Επιτυχώς.\nΈξοδος:\n{output}"
            if file_tags:
                response += f"\n{file_tags}"
            return response
        else:
            return f"❌ Σφάλμα OfficeCLI (Exit Code: {result.returncode}).\nΣφάλμα:\n{result.stderr.strip()}"
    except Exception as e:
        return f"❌ Exception κατά την εκτέλεση του OfficeCLI: {str(e)}"
