"""Queue-backed scheduling for observational behavioral-event intake."""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from typing import Any, Mapping


_logger = logging.getLogger(__name__)
_scheduler_lock = threading.Lock()
_intake_queued = False
_pending_initialization_rowid: int | None = None


def run_background_behavioral_event_intake(
    enqueue_slow_task: Callable[..., Any] | None = None,
) -> None:
    """Run one queued intake batch without allowing a worker failure to escape."""
    global _intake_queued, _pending_initialization_rowid
    with _scheduler_lock:
        initialization_rowid = _pending_initialization_rowid
        _pending_initialization_rowid = None
        _intake_queued = False

    try:
        from services.behavioral_event_extractor import MAX_INTAKE_MESSAGES, run_behavioral_event_intake

        stats = run_behavioral_event_intake(initialization_rowid=initialization_rowid)
        if enqueue_slow_task is not None and int(stats.get("loaded", 0)) >= MAX_INTAKE_MESSAGES:
            enqueue_slow_task(run_background_behavioral_event_intake, enqueue_slow_task)
    except Exception:
        _logger.exception("Behavioral event background intake failed")


def schedule_behavioral_event_intake(
    enqueue_slow_task: Callable[..., Any],
    *,
    initialization_rowid: int | None = None,
) -> None:
    """Coalesce rapid writes into one task on the caller's existing slow queue."""
    global _intake_queued, _pending_initialization_rowid
    with _scheduler_lock:
        if initialization_rowid is not None:
            if _pending_initialization_rowid is None:
                _pending_initialization_rowid = initialization_rowid
            else:
                _pending_initialization_rowid = min(_pending_initialization_rowid, initialization_rowid)
        if _intake_queued:
            return
        _intake_queued = True
    try:
        enqueue_slow_task(run_background_behavioral_event_intake, enqueue_slow_task)
    except Exception:
        with _scheduler_lock:
            _intake_queued = False
        raise


def schedule_persisted_user_intake(
    *,
    rowid: int | None,
    metadata: Mapping[str, Any] | None,
    enqueue_slow_task: Callable[..., Any],
) -> bool:
    """Queue intake only for a newly persisted, provenance-free user row."""
    if isinstance(rowid, bool) or not isinstance(rowid, int) or rowid <= 0:
        return False
    from core.untrusted_content import external_content_source_names

    if external_content_source_names(metadata or {}):
        return False
    try:
        schedule_behavioral_event_intake(
            enqueue_slow_task,
            initialization_rowid=rowid,
        )
    except Exception:
        _logger.exception("Behavioral event intake scheduling failed")
        return False
    return True


def _reset_scheduler_for_tests() -> None:
    """Reset process-local queue-debounce state for deterministic unit tests."""
    global _intake_queued, _pending_initialization_rowid
    with _scheduler_lock:
        _intake_queued = False
        _pending_initialization_rowid = None
