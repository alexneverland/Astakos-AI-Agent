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


@pytest.mark.parametrize("stage", ["preflight", "stop", "capture", "restore", "upload"])
def test_failure_stage_is_durable_and_diagnostics_are_bounded(options, stage):
    """Keep actionable stage evidence without persisting arbitrary error text."""
    import json
    runtime = Runtime()
    def fail(*args):
        raise OSError("SECRET provider token and private path")
    capture = lambda: SimpleNamespace(artifact=Path("fixture.age"), sha256="hash")
    upload = lambda *args: "fixture-id"
    if stage == "capture":
        capture = fail
    elif stage == "upload":
        upload = fail
    else:
        setattr(runtime, stage, fail)
    with pytest.raises(MatrixBackupError):
        nightly.run_nightly(options, runtime, capture=capture, upload=upload)
    status = json.loads((options.work_dir / "last-run.json").read_text())
    assert status["failed_stage"] == stage
    assert status["error_code"] == "os_error"
    assert "SECRET" not in json.dumps(status)
    assert "finished_at" in status


def test_recovery_failure_does_not_erase_original_failure(options):
    """Report both capture failure and recovery failure rather than masking one."""
    import json
    runtime = Runtime()
    def capture():
        raise OSError("SECRET capture")
    def restore(previous):
        raise MatrixBackupError("matrix_restart_not_verified")
    runtime.restore = restore
    with pytest.raises(MatrixBackupError):
        nightly.run_nightly(options, runtime, capture=capture,
                            upload=lambda *args: pytest.fail("No upload"))
    status = json.loads((options.work_dir / "last-run.json").read_text())
    assert status["failed_stage"] == "capture"
    assert status["recovery_error_code"] == "matrix_restart_not_verified"
    assert "SECRET" not in json.dumps(status)


def test_restore_is_not_skipped_when_stage_status_write_fails(options, monkeypatch):
    """An instrumentation failure must never bypass runtime recovery."""
    runtime = Runtime()
    original_write = nightly.write_status
    def write(work, status):
        if status.get("stage") == "restore":
            raise OSError("fixture unavailable status sink")
        original_write(work, status)
    monkeypatch.setattr(nightly, "write_status", write)
    nightly.run_nightly(options, runtime,
                        capture=lambda: SimpleNamespace(artifact=Path("fixture.age"), sha256="hash"),
                        upload=lambda *args: "fixture-id")
    assert runtime.running and runtime.recovered


@pytest.mark.skipif(nightly.os.name != "nt", reason="Native Windows pythonw handles")
@pytest.mark.parametrize("boundary", ["powershell", "quiescence", "docker", "dump", "permissions"])
def test_headless_scheduler_handles_do_not_break_subprocess_checks(tmp_path, boundary):
    """Reproduce invalid stdin after console detach in a disposable pythonw process."""
    import json
    import subprocess
    import sys
    work = tmp_path / "diagnostic"
    work.mkdir()
    program = (
        "import ctypes,subprocess; from pathlib import Path; "
        "from scripts.nightly_matrix_backup import WindowsRuntime,write_status; "
        "from services import matrix_snapshot as snapshot; "
        "from services import matrix_backup_maintenance as maintenance; "
        "kernel=ctypes.WinDLL('kernel32',use_last_error=True); kernel.FreeConsole(); "
        "kernel.SetStdHandle(-10,ctypes.c_void_p(-1)); "
        "actual_run=subprocess.run; "
        "subprocess.run=lambda command,**kwargs: actual_run("
        "['powershell.exe','-NoProfile','-NonInteractive','-Command','exit 0'],**kwargs); "
        "maintenance.paused_watchdog_ids=lambda: []; "
        + {
            "powershell": "WindowsRuntime.powershell('exit 0'); ",
            "quiescence": "snapshot.assert_bot_stopped(); ",
            "docker": "snapshot.docker_command(['inspect','fixture'],subprocess.run); ",
            "dump": "snapshot.docker_command(['exec','fixture'],subprocess.run,output=Path(" + repr(str(work / 'dump')) + ")); ",
            "permissions": "from services.matrix_backup import secure_directory; secure_directory(Path(" + repr(str(work / 'private')) + ")); ",
        }[boundary]
        + "write_status(Path(" + repr(str(work)) + "),{'outcome':'success'})"
    )
    result = subprocess.run([str(Path(sys.executable).with_name("pythonw.exe")), "-c", program],
                            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL, timeout=20,
                            creationflags=subprocess.CREATE_NO_WINDOW)
    assert result.returncode == 0
    assert json.loads((work / "last-run.json").read_text()) == {"outcome": "success"}


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


def test_discovery_correlates_boot_parent_only_in_same_checkout(tmp_path, monkeypatch):
    """Only the exact parent launcher may own the backup restart."""
    import json
    runtime = nightly.WindowsRuntime(tmp_path)
    python = str(nightly.ROOT / "venv/Scripts/python.exe")
    records = [{"ExecutablePath": python, "CommandLine": "python.exe clients/matrix_bot.py",
                "ProcessId": 42, "ParentProcessId": 41},
               {"ExecutablePath": python, "CommandLine": "python.exe boot.py --server", "ProcessId": 41}]
    monkeypatch.setattr(runtime, "powershell", lambda command: json.dumps(records))
    assert runtime.discover()["boot_pid"] == 41
    records[1]["CommandLine"] = "python.exe C:/other/boot.py --server"
    assert runtime.discover()["boot_pid"] is None


def test_boot_restore_uses_parent_and_fresh_startup_evidence(tmp_path, monkeypatch):
    """Boot owns restart; the coordinator must never launch a second bot."""
    runtime = nightly.WindowsRuntime(tmp_path)
    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir()
    class Pause:
        resumed = False
        cleared = False
        def resume(self):
            self.resumed = True
            (runtime_dir / "nightly-matrix.out.log").write_text("Encrypted Element channel started")
        def clear(self):
            self.cleared = True
    pause = Pause()
    runtime.boot_pause = pause
    states = iter([{"bot_pid": None}, {"bot_pid": 43}])
    monkeypatch.setattr(runtime, "discover", lambda: next(states))
    monkeypatch.setattr(nightly.subprocess, "Popen", lambda *a, **k: pytest.fail("Parent owns restart"))
    runtime.restore({"bot_pid": 42, "watchdog": None, "boot_pid": 41})
    assert pause.resumed and pause.cleared


def test_boot_pause_rejects_unrelated_pids_and_cleans_owned_request(tmp_path, monkeypatch):
    """Real file-lock handoff is correlated and does not leave a stale request."""
    import os
    from services import matrix_backup_maintenance as maintenance
    monkeypatch.setattr(maintenance, "ROOT", tmp_path)
    monkeypatch.setattr(maintenance, "REQUEST_PATH", tmp_path / "request.json")
    monkeypatch.setattr(maintenance, "LOCK_PATH", tmp_path / "pause.lock")
    pause = maintenance.BootBackupPause(os.getpid(), 42, tmp_path / "runtime")
    pause.acquire()
    assert maintenance.backup_pause_held()
    assert maintenance.boot_backup_request(42) is not None
    assert maintenance.boot_backup_request(43) is None
    pause.resume()
    assert not maintenance.backup_pause_held()
    # Parent may see the child's exit only after pause release; correlation survives.
    assert maintenance.boot_backup_request(42) is not None
    pause.clear()
    assert maintenance.boot_backup_request(42) is None


def test_watchdog_quiescence_requires_live_lock_and_matching_ack(tmp_path, monkeypatch):
    """Only an acknowledged idle watchdog can be exempted from the cold guard."""
    import os
    import json
    from services import matrix_backup_maintenance as maintenance
    monkeypatch.setattr(maintenance, "ROOT", tmp_path)
    monkeypatch.setattr(maintenance, "REQUEST_PATH", tmp_path / "request.json")
    monkeypatch.setattr(maintenance, "ACK_PATH", tmp_path / "ack.json")
    monkeypatch.setattr(maintenance, "LOCK_PATH", tmp_path / "pause.lock")
    pause = maintenance.BootBackupPause(os.getpid(), 42, tmp_path / "runtime", watchdog_pids=[os.getpid()])
    pause.acquire()
    try:
        assert maintenance.paused_watchdog_ids() == []
        maintenance.acknowledge_watchdog_pause(pause.data)
        assert maintenance.paused_watchdog_ids() == [os.getpid()]
        ack = json.loads(maintenance.ACK_PATH.read_text())
        ack["nonce"] = "wrong"
        maintenance.ACK_PATH.write_text(json.dumps(ack))
        assert maintenance.paused_watchdog_ids() == []
        maintenance.acknowledge_watchdog_pause(pause.data)
        pause.resume()
        assert maintenance.paused_watchdog_ids() == []
    finally:
        pause.clear()


def test_discovery_correlates_venv_watchdog_worker_chain(tmp_path, monkeypatch):
    """Windows venv shim and worker are one watchdog, not two launchers."""
    import json
    runtime = nightly.WindowsRuntime(tmp_path)
    python = str(nightly.ROOT / "venv/Scripts/python.exe")
    records = [
        {"ExecutablePath": python, "CommandLine": "python.exe -u run_external.py", "ProcessId": 40},
        {"ExecutablePath": "C:/Python/python.exe", "CommandLine": "python.exe -u run_external.py",
         "ProcessId": 41, "ParentProcessId": 40},
        {"ExecutablePath": python, "CommandLine": "python.exe clients/matrix_bot.py",
         "ProcessId": 42, "ParentProcessId": 41},
    ]
    monkeypatch.setattr(runtime, "powershell", lambda command: json.dumps(records))
    state = runtime.discover()
    assert state["watchdog_pid"] == 41
    assert state["watchdog_pids"] == [41, 40]
    records[1]["ParentProcessId"] = 999
    assert runtime.discover()["watchdog_pid"] is None


def test_watchdog_restore_uses_existing_parent_not_hidden_launcher(tmp_path, monkeypatch):
    """Coordinator releases its pause; the original watchdog owns recovery."""
    runtime = nightly.WindowsRuntime(tmp_path)
    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir()
    class Pause:
        cleared = False
        def resume(self):
            (runtime_dir / "nightly-matrix.out.log").write_text("Encrypted Element channel started")
        def clear(self):
            self.cleared = True
    pause = Pause()
    runtime.boot_pause = pause
    states = iter([{"bot_pid": None}, {"bot_pid": 43, "watchdog_pid": 41}])
    monkeypatch.setattr(runtime, "discover", lambda: next(states))
    monkeypatch.setattr(nightly.subprocess, "Popen", lambda *a, **k: pytest.fail("No hidden recovery"))
    runtime.restore({"bot_pid": 42, "watchdog": "run_external.py", "watchdog_pid": 41})
    assert pause.cleared


def test_unowned_recovery_refuses_hidden_fallback(tmp_path, monkeypatch):
    """Never silently replace a vanished interactive launcher."""
    runtime = nightly.WindowsRuntime(tmp_path)
    monkeypatch.setattr(runtime, "discover", lambda: {"bot_pid": None, "watchdog": None})
    monkeypatch.setattr(nightly.subprocess, "Popen", lambda *a, **k: pytest.fail("No hidden fallback"))
    with pytest.raises(MatrixBackupError, match="visible_matrix_parent_required"):
        runtime.restore({"bot_pid": 42, "watchdog": None})


def test_boot_restore_timeout_releases_pause_without_spawning(tmp_path, monkeypatch):
    """A missing parent cannot leave the capture lock held forever."""
    runtime = nightly.WindowsRuntime(tmp_path)
    class Pause:
        cleared = False
        def resume(self):
            pass
        def clear(self):
            self.cleared = True
    pause = Pause()
    runtime.boot_pause = pause
    monkeypatch.setattr(runtime, "discover", lambda: {"bot_pid": None})
    clock = iter([0, 121])
    monkeypatch.setattr(nightly.time, "monotonic", lambda: next(clock))
    monkeypatch.setattr(nightly.subprocess, "Popen", lambda *a, **k: pytest.fail("No detached bot"))
    with pytest.raises(MatrixBackupError, match="matrix_restart_not_verified"):
        runtime.restore({"bot_pid": 42, "watchdog": None, "boot_pid": 41})
    assert pause.cleared and runtime.boot_pause is None


@pytest.mark.skipif(nightly.os.name != "nt", reason="Native Windows CTRL_BREAK integration")
def test_boot_process_group_receives_native_ctrl_break(tmp_path, monkeypatch):
    """Signal only a disposable local child, never the real Matrix runtime."""
    import boot
    import subprocess
    import sys
    import time
    ready, stopped = tmp_path / "ready", tmp_path / "stopped"
    program = (
        "import signal,time; from pathlib import Path; "
        "signal.signal(signal.SIGBREAK, lambda *a: (Path(" + repr(str(stopped)) + ").touch(), exit(0))); "
        "Path(" + repr(str(ready)) + ").touch()\n"
        "for _ in range(400): time.sleep(0.05)"
    )
    actual_popen = subprocess.Popen
    def launch(command, **kwargs):
        startup = subprocess.STARTUPINFO()
        startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startup.wShowWindow = 0
        kwargs["creationflags"] |= subprocess.CREATE_NEW_CONSOLE
        return actual_popen([sys.executable, "-c", program], startupinfo=startup,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **kwargs)
    monkeypatch.setenv("ASTAKOS_EXTERNAL_CHANNEL", "matrix")
    monkeypatch.setattr(boot.subprocess, "Popen", launch)
    process = boot.start_external_transport()
    try:
        deadline = time.monotonic() + 10
        while not ready.exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        assert ready.exists()
        nightly.WindowsRuntime.signal_bot(process.pid)
        process.wait(timeout=10)
        assert stopped.exists()
    finally:
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=5)
