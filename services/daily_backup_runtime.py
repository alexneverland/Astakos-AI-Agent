"""Cooperative cold-backup handoff; supervisors retain their original consoles."""

from __future__ import annotations

from contextlib import contextmanager
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import tempfile
import time
from typing import Callable, Iterator
import uuid

from filelock import FileLock, Timeout

from services.daily_data_backup import BackupError

ROOT = Path(__file__).resolve().parents[1]


def atomic_json(path: Path, value: dict) -> None:
    """Publish complete local coordination state, never a partial JSON write."""
    fd, name = tempfile.mkstemp(prefix=".daily-backup-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def pause_held(root: Path = ROOT) -> bool:
    """Use a live OS lock; a crashed coordinator cannot strand supervisors."""
    try:
        with FileLock(str(root / ".daily-backup-pause.lock"), timeout=0):
            return False
    except Timeout:
        return True


def checkpoint(role: str, process: subprocess.Popen, restart: Callable[[], subprocess.Popen],
               *, root: Path = ROOT) -> subprocess.Popen:
    """Drain the owned child, acknowledge a correlated request, then resume once."""
    if role not in {"web", "matrix", "telegram"}:
        raise BackupError("invalid_runtime_role")
    registry = root / f".daily-backup-{role}.json"
    identity = {"parent_pid": os.getpid(), "child_pid": process.pid}
    try:
        registered = json.loads(registry.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        registered = None
    if registered != identity:
        atomic_json(registry, identity)
    if not pause_held(root):
        return process
    try:
        request = json.loads((root / ".daily-backup-request.json").read_text(encoding="utf-8"))
        participant = request["participants"].get(role)
        if participant != {"parent_pid": os.getpid(), "child_pid": process.pid}:
            return process
        if not 0 <= time.time() - request["at"] < 1800:
            return process
        nonce = request["nonce"]
    except (OSError, ValueError, KeyError, TypeError):
        return process
    tree = None
    stopped = process.poll() is not None
    try:
        if not stopped:
            if os.name == "nt":
                from services.windows_process_tree import WindowsProcessTree
                tree = WindowsProcessTree(process.pid)
            process.send_signal(signal.CTRL_BREAK_EVENT if os.name == "nt" else signal.SIGINT)
            process.wait(timeout=180)
            if tree is not None and not tree.wait(10):
                raise BackupError("descendants_not_stopped")
            stopped = True
        atomic_json(root / f".daily-backup-{role}-ack.json", {"nonce": nonce, "parent_pid": os.getpid(), "stopped": True})
        while pause_held(root):
            time.sleep(0.25)
        replacement = restart()
        atomic_json(registry, {"parent_pid": os.getpid(), "child_pid": replacement.pid})
        return replacement
    except (OSError, subprocess.TimeoutExpired) as error:
        atomic_json(root / f".daily-backup-{role}-ack.json", {"nonce": nonce, "error": "graceful_shutdown_failed"})
        while pause_held(root):
            time.sleep(0.25)
        if process.poll() is None:
            return process
        raise BackupError("shutdown_not_confirmed") from error
    finally:
        if tree is not None:
            tree.close()


def process_records() -> list[dict]:
    """Read process metadata only; never signal a guessed PID or inspect secrets."""
    if os.name != "nt":
        raise BackupError("windows_only")
    result = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command",
        "Get-CimInstance Win32_Process | Where-Object { $_.Name -match '^python.*\\.exe$' } | "
        "Select-Object ProcessId,ParentProcessId,CommandLine | ConvertTo-Json -Compress"],
        capture_output=True, text=True, timeout=30, creationflags=subprocess.CREATE_NO_WINDOW)
    if result.returncode:
        raise BackupError("process_inspection_failed")
    records = json.loads(result.stdout or "[]")
    return [records] if isinstance(records, dict) else records


def writer_records(records: list[dict]) -> list[dict]:
    """Identify supported entrypoints; unknown active launch styles fail closed."""
    pattern = r"(?i)(?:^|[\s\x22\x27\\/])(main\.py|boot\.py|matrix_bot\.py|telegram_bot\.py)(?:[\s\x22\x27]|$)|api\.server:server"
    return [record for record in records if re.search(pattern, record.get("CommandLine") or "")]


def assert_quiescent() -> None:
    """Before and after capture reject any supported live writer process."""
    if writer_records(process_records()):
        raise BackupError("writers_running")


@contextmanager
def cold_pause(*, root: Path = ROOT, records: Callable[[], list[dict]] = process_records,
               timeout: float = 240) -> Iterator[None]:
    """Request only registered supervisors and always release the pause on failure."""
    lock = FileLock(str(root / ".daily-backup-pause.lock"), timeout=0)
    with lock:
        before = records()
        by_pid = {item["ProcessId"]: item for item in before}
        participants = {}
        for role, entry in (("web", "run_web.py"), ("matrix", "run_external.py|run_matrix.py"),
                            ("telegram", "run_external.py|run_telegram.py")):
            try:
                info = json.loads((root / f".daily-backup-{role}.json").read_text(encoding="utf-8"))
                parent = by_pid.get(info["parent_pid"])
                child = by_pid.get(info["child_pid"])
                if (parent and child and child.get("ParentProcessId") == info["parent_pid"]
                        and re.search(r"(?:" + entry + r")", parent.get("CommandLine") or "")):
                    participants[role] = info
            except (OSError, ValueError, KeyError, TypeError):
                continue
        if writer_records(before) and not participants:
            raise BackupError("restart_from_updated_launcher_required")
        children = {item["child_pid"] for item in participants.values()}
        for writer in writer_records(before):
            pid = writer["ProcessId"]
            visited = set()
            while pid not in children and pid in by_pid and pid not in visited:
                visited.add(pid)
                pid = by_pid[pid].get("ParentProcessId")
            if pid not in children:
                raise BackupError("unmanaged_writer_running")
        nonce = uuid.uuid4().hex
        atomic_json(root / ".daily-backup-request.json", {"nonce": nonce, "at": time.time(), "participants": participants})
        try:
            deadline = time.monotonic() + timeout
            while True:
                acknowledged = True
                for role, participant in participants.items():
                    try:
                        ack = json.loads((root / f".daily-backup-{role}-ack.json").read_text(encoding="utf-8"))
                    except (OSError, ValueError):
                        acknowledged = False
                        continue
                    if ack.get("nonce") == nonce and ack.get("error"):
                        raise BackupError("graceful_shutdown_failed")
                    acknowledged &= ack == {"nonce": nonce, "parent_pid": participant["parent_pid"], "stopped": True}
                if acknowledged and not writer_records(records()):
                    yield
                    break
                if time.monotonic() >= deadline:
                    raise BackupError("writer_pause_timeout")
                time.sleep(0.25)
        finally:
            (root / ".daily-backup-request.json").unlink(missing_ok=True)
    # Do not upload/rotate until every previously active supervisor has resumed.
    deadline = time.monotonic() + 180
    while participants:
        live = {item["ProcessId"] for item in records()}
        for role, previous in list(participants.items()):
            info = json.loads((root / f".daily-backup-{role}.json").read_text(encoding="utf-8"))
            if info["child_pid"] != previous["child_pid"] and info["child_pid"] in live:
                if role in {"web", "matrix"}:
                    directory = root / "logs" / "daily_backup" / role
                    evidence = ""
                    for name in ("nightly-matrix.out.log", "nightly-matrix.err.log"):
                        try:
                            evidence += (directory / name).read_text(encoding="utf-8", errors="replace")
                        except OSError:
                            pass
                    marker = "Application startup complete" if role == "web" else "Encrypted Element channel started"
                    if marker not in evidence:
                        continue
                del participants[role]
        if not participants:
            return
        if time.monotonic() >= deadline:
            raise BackupError("runtime_resume_unconfirmed")
        time.sleep(0.5)
