"""Auto-restart the Matrix transport after runtime source changes."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
from pathlib import Path

from watchfiles import watch


ROOT_DIR = Path(__file__).resolve().parent
WATCH_PATHS = ("clients", "core", "tools", "memory", "services", "prompts.md")
SHUTDOWN_TIMEOUT_SECONDS = 120
LOCK_PATH = ROOT_DIR / "run_matrix.lock"
_lock_file = None


def is_reloadable_change(path: str | os.PathLike[str]) -> bool:
    """Return whether one filesystem change requires a Matrix restart."""
    normalized = str(path).replace("\\", "/").lower()
    return (
        normalized.endswith(".py")
        or normalized.endswith("/prompts.md")
        or normalized == "prompts.md"
    )


def _acquire_single_instance_lock() -> None:
    """Prevent duplicate Matrix sync loops on Windows development machines."""
    global _lock_file
    if os.name != "nt":
        return

    import msvcrt

    _lock_file = LOCK_PATH.open("w")
    try:
        msvcrt.locking(_lock_file.fileno(), msvcrt.LK_NBLCK, 1)
    except OSError:
        _lock_file.close()
        _lock_file = None
        print("\033[91m[Matrix Watchdog]: Already running - exiting.\033[0m")
        raise SystemExit(1)


def stop_process(process: subprocess.Popen | None) -> None:
    """Interrupt Matrix and allow queues and stores to close before forcing it."""
    if process is None or process.poll() is not None:
        return

    try:
        if os.name == "nt":
            process.send_signal(signal.CTRL_BREAK_EVENT)
        else:
            process.send_signal(signal.SIGINT)
        process.wait(timeout=SHUTDOWN_TIMEOUT_SECONDS)
        return
    except (OSError, subprocess.TimeoutExpired):
        process.terminate()

    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def _start_process() -> subprocess.Popen:
    """Start Matrix in a process group that can receive a graceful interrupt."""
    creationflags = (
        getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        if os.name == "nt"
        else 0
    )
    print("\033[92m[Matrix Watchdog]: Starting encrypted Matrix channel...\033[0m")
    return subprocess.Popen(
        [sys.executable, "clients/matrix_bot.py"],
        cwd=ROOT_DIR,
        creationflags=creationflags,
    )


def run() -> int:
    """Watch source files, restarting Matrix only after graceful shutdown."""
    _acquire_single_instance_lock()
    process: subprocess.Popen | None = _start_process()
    watch_paths = [
        str(ROOT_DIR / path)
        for path in WATCH_PATHS
        if (ROOT_DIR / path).exists()
    ]

    try:
        for changes in watch(
            *watch_paths,
            rust_timeout=1000,
            yield_on_timeout=True,
        ):
            exit_code = process.poll() if process is not None else 1
            if exit_code is not None:
                print(
                    "\033[91m[Matrix Watchdog]: Matrix stopped unexpectedly "
                    f"(exit={exit_code}).\033[0m"
                )
                return int(exit_code) if exit_code else 1

            reloadable = sorted(
                str(path) for _, path in changes if is_reloadable_change(path)
            )
            if not reloadable:
                continue

            for path in reloadable:
                print(f"\033[93m[Matrix Watchdog]: Change detected -> {path}\033[0m")
            print("\033[93m[Matrix Watchdog]: Restarting gracefully...\033[0m")
            stop_process(process)
            process = _start_process()
    except KeyboardInterrupt:
        return 0
    finally:
        stop_process(process)

    return 0


if __name__ == "__main__":
    raise SystemExit(run())
