"""Package an operator-prepared Matrix snapshot; never capture active stores.

No runtime configuration, credentials, Docker or provider is loaded at import.
Only the final recipient-encrypted artifact may cross the upload boundary.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import stat
import subprocess
import tarfile
import tempfile
import uuid
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from filelock import FileLock, Timeout


class MatrixBackupError(RuntimeError):
    """Safe operator error code, without credential-bearing diagnostics."""


@dataclass(frozen=True)
class BackupSettings:
    """Explicit paths; work_dir must be outside source, repository and sync roots."""

    snapshot_dir: Path
    work_dir: Path
    recipient_file: Path
    age_executable: str


@dataclass(frozen=True)
class BackupResult:
    """A local package is not evidence of successful remote recovery."""

    artifact: Path
    sha256: str
    drive_file_id: str | None = None


def is_reparse_point(path: Path) -> bool:
    """Reject links, Windows junctions and special files without following them."""
    info = path.lstat()
    return path.is_symlink() or bool(
        getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT
    ) or not (stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode))


def validate_path(path: Path) -> Path:
    """Reject links in the complete existing path, including ancestor junctions."""
    absolute = path.absolute()
    for part in (absolute, *absolute.parents):
        if part.exists() or part.is_symlink():
            if is_reparse_point(part):
                raise MatrixBackupError("unsafe_backup_path")
    return absolute.resolve()


def secure_directory(path: Path) -> None:
    """Provision private staging permissions, then verify the Windows allowlist."""
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    if os.name != "nt":
        path.chmod(0o700)
        return
    try:
        # Pass the path as an environment value, never interpolate it into code.
        env = dict(os.environ, MATRIX_BACKUP_ACL_PATH=str(path))
        subprocess.run([
            "powershell.exe", "-NoProfile", "-NonInteractive", "-Command",
            "$ErrorActionPreference='Stop'; "
            "$s=[System.Security.Principal.WindowsIdentity]::GetCurrent().User; "
            "& icacls.exe $env:MATRIX_BACKUP_ACL_PATH /inheritance:r /grant:r "
            "('*'+$s.Value+':(OI)(CI)F') '*S-1-5-18:(OI)(CI)F' | Out-Null; "
            "if($LASTEXITCODE -ne 0){exit 1}; "
            "$a=[System.IO.Directory]::GetAccessControl($env:MATRIX_BACKUP_ACL_PATH); "
            "foreach($r in $a.GetAccessRules($true,$true,[System.Security.Principal.SecurityIdentifier])){ "
            "$id=$r.IdentityReference.Value; "
            "if($id -notin @($s.Value,'S-1-5-18')){ "
            "& icacls.exe $env:MATRIX_BACKUP_ACL_PATH /remove:g ('*'+$id) | Out-Null; "
            "if($LASTEXITCODE -ne 0){exit 1}; "
            "& icacls.exe $env:MATRIX_BACKUP_ACL_PATH /remove:d ('*'+$id) | Out-Null; "
            "if($LASTEXITCODE -ne 0){exit 1} }}",
        ], env=env, capture_output=True, check=True, timeout=30)
        check = subprocess.run([
            "powershell.exe", "-NoProfile", "-NonInteractive", "-Command",
            "$a=[System.IO.Directory]::GetAccessControl($env:MATRIX_BACKUP_ACL_PATH); "
            "$s=[System.Security.Principal.WindowsIdentity]::GetCurrent().User.Value; "
            "$bad=@($a.GetAccessRules($true,$true,[System.Security.Principal.SecurityIdentifier]) | Where-Object { "
            "$_.IdentityReference.Value "
            "-notin @($s,'S-1-5-18') -or $_.AccessControlType -ne 'Allow' }); "
            "if(-not $a.AreAccessRulesProtected -or $bad.Count -ne 0){exit 1}",
        ], env=env, capture_output=True, timeout=30)
        if check.returncode:
            raise MatrixBackupError("unsafe_staging_permissions")
    except Exception:
        raise MatrixBackupError("unsafe_staging_permissions") from None


def file_digest(path: Path, algorithm: str = "sha256") -> str:
    """Stream hashes without loading large archives into memory."""
    digest = hashlib.new(algorithm, usedforsecurity=algorithm != "md5")
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def snapshot_inventory(root: Path) -> dict[str, tuple[int, int, str]]:
    """Validate the completed snapshot contract and fingerprint every regular file."""
    root = validate_path(root)
    if not root.is_dir():
        raise MatrixBackupError("snapshot_missing")
    entries = list(root.rglob("*"))
    if any(is_reparse_point(path) for path in entries):
        raise MatrixBackupError("unsafe_snapshot_entry")
    try:
        metadata = json.loads((root / "snapshot.json").read_text(encoding="utf-8"))
        if (metadata.get("format_version") != 1 or metadata.get("consistent") is not True
                or not metadata.get("captured_at") or not metadata.get("images")):
            raise ValueError
        signing = Path(metadata["signing_key"])
        if signing.is_absolute() or ".." in signing.parts or signing.parts[0] != "synapse":
            raise ValueError
        required = ["postgres.dump", "postgres-roles.sql", "compose.yaml", "snapshot.json",
                    "synapse/homeserver.yaml", "bot-store/matrix_store.db", str(signing)]
        if any(not (root / name).is_file() or (root / name).stat().st_size == 0 for name in required):
            raise ValueError
        if not (root / "synapse" / "media_store").is_dir():
            raise ValueError
        with (root / "postgres.dump").open("rb") as dump:
            if dump.read(5) != b"PGDMP":
                raise ValueError
    except Exception:
        raise MatrixBackupError("incomplete_or_unconfirmed_snapshot") from None
    inventory = {}
    for path in entries:
        if path.is_file():
            with path.open("rb") as source:
                prefix = source.read(4096)
            if b"AGE-SECRET-KEY-" in prefix:
                raise MatrixBackupError("recovery_identity_in_snapshot")
            info = path.stat()
            inventory[path.relative_to(root).as_posix()] = (
                info.st_size, info.st_mtime_ns, file_digest(path),
            )
    if "backup-manifest.json" in inventory:
        raise MatrixBackupError("reserved_manifest_name")
    return inventory


def archive_snapshot(root: Path, archive: Path, inventory: dict) -> None:
    """Archive regular files and the empty media directory without following links."""
    manifest = json.dumps({
        "format_version": 1, "packaged_at": datetime.now(timezone.utc).isoformat(),
        "files": {name: {"size": value[0], "sha256": value[2]}
                  for name, value in sorted(inventory.items())},
    }, sort_keys=True).encode("utf-8")
    with tarfile.open(archive, "w:gz", dereference=False) as bundle:
        for name in sorted(inventory):
            path = root / name
            if is_reparse_point(path):
                raise MatrixBackupError("snapshot_changed")
            bundle.add(path, arcname=name, recursive=False)
        bundle.add(root / "synapse" / "media_store", arcname="synapse/media_store", recursive=False)
        info = tarfile.TarInfo("backup-manifest.json")
        info.size = len(manifest)
        info.mode = 0o600
        bundle.addfile(info, io.BytesIO(manifest))


def validate_archive(archive: Path, inventory: dict) -> None:
    """Verify archived bytes against the inventory, including mid-copy mutations."""
    seen = set()
    with tarfile.open(archive, "r:gz") as bundle:
        for member in bundle:
            if member.name in seen:
                raise MatrixBackupError("archive_integrity_failed")
            seen.add(member.name)
            if member.name == "synapse/media_store" and member.isdir():
                continue
            if not member.isfile():
                raise MatrixBackupError("archive_integrity_failed")
            source = bundle.extractfile(member)
            if source is None:
                raise MatrixBackupError("archive_integrity_failed")
            with source:
                if member.name == "backup-manifest.json":
                    manifest = json.load(source)
                    expected = {name: {"size": value[0], "sha256": value[2]}
                                for name, value in inventory.items()}
                    if manifest.get("files") != expected:
                        raise MatrixBackupError("archive_integrity_failed")
                    continue
                if member.name not in inventory or member.size != inventory[member.name][0]:
                    raise MatrixBackupError("archive_integrity_failed")
                digest = hashlib.sha256()
                for block in iter(lambda: source.read(1024 * 1024), b""):
                    digest.update(block)
                if digest.hexdigest() != inventory[member.name][2]:
                    raise MatrixBackupError("archive_integrity_failed")
        if seen != set(inventory) | {"backup-manifest.json", "synapse/media_store"}:
            raise MatrixBackupError("archive_integrity_failed")


def validate_ciphertext(path: Path) -> None:
    """Validate the output envelope, not cryptographic validity or recoverability."""
    path = validate_path(path)
    if not path.is_file() or path.suffix != ".age":
        raise MatrixBackupError("encrypted_artifact_missing")
    with path.open("rb") as artifact:
        if artifact.read(22) != b"age-encryption.org/v1\n" or path.stat().st_size <= 22:
            raise MatrixBackupError("encrypted_artifact_invalid")


def record_artifact_digest(artifact: Path, digest: str) -> None:
    """Publish the original encryption checksum before any upload attempt."""
    destination = artifact.with_suffix(".age.sha256")
    fd, name = tempfile.mkstemp(prefix="digest-", dir=artifact.parent)
    try:
        with os.fdopen(fd, "w", encoding="ascii") as stream:
            stream.write(digest + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, destination)
    finally:
        Path(name).unlink(missing_ok=True)


def original_artifact_digest(artifact: Path) -> str:
    """Reject missing provenance or changed bytes; never bless a retry's new hash."""
    try:
        validate_ciphertext(artifact)
        receipt = validate_path(artifact.with_suffix(".age.sha256"))
        digest = receipt.read_text(encoding="ascii").strip()
        if (len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest)
                or file_digest(artifact) != digest):
            raise ValueError
        return digest
    except Exception:
        raise MatrixBackupError("retry_artifact_integrity_failed") from None


def create_encrypted_backup(
    settings: BackupSettings, *, runner: Callable = subprocess.run,
    uploader: Callable[[Path, str, str], str] | None = None,
    drive_folder: str | None = None,
) -> BackupResult:
    """Encrypt a prepared snapshot, optionally upload, and scrub owned staging.

    Caller supplies a quiescent snapshot, not the active installation. Snapshot
    metadata is an operator attestation, not independent proof of consistency.
    On upload failure the encrypted package remains available for explicit retry.
    """
    try:
        source = validate_path(settings.snapshot_dir)
        work = validate_path(settings.work_dir)
        recipient = validate_path(settings.recipient_file)
        repository = Path(__file__).resolve().parents[1]
        if (work.is_relative_to(source) or source.is_relative_to(work)
                or work.is_relative_to(repository) or recipient.is_relative_to(source)):
            raise MatrixBackupError("overlapping_backup_paths")
        if not recipient.is_file():
            raise MatrixBackupError("recipient_missing")
        lines = [line.strip() for line in recipient.read_text(encoding="utf-8-sig").splitlines()
                 if line.strip() and not line.startswith("#")]
        if not lines or any(not line.startswith("age1") for line in lines):
            raise MatrixBackupError("public_recipient_required")
        if uploader is not None and (not drive_folder or drive_folder == "root"):
            raise MatrixBackupError("explicit_private_drive_folder_required")
        secure_directory(work)
        with FileLock(str(work / "backup.lock"), timeout=0):
            inventory = snapshot_inventory(source)
            run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex
            artifact = work / f"matrix-backup-{run_id}.age"
            partial = work / f"matrix-backup-{run_id}.age.part"
            try:
                with tempfile.TemporaryDirectory(prefix="stage-", dir=work) as stage:
                    archive = Path(stage) / "snapshot.tar.gz"
                    archive_snapshot(source, archive, inventory)
                    validate_archive(archive, inventory)
                    if snapshot_inventory(source) != inventory:
                        raise MatrixBackupError("snapshot_changed")
                    completed = runner([
                        settings.age_executable, "--encrypt", "-R", str(recipient),
                        "-o", str(partial), str(archive),
                    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       check=False, timeout=3600)
                    if completed.returncode != 0:
                        raise MatrixBackupError("encryption_failed")
                    # The format check requires the final extension; validate bytes first.
                    with partial.open("rb") as output:
                        if output.read(22) != b"age-encryption.org/v1\n" or partial.stat().st_size <= 22:
                            raise MatrixBackupError("encrypted_artifact_invalid")
                    with partial.open("rb+") as output:
                        os.fsync(output.fileno())
                    os.replace(partial, artifact)
            finally:
                partial.unlink(missing_ok=True)
            result = BackupResult(artifact, file_digest(artifact))
            record_artifact_digest(artifact, result.sha256)
            if uploader is not None:
                file_id = uploader(artifact, drive_folder, result.sha256)
                if not file_id:
                    raise MatrixBackupError("upload_not_confirmed")
                result = replace(result, drive_file_id=file_id)
            return result
    except Timeout:
        raise MatrixBackupError("backup already running") from None
    except MatrixBackupError:
        raise
    except Exception:
        raise MatrixBackupError("backup_failed") from None


def upload_encrypted_artifact(path: Path, drive_folder: str, sha256: str) -> str:
    """Upload only ciphertext, using canonical OAuth and verified Drive metadata.

    A preallocated Drive ID persists beside the encrypted package. Explicit retry
    checks that ID first, preventing duplicates after an ambiguous response.
    """
    try:
        validate_ciphertext(path)
        if file_digest(path) != sha256 or not drive_folder or drive_folder == "root":
            raise MatrixBackupError("invalid_upload_request")
        expected_size = path.stat().st_size
        expected_md5 = file_digest(path, "md5")
        # Imports and credential access occur only after explicit upload opt-in.
        from core.workspace_oauth import load_workspace_credentials
        from googleapiclient.discovery import build
        from googleapiclient.errors import HttpError
        from googleapiclient.http import MediaFileUpload

        creds = load_workspace_credentials(scopes=["https://www.googleapis.com/auth/drive"])
        service = build("drive", "v3", credentials=creds, cache_discovery=False)
        folder = service.files().get(fileId=drive_folder, fields="mimeType,trashed").execute()
        if folder.get("trashed") or folder.get("mimeType") != "application/vnd.google-apps.folder":
            raise MatrixBackupError("invalid_drive_destination")
        with FileLock(str(path) + ".upload.lock", timeout=0):
            receipt_path = path.with_suffix(".age.upload-id")
            if receipt_path.exists():
                file_id = receipt_path.read_text(encoding="ascii").strip()
            else:
                file_id = service.files().generateIds(count=1, space="drive").execute()["ids"][0]
                receipt_temp = receipt_path.with_name(receipt_path.name + "." + uuid.uuid4().hex + ".part")
                try:
                    with receipt_temp.open("x", encoding="ascii") as receipt:
                        receipt.write(file_id)
                        receipt.flush()
                        os.fsync(receipt.fileno())
                    os.replace(receipt_temp, receipt_path)
                finally:
                    receipt_temp.unlink(missing_ok=True)
            fields = "id,size,md5Checksum,parents,trashed,appProperties"
            try:
                remote = service.files().get(fileId=file_id, fields=fields).execute()
            except HttpError as error:
                if error.resp.status != 404:
                    raise
                remote = None
            if remote is None:
                service.files().create(body={
                    "id": file_id, "name": path.name, "parents": [drive_folder],
                    "appProperties": {"astakos_matrix_sha256": sha256},
                }, media_body=MediaFileUpload(str(path), mimetype="application/octet-stream",
                                              resumable=True), fields="id").execute()
                remote = service.files().get(fileId=file_id, fields=fields).execute()
            if (remote.get("trashed") or drive_folder not in remote.get("parents", [])
                    or int(remote.get("size", -1)) != expected_size
                    or remote.get("md5Checksum") != expected_md5
                    or file_digest(path) != sha256
                    or remote.get("appProperties", {}).get("astakos_matrix_sha256") != sha256):
                raise MatrixBackupError("remote_artifact_not_verified")
            return file_id
    except MatrixBackupError:
        raise
    except Exception:
        raise MatrixBackupError("drive_upload_failed") from None
