"""Visible Web supervisor with graceful, coordinated daily-backup downtime."""

from __future__ import annotations

import os
from pathlib import Path
import signal
import subprocess
import sys

from watchfiles import watch

from services.daily_backup_runtime import checkpoint

ROOT = Path(__file__).resolve().parent


def start(*, log_dir: Path | None = None) -> subprocess.Popen:
    """Inherit this console; avoid Uvicorn's unmanaged reload grandchild."""
    command = [sys.executable, "-m", "uvicorn", "api.server:server",
               "--host", "0.0.0.0", "--no-access-log"]
    if log_dir is not None:
        from services.matrix_backup_maintenance import start_logged_matrix_process
        return start_logged_matrix_process(command, log_dir=log_dir)
    return subprocess.Popen(command, cwd=ROOT,
                            creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) if os.name == "nt" else 0)


def stop(process: subprocess.Popen) -> None:
    """Drain the Web process without force-killing database writers."""
    if process.poll() is None:
        process.send_signal(signal.CTRL_BREAK_EVENT if os.name == "nt" else signal.SIGINT)
        process.wait(timeout=180)


def run() -> int:
    """Watch the same source directories and retain the visible parent on backup."""
    process = start()
    try:
        paths = [str(ROOT / path) for path in ("api", "core", "tools", "memory", "services", "clients", "prompts.md")
                 if (ROOT / path).exists()]
        for changes in watch(*paths, rust_timeout=1000, yield_on_timeout=True):
            process = checkpoint("web", process, lambda: start(log_dir=ROOT / "logs" / "daily_backup" / "web"))
            if process.poll() is not None:
                return int(process.returncode or 1)
            if any(str(path).endswith((".py", "prompts.md")) for _, path in changes):
                stop(process)
                process = start()
    except KeyboardInterrupt:
        return 0
    finally:
        stop(process)
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
