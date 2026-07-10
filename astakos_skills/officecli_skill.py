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
    Εκτελεί εντολές στο OfficeCLI για δημιουργία και επεξεργασία αρχείων Word (.docx), Excel (.xlsx), και PowerPoint (.pptx).
    Το OfficeCLI υποστηρίζει templates, rendering HTML σε docx, formulas στο Excel κ.α.

    ΑΠΑΓΟΡΕΥΕΤΑΙ: Μην χρησιμοποιείς τα παλιά create_file_tool ή generate_word_doc για Office αρχεία. 
    Χρησιμοποίησε αυτό το tool για απλές μετατροπές ή templates. ΑΝ ΟΜΩΣ χρειάζεται περίπλοκη δομή (π.χ. custom ημερολόγια, ειδικά κελιά με openpyxl/python-docx), ΕΠΙΤΡΕΠΕΤΑΙ να χρησιμοποιήσεις python (run_terminal_command ή run_code) παρακάμπτοντας αυτό το tool.
    ΠΑΝΤΑ να δημιουργείς ή να σώζεις τα αρχεία μέσα στον φάκελο:
    C:/astakos_v2/outputs/
    Ώστε το drive_manager και τα Web UIs να τα βρίσκουν!
    
    Παραδείγματα:
    - officecli add deck.pptx / --type slide --title "Intro"
    - officecli render template.docx data.json --out C:/astakos_v2/outputs/report.docx
    - officecli formula calc C:/astakos_v2/outputs/data.xlsx
    
    Αν το command ξεκινάει με 'officecli ', θα αντικατασταθεί με το πλήρες path του εκτελέσιμου.
    """
    officecli_path = os.path.join(BASE_DIR, "vendor", "officecli", "officecli.exe")
    outputs_dir = os.path.join(BASE_DIR, "outputs")
    os.makedirs(outputs_dir, exist_ok=True)
    
    if not os.path.exists(officecli_path):
        return f"❌ Το OfficeCLI δεν βρέθηκε στο {officecli_path}. Παρακαλώ κατεβάστε το πρώτα."
    
    # Αφαίρεση του 'officecli ' από την αρχή αν υπάρχει, για να βάλουμε το δικό μας path
    if command.startswith("officecli "):
        command = command[10:]
        
    if any(token in command for token in ["&", "|", ";", ">", "<", "\n", "\r"]):
        return "❌ Μη ασφαλής OfficeCLI εντολή: περιέχει shell metacharacters."
    
    try:
        # Εκτελούμε την εντολή μέσα στον φάκελο outputs για μεγαλύτερη ασφάλεια
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
