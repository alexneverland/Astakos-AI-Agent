"""Non-blocking, debounced scheduling for behavioral event intake."""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from typing import Any, Mapping


BEHAVIORAL_EVENT_INTAKE_DEBOUNCE_SECONDS = 15.0
_logger = logging.getLogger(__name__)
_scheduler_lock = threading.Lock()
_pending_timer: threading.Timer | None = None
_pending_initialization_rowid: int | None = None
_schedule_generation = 0


def run_background_behavioral_event_intake(
    initialization_rowid: int | None = None,
    enqueue_slow_task: Callable[..., Any] | None = None,
) -> None:
    """Run the observational intake without letting a queue worker fail."""
    try:
        from services.behavioral_event_extractor import MAX_INTAKE_MESSAGES, run_behavioral_event_intake

        stats = run_behavioral_event_intake(initialization_rowid=initialization_rowid)
        if (
            enqueue_slow_task is not None
            and int(stats.get("errors", 0)) == 0
            and int(stats.get("loaded", 0)) >= MAX_INTAKE_MESSAGES
        ):
            enqueue_slow_task(run_background_behavioral_event_intake, None, enqueue_slow_task)
    except Exception:
        _logger.exception("Behavioral event background intake failed")


def schedule_behavioral_event_intake(
    enqueue_slow_task: Callable[..., Any],
    *,
    delay_seconds: float = BEHAVIORAL_EVENT_INTAKE_DEBOUNCE_SECONDS,
    timer_factory: Callable[[float, Callable[[], None]], threading.Timer] = threading.Timer,
    initialization_rowid: int | None = None,
) -> None:
    """Coalesce rapid user-message writes into one later slow-queue task."""
    global _pending_timer, _pending_initialization_rowid, _schedule_generation
    with _scheduler_lock:
        _schedule_generation += 1
        generation = _schedule_generation
        if initialization_rowid is not None:
            if _pending_initialization_rowid is None:
                _pending_initialization_rowid = initialization_rowid
            else:
                _pending_initialization_rowid = min(_pending_initialization_rowid, initialization_rowid)
        if _pending_timer is not None:
            _pending_timer.cancel()

        def enqueue_current_generation() -> None:
            global _pending_timer, _pending_initialization_rowid
            with _scheduler_lock:
                if generation != _schedule_generation:
                    return
                first_rowid = _pending_initialization_rowid
                _pending_timer = None
                _pending_initialization_rowid = None
            # The queue workers log ``task_func.__name__`` before invocation,
            # so enqueue the named runner and its argument separately.
            enqueue_slow_task(run_background_behavioral_event_intake, first_rowid, enqueue_slow_task)

        timer = timer_factory(delay_seconds, enqueue_current_generation)
        timer.daemon = True
        _pending_timer = timer
        timer.start()


def schedule_persisted_user_intake(
    *,
    rowid: int | None,
    metadata: Mapping[str, Any] | None,
    enqueue_slow_task: Callable[..., Any],
) -> bool:
    """Schedule intake only for a newly persisted, provenance-free user row."""
    if isinstance(rowid, bool) or not isinstance(rowid, int) or rowid <= 0:
        return False
    from core.untrusted_content import external_content_source_names

    if external_content_source_names(metadata or {}):
        return False
    try:
        from memory.behavioral_event_state import register_initialization_boundary

        register_initialization_boundary(last_rowid=rowid - 1)
        schedule_behavioral_event_intake(
            enqueue_slow_task,
            initialization_rowid=rowid,
        )
    except Exception:
        _logger.exception("Behavioral event intake scheduling failed")
        return False
    return True


def _reset_scheduler_for_tests() -> None:
    """Reset process-local debounce state for deterministic unit tests."""
    global _pending_timer, _pending_initialization_rowid, _schedule_generation
    with _scheduler_lock:
        if _pending_timer is not None:
            _pending_timer.cancel()
        _pending_timer = None
        _pending_initialization_rowid = None
        _schedule_generation = 0
