"""Local, PID-correlated backup handoff between the coordinator and boot supervisor."""

from __future__ import annotations

import json
import os
import tempfile
import time
import uuid
import subprocess
import sys
import threading
from pathlib import Path
from typing import TextIO

from filelock import FileLock, Timeout

from services.matrix_backup import MatrixBackupError, secure_directory, validate_path

ROOT = Path(__file__).resolve().parents[1]
REQUEST_PATH = ROOT / ".matrix-backup-maintenance.json"
LOCK_PATH = ROOT / ".matrix-backup-maintenance.lock"
ACK_PATH = ROOT / ".matrix-backup-paused.json"


def start_logged_matrix_process(command: list[str], *, log_dir: Path) -> subprocess.Popen:
    """Inherit the parent's console while teeing recovery output to private logs."""
    log_dir = validate_path(log_dir)
    secure_directory(log_dir)
    logs = []
    try:
        for name in ("nightly-matrix.out.log", "nightly-matrix.err.log"):
            logs.append(validate_path(log_dir / name).open("w", encoding="utf-8"))
        process = subprocess.Popen(
            command, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", errors="replace", bufsize=1,
            env=dict(os.environ, PYTHONUNBUFFERED="1", PYTHONIOENCODING="utf-8"),
            creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) if os.name == "nt" else 0,
        )
    except BaseException:
        for stream in logs:
            stream.close()
        raise
    process.matrix_process_group = os.name == "nt"

    def relay(source: TextIO, logfile: TextIO, console: TextIO | None) -> None:
        """Keep draining even if a console cannot represent one output line."""
        with source, logfile:
            for line in source:
                logfile.write(line)
                logfile.flush()
                try:
                    if console is not None:
                        console.write(line)
                        console.flush()
                except (OSError, ValueError, UnicodeError):
                    pass

    threads = []
    for source, logfile, console in zip((process.stdout, process.stderr), logs, (sys.stdout, sys.stderr)):
        thread = threading.Thread(target=relay, args=(source, logfile, console), daemon=True)
        thread.start()
        threads.append(thread)
    process.matrix_output_threads = threads
    return process


def drain_matrix_output(process: subprocess.Popen) -> None:
    """Finish closed-child logging before reusing its startup-evidence files."""
    for thread in getattr(process, "matrix_output_threads", ()):
        thread.join(timeout=5)


def backup_pause_held() -> bool:
    """A live lock, not a stale file, determines whether capture is still paused."""
    try:
        with FileLock(str(LOCK_PATH), timeout=0):
            return False
    except Timeout:
        return True


def boot_backup_request(child_pid: int | None) -> dict | None:
    """Accept only a recent request targeting this parent and its exact old child."""
    try:
        data = json.loads(REQUEST_PATH.read_text(encoding="utf-8"))
        if (data["parent_pid"] != os.getpid() or data["child_pid"] != child_pid
                or not 0 <= time.time() - data["created_at"] < 8 * 3600
                or not isinstance(data["nonce"], str) or len(data["nonce"]) != 32):
            return None
        return data
    except (OSError, ValueError, KeyError, TypeError):
        return None


def acknowledge_watchdog_pause(request: dict) -> None:
    """Record that the exact parent has observed its old child exit."""
    if request.get("parent_pid") != os.getpid():
        raise MatrixBackupError("watchdog_pause_parent_mismatch")
    fd, name = tempfile.mkstemp(prefix=".matrix-backup-request-", dir=ROOT)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump({"nonce": request["nonce"], "parent_pid": os.getpid()}, stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, ACK_PATH)
    finally:
        Path(name).unlink(missing_ok=True)


def paused_watchdog_ids() -> list[int]:
    """Allow only this coordinator's acknowledged, live-locked idle watchdog."""
    try:
        request = json.loads(REQUEST_PATH.read_text(encoding="utf-8"))
        ack = json.loads(ACK_PATH.read_text(encoding="utf-8"))
        ids = request["watchdog_pids"]
        if (request["coordinator_pid"] == os.getpid()
                and ack == {"nonce": request["nonce"], "parent_pid": request["parent_pid"]}
                and 0 <= time.time() - request["created_at"] < 8 * 3600
                and isinstance(ids, list) and 1 <= len(ids) <= 2
                and all(type(pid) is int and pid > 0 for pid in ids)
                and request["parent_pid"] in ids and backup_pause_held()):
            return ids
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return []


class BootBackupPause:
    """Keep Web supervised while the coordinator temporarily stops its Matrix child."""

    def __init__(self, parent_pid: int, child_pid: int, log_dir: Path,
                 *, watchdog_pids: list[int] | None = None) -> None:
        self.lock = FileLock(str(LOCK_PATH), timeout=0)
        self.nonce = uuid.uuid4().hex
        self.data = {"parent_pid": parent_pid, "child_pid": child_pid,
                     "log_dir": str(log_dir), "created_at": time.time(), "nonce": self.nonce,
                     "coordinator_pid": os.getpid(), "watchdog_pids": watchdog_pids or []}

    def acquire(self) -> None:
        """Atomically publish correlation before signaling the boot child."""
        try:
            self.lock.acquire()
        except Timeout:
            raise MatrixBackupError("boot_backup_already_running") from None
        try:
            fd, name = tempfile.mkstemp(prefix=".matrix-backup-request-", dir=ROOT)
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as stream:
                    json.dump(self.data, stream)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(name, REQUEST_PATH)
            finally:
                Path(name).unlink(missing_ok=True)
        except Exception:
            self.lock.release()
            raise MatrixBackupError("boot_backup_request_failed") from None

    def resume(self) -> None:
        """Release capture pause; boot restarts and continues owning the new child."""
        self.lock.release()

    def clear(self) -> None:
        """Remove only this request after recovery, never another operator's request."""
        self.resume()
        try:
            if json.loads(REQUEST_PATH.read_text(encoding="utf-8")).get("nonce") == self.nonce:
                REQUEST_PATH.unlink()
                if ACK_PATH.exists() and json.loads(ACK_PATH.read_text(encoding="utf-8")).get("nonce") == self.nonce:
                    ACK_PATH.unlink()
        except (OSError, ValueError):
            pass
