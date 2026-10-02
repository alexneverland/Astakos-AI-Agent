"""Offline coordinator tests: no Docker, providers or live stores."""

from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import nightly_matrix_backup as nightly
from services.matrix_backup import MatrixBackupError


class Runtime:
    """Synthetic runtime with observable stopped/running state."""

    def __init__(self, running=True):
        self.running = running
        self.recovered = False

    def preflight(self):
        return self.running

    def stop(self, previous):
        self.running = False

    def restore(self, previous):
        self.running = previous
        self.recovered = True


@pytest.fixture
def options(tmp_path, monkeypatch):
    monkeypatch.setattr(nightly, "secure_directory", lambda p: p.mkdir(parents=True, exist_ok=True))
    return SimpleNamespace(work_dir=tmp_path / "private", drive_folder="fixture-folder")


def test_upload_only_after_runtime_recovered(options):
    runtime = Runtime()
    def capture():
        assert not runtime.running
        return SimpleNamespace(artifact=Path("fixture.age"), sha256="fixture-hash")
    def upload(path, folder, digest):
        assert runtime.running and runtime.recovered
        return "fixture-id"
    result = nightly.run_nightly(options, runtime, capture=capture, upload=upload)
    assert result["status"] == "uploaded"
    assert (options.work_dir / "last-run.json").exists()


def test_capture_failure_restores_runtime_and_records_failure(options):
    runtime = Runtime()
    def fail():
        raise OSError("SECRET provider diagnostic")
    with pytest.raises(MatrixBackupError):
        nightly.run_nightly(options, runtime, capture=fail,
                            upload=lambda *a: pytest.fail("No incomplete upload"))
    assert runtime.running and runtime.recovered
    status = (options.work_dir / "last-run.json").read_text()
    assert "failed" in status and "SECRET" not in status


def test_stopped_runtime_stays_stopped(options):
    runtime = Runtime(False)
    nightly.run_nightly(options, runtime,
                        capture=lambda: SimpleNamespace(artifact=Path("fixture.age"), sha256="hash"),
                        upload=lambda *a: "fixture-id")
    assert not runtime.running


def test_stop_timeout_attempts_recovery_but_never_uploads(options):
    runtime = Runtime()
    def fail(previous):
        runtime.running = False
        raise MatrixBackupError("graceful_stop_timeout")
    runtime.stop = fail
    with pytest.raises(MatrixBackupError):
        nightly.run_nightly(options, runtime, capture=lambda: pytest.fail("No capture"),
                            upload=lambda *a: pytest.fail("No upload"))
    assert runtime.running and runtime.recovered


def test_failed_restart_prevents_upload(options):
    runtime = Runtime()
    def fail(previous):
        raise MatrixBackupError("restart_failed")
    runtime.restore = fail
    with pytest.raises(MatrixBackupError):
        nightly.run_nightly(options, runtime,
                            capture=lambda: SimpleNamespace(artifact=Path("fixture.age"), sha256="hash"),
                            upload=lambda *a: pytest.fail("No upload before recovery"))


def test_upload_failure_is_not_success_but_runtime_is_running(options):
    runtime = Runtime()
    def fail(*args):
        raise OSError("SECRET")
    with pytest.raises(MatrixBackupError):
        nightly.run_nightly(options, runtime,
                            capture=lambda: SimpleNamespace(artifact=Path("fixture.age"), sha256="hash"),
                            upload=fail)
    assert runtime.running
    assert "SECRET" not in (options.work_dir / "last-run.json").read_text()


@pytest.mark.parametrize("command,entry", [
    ('"C:\\astakos_v2\\venv\\Scripts\\python.exe" clients/matrix_bot.py', "clients/matrix_bot.py"),
    ('python.exe -u run_external.py', "run_external.py"),
    ('python.exe arbitrary.py --label run_external.py-backup', None),
    ('python.exe C:/other/clients/matrix_bot.py', None),
])
def test_entrypoint_matching_is_exact(command, entry):
    assert nightly.process_entry(command) == entry


def test_runtime_stop_uses_only_discovered_bot_group(tmp_path, monkeypatch):
    runtime = nightly.WindowsRuntime(tmp_path)
    signaled = []
    monkeypatch.setattr(runtime, "signal_bot", lambda pid: signaled.append(pid))
    monkeypatch.setattr(nightly, "assert_bot_stopped", lambda: None)
    runtime.stop({"bot_pid": 42, "watchdog": "run_external.py"})
    assert signaled == [42]


def test_runtime_without_bot_does_not_signal(tmp_path, monkeypatch):
    runtime = nightly.WindowsRuntime(tmp_path)
    monkeypatch.setattr(runtime, "signal_bot", lambda pid: pytest.fail("No signal"))
    monkeypatch.setattr(nightly, "assert_bot_stopped", lambda: None)
    runtime.stop({"bot_pid": None, "watchdog": None})


def test_existing_backup_busy_prevents_provider_or_stop(tmp_path, monkeypatch):
    runtime = nightly.WindowsRuntime(tmp_path)
    monkeypatch.setattr(runtime, "powershell", lambda command: "Running")
    with pytest.raises(MatrixBackupError, match="existing_backup_running"):
        runtime.preflight()


def test_lock_prevents_second_runtime_pause(options):
    from filelock import FileLock
    options.work_dir.mkdir()
    with FileLock(str(options.work_dir / "nightly.lock")):
        with pytest.raises(MatrixBackupError, match="nightly_already_running"):
            nightly.run_nightly(options, Runtime(), capture=lambda: pytest.fail("No second capture"))


def test_discovery_ignores_other_python_and_rejects_duplicate_launchers(tmp_path, monkeypatch):
    import json
    runtime = nightly.WindowsRuntime(tmp_path)
    records = [{"ExecutablePath": str(nightly.ROOT / "venv/Scripts/python.exe"),
                "CommandLine": 'python.exe clients/matrix_bot.py', "ProcessId": 42},
               {"ExecutablePath": "C:/other/python.exe",
                "CommandLine": 'python.exe clients/matrix_bot.py', "ProcessId": 99}]
    monkeypatch.setattr(runtime, "powershell", lambda command: json.dumps(records))
    assert runtime.discover()["bot_pid"] == 42
    records.append(dict(records[0], ProcessId=43))
    with pytest.raises(MatrixBackupError, match="ambiguous_matrix_runtime"):
        runtime.discover()


def test_stop_timeout_does_not_force_terminate(tmp_path, monkeypatch):
    runtime = nightly.WindowsRuntime(tmp_path)
    clock = iter([0, 200])
    monkeypatch.setattr(nightly.time, "monotonic", lambda: next(clock))
    monkeypatch.setattr(runtime, "signal_bot", lambda pid: None)
    def busy():
        raise MatrixBackupError("matrix_bot_or_watchdog_running")
    monkeypatch.setattr(nightly, "assert_bot_stopped", busy)
    with pytest.raises(MatrixBackupError, match="graceful_stop_timeout"):
        runtime.stop({"bot_pid": 42, "watchdog": "run_external.py"})


def test_restore_does_not_start_duplicate_or_previously_stopped_bot(tmp_path, monkeypatch):
    runtime = nightly.WindowsRuntime(tmp_path)
    monkeypatch.setattr(nightly.subprocess, "Popen", lambda *a, **kw: pytest.fail("No duplicate launch"))
    runtime.restore({"bot_pid": None, "watchdog": None})
    monkeypatch.setattr(runtime, "discover", lambda: {"bot_pid": 42, "watchdog": "run_external.py"})
    runtime.restore({"bot_pid": 42, "watchdog": "run_external.py"})
