"""Offline cold-snapshot regressions; no cloud or live user stores."""

import json
from pathlib import Path
import zipfile

import pytest

from services.daily_data_backup import BackupError, build_data_package, upload_verified_package
from unittest.mock import MagicMock
import hashlib
import os
import time
from services import daily_backup_runtime as runtime
from contextlib import contextmanager
from services import daily_backup_job as job


def fixture_tree(root: Path) -> None:
    """Create a synthetic installation containing data and excluded material."""
    (root / "chroma_db").mkdir()
    (root / "chroma_db" / "chroma.sqlite3").write_bytes(b"fixture-chroma")
    (root / "astakos_state.db").write_bytes(b"fixture-sqlite")
    (root / "astakos_state.db-wal").write_bytes(b"fixture-wal")
    (root / "astakos_settings.json").write_text('{"quiet": true}')
    (root / "telegram_photos").mkdir()
    photo = root / "telegram_photos" / "saved.jpg"
    photo.write_bytes(b"indexed-photo")
    (root / "telegram_photos" / "temp.jpg").write_bytes(b"temporary")
    (root / "astakos_photos_index.json").write_text(json.dumps([{"file_path": str(photo)}]))
    (root / "astakos_docs_index.json").write_text("[]")
    (root / "source.py").write_text("code")
    (root / "credentials.json").write_text("secret")
    (root / ".env").write_text("secret")
    (root / "unknown.json").write_text("not-a-state-file")


def test_package_contains_only_recovery_data_and_indexed_assets(tmp_path: Path) -> None:
    """Preserve cold data/sidecars; exclude code, unknown JSON and temp media."""
    root = tmp_path / "installation"
    root.mkdir()
    fixture_tree(root)
    archive = tmp_path / "backup.zip"
    build_data_package(root, archive, assert_quiescent=lambda: None)
    with zipfile.ZipFile(archive) as package:
        names = set(package.namelist())
        assert {"astakos_state.db", "astakos_state.db-wal", "chroma_db/chroma.sqlite3",
                "telegram_photos/saved.jpg", "astakos_settings.json", "backup-manifest.json"} <= names
        assert not names & {"source.py", ".env", "credentials.json", "unknown.json", "telegram_photos/temp.jpg"}


def test_missing_indexed_asset_fails_without_publishing_package(tmp_path: Path) -> None:
    """A missing binary must not silently produce a successful backup."""
    root = tmp_path / "installation"
    root.mkdir()
    fixture_tree(root)
    (root / "telegram_photos" / "saved.jpg").unlink()
    with pytest.raises(BackupError, match="indexed_asset_missing"):
        build_data_package(root, tmp_path / "backup.zip", assert_quiescent=lambda: None)
    assert not (tmp_path / "backup.zip").exists()


def test_live_writer_guard_prevents_capture(tmp_path: Path) -> None:
    """Never copy stores when the coordinator cannot prove quiescence."""
    root = tmp_path / "installation"
    root.mkdir()
    fixture_tree(root)
    def refuse() -> None:
        raise BackupError("writers_running")
    with pytest.raises(BackupError, match="writers_running"):
        build_data_package(root, tmp_path / "backup.zip", assert_quiescent=refuse)


def test_index_cannot_pull_secrets_into_archive(tmp_path: Path) -> None:
    """An index path is not permission to archive arbitrary local files."""
    root = tmp_path / "installation"
    root.mkdir()
    fixture_tree(root)
    (root / "astakos_photos_index.json").write_text(json.dumps([
        {"file_path": str(root / "credentials.json")}
    ]))
    with pytest.raises(BackupError, match="unsafe_asset_path"):
        build_data_package(root, tmp_path / "backup.zip", assert_quiescent=lambda: None)


@pytest.mark.parametrize("valid", [False, True])
def test_retention_only_after_verified_upload_and_only_own_daily_backups(tmp_path: Path, valid: bool) -> None:
    """Bad upload preserves everything; pagination cannot remove Matrix/unrelated files."""
    archive = tmp_path / "daily.zip"
    archive.write_bytes(b"fixture-package")
    service = MagicMock()
    api = service.files.return_value
    api.list.return_value.execute.side_effect = [
        {"files": [{"id": "legacy", "name": "astakos_v2_backup_2026-10-01",
                    "mimeType": "application/vnd.google-apps.folder", "ownedByMe": True},
                   {"id": "matrix", "name": "matrix-backup.age", "ownedByMe": True}],
         "nextPageToken": "page2"},
        {"files": [{"id": "unrelated", "name": "holiday.zip", "mimeType": "application/zip", "ownedByMe": True}]},
    ]
    api.get.return_value.execute.side_effect = [
        {"id": "parent", "mimeType": "application/vnd.google-apps.folder", "ownedByMe": True,
         "permissions": [{"type": "user", "role": "owner"}]},
        {"id": "new", "size": "15", "parents": ["parent"], "ownedByMe": True,
         "md5Checksum": hashlib.md5(b"fixture-package").hexdigest() if valid else "wrong"},
        {"parents": ["parent"], "ownedByMe": True},
    ]
    api.create.return_value.execute.return_value = {"id": "new"}
    if not valid:
        with pytest.raises(BackupError, match="remote_verification_failed"):
            upload_verified_package(service, archive, "parent")
        api.update.assert_not_called()
    else:
        assert upload_verified_package(service, archive, "parent") == "new"
        assert [call.kwargs["fileId"] for call in api.update.call_args_list] == ["legacy"]
        assert api.update.call_args.kwargs["body"] == {"trashed": True}


def test_unmanaged_writer_aborts_before_request_or_downtime(tmp_path: Path) -> None:
    """An old launcher cannot be paused implicitly or force-killed."""
    with pytest.raises(BackupError, match="restart_from_updated_launcher_required"):
        with runtime.cold_pause(root=tmp_path, records=lambda: [{"ProcessId": 7, "CommandLine": "python -m uvicorn api.server:server"}]):
            pytest.fail("capture must not run")
    assert not (tmp_path / ".daily-backup-request.json").exists()
    assert not runtime.pause_held(tmp_path)


def test_coordinator_failure_releases_pause(tmp_path: Path) -> None:
    """A failed snapshot releases the OS lock so supervisors recover."""
    with pytest.raises(BackupError, match="fixture_failure"):
        with runtime.cold_pause(root=tmp_path, records=lambda: []):
            assert runtime.pause_held(tmp_path)
            raise BackupError("fixture_failure")
    assert not runtime.pause_held(tmp_path)


def test_checkpoint_stops_owned_child_and_resumes_once(monkeypatch, tmp_path: Path) -> None:
    """Exercise the real correlated checkpoint without signaling any real process."""
    old = MagicMock(pid=42)
    old.poll.return_value = None
    new = MagicMock(pid=43)
    new.poll.return_value = None
    tree = MagicMock()
    tree.wait.return_value = True
    from services import windows_process_tree
    monkeypatch.setattr(windows_process_tree, "WindowsProcessTree", lambda _: tree)
    held = iter([True, True, False])
    monkeypatch.setattr(runtime, "pause_held", lambda root: next(held))
    monkeypatch.setattr(runtime.time, "sleep", lambda seconds: None)
    runtime.atomic_json(tmp_path / ".daily-backup-request.json", {
        "nonce": "fixture", "at": time.time(),
        "participants": {"matrix": {"parent_pid": os.getpid(), "child_pid": 42}}})
    restart = MagicMock(return_value=new)
    assert runtime.checkpoint("matrix", old, restart, root=tmp_path) is new
    old.send_signal.assert_called_once()
    restart.assert_called_once()
    assert json.loads((tmp_path / ".daily-backup-matrix.json").read_text())["child_pid"] == 43


def test_real_packaging_finishes_and_resumes_before_any_upload(monkeypatch, tmp_path: Path) -> None:
    """Real fixture archive + manifest; only the process/Drive edges are fake."""
    root = tmp_path / "installation"
    root.mkdir()
    fixture_tree(root)
    stages = []
    @contextmanager
    def pause(**kwargs):
        stages.append("paused")
        try:
            yield
        finally:
            stages.append("resumed")
    def upload(service, archive, parent):
        assert stages == ["paused", "resumed"]
        with zipfile.ZipFile(archive) as package:
            manifest = json.loads(package.read("backup-manifest.json"))
            assert manifest["git_revision"] == "fixture-revision"
            assert package.read("telegram_photos/saved.jpg") == b"indexed-photo"
        stages.append("uploaded")
        return "remote-fixture"
    monkeypatch.setattr(job, "upload_verified_package", upload)
    monkeypatch.setattr(job.subprocess, "run", lambda *args, **kwargs: MagicMock(returncode=0, stdout="fixture-revision"))
    result = job.run_data_backup(object(), root, "parent", pause=pause, guard=lambda: None)
    assert result["status"] == "complete"
    assert stages == ["paused", "resumed", "uploaded"]


def test_missing_asset_preflight_does_not_pause_or_upload(monkeypatch, tmp_path: Path) -> None:
    """Incomplete input preserves uptime as well as the previous remote backup."""
    root = tmp_path / "installation"
    root.mkdir()
    fixture_tree(root)
    (root / "telegram_photos" / "saved.jpg").unlink()
    pause = MagicMock(side_effect=AssertionError("must not pause"))
    monkeypatch.setattr(job, "upload_verified_package", MagicMock(side_effect=AssertionError("must not upload")))
    with pytest.raises(BackupError, match="indexed_asset_missing"):
        job.run_data_backup(object(), root, "parent", pause=pause, guard=lambda: None)


def test_source_change_during_capture_rejects_package(monkeypatch, tmp_path: Path) -> None:
    """A writer racing capture cannot publish a successful-looking artifact."""
    root = tmp_path / "installation"
    root.mkdir()
    fixture_tree(root)
    checks = []
    def guard():
        checks.append(True)
        if len(checks) == 2:
            (root / "astakos_state.db").write_bytes(b"modified")
    with pytest.raises(BackupError, match="snapshot_changed"):
        build_data_package(root, tmp_path / "backup.zip", assert_quiescent=guard)
    assert not (tmp_path / "backup.zip").exists()


def test_retention_never_runs_after_upload_exception(tmp_path: Path) -> None:
    """A network error cannot remove the last known-good copy."""
    archive = tmp_path / "fixture.zip"
    archive.write_bytes(b"fixture")
    service = MagicMock()
    api = service.files.return_value
    api.get.return_value.execute.return_value = {"id": "parent", "ownedByMe": True,
        "mimeType": "application/vnd.google-apps.folder", "permissions": [{"type": "user", "role": "owner"}]}
    api.list.return_value.execute.return_value = {"files": []}
    api.create.return_value.execute.side_effect = OSError("fixture-network")
    with pytest.raises(OSError):
        upload_verified_package(service, archive, "parent")
    api.update.assert_not_called()
