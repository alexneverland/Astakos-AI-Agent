"""Offline tests for the Matrix development watchdog."""

from __future__ import annotations

import os
import signal


def test_watchdog_backup_pause_preserves_parent_and_adopts_child(monkeypatch, tmp_path):
    """Planned stop waits for capture then restarts under the same watchdog."""
    import run_matrix
    from services import matrix_backup_maintenance as maintenance
    from types import SimpleNamespace
    request = {"log_dir": str(tmp_path), "nonce": "a" * 32}
    old = SimpleNamespace(pid=42)
    new = object()
    monkeypatch.setattr(maintenance, "boot_backup_request", lambda pid: request if pid == 42 else None)
    acknowledged = []
    monkeypatch.setattr(maintenance, "acknowledge_watchdog_pause", lambda req: acknowledged.append(req))
    held = iter([True, False])
    monkeypatch.setattr(maintenance, "backup_pause_held", lambda: next(held))
    monkeypatch.setattr(run_matrix.time, "sleep", lambda _: None)
    monkeypatch.setattr(run_matrix, "_start_process", lambda **kw: new if kw["log_dir"] == tmp_path else None)
    assert run_matrix.resume_after_backup(old) is new
    assert acknowledged == [request]


def test_watchdog_unplanned_exit_is_not_restarted(monkeypatch):
    """Normal startup failure stays a failure, not an unconditional reboot."""
    import run_matrix
    from services import matrix_backup_maintenance as maintenance
    from types import SimpleNamespace
    monkeypatch.setattr(maintenance, "boot_backup_request", lambda pid: None)
    monkeypatch.setattr(run_matrix, "_start_process", lambda **kw: (_ for _ in ()).throw(AssertionError()))
    assert run_matrix.resume_after_backup(SimpleNamespace(pid=42)) is None


def test_watchdog_ctrl_c_stops_replacement(monkeypatch):
    """Exercise the run loop's final cleanup after adopting a backup restart."""
    import run_matrix
    from types import SimpleNamespace
    old = SimpleNamespace(poll=lambda: 0)
    new = SimpleNamespace(poll=lambda: None)
    stopped = []
    monkeypatch.setattr(run_matrix, "_acquire_single_instance_lock", lambda: None)
    monkeypatch.setattr(run_matrix, "_start_process", lambda: old)
    monkeypatch.setattr(run_matrix, "resume_after_backup", lambda process: new)
    monkeypatch.setattr(run_matrix, "stop_process", lambda process: stopped.append(process))
    def events(*args, **kwargs):
        yield set()
        raise KeyboardInterrupt
    monkeypatch.setattr(run_matrix, "watch", events)
    assert run_matrix.run() == 0
    assert stopped == [new]


def test_matrix_watchdog_restarts_only_for_runtime_source_changes() -> None:
    """Generated files never restart the encrypted transport."""
    from run_matrix import is_reloadable_change

    assert is_reloadable_change("clients/matrix_bot.py") is True
    assert is_reloadable_change("core/agents.py") is True
    assert is_reloadable_change("prompts.md") is True
    assert is_reloadable_change("runtime_snapshot.json") is False
    assert is_reloadable_change("matrix_store/matrix_store.db") is False


def test_matrix_watchdog_stops_child_gracefully_before_restart() -> None:
    """A restart gives Matrix time to drain memory queues and close stores."""
    from run_matrix import stop_process

    class FakeProcess:
        def __init__(self) -> None:
            self.signals: list[int] = []
            self.wait_timeouts: list[float] = []

        def poll(self) -> None:
            return None

        def send_signal(self, signal_number: int) -> None:
            self.signals.append(signal_number)

        def wait(self, timeout: float | None = None) -> int:
            assert timeout is not None
            self.wait_timeouts.append(timeout)
            return 0

    process = FakeProcess()

    stop_process(process)

    expected_signal = (
        signal.CTRL_BREAK_EVENT if os.name == "nt" else signal.SIGINT
    )
    assert process.signals == [expected_signal]
    assert process.wait_timeouts == [120]
