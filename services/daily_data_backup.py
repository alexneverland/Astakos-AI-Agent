"""Selective cold Astakos data snapshots; never open live databases."""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable
import zipfile
import re

from services.matrix_backup import is_reparse_point


class BackupError(RuntimeError):
    """A bounded backup failure, safe to report without source contents."""


STATE_FILES = frozenset({
    "astakos_state.db", "astakos_profile.db", "astakos_routines.db",
    "astakos_conversation_history.db", "astakos_embeddings_cache.db",
    "astakos_followups.db", "astakos_events.db", "analytics_state.db",
    "behavioral_event_observations.db",
    "astakos_settings.json", "astakos_custom_intents.json", "astakos_context_schema.json",
    "astakos_working_memory.json", "astakos_sessions.json", "astakos_capabilities.json",
    "astakos_pending_approval.json", "astakos_photos_index.json", "astakos_docs_index.json",
    "behavioral_initiative_state.json", "behavioral_conversation_preferences.json",
    "astakos_routine_context_questions.json",
    "project_access.json", "room_map.json", "messenger_draft.json", "linkedin_draft.json",
    "scheduler_state.json", "persona.md", "last_location.json", "known_places.json",
    "astakos_skills/food_history.json", "astakos_skills/recipe_library.json",
    ".goal_followup_sent", ".hn_briefing_sent", ".calendar_briefing_sent", ".ai_briefing_sent",
})
ASSET_ROOTS = ("telegram_photos", "telegram_uploads", "outputs/documents_archive")


def checked_path(root: Path, path: Path) -> Path:
    """Reject links/reparse points and escapes, including linked ancestors."""
    path = path.absolute()
    try:
        relative = path.relative_to(root)
    except ValueError:
        raise BackupError("unsafe_asset_path") from None
    for parent in (root, *(root / Path(*relative.parts[:i]) for i in range(1, len(relative.parts) + 1))):
        if (parent.exists() and is_reparse_point(parent)) or parent.is_symlink():
            raise BackupError("unsafe_asset_path")
    return path


def select_data_files(root: Path) -> list[Path]:
    """Choose an explicit state allowlist and binaries referenced by both indexes."""
    root = root.absolute()
    files: set[Path] = set()
    for name in STATE_FILES:
        path = checked_path(root, root / name)
        if path.is_file():
            files.add(path)
            if name.endswith(".db"):
                for suffix in ("-wal", "-shm", "-journal"):
                    sidecar = checked_path(root, Path(str(path) + suffix))
                    if sidecar.is_file():
                        files.add(sidecar)
    chroma = checked_path(root, root / "chroma_db")
    if not chroma.is_dir():
        raise BackupError("chroma_missing")
    for path in chroma.rglob("*"):
        checked_path(root, path)
        if path.is_file():
            files.add(path)
    for name in ("astakos_photos_index.json", "astakos_docs_index.json"):
        index = root / name
        if not index.is_file():
            raise BackupError("asset_index_missing")
        try:
            entries = json.loads(index.read_text(encoding="utf-8"))
            if not isinstance(entries, list):
                raise ValueError
            for entry in entries:
                raw = entry["file_path"]
                if not isinstance(raw, str) or not raw:
                    raise ValueError
                path = checked_path(root, Path(raw) if Path(raw).is_absolute() else root / raw)
                relative = path.relative_to(root).as_posix()
                if not any(relative.startswith(folder + "/") for folder in ASSET_ROOTS):
                    raise BackupError("unsafe_asset_path")
                if path.name.casefold() in {"credentials.json", "token.json", "client_secrets.json", ".astakos_token"} or path.name.casefold().startswith(".env"):
                    raise BackupError("unsafe_asset_path")
                if not path.is_file():
                    raise BackupError("indexed_asset_missing")
                files.add(path)
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            raise BackupError("asset_index_invalid") from None
    return sorted(files)


def digest(path: Path) -> str:
    """Hash an artifact without loading it into memory."""
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def verify_package(archive: Path, manifest: dict) -> None:
    """Read every archived byte and compare it with the captured manifest."""
    with zipfile.ZipFile(archive) as package:
        names = package.namelist()
        if len(names) != len(set(names)) or set(names) != set(manifest["files"]) | {"backup-manifest.json"}:
            raise BackupError("archive_integrity_failed")
        if json.loads(package.read("backup-manifest.json")) != manifest:
            raise BackupError("archive_integrity_failed")
        for name, info in manifest["files"].items():
            with package.open(name) as source:
                if package.getinfo(name).file_size != info["size"] or hashlib.file_digest(source, "sha256").hexdigest() != info["sha256"]:
                    raise BackupError("archive_integrity_failed")


def build_data_package(root: Path, archive: Path, *, assert_quiescent: Callable[[], None],
                       git_revision: str = "unknown") -> dict:
    """Build only while all writers are stopped; validate every included file."""
    root = root.absolute()
    archive = archive.absolute()
    if archive.is_relative_to(root) or archive.exists():
        raise BackupError("unsafe_archive_destination")
    assert_quiescent()
    paths = select_data_files(root)
    manifest = {"format_version": 1, "captured_at": datetime.now(timezone.utc).isoformat(), "git_revision": git_revision,
                "original_root": str(root), "files": {}}
    for path in paths:
        info = path.stat()
        manifest["files"][path.relative_to(root).as_posix()] = {
            "size": info.st_size, "mtime_ns": info.st_mtime_ns, "sha256": digest(path)}
    partial = archive.with_name(archive.name + ".part")
    try:
        with zipfile.ZipFile(partial, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=3) as package:
            for path in paths:
                checked_path(root, path)
                package.write(path, path.relative_to(root).as_posix())
            package.writestr("backup-manifest.json", json.dumps(manifest, sort_keys=True))
        assert_quiescent()
        if paths != select_data_files(root):
            raise BackupError("snapshot_changed")
        for path in paths:
            info = manifest["files"][path.relative_to(root).as_posix()]
            if path.stat().st_mtime_ns != info["mtime_ns"] or digest(path) != info["sha256"]:
                raise BackupError("snapshot_changed")
        verify_package(partial, manifest)
        os.replace(partial, archive)
        return manifest
    finally:
        partial.unlink(missing_ok=True)


def upload_verified_package(service: object, archive: Path, parent_id: str) -> str:
    """Publish one package; trash only frozen, scoped predecessors after verification."""
    from googleapiclient.http import MediaFileUpload

    if not re.fullmatch(r"[A-Za-z0-9_-]+", parent_id):
        raise BackupError("invalid_drive_parent")
    api = service.files()
    parent = api.get(fileId=parent_id, fields="id,mimeType,trashed,ownedByMe,permissions(type,role)").execute()
    permissions = parent.get("permissions", [])
    if (parent.get("mimeType") != "application/vnd.google-apps.folder" or parent.get("trashed")
            or not parent.get("ownedByMe") or not permissions
            or any(item.get("type") != "user" or item.get("role") != "owner" for item in permissions)):
        raise BackupError("drive_parent_not_private")
    parent_id = parent["id"]
    predecessors = []
    token = None
    while True:
        page = api.list(q=f"'{parent_id}' in parents and trashed = false", pageToken=token,
                        fields="nextPageToken,files(id,name,mimeType,ownedByMe,appProperties)").execute()
        for item in page.get("files", []):
            legacy = (item.get("mimeType") == "application/vnd.google-apps.folder"
                      and re.fullmatch(r"astakos_v2_backup_\d{4}-\d{2}-\d{2}", item.get("name", "")))
            managed = (item.get("mimeType") == "application/zip"
                       and item.get("appProperties", {}).get("astakos_daily_data") == "v1")
            if item.get("ownedByMe") and (legacy or managed):
                predecessors.append(item["id"])
        token = page.get("nextPageToken")
        if not token:
            break
    with archive.open("rb") as source:
        checksum = hashlib.file_digest(source, "md5").hexdigest()
    created = api.create(body={"name": archive.name, "parents": [parent_id],
                              "mimeType": "application/zip",
                              "appProperties": {"astakos_daily_data": "v1"}},
                         media_body=MediaFileUpload(str(archive), mimetype="application/zip", resumable=True),
                         fields="id").execute()
    file_id = created["id"]
    verified = api.get(fileId=file_id, fields="id,size,md5Checksum,parents,trashed,ownedByMe").execute()
    if (verified.get("id") != file_id or verified.get("trashed") or not verified.get("ownedByMe")
            or verified.get("parents") != [parent_id]
            or str(verified.get("size")) != str(archive.stat().st_size)
            or verified.get("md5Checksum") != checksum):
        raise BackupError("remote_verification_failed")
    for predecessor in predecessors:
        if predecessor == file_id:
            continue
        # Recheck membership/ownership immediately before the destructive action.
        current = api.get(fileId=predecessor, fields="parents,ownedByMe,trashed").execute()
        if current.get("ownedByMe") and current.get("parents") == [parent_id] and not current.get("trashed"):
            api.update(fileId=predecessor, body={"trashed": True}, fields="id,trashed").execute()
    return file_id
