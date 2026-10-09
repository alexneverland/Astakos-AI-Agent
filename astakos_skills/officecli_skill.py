import os
import shlex
import subprocess
from pathlib import Path
from langchain_core.tools import tool
from config import BASE_DIR
from core.i18n import t
from services.officecli_installation import officecli_binary_path


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
        tags += t("skills.officecli_skill.msg_more_files", count=len(changed) - 5)
    return tags

@tool
def run_officecli(command: str) -> str:
    """
    Executes commands in OfficeCLI to create and edit Word (.docx), Excel (.xlsx), and PowerPoint (.pptx) files.
    OfficeCLI supports document nodes, template merging, and Excel cell values/formulas.

    First choice for Word, Excel and PowerPoint output, even simple Office files.
    Native generators may be used directly for PDF, TXT and CSV.
    For Office output, native DOCX/XLSX generators or custom Python are fallback
    options only when OfficeCLI is unavailable, returns an error, or cannot cover
    the required structure. Preserve the requested format and all safety/approval
    gates; never use fallback to bypass a security rejection.
    ALWAYS create or save files inside this installation's outputs folder so
    drive_manager and the Web UIs can find them. Commands run in that folder;
    use relative filenames as in the examples, without a host-specific path.
    
    Examples:
    - officecli create report.docx
    - officecli add report.docx /body --type paragraph --prop "text=Hello"
    - officecli add deck.pptx / --type slide --prop "title=Intro"
    - officecli set data.xlsx /Sheet1/A1 --prop "value=42"
    - officecli help docx paragraph
    Use create before editing a new file; inspect help for supported properties.
    
    If the command starts with 'officecli ', it will be replaced with the full path of the executable.
    """
    officecli_path = str(officecli_binary_path(BASE_DIR))
    outputs_dir = os.path.join(BASE_DIR, "outputs")
    os.makedirs(outputs_dir, exist_ok=True)
    
    if not os.path.exists(officecli_path):
        return t("skills.officecli_skill.msg_not_found_2", path=officecli_path)
    
    # Remove 'officecli ' from the beginning if it exists, in order to insert our own path
    if command.startswith("officecli "):
        command = command[10:]
        
    if any(token in command for token in ["&", "|", ";", ">", "<", "\n", "\r"]):
        return t("skills.officecli_skill.unsafe")
    
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
            response = t("skills.officecli_skill.msg_success", out=output)
            if file_tags:
                response += f"\n{file_tags}"
            return response
        else:
            return t("skills.officecli_skill.msg_exit_error_2", code=result.returncode, err=result.stderr.strip())
    except Exception as e:
        return t("skills.officecli_skill.msg_exec_error", e=str(e))
