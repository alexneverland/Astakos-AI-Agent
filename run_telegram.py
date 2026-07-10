# run_telegram.py — Auto-restart Telegram Bot on code changes
import subprocess
import sys
import os
import signal
from watchfiles import watch

# Ensure UTF-8 on stdout/stderr — if this runs inside a console
# without chcp 65001 (e.g. directly, not via start_astakos.bat), the Greek characters
# the prints below would crash with UnicodeEncodeError on cp1252.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

WATCH_DIRS = ["clients", "core", "tools", "memory", "services"]
SHUTDOWN_TIMEOUT_SECONDS = 20
LOCK_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "run_telegram.lock")

# ────────────────────────────────────────────────────────────────
# SINGLE-INSTANCE LOCK
# Prevents 2 watchdogs from running simultaneously (double polling on the
# same Telegram token → conflict / double reminders). The OS keeps
# the lock as long as the process lives and releases it automatically even
# and on crash/kill — no manual cleanup of a pidfile is required.
# ────────────────────────────────────────────────────────────────
_lock_file = None
if os.name == "nt":
    import msvcrt
    _lock_file = open(LOCK_PATH, "w")
    try:
        msvcrt.locking(_lock_file.fileno(), msvcrt.LK_NBLCK, 1)
    except OSError:
        print("\033[91m[Watchdog]: Τρέχει ήδη ένα instance του run_telegram.py — έξοδος.\033[0m")
        sys.exit(1)


def stop_process(process):
    if not process or process.poll() is not None:
        return

    try:
        if os.name == "nt":
            process.send_signal(signal.CTRL_BREAK_EVENT)
        else:
            process.send_signal(signal.SIGINT)
        process.wait(timeout=SHUTDOWN_TIMEOUT_SECONDS)
    except Exception:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except Exception:
                process.kill()

def run():
    process = None
    try:
        def start():
            nonlocal process
            if process:
                stop_process(process)
            print("\033[92m[Watchdog]: Εκκίνηση Telegram Bot...\033[0m")
            creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) if os.name == "nt" else 0
            process = subprocess.Popen(
                [sys.executable, "clients/telegram_bot.py"],
                cwd="C:\\astakos_v2",
                creationflags=creationflags,
            )

        start()
        dirs = [d for d in WATCH_DIRS if os.path.exists(d)]
        for changes in watch(*dirs):
            py_changes = [c for c in changes if str(c[1]).endswith(".py") or str(c[1]).endswith("prompts.md")]
            if py_changes:
                for _, path in py_changes:
                    print(f"\033[93m[Watchdog]: Αλλαγή εντοπίστηκε → {path}\033[0m")
                print(f"\033[93m[Watchdog]: Επανεκκίνηση...\033[0m")
                start()
    except KeyboardInterrupt:
        stop_process(process)

if __name__ == "__main__":
    run()
