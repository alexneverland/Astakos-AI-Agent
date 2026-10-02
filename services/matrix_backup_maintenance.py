"""Local, PID-correlated backup handoff between the coordinator and boot supervisor."""

from __future__ import annotations

import json
import os
import tempfile
import time
import uuid
from pathlib import Path

from filelock import FileLock, Timeout

from services.matrix_backup import MatrixBackupError

ROOT = Path(__file__).resolve().parents[1]
REQUEST_PATH = ROOT / ".matrix-backup-maintenance.json"
LOCK_PATH = ROOT / ".matrix-backup-maintenance.lock"


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


class BootBackupPause:
    """Keep Web supervised while the coordinator temporarily stops its Matrix child."""

    def __init__(self, parent_pid: int, child_pid: int, log_dir: Path) -> None:
        self.lock = FileLock(str(LOCK_PATH), timeout=0)
        self.nonce = uuid.uuid4().hex
        self.data = {"parent_pid": parent_pid, "child_pid": child_pid,
                     "log_dir": str(log_dir), "created_at": time.time(), "nonce": self.nonce}

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
        except (OSError, ValueError):
            pass
