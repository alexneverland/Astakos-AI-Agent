# run_telegram.py — Auto-restart Telegram Bot on code changes
import subprocess
import sys
import os
import signal
from watchfiles import watch

WATCH_DIRS = ["clients", "core", "tools", "memory", "services", "astakos_skills"]
SHUTDOWN_TIMEOUT_SECONDS = 20


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
