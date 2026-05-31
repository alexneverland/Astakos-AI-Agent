# run_telegram.py — Auto-restart Telegram Bot on code changes
import subprocess
import sys
import os
from watchfiles import watch

WATCH_DIRS = ["clients", "core", "tools", "memory", "services"]

def run():
    process = None
    try:
        def start():
            nonlocal process
            if process:
                process.terminate()
                process.wait()
            print("\033[92m[Watchdog]: Εκκίνηση Telegram Bot...\033[0m")
            process = subprocess.Popen(
                [sys.executable, "clients/telegram_bot.py"],
                cwd="C:\\astakos_v2"
            )

        start()
        dirs = [d for d in WATCH_DIRS if os.path.exists(d)]
        for changes in watch(*dirs):
            py_changes = [c for c in changes if str(c[1]).endswith(".py")]
            if py_changes:
                for _, path in py_changes:
                    print(f"\033[93m[Watchdog]: Αλλαγή εντοπίστηκε → {path}\033[0m")
                print(f"\033[93m[Watchdog]: Επανεκκίνηση...\033[0m")
                start()
    except KeyboardInterrupt:
        if process:
            process.terminate()

if __name__ == "__main__":
    run()