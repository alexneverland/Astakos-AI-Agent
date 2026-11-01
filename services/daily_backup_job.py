"""Standalone daily backup orchestration; return nonzero on incomplete stages."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import tempfile
from typing import Callable

from filelock import FileLock

from services.daily_backup_runtime import assert_quiescent, cold_pause, atomic_json
from services.daily_data_backup import BackupError, build_data_package, upload_verified_package, select_data_files


def run_data_backup(service: object, root: Path, parent_id: str,
                    *, pause: Callable = cold_pause, guard: Callable = assert_quiescent) -> dict:
    """Resume before upload/retention; keep stages failure-atomic."""
    with FileLock(str(root / ".daily-backup-job.lock"), timeout=0):
        # Preflight missing/unsafe assets before asking any writer to stop.
        select_data_files(root)
        with tempfile.TemporaryDirectory(prefix="astakos-data-backup-") as directory:
            archive = Path(directory) / ("astakos-data-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ") + ".zip")
            with pause(root=root):
                result = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"],
                                        capture_output=True, text=True, timeout=10)
                revision = result.stdout.strip() if result.returncode == 0 else "unknown"
                manifest = build_data_package(root, archive, assert_quiescent=guard, git_revision=revision)
            file_id = upload_verified_package(service, archive, parent_id)
            return {"status": "complete", "drive_file_id": file_id,
                    "archive": archive.name, "files": len(manifest["files"]), "git_revision": revision}


def main() -> int:
    """Use existing Astakos OAuth/settings; do not expose credentials/errors."""
    from services.daily_backup_runtime import ROOT
    try:
        import config
        from googleapiclient.discovery import build
        from core.workspace_oauth import load_workspace_credentials
        result = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command",
            "$ErrorActionPreference='Stop'; $t=Get-ScheduledTask -TaskName Astakos_Matrix_Encrypted_Backup "
            "-ErrorAction SilentlyContinue; if($t -and $t.State -eq 'Running'){exit 2}"],
            capture_output=True, timeout=30, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if result.returncode:
            raise BackupError("matrix_backup_running_or_inspection_failed")
        credentials = load_workspace_credentials(scopes=["https://www.googleapis.com/auth/drive"])
        service = build("drive", "v3", credentials=credentials, cache_discovery=False)
        result = run_data_backup(service, Path(config.BASE_DIR), getattr(config, "BACKUP_DRIVE_FOLDER_ID", "") or "root")
        atomic_json(ROOT / ".daily-backup-status.json", dict(result, at=datetime.now(timezone.utc).isoformat()))
        print(json.dumps(result))
        return 0
    except Exception as error:
        code = str(error) if isinstance(error, BackupError) else "daily_backup_failed"
        atomic_json(ROOT / ".daily-backup-status.json", {"status": "failed", "code": code, "at": datetime.now(timezone.utc).isoformat()})
        print(json.dumps({"status": "failed", "code": code}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
