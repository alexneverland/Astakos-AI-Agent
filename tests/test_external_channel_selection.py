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
    """Preserved Telegram credentials stay inactive when Matrix is selected."""
    import boot

    spawned: list[list[str]] = []
    monkeypatch.setenv("ASTAKOS_EXTERNAL_CHANNEL", "matrix")
    monkeypatch.setenv("TELEGRAM_TOKEN", "preserved-inactive-token")
    monkeypatch.setattr(
        boot.subprocess,
        "Popen",
        lambda command: spawned.append(command) or object(),
    )

    assert boot.start_external_transport() is None
    assert spawned == []


def test_matrix_runtime_directories_are_gitignored() -> None:
    """Matrix encryption state and downloaded media cannot be staged accidentally."""
    from pathlib import Path

    ignore_lines = {
        line.strip()
        for line in Path(".gitignore").read_text(encoding="utf-8").splitlines()
    }

    assert "matrix_store/" in ignore_lines
    assert "matrix_media/" in ignore_lines
