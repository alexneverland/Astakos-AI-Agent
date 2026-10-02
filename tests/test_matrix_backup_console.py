"""Local subprocess fixtures: recovery output remains visible and privately logged."""

import sys
import os
import pytest


@pytest.mark.skipif(os.name != "nt", reason="Real Windows venv shim/worker lifecycle")
@pytest.mark.parametrize("recovery", [False, True])
def test_boot_cleanup_stops_real_venv_worker(tmp_path, monkeypatch, recovery):
    """Stopping the boot Popen must also stop its actual venv interpreter worker."""
    import ctypes
    import subprocess
    import time
    import boot
    from pathlib import Path
    ready, stopped = tmp_path / "worker-pid", tmp_path / "stopped"
    program = (
        "import os,signal,time; from pathlib import Path; "
        "signal.signal(signal.SIGBREAK, lambda *a: (Path(" + repr(str(stopped)) + ").touch(), exit(0))); "
        "Path(" + repr(str(ready)) + ").write_text(str(os.getpid()))\n"
        "for _ in range(1200): time.sleep(0.05)"
    )
    real_popen = subprocess.Popen
    startup = subprocess.STARTUPINFO()
    startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startup.wShowWindow = 0
    # An independent fixture host keeps the console alive like the real boot
    # parent; otherwise destroying the shim's only console can mask the orphan.
    host_ready = tmp_path / "console-ready"
    host_program = "import time; from pathlib import Path; Path(" + repr(str(host_ready)) + ").touch()\nfor _ in range(1200): time.sleep(0.05)"
    host = real_popen([sys._base_executable, "-c", host_program],
                      creationflags=subprocess.CREATE_NEW_CONSOLE, startupinfo=startup)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    def launch(command, **kwargs):
        if len(command) < 2 or command[1] != "clients/matrix_bot.py":
            return real_popen(command, **kwargs)
        return real_popen([str(Path(boot.__file__).parent / "venv/Scripts/python.exe"), "-c", program],
                          **kwargs)
    monkeypatch.setenv("ASTAKOS_EXTERNAL_CHANNEL", "matrix")
    monkeypatch.setattr(boot.subprocess, "Popen", launch)
    process = None
    kernel.OpenProcess.restype = ctypes.c_void_p
    kernel.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
    kernel.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    kernel.TerminateProcess.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    worker_handle = None
    try:
        deadline = time.monotonic() + 10
        while not host_ready.exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        assert host_ready.exists()
        kernel.FreeConsole()
        assert kernel.AttachConsole(host.pid)
        process = boot.start_external_transport(log_dir=tmp_path / "runtime" if recovery else None)
        deadline = time.monotonic() + 10
        while not ready.exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        assert ready.exists()
        worker_pid = int(ready.read_text())
        assert worker_pid != process.pid, "Fixture must exercise the actual venv shim"
        worker_handle = kernel.OpenProcess(0x100001, False, worker_pid)
        assert worker_handle
        boot._terminate_child(process)
        assert kernel.WaitForSingleObject(worker_handle, 1000) == 0
        assert stopped.exists(), "The actual worker must run its graceful handler"
    finally:
        kernel.FreeConsole()
        if worker_handle:
            if kernel.WaitForSingleObject(worker_handle, 0) != 0:
                kernel.TerminateProcess(worker_handle, 1)
                kernel.WaitForSingleObject(worker_handle, 5000)
            kernel.CloseHandle(worker_handle)
        if process is not None and process.poll() is None:
            process.terminate()
            process.wait(timeout=5)
        host.terminate()
        host.wait(timeout=5)


def test_recovery_output_reaches_console_and_logs(tmp_path, capsys):
    """Run a real disposable child, not a mocked startup-message intermediate."""
    from services.matrix_backup_maintenance import start_logged_matrix_process, drain_matrix_output
    child = start_logged_matrix_process(
        [sys.executable, "-c", "import sys; print('visible startup'); print('visible error', file=sys.stderr)"],
        log_dir=tmp_path / "runtime",
    )
    assert child.wait(timeout=10) == 0
    drain_matrix_output(child)
    captured = capsys.readouterr()
    assert "visible startup" in captured.out
    assert "visible error" in captured.err
    assert "visible startup" in (tmp_path / "runtime/nightly-matrix.out.log").read_text()
    assert "visible error" in (tmp_path / "runtime/nightly-matrix.err.log").read_text()
