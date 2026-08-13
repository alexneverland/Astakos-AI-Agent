"""Regression coverage for queue-backed behavioral event intake scheduling."""

from __future__ import annotations

import sys
from types import SimpleNamespace
from typing import Any

from services import behavioral_event_scheduler as scheduler


def setup_function() -> None:
    scheduler._reset_scheduler_for_tests()


def test_rapid_requests_coalesce_into_one_existing_slow_queue_task() -> None:
    queued: list[tuple[Any, tuple[Any, ...]]] = []

    def enqueue(task: Any, *args: Any) -> None:
        queued.append((task, args))

    scheduler.schedule_behavioral_event_intake(enqueue, initialization_rowid=15)
    scheduler.schedule_behavioral_event_intake(enqueue, initialization_rowid=12)

    assert queued == [(scheduler.run_background_behavioral_event_intake, (enqueue,))]


def test_queued_runner_receives_the_earliest_initialization_rowid(monkeypatch: Any) -> None:
    queued: list[tuple[Any, tuple[Any, ...]]] = []
    calls: list[int | None] = []
    monkeypatch.setitem(
        sys.modules,
        "services.behavioral_event_extractor",
        SimpleNamespace(
            MAX_INTAKE_MESSAGES=100,
            run_behavioral_event_intake=lambda *, initialization_rowid=None: calls.append(initialization_rowid) or {"loaded": 0},
        ),
    )

    def enqueue(task: Any, *args: Any) -> None:
        queued.append((task, args))

    scheduler.schedule_behavioral_event_intake(enqueue, initialization_rowid=15)
    scheduler.schedule_behavioral_event_intake(enqueue, initialization_rowid=12)
    task, args = queued.pop()
    task(*args)

    assert calls == [12]


def test_background_runner_enqueues_a_named_continuation_for_a_full_page(monkeypatch: Any) -> None:
    queued: list[tuple[Any, tuple[Any, ...]]] = []
    monkeypatch.setitem(
        sys.modules,
        "services.behavioral_event_extractor",
        SimpleNamespace(
            MAX_INTAKE_MESSAGES=100,
            run_behavioral_event_intake=lambda **_kwargs: {"loaded": 100},
        ),
    )

    def enqueue(task: Any, *args: Any) -> None:
        queued.append((task, args))

    scheduler.run_background_behavioral_event_intake(enqueue)

    assert queued == [(scheduler.run_background_behavioral_event_intake, (enqueue,))]


def test_background_runner_does_not_paginate_a_failed_full_page(monkeypatch: Any) -> None:
    queued: list[tuple[Any, tuple[Any, ...]]] = []
    monkeypatch.setitem(
        sys.modules,
        "services.behavioral_event_extractor",
        SimpleNamespace(
            MAX_INTAKE_MESSAGES=100,
            run_behavioral_event_intake=lambda **_kwargs: {"loaded": 100, "errors": 1},
        ),
    )

    scheduler.run_background_behavioral_event_intake(
        lambda task, *args: queued.append((task, args)),
    )

    assert queued == []


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


def test_web_persisted_user_message_schedules_local_slow_queue(monkeypatch: Any) -> None:
    import api.server as server
    import memory.conversation_history as history

    scheduled: list[tuple[Any, dict[str, Any]]] = []
    monkeypatch.setattr(history, "append_message", lambda **_kwargs: {"id": "web:1", "rowid": 1})
    monkeypatch.setattr(server, "_broadcast_ws", lambda _event: None)
    monkeypatch.setattr(
        scheduler,
        "schedule_behavioral_event_intake",
        lambda enqueue, **kwargs: scheduled.append((enqueue, kwargs)),
    )

    server.append_to_chat_history("user", "I had lunch")

    assert scheduled == [(server.enqueue_slow_task, {"initialization_rowid": 1})]


def test_telegram_persisted_user_message_schedules_telegram_slow_queue(monkeypatch: Any) -> None:
    import api.server as server
    import clients.telegram_bot as bot

    scheduled: list[tuple[Any, dict[str, Any]]] = []
    monkeypatch.setattr(server, "notify_telegram_message", lambda **_kwargs: {"rowid": 7})
    monkeypatch.setattr(
        scheduler,
        "schedule_behavioral_event_intake",
        lambda enqueue, **kwargs: scheduled.append((enqueue, kwargs)),
    )

    bot._append_to_analytics_log("user", "I had lunch")

    assert scheduled == [(bot.enqueue_slow_task, {"initialization_rowid": 7})]


def test_telegram_deduplicated_user_message_does_not_schedule_intake(monkeypatch: Any) -> None:
    import api.server as server
    import clients.telegram_bot as bot

    scheduled: list[Any] = []
    monkeypatch.setattr(server, "notify_telegram_message", lambda **_kwargs: {"rowid": None})
    monkeypatch.setattr(scheduler, "schedule_behavioral_event_intake", scheduled.append)

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


def test_scheduler_failure_is_contained_before_history_callers_observe_it(monkeypatch: Any) -> None:
    monkeypatch.setattr(
        scheduler,
        "schedule_behavioral_event_intake",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("queue unavailable")),
    )

    scheduled = scheduler.schedule_persisted_user_intake(
        rowid=3,
        metadata=None,
        enqueue_slow_task=lambda _task: None,
    )

    assert scheduled is False
