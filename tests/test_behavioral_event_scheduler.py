"""Regression coverage for non-blocking behavioral event intake scheduling."""

from __future__ import annotations

import sys
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
    queued: list[tuple[Any, tuple[Any, ...]]] = []

    def enqueue(task: Any, *args: Any) -> None:
        queued.append((task, args))

    scheduler.schedule_behavioral_event_intake(
        enqueue,
        delay_seconds=10,
        timer_factory=_FakeTimer,
    )
    scheduler.schedule_behavioral_event_intake(
        enqueue,
        delay_seconds=10,
        timer_factory=_FakeTimer,
    )

    first, second = _FakeTimer.instances
    assert first.cancelled is True
    assert second.started is True

    first.fire()
    second.fire()

    assert len(queued) == 1
    assert queued == [(scheduler.run_background_behavioral_event_intake, (None, enqueue))]


def test_old_timer_cannot_enqueue_after_a_newer_request() -> None:
    queued: list[tuple[Any, tuple[Any, ...]]] = []

    def enqueue(task: Any, *args: Any) -> None:
        queued.append((task, args))

    scheduler.schedule_behavioral_event_intake(enqueue, timer_factory=_FakeTimer)
    first = _FakeTimer.instances[-1]
    scheduler.schedule_behavioral_event_intake(enqueue, timer_factory=_FakeTimer)
    second = _FakeTimer.instances[-1]

    first.fire()
    assert queued == []

    second.fire()
    assert len(queued) == 1
    assert queued == [(scheduler.run_background_behavioral_event_intake, (None, enqueue))]


def test_slow_queue_receives_a_named_runner_with_the_initialization_rowid() -> None:
    queued: list[tuple[Any, tuple[Any, ...]]] = []

    def enqueue(task: Any, *args: Any) -> None:
        queued.append((task, args))

    scheduler.schedule_behavioral_event_intake(
        enqueue,
        timer_factory=_FakeTimer,
        initialization_rowid=12,
    )

    _FakeTimer.instances[-1].fire()

    task, args = queued[0]
    assert task is scheduler.run_background_behavioral_event_intake
    assert task.__name__ == "run_background_behavioral_event_intake"
    assert args == (12, enqueue)


def test_background_runner_enqueues_a_named_continuation_for_a_full_page(monkeypatch: Any) -> None:
    calls: list[Any] = []
    queued: list[tuple[Any, tuple[Any, ...]]] = []

    def intake(**_kwargs: Any) -> dict[str, int]:
        calls.append(True)
        return {"loaded": 100, "errors": 0}

    def enqueue(task: Any, *args: Any) -> None:
        queued.append((task, args))

    monkeypatch.setitem(
        sys.modules,
        "services.behavioral_event_extractor",
        SimpleNamespace(run_behavioral_event_intake=intake, MAX_INTAKE_MESSAGES=100),
    )

    scheduler.run_background_behavioral_event_intake(12, enqueue)

    assert calls == [True]
    assert queued == [(scheduler.run_background_behavioral_event_intake, (None, enqueue))]


def test_background_runner_retries_a_transient_extraction_failure_after_a_delay(monkeypatch: Any) -> None:
    queued: list[tuple[Any, tuple[Any, ...]]] = []
    monkeypatch.setitem(
        sys.modules,
        "services.behavioral_event_extractor",
        SimpleNamespace(
            MAX_INTAKE_MESSAGES=100,
            run_behavioral_event_intake=lambda **_kwargs: {"loaded": 3, "errors": 1},
        ),
    )
    monkeypatch.setattr(scheduler.threading, "Timer", _FakeTimer)

    def enqueue(task: Any, *args: Any) -> None:
        queued.append((task, args))

    scheduler.run_background_behavioral_event_intake(12, enqueue)

    retry_timer = _FakeTimer.instances[-1]
    assert retry_timer.started is True
    retry_timer.fire()
    assert queued == [(scheduler.run_background_behavioral_event_intake, (12, enqueue, 1))]


def test_background_runner_stops_retrying_after_the_bounded_limit(monkeypatch: Any) -> None:
    queued: list[tuple[Any, tuple[Any, ...]]] = []
    monkeypatch.setitem(
        sys.modules,
        "services.behavioral_event_extractor",
        SimpleNamespace(
            MAX_INTAKE_MESSAGES=100,
            run_behavioral_event_intake=lambda **_kwargs: {"loaded": 3, "errors": 1},
        ),
    )
    monkeypatch.setattr(scheduler.threading, "Timer", _FakeTimer)

    scheduler.run_background_behavioral_event_intake(
        12,
        lambda task, *args: queued.append((task, args)),
        retry_attempt=scheduler.BEHAVIORAL_EVENT_INTAKE_MAX_RETRIES,
    )

    assert _FakeTimer.instances == []
    assert queued == []


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


def test_first_persisted_row_registers_its_predecessor_as_the_bootstrap_boundary(monkeypatch: Any) -> None:
    import memory.behavioral_event_state as event_state

    boundaries: list[int] = []
    monkeypatch.setattr(
        event_state,
        "register_initialization_boundary",
        lambda *, last_rowid: boundaries.append(last_rowid),
    )
    monkeypatch.setattr(scheduler, "schedule_behavioral_event_intake", lambda *_args, **_kwargs: None)

    scheduled = scheduler.schedule_persisted_user_intake(
        rowid=10,
        metadata=None,
        enqueue_slow_task=lambda *_args: None,
    )

    assert scheduled is True
    assert boundaries == [9]


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
        SimpleNamespace(
            MAX_INTAKE_MESSAGES=100,
            run_behavioral_event_intake=lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("offline")),
        ),
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
