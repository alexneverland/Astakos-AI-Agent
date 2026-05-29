# run_telegram.py — Auto-restart Telegram Bot on code changes
import subprocess
import sys
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
import time
import os

WATCH_DIRS = ["clients", "core", "tools", "memory", "services"]
IGNORE_DIRS = ["venv", "__pycache__", ".git"]

class RestartHandler(FileSystemEventHandler):
    def __init__(self):
        self.process = None
        self.restart()

    def restart(self):
        if self.process:
            self.process.terminate()
            self.process.wait()
        print("\033[92m[Watchdog]: Εκκίνηση Telegram Bot...\033[0m")
        self.process = subprocess.Popen([sys.executable, "clients/telegram_bot.py"])

    def on_modified(self, event):
        if event.is_directory:
            return
        if any(d in event.src_path for d in IGNORE_DIRS):
            return
        if event.src_path.endswith(".py"):
            print(f"\033[93m[Watchdog]: Άλλαξε {event.src_path} — Επανεκκίνηση...\033[0m")
            self.restart()

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