from datetime import datetime, timedelta
from pathlib import Path
import os
import pytest

from scripts.rotate_memory_audit import main, rotate_memory_audit_logs


def _touch(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("[]", encoding="utf-8")


def test_rotate_memory_audit_logs_deletes_only_old_daily_json(tmp_path):
    today = datetime.now().date()
    old_day = today - timedelta(days=90)
    recent_day = today - timedelta(days=5)

    old_file = tmp_path / f"{old_day.isoformat()}.json"
    recent_file = tmp_path / f"{recent_day.isoformat()}.json"
    odd_file = tmp_path / "notes.json"
    _touch(old_file)
    _touch(recent_file)
    _touch(odd_file)

    assert rotate_memory_audit_logs(keep_days=60, dry_run=False, audit_dir=str(tmp_path))

    assert not old_file.exists()
    assert recent_file.exists()
    assert odd_file.exists()


def test_rotate_memory_audit_logs_dry_run_keeps_old_files(tmp_path):
    old_day = datetime.now().date() - timedelta(days=90)
    old_file = tmp_path / f"{old_day.isoformat()}.json"
    _touch(old_file)

    assert rotate_memory_audit_logs(keep_days=60, dry_run=True, audit_dir=str(tmp_path))

    assert old_file.exists()


def test_audit_cli_previews_by_default_and_applies_only_explicitly(tmp_path: Path) -> None:
    """Keep old logs until explicit apply while preserving recent and unrelated files."""
    old_day = datetime.now().date() - timedelta(days=90)
    old_file = tmp_path / f"{old_day.isoformat()}.json"
    recent_file = tmp_path / f"{datetime.now().date().isoformat()}.json"
    notes = tmp_path / "notes.json"
    for path in (old_file, recent_file, notes):
        _touch(path)

    assert main(["--audit-dir", str(tmp_path)]) == 0
    assert old_file.exists()
    assert main(["--audit-dir", str(tmp_path), "--apply"]) == 0
    assert not old_file.exists()
    assert recent_file.exists()
    assert notes.exists()


def test_rotation_preserves_noncanonical_date_names(tmp_path: Path) -> None:
    """A parseable date is not enough to identify a logger-created daily file."""
    unrelated = tmp_path / "2020-1-2.json"
    canonical = tmp_path / "2020-01-02.json"
    _touch(unrelated)
    _touch(canonical)
    assert main(["--audit-dir", str(tmp_path), "--apply"]) == 0
    assert unrelated.exists()
    assert not canonical.exists()


def test_rotation_returns_failure_when_directory_metadata_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Preflight permission failures preserve logs and return the CLI failure status."""
    old_file = tmp_path / "2020-01-02.json"
    _touch(old_file)
    original_lstat = Path.lstat

    def denied_lstat(path: Path, *args: object, **kwargs: object) -> os.stat_result:
        if path == tmp_path:
            raise PermissionError("synthetic preflight failure")
        return original_lstat(path, *args, **kwargs)

    monkeypatch.setattr(Path, "lstat", denied_lstat)
    assert main(["--audit-dir", str(tmp_path), "--apply"]) == 1
    assert old_file.exists()


def test_rotation_succeeds_when_another_rotator_removes_the_selected_log(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A concurrent successful removal must not turn this rotation into failure."""
    old_file = tmp_path / "2020-01-02.json"
    _touch(old_file)
    original_unlink = Path.unlink

    def concurrent_unlink(path: Path, *args: object, **kwargs: object) -> None:
        if path == old_file:
            original_unlink(path, missing_ok=True)
        original_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", concurrent_unlink)
    assert main(["--audit-dir", str(tmp_path), "--apply"]) == 0
    assert not old_file.exists()
