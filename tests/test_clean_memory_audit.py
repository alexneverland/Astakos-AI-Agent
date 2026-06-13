from datetime import datetime, timedelta

from clean import rotate_memory_audit_logs


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
