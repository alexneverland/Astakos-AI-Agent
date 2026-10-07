"""Offline contracts for scheduler startup independent of channel polling."""

from __future__ import annotations

from dataclasses import dataclass

import pytest


@dataclass
class FakeThread:
    target: object
    daemon: bool
    args: tuple = ()
    started: bool = False

    def start(self) -> None:
        self.started = True


class FakeScheduler:
    def run(self) -> None:
        return None


def test_routine_tick_serializes_the_entire_dispatch_not_only_elapsed_calculation(monkeypatch):
    """Answer wakeups cannot enter dispatch while the periodic tick is in inference."""
    import threading
    from clients import telegram_bot as bot
    entered, release = threading.Event(), threading.Event()
    calls = []
    def maintenance(now):
        calls.append(now)
        if len(calls) == 1:
            entered.set()
            assert release.wait(5)
        return True
    monkeypatch.setattr(bot, "_dated_routine_feedback_tick", maintenance)
    monkeypatch.setattr(bot, "is_proactive_muted", lambda: True)
    thread = threading.Thread(target=bot.job_check_routines)
    thread.start()
    try:
        assert entered.wait(5)
        bot.job_check_routines()
        assert len(calls) == 1
    finally:
        release.set()
        thread.join(5)
    assert not thread.is_alive()


@pytest.mark.parametrize("channel", ["matrix", "telegram"])
def test_existing_routine_tick_runs_injected_maintenance_before_quiet_gate(monkeypatch, channel):
    """Quiet/muted hours stop sends, not confirmed recording or day-close work."""
    import clients.telegram_bot as bot
    events = []
    monkeypatch.setattr(bot, "_external_background_runtime_channel", channel)
    monkeypatch.setattr(bot, "pending_routine_confirmations", {})
    def maintenance(at):
        assert at.tzinfo is not None
        events.append("maintenance")
        return True
    monkeypatch.setattr(bot, "_dated_routine_feedback_tick", maintenance)
    monkeypatch.setattr(bot, "is_proactive_muted", lambda: events.append("muted") or False)
    monkeypatch.setattr(bot, "is_quiet_hours", lambda: events.append("quiet") or True)
    monkeypatch.setattr(bot, "_active_routine_pause_until", lambda: "paused")
    monkeypatch.setattr(bot, "_log_vacation_routine_skip", lambda at: None)
    bot.job_check_routines()
    assert events == ["maintenance", "muted", "quiet"]


@pytest.mark.parametrize("outcome", [False, None, "raises"])
def test_failed_tick_maintenance_never_falls_through_to_dispatch(monkeypatch, outcome):
    """Uncertain ledger readiness cannot authorize normal reminders."""
    import clients.telegram_bot as bot
    def maintenance(at):
        if outcome == "raises":
            raise OSError("unavailable")
        return outcome
    monkeypatch.setattr(bot, "_dated_routine_feedback_tick", maintenance)
    monkeypatch.setattr(bot, "is_proactive_muted", lambda: pytest.fail("dispatch after failed maintenance"))
    bot.job_check_routines()


def test_default_tick_does_not_open_dated_storage(monkeypatch):
    """An unconfigured callback is completely inactive, preserving legacy behavior."""
    import clients.telegram_bot as bot
    from memory.routine_feedback import RoutineFeedbackStore
    monkeypatch.setattr(bot, "_dated_routine_feedback_tick", None)
    monkeypatch.setattr(RoutineFeedbackStore, "initialize", lambda self: pytest.fail("implicit migration"))
    monkeypatch.setattr(bot, "pending_routine_confirmations", {})
    monkeypatch.setattr(bot, "is_proactive_muted", lambda: True)
    bot.job_check_routines()


def test_external_scheduler_registers_queued_matrix_approval_delivery(monkeypatch) -> None:
    """The active external runtime regularly drains Web-origin approvals."""
    import clients.telegram_bot as bot

    class CapturingScheduler:
        def __init__(self) -> None:
            self.jobs: dict[str, tuple[object, int]] = {}

        def register(self, func, interval_seconds: int, name: str, verbose: bool) -> None:
            self.jobs[name] = (func, interval_seconds)

    monkeypatch.setattr(bot, "AstakosScheduler", CapturingScheduler)
    scheduler = bot._build_external_scheduler()

    assert scheduler.jobs["matrix_approvals"][1] == 5
    assert scheduler.jobs["matrix_approvals"][0].__name__ == "drain_queued_matrix_approvals"


def test_external_background_runtime_starts_once_for_matrix(monkeypatch) -> None:
    import clients.telegram_bot as bot

    threads: list[FakeThread] = []
    initialized: list[bool] = []
    cleanup_channels: list[str] = []
    summary_channels: list[str] = []
    missed_checks: list[bool] = []
    scheduler = FakeScheduler()

    bot._reset_external_background_runtime_for_tests()
    monkeypatch.setattr(
        bot.threading,
        "Thread",
        lambda *, target, daemon, args=(): threads.append(
            FakeThread(target, daemon, args)
        )
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
    monkeypatch.setattr(
        bot,
        "startup_check_missed_routines",
        lambda: missed_checks.append(True),
    )

    try:
        first = bot.start_external_background_runtime("matrix")
        second = bot.start_external_background_runtime("matrix")
        bot.shutdown_event.set()
        monkeypatch.setattr("time.sleep", lambda _: None)
        threads[3].target()
    finally:
        bot._reset_external_background_runtime_for_tests()

    assert first is scheduler
    assert second is scheduler
    assert initialized == [True]
    assert cleanup_channels == ["matrix"]
    assert summary_channels == ["matrix"]
    assert len(threads) == 4
    assert all(thread.started and thread.daemon for thread in threads)
    assert threads[0].args == threads[1].args
    assert threads[0].args[0] is not bot.shutdown_event
    assert missed_checks == []


def test_external_background_runtime_rejects_channel_change_in_same_process(
    monkeypatch,
) -> None:
    import clients.telegram_bot as bot

    threads: list[FakeThread] = []
    bot._reset_external_background_runtime_for_tests()
    monkeypatch.setattr(
        bot.threading,
        "Thread",
        lambda **kwargs: threads.append(FakeThread(**kwargs)) or threads[-1],
    )
    monkeypatch.setattr(bot, "_initialize_external_background_state", lambda: None)
    monkeypatch.setattr(bot, "_build_external_scheduler", FakeScheduler)
    monkeypatch.setattr(bot, "startup_stale_cleanup", lambda channel: None)
    monkeypatch.setattr(bot, "_maybe_trigger_auto_session_summary", lambda channel: None)

    try:
        bot.start_external_background_runtime("telegram")
        assert threads[0].args[0] is not bot.shutdown_event
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
