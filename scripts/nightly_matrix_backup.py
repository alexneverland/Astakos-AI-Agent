"""Explicit Windows nightly coordinator; no credentials or side effects at import."""

from __future__ import annotations

import argparse
import ctypes
import json
import os
import shlex
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from filelock import FileLock, Timeout
from services.matrix_backup import (
    BackupSettings, MatrixBackupError, create_encrypted_backup,
    secure_directory, upload_encrypted_artifact,
)
from services.matrix_snapshot import SnapshotSettings, assert_bot_stopped, captured_snapshot


def write_status(work: Path, status: dict) -> None:
    """Atomically persist safe operational metadata, never raw exception text."""
    fd, name = tempfile.mkstemp(prefix="status-", dir=work)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(status, stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, work / "last-run.json")
    finally:
        Path(name).unlink(missing_ok=True)


def run_nightly(options: argparse.Namespace, runtime: object, *,
                capture: Callable, upload: Callable = upload_encrypted_artifact) -> dict:
    """Restore prior runtime state even on failure; upload only after recovery."""
    secure_directory(options.work_dir)
    try:
        with FileLock(str(options.work_dir / "nightly.lock"), timeout=0):
            status = {"status": "running", "started_at": datetime.now(timezone.utc).isoformat()}
            write_status(options.work_dir, status)
            try:
                previous = runtime.preflight()
                try:
                    runtime.stop(previous)
                    result = capture()
                    status.update(artifact=str(result.artifact), sha256=result.sha256)
                finally:
                    runtime.restore(previous)
                file_id = upload(result.artifact, options.drive_folder, result.sha256)
                status.update(status="uploaded", drive_file_id=file_id)
                return status
            except Exception:
                status.update(status="failed", code="nightly_backup_or_runtime_recovery_failed")
                raise MatrixBackupError(status["code"]) from None
            finally:
                status["finished_at"] = datetime.now(timezone.utc).isoformat()
                write_status(options.work_dir, status)
    except Timeout:
        raise MatrixBackupError("nightly_already_running") from None


def process_entry(command: str) -> str | None:
    """Recognize exact structured entrypoint tokens, not arbitrary substrings."""
    for token in shlex.split(command, posix=False)[1:]:
        normalized = token.strip('"').replace("\\", "/")
        for entry in ("clients/matrix_bot.py", "run_external.py", "run_matrix.py"):
            if normalized.casefold() in {entry, (ROOT.as_posix() + "/" + entry).casefold()}:
                return entry
    return None


class WindowsRuntime:
    """Coordinate only this checkout's venv launchers; never kill processes."""

    def __init__(self, work: Path, drive_folder: str = "") -> None:
        self.work = work
        self.drive_folder = drive_folder

    @staticmethod
    def powershell(command: str) -> str:
        """Execute fixed diagnostic commands with sanitized failure output."""
        result = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
                                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                text=True, timeout=30, creationflags=subprocess.CREATE_NO_WINDOW)
        if result.returncode:
            raise MatrixBackupError("runtime_inspection_failed")
        return result.stdout.strip()

    def discover(self) -> dict:
        """Select exact venv launchers, rejecting ambiguous local instances."""
        raw = self.powershell(
            "Get-CimInstance Win32_Process | Where-Object { $_.Name -match '^python.*\\.exe$' } | "
            "Select-Object ProcessId,ExecutablePath,CommandLine | ConvertTo-Json -Compress")
        records = json.loads(raw or "[]")
        if isinstance(records, dict):
            records = [records]
        bots, watchdogs = [], []
        python = ROOT / "venv" / "Scripts" / "python.exe"
        for record in records:
            if not record.get("ExecutablePath") or Path(record["ExecutablePath"]) != python:
                continue
            entry = process_entry(record.get("CommandLine") or "")
            if entry == "clients/matrix_bot.py":
                bots.append(int(record["ProcessId"]))
            elif entry:
                watchdogs.append(entry)
        if len(bots) > 1 or len(watchdogs) > 1:
            raise MatrixBackupError("ambiguous_matrix_runtime")
        return {"bot_pid": bots[0] if bots else None,
                "watchdog": watchdogs[0] if watchdogs else None}

    def preflight(self) -> dict:
        """Validate old-task exclusion and private destination before downtime."""
        if os.name != "nt":
            raise MatrixBackupError("windows_only")
        state = self.powershell("$t=Get-ScheduledTask -TaskName Astakos_Daily_Backup -ErrorAction SilentlyContinue; [string]$t.State")
        if state == "Running":
            raise MatrixBackupError("existing_backup_running")
        from googleapiclient.discovery import build
        from core.workspace_oauth import load_workspace_credentials
        service = build("drive", "v3", credentials=load_workspace_credentials(
            scopes=["https://www.googleapis.com/auth/drive"]), cache_discovery=False)
        folder = service.files().get(fileId=self.drive_folder,
            fields="mimeType,trashed,permissions(type,role)").execute()
        permissions = folder.get("permissions", [])
        if (folder.get("mimeType") != "application/vnd.google-apps.folder" or folder.get("trashed")
                or not permissions or any(p["type"] != "user" or p["role"] != "owner" for p in permissions)):
            raise MatrixBackupError("backup_destination_not_owner_only")
        return self.discover()

    @staticmethod
    def signal_bot(pid: int) -> None:
        """Send CTRL_BREAK to the discovered bot group; no forced termination."""
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.FreeConsole()
        try:
            if not kernel.AttachConsole(pid):
                raise MatrixBackupError("bot_console_attach_failed")
            kernel.SetConsoleCtrlHandler(None, True)
            if not kernel.GenerateConsoleCtrlEvent(1, pid):
                raise MatrixBackupError("bot_signal_failed")
        finally:
            kernel.FreeConsole()

    def stop(self, previous: dict) -> None:
        """Wait for graceful bot/watchdog exit; refuse an unquiesced capture."""
        if previous["bot_pid"] is not None:
            self.signal_bot(previous["bot_pid"])
        deadline = time.monotonic() + 150
        while True:
            try:
                assert_bot_stopped()
                return
            except MatrixBackupError:
                if time.monotonic() >= deadline:
                    raise MatrixBackupError("graceful_stop_timeout") from None
                time.sleep(2)

    def restore(self, previous: dict) -> None:
        """Restore the prior entrypoint in a hidden console and verify startup."""
        if not previous["bot_pid"] and not previous["watchdog"]:
            return
        current = self.discover()
        if current["bot_pid"]:
            return  # Stop failed; never create a duplicate live bot.
        if current["watchdog"]:
            raise MatrixBackupError("watchdog_still_running")
        runtime_dir = self.work / "runtime"
        secure_directory(runtime_dir)
        out, err = runtime_dir / "nightly-matrix.out.log", runtime_dir / "nightly-matrix.err.log"
        startup = subprocess.STARTUPINFO()
        startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startup.wShowWindow = 0
        entry = previous["watchdog"] or "clients/matrix_bot.py"
        with out.open("wb") as stdout, err.open("wb") as stderr:
            process = subprocess.Popen([str(ROOT / "venv/Scripts/python.exe"), "-u", entry],
                cwd=ROOT, stdout=stdout, stderr=stderr,
                env=dict(os.environ, PYTHONUNBUFFERED="1"), startupinfo=startup,
                creationflags=subprocess.CREATE_NEW_CONSOLE | subprocess.CREATE_NEW_PROCESS_GROUP)
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise MatrixBackupError("matrix_restart_failed")
            text = out.read_text(encoding="utf-8", errors="replace")
            if "Encrypted Element channel started" in text:
                return
            if "Startup failed" in text:
                raise MatrixBackupError("matrix_restart_failed")
            time.sleep(2)
        raise MatrixBackupError("matrix_restart_not_verified")


def main(argv: list[str] | None = None) -> int:
    """Scheduled entrypoint: safe status file and a reliable nonzero failure exit."""
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("work-dir", "recipient-file", "synapse-dir", "bot-store-dir",
                 "compose-file", "deployment-environment-file"):
        parser.add_argument("--" + name, required=True, type=Path)
    for name in ("age-executable", "drive-folder", "synapse-container", "postgres-container"):
        parser.add_argument("--" + name, required=True)
    options = parser.parse_args(argv)
    try:
        def capture():
            """Reuse the verified cold collector and encrypt before returning."""
            settings = SnapshotSettings(
                options.synapse_dir, options.bot_store_dir, options.compose_file,
                options.work_dir / "capture", options.synapse_container, options.postgres_container,
                allow_server_pause=True, deployment_environment_file=options.deployment_environment_file,
                include_bot_runtime=True)
            with captured_snapshot(settings) as snapshot:
                return create_encrypted_backup(BackupSettings(
                    snapshot, options.work_dir / "packages", options.recipient_file, options.age_executable))
        run_nightly(options, WindowsRuntime(options.work_dir, options.drive_folder), capture=capture)
        return 0
    except Exception:
        # The durable status carries only a safe fixed error code. pythonw has no console.
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
