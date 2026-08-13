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
_schedule_generation = 0


def run_background_behavioral_event_intake() -> None:
    """Run the observational intake without letting a queue worker fail."""
    try:
        from services.behavioral_event_extractor import run_behavioral_event_intake

        run_behavioral_event_intake()
    except Exception:
        _logger.exception("Behavioral event background intake failed")


def schedule_behavioral_event_intake(
    enqueue_slow_task: Callable[[Callable[[], None]], Any],
    *,
    delay_seconds: float = BEHAVIORAL_EVENT_INTAKE_DEBOUNCE_SECONDS,
    timer_factory: Callable[[float, Callable[[], None]], threading.Timer] = threading.Timer,
) -> None:
    """Coalesce rapid user-message writes into one later slow-queue task."""
    global _pending_timer, _schedule_generation
    with _scheduler_lock:
        _schedule_generation += 1
        generation = _schedule_generation
        if _pending_timer is not None:
            _pending_timer.cancel()

        def enqueue_current_generation() -> None:
            global _pending_timer
            with _scheduler_lock:
                if generation != _schedule_generation:
                    return
                _pending_timer = None
            enqueue_slow_task(run_background_behavioral_event_intake)

        timer = timer_factory(delay_seconds, enqueue_current_generation)
        timer.daemon = True
        _pending_timer = timer
        timer.start()


def schedule_persisted_user_intake(
    *,
    rowid: int | None,
    metadata: Mapping[str, Any] | None,
    enqueue_slow_task: Callable[[Callable[[], None]], Any],
) -> bool:
    """Schedule intake only for a newly persisted, provenance-free user row."""
    if isinstance(rowid, bool) or not isinstance(rowid, int) or rowid <= 0:
        return False
    from core.untrusted_content import external_content_source_names

    if external_content_source_names(metadata or {}):
        return False
    schedule_behavioral_event_intake(enqueue_slow_task)
    return True


def _reset_scheduler_for_tests() -> None:
    """Reset process-local debounce state for deterministic unit tests."""
    global _pending_timer, _schedule_generation
    with _scheduler_lock:
        if _pending_timer is not None:
            _pending_timer.cancel()
        _pending_timer = None
        _schedule_generation = 0
