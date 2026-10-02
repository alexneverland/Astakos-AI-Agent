"""Explicit operator entry point; capture requires a separately authorized pause."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.matrix_backup import (
    BackupSettings, MatrixBackupError, create_encrypted_backup,
    original_artifact_digest, upload_encrypted_artifact,
)
from services.matrix_snapshot import SnapshotSettings, captured_snapshot


def main(argv: list[str] | None = None) -> int:
    """Return a nonzero exit on any unverified package/upload; hide raw errors."""
    parser = argparse.ArgumentParser(description=__doc__)
    choice = parser.add_mutually_exclusive_group(required=True)
    choice.add_argument("--snapshot-dir", type=Path)
    choice.add_argument("--retry-artifact", type=Path)
    choice.add_argument("--capture", action="store_true")
    parser.add_argument("--work-dir", type=Path)
    parser.add_argument("--recipient-file", type=Path)
    parser.add_argument("--age-executable", default="age")
    parser.add_argument("--upload", action="store_true")
    parser.add_argument("--drive-folder")
    parser.add_argument("--synapse-dir", type=Path)
    parser.add_argument("--bot-store-dir", type=Path)
    parser.add_argument("--compose-file", type=Path)
    parser.add_argument("--synapse-container")
    parser.add_argument("--postgres-container")
    parser.add_argument("--allow-server-pause", action="store_true")
    parser.add_argument("--deployment-environment-file", type=Path)
    parser.add_argument("--include-bot-runtime", action="store_true")
    args = parser.parse_args(argv)
    if args.include_bot_runtime and not args.capture:
        parser.error("--include-bot-runtime requires --capture")
    if args.retry_artifact and not args.upload:
        parser.error("--retry-artifact requires --upload")
    if args.upload and not args.drive_folder:
        parser.error("--upload requires --drive-folder")
    if args.snapshot_dir and (not args.work_dir or not args.recipient_file):
        parser.error("--snapshot-dir requires --work-dir and --recipient-file")
    if args.capture and not all((args.work_dir, args.recipient_file, args.synapse_dir,
                                 args.bot_store_dir, args.compose_file, args.synapse_container,
                                 args.postgres_container, args.allow_server_pause)):
        parser.error("--capture requires explicit source/container paths, work/recipient files and --allow-server-pause")
    try:
        if args.retry_artifact:
            artifact = args.retry_artifact
            file_id = upload_encrypted_artifact(artifact, args.drive_folder,
                                               original_artifact_digest(artifact))
        elif args.capture:
            settings = SnapshotSettings(
                args.synapse_dir, args.bot_store_dir, args.compose_file,
                args.work_dir / "capture", args.synapse_container, args.postgres_container,
                allow_server_pause=args.allow_server_pause,
                deployment_environment_file=args.deployment_environment_file,
                include_bot_runtime=args.include_bot_runtime,
            )
            with captured_snapshot(settings) as snapshot:
                result = create_encrypted_backup(
                    BackupSettings(snapshot, args.work_dir / "packages", args.recipient_file, args.age_executable),
                    uploader=upload_encrypted_artifact if args.upload else None,
                    drive_folder=args.drive_folder,
                )
            artifact, file_id = result.artifact, result.drive_file_id
        else:
            result = create_encrypted_backup(
                BackupSettings(args.snapshot_dir, args.work_dir, args.recipient_file, args.age_executable),
                uploader=upload_encrypted_artifact if args.upload else None,
                drive_folder=args.drive_folder,
            )
            artifact, file_id = result.artifact, result.drive_file_id
        print(json.dumps({"status": "uploaded" if file_id else "encrypted_local_only",
                          "artifact": str(artifact), "drive_file_id": file_id}))
        return 0
    except MatrixBackupError as error:
        print(json.dumps({"status": "failed", "code": str(error)}))
        return 1
    except Exception:
        print(json.dumps({"status": "failed", "code": "backup_failed"}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
