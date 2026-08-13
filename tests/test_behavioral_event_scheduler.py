"""Regression coverage for non-blocking behavioral event intake scheduling."""

from __future__ import annotations

import sys
from functools import partial
from types import SimpleNamespace
from typing import Any

from services import behavioral_event_scheduler as scheduler


class _FakeTimer:
    """Deterministic timer used to test debounce behavior without waiting."""

    instances: list["_FakeTimer"] = []

    def __init__(self, delay: float, callback: Any) -> None:
        self.delay = delay
        self.callback = callback
        self.cancelled = False
        self.daemon = False
        self.started = False
        self.instances.append(self)

    def cancel(self) -> None:
        self.cancelled = True

    def start(self) -> None:
        self.started = True

    def fire(self) -> None:
        self.callback()


def setup_function() -> None:
    _FakeTimer.instances.clear()
    scheduler._reset_scheduler_for_tests()


def test_rapid_requests_coalesce_into_one_slow_queue_task() -> None:
    queued: list[Any] = []

    scheduler.schedule_behavioral_event_intake(
        queued.append,
        delay_seconds=10,
        timer_factory=_FakeTimer,
    )
    scheduler.schedule_behavioral_event_intake(
        queued.append,
        delay_seconds=10,
        timer_factory=_FakeTimer,
    )

    first, second = _FakeTimer.instances
    assert first.cancelled is True
    assert second.started is True

    first.fire()
    second.fire()

    assert len(queued) == 1
    assert isinstance(queued[0], partial)
    assert queued[0].func is scheduler.run_background_behavioral_event_intake


def test_old_timer_cannot_enqueue_after_a_newer_request() -> None:
    queued: list[Any] = []

    scheduler.schedule_behavioral_event_intake(queued.append, timer_factory=_FakeTimer)
    first = _FakeTimer.instances[-1]
    scheduler.schedule_behavioral_event_intake(queued.append, timer_factory=_FakeTimer)
    second = _FakeTimer.instances[-1]

    first.fire()
    assert queued == []

    second.fire()
    assert len(queued) == 1
    assert isinstance(queued[0], partial)
    assert queued[0].func is scheduler.run_background_behavioral_event_intake


def test_web_persisted_user_message_schedules_local_slow_queue(monkeypatch: Any) -> None:
    import api.server as server
    import memory.conversation_history as history

    scheduled: list[Any] = []
    monkeypatch.setattr(history, "append_message", lambda **_kwargs: {"id": "web:1", "rowid": 1})
    monkeypatch.setattr(server, "_broadcast_ws", lambda _event: None)
    monkeypatch.setattr(scheduler, "schedule_behavioral_event_intake", lambda enqueue, **_kwargs: scheduled.append(enqueue))

    server.append_to_chat_history("user", "I had lunch")

    assert scheduled == [server.enqueue_slow_task]


def test_telegram_persisted_user_message_schedules_telegram_slow_queue(monkeypatch: Any) -> None:
    import api.server as server
    import clients.telegram_bot as bot

    scheduled: list[Any] = []
    monkeypatch.setattr(server, "notify_telegram_message", lambda **_kwargs: {"rowid": 7})
    monkeypatch.setattr(scheduler, "schedule_behavioral_event_intake", lambda enqueue, **_kwargs: scheduled.append(enqueue))

    bot._append_to_analytics_log("user", "I had lunch")

    assert scheduled == [bot.enqueue_slow_task]


def test_telegram_deduplicated_user_message_does_not_schedule_intake(monkeypatch: Any) -> None:
    import api.server as server
    import clients.telegram_bot as bot

    scheduled: list[Any] = []
    monkeypatch.setattr(server, "notify_telegram_message", lambda **_kwargs: {"rowid": None})
    monkeypatch.setattr(scheduler, "schedule_behavioral_event_intake", lambda enqueue, **_kwargs: scheduled.append(enqueue))

    bot._append_to_analytics_log("user", "duplicate message")

    assert scheduled == []


def test_provenance_marked_user_history_does_not_schedule_intake(monkeypatch: Any) -> None:
    import api.server as server
    import memory.conversation_history as history

    scheduled: list[Any] = []
    monkeypatch.setattr(history, "append_message", lambda **_kwargs: {"id": "web:2", "rowid": 2})
    monkeypatch.setattr(server, "_broadcast_ws", lambda _event: None)
    monkeypatch.setattr(scheduler, "schedule_behavioral_event_intake", scheduled.append)

    server.append_to_chat_history(
        "user",
        "external analysis",
        metadata={"untrusted_external_tool_names": ["browse_url"]},
    )

    assert scheduled == []


def test_background_runner_contains_intake_failures(monkeypatch: Any) -> None:
    monkeypatch.setitem(
        sys.modules,
        "services.behavioral_event_extractor",
        SimpleNamespace(run_behavioral_event_intake=lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("offline"))),
    )

    scheduler.run_background_behavioral_event_intake()


def test_scheduler_failure_is_contained_before_history_callers_observe_it(monkeypatch: Any) -> None:
    def fail_schedule(*_args: Any, **_kwargs: Any) -> None:
        raise RuntimeError("thread exhaustion")

    monkeypatch.setattr(scheduler, "schedule_behavioral_event_intake", fail_schedule)

    scheduled = scheduler.schedule_persisted_user_intake(
        rowid=3,
        metadata=None,
        enqueue_slow_task=lambda _task: None,
    )

    assert scheduled is False
