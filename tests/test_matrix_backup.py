"""Offline package tests; all provider/process boundaries use local doubles."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tarfile
from types import SimpleNamespace
from pathlib import Path

import pytest

from services import matrix_backup as backup


@pytest.mark.skipif(os.name != "nt", reason="Windows ACL integration")
def test_private_directory_replaces_unrelated_explicit_grants(tmp_path):
    """Native staging must secure a new directory despite extra explicit ACEs."""
    work = tmp_path / "private-work"
    work.mkdir()
    result = subprocess.run(["icacls.exe", str(work), "/grant", "*S-1-5-32-544:(OI)(CI)F"],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    assert result.returncode == 0
    backup.secure_directory(work)


@pytest.fixture
def snapshot(tmp_path: Path) -> Path:
    """Create a synthetic, explicitly completed snapshot, never live data."""
    root = tmp_path / "snapshot"
    (root / "synapse" / "media_store").mkdir(parents=True)
    (root / "bot-store").mkdir()
    files = {
        "postgres.dump": b"PGDMPfixture",
        "postgres-roles.sql": b"-- synthetic roles",
        "compose.yaml": b"services: {}",
        "synapse/homeserver.yaml": b"server_name: fixture.invalid",
        "synapse/server.signing.key": b"synthetic server key",
        "bot-store/matrix_store.db": b"synthetic crypto store; not SQLite",
    }
    for name, content in files.items():
        (root / name).write_bytes(content)
    (root / "snapshot.json").write_text(json.dumps({
        "format_version": 1, "consistent": True,
        "signing_key": "synapse/server.signing.key",
        "captured_at": "2026-10-02T10:00:00+00:00",
        "images": {"synapse": "fixture:1", "postgres": "fixture:17"},
    }), encoding="utf-8")
    return root


@pytest.fixture
def settings(tmp_path: Path, snapshot: Path, monkeypatch: pytest.MonkeyPatch):
    """Inject process isolation and a public-only fixture recipient."""
    recipient = tmp_path / "recipient.txt"
    recipient.write_text("age1fixture", encoding="ascii")
    monkeypatch.setattr(backup, "secure_directory", lambda path: path.mkdir(exist_ok=True))
    return backup.BackupSettings(snapshot, tmp_path / "work", recipient, "age-fixture")


def fake_encrypt(arguments: list[str], **kwargs) -> subprocess.CompletedProcess:
    """Assert the staged tar is readable and emit a fake ciphertext envelope."""
    archive = Path(arguments[-1])
    with tarfile.open(archive) as bundle:
        assert "postgres.dump" in bundle.getnames()
        assert "backup-manifest.json" in bundle.getnames()
    Path(arguments[arguments.index("-o") + 1]).write_bytes(b"age-encryption.org/v1\nfixture")
    return subprocess.CompletedProcess(arguments, 0, b"", b"")


def test_package_only_keeps_ciphertext_and_does_not_upload(settings):
    result = backup.create_encrypted_backup(settings, runner=fake_encrypt)
    assert result.artifact.read_bytes().startswith(b"age-encryption.org/v1\n")
    assert result.sha256 == hashlib.sha256(result.artifact.read_bytes()).hexdigest()
    assert not list(settings.work_dir.glob("stage-*"))
    assert not list(settings.work_dir.glob("*.part"))
    assert result.drive_file_id is None


def test_upload_boundary_receives_only_final_ciphertext(settings):
    received = []
    def upload(path: Path, folder: str, digest: str) -> str:
        assert path.suffix == ".age"
        assert path.read_bytes().startswith(b"age-encryption.org/v1\n")
        received.append((folder, digest))
        return "fixture-id"
    result = backup.create_encrypted_backup(
        settings, runner=fake_encrypt, uploader=upload, drive_folder="private-fixture",
    )
    assert result.drive_file_id == "fixture-id"
    assert received == [("private-fixture", result.sha256)]


@pytest.mark.parametrize("failure", ["nonzero", "exception", "empty", "plaintext"])
def test_encryption_failure_never_uploads_or_replaces_previous(settings, failure):
    settings.work_dir.mkdir()
    previous = settings.work_dir / "previous.age"
    previous.write_bytes(b"previous known good")
    def run(arguments, **kwargs):
        if failure == "exception":
            raise OSError("SENSITIVE subprocess diagnostic")
        output = Path(arguments[arguments.index("-o") + 1])
        output.write_bytes(b"private plaintext" if failure == "plaintext" else b"")
        return subprocess.CompletedProcess(arguments, 1 if failure == "nonzero" else 0)
    def forbidden_upload(*args):
        pytest.fail("Encryption failure must not upload")
    with pytest.raises(backup.MatrixBackupError) as error:
        backup.create_encrypted_backup(settings, runner=run, uploader=forbidden_upload,
                                       drive_folder="fixture")
    assert "SENSITIVE" not in str(error.value)
    assert previous.read_bytes() == b"previous known good"
    assert not list(settings.work_dir.glob("stage-*"))


def test_upload_failure_preserves_encrypted_artifact_for_explicit_retry(settings):
    def upload(*args):
        raise RuntimeError("SENSITIVE credential")
    with pytest.raises(backup.MatrixBackupError) as error:
        backup.create_encrypted_backup(settings, runner=fake_encrypt, uploader=upload,
                                       drive_folder="fixture")
    assert "SENSITIVE" not in str(error.value)
    assert len(list(settings.work_dir.glob("*.age"))) == 1
    assert not list(settings.work_dir.glob("stage-*"))


@pytest.mark.parametrize("missing", ["postgres.dump", "postgres-roles.sql", "compose.yaml",
                                     "synapse/homeserver.yaml", "bot-store/matrix_store.db"])
def test_incomplete_snapshot_is_rejected_before_encryption(settings, missing):
    (settings.snapshot_dir / missing).unlink()
    with pytest.raises(backup.MatrixBackupError):
        backup.create_encrypted_backup(settings, runner=lambda *a, **k: pytest.fail("No process"))


def test_active_snapshot_is_not_accepted(settings):
    path = settings.snapshot_dir / "snapshot.json"
    metadata = json.loads(path.read_text())
    metadata["consistent"] = False
    path.write_text(json.dumps(metadata))
    with pytest.raises(backup.MatrixBackupError):
        backup.create_encrypted_backup(settings, runner=fake_encrypt)


def test_recovery_identity_cannot_be_packaged(settings):
    (settings.snapshot_dir / "arbitrary.txt").write_text("AGE-SECRET-KEY-1FIXTURE")
    with pytest.raises(backup.MatrixBackupError):
        backup.create_encrypted_backup(settings, runner=fake_encrypt)


def test_destination_inside_snapshot_is_rejected(settings):
    from dataclasses import replace
    with pytest.raises(backup.MatrixBackupError):
        backup.create_encrypted_backup(replace(settings, work_dir=settings.snapshot_dir / "work"),
                                       runner=fake_encrypt)


def test_link_is_rejected(settings, monkeypatch):
    original = backup.is_reparse_point
    monkeypatch.setattr(backup, "is_reparse_point", lambda p: p.name == "compose.yaml" or original(p))
    with pytest.raises(backup.MatrixBackupError):
        backup.create_encrypted_backup(settings, runner=fake_encrypt)


def test_two_runs_do_not_overlap(settings):
    from filelock import FileLock
    settings.work_dir.mkdir()
    with FileLock(str(settings.work_dir / "backup.lock")):
        with pytest.raises(backup.MatrixBackupError, match="already running"):
            backup.create_encrypted_backup(settings, runner=fake_encrypt)


def test_snapshot_mutation_is_rejected(settings, monkeypatch):
    original = backup.archive_snapshot
    def archive(*args):
        original(*args)
        (settings.snapshot_dir / "compose.yaml").write_bytes(b"changed fixture")
    monkeypatch.setattr(backup, "archive_snapshot", archive)
    with pytest.raises(backup.MatrixBackupError):
        backup.create_encrypted_backup(settings, runner=lambda *a, **k: pytest.fail("No encryption"))


def test_snapshot_changed_and_restored_during_archive_is_rejected(settings, monkeypatch):
    """The tar's contents must match its manifest, not just the source afterwards."""
    original_archive = backup.archive_snapshot
    path = settings.snapshot_dir / "compose.yaml"
    original_bytes, original_stat = path.read_bytes(), path.stat()
    def archive(*args):
        path.write_bytes(b"different contents")
        original_archive(*args)
        path.write_bytes(original_bytes)
        os.utime(path, ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns))
    monkeypatch.setattr(backup, "archive_snapshot", archive)
    with pytest.raises(backup.MatrixBackupError):
        backup.create_encrypted_backup(settings, runner=fake_encrypt)


@pytest.fixture
def fake_drive(monkeypatch):
    """Exercise the real upload orchestration without OAuth or network access."""
    from core import workspace_oauth
    from googleapiclient import discovery
    from googleapiclient.errors import HttpError
    state = {"remote": None, "creates": 0, "ambiguous": False, "corrupt": False, "mutate": False}
    class Request:
        def __init__(self, execute):
            self.action = execute
        def execute(self):
            return self.action()
    class Files:
        def get(self, *, fileId, fields):
            def run():
                if fileId == "fixture-folder":
                    return {"mimeType": "application/vnd.google-apps.folder", "trashed": False}
                if state["remote"] is None:
                    raise HttpError(SimpleNamespace(status=404, reason="missing"), b"{}")
                return state["remote"]
            return Request(run)
        def generateIds(self, **kwargs):
            return Request(lambda: {"ids": ["stable-fixture-id"]})
        def create(self, *, body, media_body, fields):
            def run():
                path = Path(media_body._filename)
                assert path.suffix == ".age"
                if state["mutate"]:
                    path.write_bytes(path.read_bytes() + b"changed-during-upload")
                state["creates"] += 1
                state["remote"] = {
                    "id": body["id"], "size": str(path.stat().st_size),
                    "md5Checksum": "bad" if state["corrupt"] else backup.file_digest(path, "md5"),
                    "parents": body["parents"], "appProperties": body["appProperties"],
                    "trashed": False,
                }
                if state["ambiguous"]:
                    raise OSError("SENSITIVE network response")
                return {"id": body["id"]}
            return Request(run)
    monkeypatch.setattr(workspace_oauth, "load_workspace_credentials", lambda **kwargs: object())
    monkeypatch.setattr(discovery, "build", lambda *a, **k: SimpleNamespace(files=lambda: Files()))
    return state


def test_remote_upload_verifies_size_checksum_and_destination(settings, fake_drive):
    result = backup.create_encrypted_backup(settings, runner=fake_encrypt)
    assert backup.upload_encrypted_artifact(result.artifact, "fixture-folder", result.sha256) == "stable-fixture-id"
    assert fake_drive["creates"] == 1


def test_remote_retry_does_not_duplicate_after_ambiguous_create(settings, fake_drive):
    result = backup.create_encrypted_backup(settings, runner=fake_encrypt)
    fake_drive["ambiguous"] = True
    with pytest.raises(backup.MatrixBackupError, match="drive_upload_failed"):
        backup.upload_encrypted_artifact(result.artifact, "fixture-folder", result.sha256)
    assert backup.upload_encrypted_artifact(result.artifact, "fixture-folder", result.sha256) == "stable-fixture-id"
    assert fake_drive["creates"] == 1


def test_corrupt_remote_is_not_reported_as_success(settings, fake_drive):
    result = backup.create_encrypted_backup(settings, runner=fake_encrypt)
    fake_drive["corrupt"] = True
    with pytest.raises(backup.MatrixBackupError, match="remote_artifact_not_verified"):
        backup.upload_encrypted_artifact(result.artifact, "fixture-folder", result.sha256)


def test_local_mutation_during_upload_cannot_pass_with_stale_sha(settings, fake_drive):
    result = backup.create_encrypted_backup(settings, runner=fake_encrypt)
    fake_drive["mutate"] = True
    with pytest.raises(backup.MatrixBackupError):
        backup.upload_encrypted_artifact(result.artifact, "fixture-folder", result.sha256)


def test_plaintext_retry_cannot_load_oauth(tmp_path, monkeypatch):
    from core import workspace_oauth
    path = tmp_path / "secret.age"
    path.write_bytes(b"plaintext must not be uploaded")
    monkeypatch.setattr(workspace_oauth, "load_workspace_credentials",
                        lambda **k: pytest.fail("No credentials for plaintext"))
    with pytest.raises(backup.MatrixBackupError):
        backup.upload_encrypted_artifact(path, "fixture-folder", backup.file_digest(path))


def test_cli_error_is_nonzero_and_does_not_print_diagnostics(monkeypatch, capsys):
    from scripts import backup_matrix
    def fail(*a, **k):
        raise OSError("SENSITIVE subprocess details")
    monkeypatch.setattr(backup_matrix, "create_encrypted_backup", fail)
    code = backup_matrix.main(["--snapshot-dir", "fixture", "--work-dir", "work",
                               "--recipient-file", "public"])
    assert code == 1
    assert "SENSITIVE" not in capsys.readouterr().out


def test_real_age_fixture_roundtrip_and_wrong_key(settings, tmp_path):
    """Use installed age only with disposable synthetic fixtures, never providers."""
    import shutil
    available = shutil.which("age")
    age = Path(available) if available else Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft/WinGet/Links/age.exe"
    keygen = age.with_name("age-keygen.exe")
    if not age.exists():
        pytest.skip("Optional local age binary is not installed")
    from dataclasses import replace
    key = tmp_path / "fixture-key.txt"
    other = tmp_path / "fixture-other-key.txt"
    for identity in (key, other):
        subprocess.run([str(keygen), "-o", str(identity)], check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    recipient = tmp_path / "fixture-recipient.txt"
    subprocess.run([str(keygen), "-y", "-o", str(recipient), str(key)], check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    result = backup.create_encrypted_backup(replace(settings, recipient_file=recipient,
                                                   age_executable=str(age)))
    output = tmp_path / "restored.tar.gz"
    subprocess.run([str(age), "--decrypt", "-i", str(key), "-o", str(output), str(result.artifact)],
                   check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    with tarfile.open(output) as bundle:
        assert bundle.extractfile("synapse/homeserver.yaml").read() == b"server_name: fixture.invalid"
    wrong = subprocess.run([str(age), "--decrypt", "-i", str(other), "-o",
                            str(tmp_path / "wrong.tar.gz"), str(result.artifact)],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    assert wrong.returncode != 0
    corrupted = tmp_path / "corrupt.age"
    data = bytearray(result.artifact.read_bytes())
    data[-1] ^= 1
    corrupted.write_bytes(data)
    tampered = subprocess.run([str(age), "--decrypt", "-i", str(key), "-o",
                               str(tmp_path / "tampered.tar.gz"), str(corrupted)],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    assert tampered.returncode != 0
