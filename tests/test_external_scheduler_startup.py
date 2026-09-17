"""Offline contracts for scheduler startup independent of channel polling."""

from __future__ import annotations

from dataclasses import dataclass

import pytest


@dataclass
class FakeThread:
    target: object
    daemon: bool
    started: bool = False

    def start(self) -> None:
        self.started = True


class FakeScheduler:
    def run(self) -> None:
        return None


def test_external_background_runtime_starts_once_for_matrix(monkeypatch) -> None:
    import clients.telegram_bot as bot

    threads: list[FakeThread] = []
    initialized: list[bool] = []
    cleanup_channels: list[str] = []
    summary_channels: list[str] = []
    scheduler = FakeScheduler()

    bot._reset_external_background_runtime_for_tests()
    monkeypatch.setattr(
        bot.threading,
        "Thread",
        lambda *, target, daemon: threads.append(FakeThread(target, daemon))
        or threads[-1],
    )
    monkeypatch.setattr(
        bot,
        "_initialize_external_background_state",
        lambda: initialized.append(True),
    )
    monkeypatch.setattr(bot, "_build_external_scheduler", lambda: scheduler)
    monkeypatch.setattr(
        bot,
        "startup_stale_cleanup",
        lambda *, channel: cleanup_channels.append(channel),
    )
    monkeypatch.setattr(
        bot,
        "_maybe_trigger_auto_session_summary",
        lambda *, channel: summary_channels.append(channel),
    )

    try:
        first = bot.start_external_background_runtime("matrix")
        second = bot.start_external_background_runtime("matrix")
    finally:
        bot._reset_external_background_runtime_for_tests()

    assert first is scheduler
    assert second is scheduler
    assert initialized == [True]
    assert cleanup_channels == ["matrix"]
    assert summary_channels == ["matrix"]
    assert len(threads) == 4
    assert all(thread.started and thread.daemon for thread in threads)


def test_external_background_runtime_rejects_channel_change_in_same_process(
    monkeypatch,
) -> None:
    import clients.telegram_bot as bot

    bot._reset_external_background_runtime_for_tests()
    monkeypatch.setattr(bot.threading, "Thread", lambda **kwargs: FakeThread(**kwargs))
    monkeypatch.setattr(bot, "_initialize_external_background_state", lambda: None)
    monkeypatch.setattr(bot, "_build_external_scheduler", FakeScheduler)
    monkeypatch.setattr(bot, "startup_stale_cleanup", lambda channel: None)
    monkeypatch.setattr(bot, "_maybe_trigger_auto_session_summary", lambda channel: None)

    try:
        bot.start_external_background_runtime("telegram")
        with pytest.raises(RuntimeError, match="already started"):
            bot.start_external_background_runtime("matrix")
    finally:
        bot._reset_external_background_runtime_for_tests()


@pytest.mark.parametrize("channel", ["", "web", "email"])
def test_external_background_runtime_rejects_invalid_channel(channel) -> None:
    import clients.telegram_bot as bot

    bot._reset_external_background_runtime_for_tests()
    with pytest.raises(ValueError, match="telegram.*matrix"):
        bot.start_external_background_runtime(channel)
