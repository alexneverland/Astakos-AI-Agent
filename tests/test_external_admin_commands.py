"""Offline contracts for shared text-only external channel commands."""

from __future__ import annotations


class FakeScheduler:
    def status(self) -> str:
        return "scheduler status"


def test_status_command_uses_shared_scheduler(monkeypatch) -> None:
    import clients.telegram_bot as bot

    monkeypatch.setattr(bot, "astakos_scheduler", FakeScheduler())

    assert bot.handle_external_admin_command("/status") == "scheduler status"


def test_pause_and_resume_commands_update_the_shared_override_state(monkeypatch) -> None:
    import clients.telegram_bot as bot

    saved: list[dict] = []
    monkeypatch.setattr(bot, "_save_override_state", lambda: saved.append(dict(bot._override_state)))
    monkeypatch.setattr(bot, "_reset_vacation_pause_skip_log", lambda: None)
    bot._override_state.update(
        {
            "pause_reminders": False,
            "mute_proactive": False,
            "sleep_until": None,
            "routine_pause_until": None,
        }
    )

    pause_reply = bot.handle_external_admin_command("/pause")
    assert pause_reply
    assert bot._override_state["pause_reminders"] is True

    resume_reply = bot.handle_external_admin_command("/resume")
    assert resume_reply
    assert bot._override_state == {
        "pause_reminders": False,
        "mute_proactive": False,
        "sleep_until": None,
        "routine_pause_until": None,
    }
    assert len(saved) == 2


def test_unknown_or_media_command_is_not_claimed() -> None:
    import clients.telegram_bot as bot

    assert bot.handle_external_admin_command("/unknown") is None
    assert bot.handle_external_admin_command("/voice") is None
    assert bot.handle_external_admin_command("καλημέρα") is None


def test_telegram_end_session_uses_shared_finalizer(monkeypatch) -> None:
    import clients.telegram_bot as bot
    import services.session_end as session_end

    finalized: list[str] = []
    sent: list[str] = []
    monkeypatch.setattr(
        session_end,
        "finalize_session",
        lambda *, channel: finalized.append(channel),
    )
    monkeypatch.setattr(bot, "send_telegram_msg", sent.append)

    bot.handle_end_session("owner-chat")

    assert finalized == ["telegram"]
    assert sent == [
        bot.t("clients.telegram_bot.bot_msg_139ed4"),
        bot.t("clients.telegram_bot.bot_msg_bfe08b"),
    ]


def test_telegram_process_shutdown_drains_before_archive_and_store_close(
    monkeypatch,
) -> None:
    """Watchdog restart must preserve queued work before archiving Telegram."""
    from types import SimpleNamespace

    import clients.telegram_bot as bot

    calls: list[str] = []
    sent: list[str] = []

    class FakeEvent:
        def __init__(self, name: str) -> None:
            self.name = name

        def set(self) -> None:
            calls.append(self.name)

    class FakeQueue:
        def __init__(self, name: str) -> None:
            self.name = name

        def join(self) -> None:
            calls.append(self.name)

    runtime = SimpleNamespace(
        shutdown_event=FakeEvent("stop-scheduler"),
        _external_worker_stop_event=FakeEvent("stop-workers"),
        fast_queue=FakeQueue("fast"),
        slow_queue=FakeQueue("slow"),
    )
    monkeypatch.setattr(
        "services.session_end.finalize_session",
        lambda *, channel: calls.append(f"archive:{channel}"),
    )
    monkeypatch.setattr(
        "memory.vector_store.close_vector_store",
        lambda: calls.append("close-store"),
    )

    result = bot.archive_telegram_runtime(
        runtime,
        send_message=sent.append,
        drain_timeout=1,
    )

    assert result is True
    assert calls == [
        "stop-scheduler", "fast", "slow", "stop-workers",
        "archive:telegram", "close-store",
    ]
    assert sent == [
        bot.t("clients.telegram_bot.bot_msg_139ed4"),
        bot.t("clients.telegram_bot.bot_msg_bfe08b"),
    ]


def test_telegram_shutdown_archives_even_if_notification_fails(monkeypatch) -> None:
    """Telegram delivery failures must not prevent local memory shutdown."""
    import clients.telegram_bot as bot

    archived: list[str] = []
    monkeypatch.setattr(
        "services.external_runtime_shutdown.drain_and_archive_external_runtime",
        lambda runtime, *, channel, drain_timeout: archived.append(channel) or True,
    )

    def unavailable_telegram(message: str) -> None:
        raise RuntimeError("Telegram unavailable")

    assert bot.archive_telegram_runtime(
        object(),
        send_message=unavailable_telegram,
        drain_timeout=1,
    ) is True
    assert archived == ["telegram"]
