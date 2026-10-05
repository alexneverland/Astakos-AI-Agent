import os
import subprocess
import sys
import shutil
from langchain_core.tools import tool
from config import BASE_DIR
from core.i18n import t


def _research_python_command() -> list[str]:
    """Resolve a Python 3.12+ launcher without changing the application runtime."""
    if sys.version_info[:2] >= (3, 12):
        return [sys.executable]
    candidates = []
    for name in ("python", "python3", "python3.14", "python3.13", "python3.12"):
        executable = shutil.which(name)
        if executable and [executable] not in candidates:
            candidates.append([executable])
    launcher = shutil.which("py")
    if launcher:
        candidates.append([launcher, "-3"])
    for command in candidates:
        try:
            probe = subprocess.run(
                [*command, "-I", "-c", "import sys; print('%s.%s' % sys.version_info[:2])"],
                capture_output=True, text=True, timeout=5,
            )
            version = tuple(int(part) for part in probe.stdout.strip().split("."))
            if probe.returncode == 0 and len(version) == 2 and version >= (3, 12):
                return command
        except (OSError, ValueError, subprocess.TimeoutExpired):
            continue
    raise RuntimeError("last30days requires an available Python 3.12+ interpreter")


@tool
def research_last30days(topic: str) -> str:
    """
    Conducts deep web research on any topic, scanning sources such as Reddit, X (Twitter), 
    YouTube, Hacker News, and Polymarket, searching for data only from the last 30 days.
    Returns a collective community analysis (synthesis) based on engagement metrics (upvotes, likes, etc.).
    """
    script_path = os.path.join(BASE_DIR, "vendor", "last30days-skill", "skills", "last30days", "scripts", "last30days.py")
    
    if not os.path.exists(script_path):
        return t("skills.research_last30days.msg_missing_script_2", path=script_path)

    try:
        # Keep the pre-upgrade empty-only paid Reddit fallback. Explicit
        # process configuration may opt into upstream's thin-result backfill.
        child_env = os.environ.copy()
        child_env.setdefault("LAST30DAYS_REDDIT_SC_MIN_ITEMS", "0")
        # We run the command and return the stdout in compact md format for easier parsing by the Agent.
        result = subprocess.run(
            [*_research_python_command(), script_path, "--emit", "md", topic],
            capture_output=True,
            text=True,
            encoding="utf-8",
            cwd=BASE_DIR,
            timeout=120,
            env=child_env,
        )

        if result.returncode != 0:
            return t("skills.research_last30days.msg_exec_error", err=result.stderr)
        
        # If the execution succeeded, we return the result.
        # stdout may contain warnings etc., but usually the output is markdown text.
        return result.stdout.strip()
        
    except subprocess.TimeoutExpired:
        return t("skills.research_last30days.timeout")
    except Exception as e:
        return t("skills.research_last30days.msg_unexpected_error", e=str(e))
