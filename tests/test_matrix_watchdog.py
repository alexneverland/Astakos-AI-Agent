"""Offline tests for the Matrix development watchdog."""

from __future__ import annotations

import os
import signal


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
