"""Tests for selecting one isolated external-channel watchdog."""

from __future__ import annotations

import pytest


@pytest.mark.parametrize(
    ("channel", "module_name"),
    [("matrix", "run_matrix"), ("telegram", "run_telegram")],
)
def test_selected_watchdog_module_matches_active_channel(
    channel: str,
    module_name: str,
) -> None:
    """The launcher imports exactly one watcher for the selected channel."""
    from run_external import selected_watchdog_module

    assert selected_watchdog_module(channel) == module_name


def test_selected_watchdog_module_rejects_unsupported_channel() -> None:
    """An invalid channel never falls back to a different transport."""
    from core.messaging_channel import ExternalChannelConfigurationError
    from run_external import selected_watchdog_module

    with pytest.raises(ExternalChannelConfigurationError):
        selected_watchdog_module("both")
