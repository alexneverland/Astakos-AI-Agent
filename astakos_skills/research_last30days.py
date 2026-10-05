import os
import subprocess
import sys
from langchain_core.tools import tool
from config import BASE_DIR
from core.i18n import t


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
            [sys.executable, script_path, "--emit", "md", topic],
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
