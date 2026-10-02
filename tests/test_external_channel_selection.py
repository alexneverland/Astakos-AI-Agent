"""Contract tests for the external messaging channel selector."""

from __future__ import annotations

import pytest


def test_missing_setting_preserves_telegram_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """Existing installations keep Telegram when no channel is configured."""
    monkeypatch.delenv("ASTAKOS_EXTERNAL_CHANNEL", raising=False)

    from core.messaging_channel import resolve_external_channel

    assert resolve_external_channel() == "telegram"


@pytest.mark.parametrize("channel", ["telegram", "matrix"])
def test_supported_channel_is_returned(
    monkeypatch: pytest.MonkeyPatch,
    channel: str,
) -> None:
    """Each supported external channel is selected explicitly."""
    monkeypatch.setenv("ASTAKOS_EXTERNAL_CHANNEL", channel)

    from core.messaging_channel import resolve_external_channel

    assert resolve_external_channel() == channel


def test_channel_value_normalizes_case_and_whitespace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Harmless formatting differences do not create a second channel name."""
    monkeypatch.setenv("ASTAKOS_EXTERNAL_CHANNEL", "  MaTrIx  ")

    from core.messaging_channel import resolve_external_channel

    assert resolve_external_channel() == "matrix"


@pytest.mark.parametrize("value", ["", "   ", "both", "web", "signal"])
def test_configured_invalid_channel_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
    value: str,
) -> None:
    """Blank or unsupported configuration never starts an arbitrary transport."""
    monkeypatch.setenv("ASTAKOS_EXTERNAL_CHANNEL", value)

    from core.messaging_channel import (
        ExternalChannelConfigurationError,
        resolve_external_channel,
    )

    with pytest.raises(
        ExternalChannelConfigurationError,
        match="ASTAKOS_EXTERNAL_CHANNEL",
    ):
        resolve_external_channel()


def test_explicit_value_can_be_validated_without_mutating_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Callers can validate a candidate value before changing runtime config."""
    monkeypatch.setenv("ASTAKOS_EXTERNAL_CHANNEL", "telegram")

    from core.messaging_channel import resolve_external_channel

    assert resolve_external_channel(" matrix ") == "matrix"
    assert resolve_external_channel() == "telegram"


def test_boot_matrix_selection_never_spawns_telegram(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Matrix starts its own entrypoint and never the preserved Telegram one."""
    import boot
    import sys

    spawned: list[list[str]] = []
    process = object()
    monkeypatch.setenv("ASTAKOS_EXTERNAL_CHANNEL", "matrix")
    monkeypatch.setenv("TELEGRAM_TOKEN", "preserved-inactive-token")
    monkeypatch.setattr(
        boot.subprocess,
        "Popen",
        lambda command, **kwargs: spawned.append(command) or process,
    )

    assert boot.start_external_transport() is process
    assert spawned == [[sys.executable, "clients/matrix_bot.py"]]


def test_boot_matrix_child_has_dedicated_windows_signal_group(monkeypatch):
    """Nightly CTRL_BREAK must address the actual child process group."""
    import boot
    calls = []
    monkeypatch.setenv("ASTAKOS_EXTERNAL_CHANNEL", "matrix")
    monkeypatch.setattr(boot.subprocess, "Popen", lambda *a, **k: calls.append(k) or object())
    boot.start_external_transport()
    if boot.os.name == "nt":
        assert calls[0].get("creationflags", 0) & boot.subprocess.CREATE_NEW_PROCESS_GROUP


def test_boot_keeps_web_alive_for_owned_backup_then_adopts_restarted_child(monkeypatch, tmp_path):
    """A planned backup exit is not an external-channel failure."""
    import boot
    import services.matrix_backup_maintenance as maintenance
    api = FakeProcess([None, None, None, 0])
    old = FakeProcess([0])
    old.pid = 42
    new = FakeProcess([None, None, None])
    monkeypatch.setattr(maintenance, "boot_backup_request", lambda pid: {"log_dir": str(tmp_path)})
    held = iter([True, False])
    monkeypatch.setattr(maintenance, "backup_pause_held", lambda: next(held))
    monkeypatch.setattr(boot, "start_external_transport", lambda **kw: new)
    assert boot.supervise_server_processes(api, old, sleep=lambda _: None) == 0
    assert not api.terminated
    assert new.terminated


def test_windows_launcher_full_choice_isolates_both_reloaders() -> None:
    """Choice 1 starts Web and the selected channel in separate consoles."""
    from pathlib import Path

    source = Path("start_astakos.bat").read_text(encoding="utf-8")

    assert ":full" in source
    full_section = source.split(":full", 1)[1].split(":web", 1)[0]
    assert 'start "Astakos Web Server"' in full_section
    assert "uvicorn api.server:server" in full_section
    assert "python run_external.py" in full_section


def test_boot_interrupt_cleans_adopted_child(monkeypatch, tmp_path):
    """Ctrl+C after backup stops the replacement, not only the old Popen."""
    import boot
    import services.matrix_backup_maintenance as maintenance
    api = FakeProcess([None, None, None])
    old = FakeProcess([0])
    old.pid = 42
    new = FakeProcess([None, None])
    monkeypatch.setattr(maintenance, "boot_backup_request", lambda pid: {"log_dir": str(tmp_path)})
    monkeypatch.setattr(maintenance, "backup_pause_held", lambda: False)
    monkeypatch.setattr(boot, "start_external_transport", lambda **kw: new)
    def interrupt(_):
        raise KeyboardInterrupt
    with pytest.raises(KeyboardInterrupt):
        boot.supervise_server_processes(api, old, sleep=interrupt)
    assert new.terminated and api.terminated


def test_matrix_runtime_directories_are_gitignored() -> None:
    """Matrix encryption state and downloaded media cannot be staged accidentally."""
    from pathlib import Path

    ignore_lines = {
        line.strip()
        for line in Path(".gitignore").read_text(encoding="utf-8").splitlines()
    }

    assert "matrix_store/" in ignore_lines
    assert "matrix_media/" in ignore_lines


class FakeProcess:
    def __init__(self, poll_results: list[int | None]) -> None:
        self._poll_results = iter(poll_results)
        self.terminated = False
        self.waited = False

    def poll(self) -> int | None:
        return next(self._poll_results)

    def terminate(self) -> None:
        self.terminated = True

    def wait(self, timeout: int | None = None) -> int:
        del timeout
        self.waited = True
        return 0


def test_server_supervisor_propagates_matrix_startup_failure() -> None:
    """A failed selected transport stops the API instead of going unnoticed."""
    import boot

    api = FakeProcess([None, None])
    matrix = FakeProcess([1])

    assert boot.supervise_server_processes(api, matrix, sleep=lambda _: None) == 1
    assert api.terminated is True
    assert api.waited is True


def test_server_supervisor_stops_transport_when_api_exits() -> None:
    """A normal API exit does not leave an orphan external transport."""
    import boot

    api = FakeProcess([0])
    matrix = FakeProcess([None, None])

    assert boot.supervise_server_processes(api, matrix, sleep=lambda _: None) == 0
    assert matrix.terminated is True
    assert matrix.waited is True
