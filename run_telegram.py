# run_telegram.py — Auto-restart Telegram Bot on code changes
import subprocess
import sys
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
import time
import os
import threading

WATCH_DIRS = ["clients", "core", "tools", "memory", "services"]
IGNORE_DIRS = ["venv", "__pycache__", ".git"]

class RestartHandler(FileSystemEventHandler):
    def __init__(self):
        self.process = None
        self._timer = None
        self.restart()

    def restart(self):
        if self.process:
            self.process.terminate()
            self.process.wait()
        print("\033[92m[Watchdog]: Εκκίνηση Telegram Bot...\033[0m")
        self.process = subprocess.Popen(
            [sys.executable, "clients/telegram_bot.py"],
            cwd="C:\\astakos_v2"
        )

    def _debounced_restart(self):
        print(f"\033[93m[Watchdog]: Αλλαγές εντοπίστηκαν — Επανεκκίνηση σε 3s...\033[0m")
        self.restart()

    def on_modified(self, event):
        if event.is_directory:
            return
        if any(d in event.src_path for d in IGNORE_DIRS):
            return
        if event.src_path.endswith(".py"):
            print(f"\033[93m[Watchdog]: Αλλαγή εντοπίστηκε → {event.src_path}\033[0m")
            if self._timer:
                self._timer.cancel()
            self._timer = threading.Timer(3.0, self._debounced_restart)
            self._timer.start()

if __name__ == "__main__":
    handler = RestartHandler()
    observer = Observer()
    for d in WATCH_DIRS:
        if os.path.exists(d):
            observer.schedule(handler, d, recursive=True)
    observer.start()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
        if handler.process:
            handler.process.terminate()
    observer.join()