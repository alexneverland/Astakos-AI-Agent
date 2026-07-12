from core.i18n import t
# ================================================================
# Project: Astakos AI Agent 🦞
# Developer: Lazaros (Piston-7)
# Description: Structured Exception Classes
# Copyright (c) 2026 - All Rights Reserved
# ================================================================


class AstakosError(Exception):
    """Base class for all custom exceptions of Astakos."""
    def __init__(self, message: str, context: dict = None):
        super().__init__(message)
        self.context = context or {}

    def __str__(self):
        base = super().__str__()
        if self.context:
            ctx = ", ".join(f"{k}={v}" for k, v in self.context.items())
            return f"{base} [{ctx}]"
        return base


class RoutineConflictError(AstakosError):
    """
    Raised when a collision is detected during a routine upsert.
    E.g., fingerprint collision with incompatible data, or DB corruption.
    """
    pass


class DuplicateEventError(AstakosError):
    """
    Raised when an event/notification attempts to be sent within a cooldown period.
    Used as a signal — does not propagate, just logs & skips.
    """
    def __init__(self, routine_id: int, cooldown_hours: float, remaining_hours: float):
        super().__init__(
            t("core.exceptions.routine_cooldown", id=routine_id),
            context={"cooldown_h": cooldown_hours, "remaining_h": round(remaining_hours, 1)}
        )
        self.routine_id    = routine_id
        self.cooldown_hours = cooldown_hours
        self.remaining_hours = remaining_hours


class PendingTimeoutError(AstakosError):
    """
    Raised when a pending routine confirmation expires without a response.
    Trigger for decay + ignore_count increment.
    """
    def __init__(self, routine_id: int, event_name: str, elapsed_seconds: float):
        super().__init__(
            t("core.exceptions.timeout", event=event_name),
            context={"routine_id": routine_id, "elapsed_s": int(elapsed_seconds)}
        )
        self.routine_id   = routine_id
        self.event_name   = event_name
        self.elapsed_seconds = elapsed_seconds


class SchedulerCrashError(AstakosError):
    """
    Raised when a scheduler job fails more than MAX_FAILURES times.
    Trigger for auto-disabling the job + alerting the user.
    """
    def __init__(self, job_name: str, fail_count: int, last_error: str):
        super().__init__(
            t("core.exceptions.job_disabled", job=job_name, fails=fail_count),
            context={"job": job_name, "fails": fail_count, "last_error": last_error[:100]}
        )
        self.job_name   = job_name
        self.fail_count = fail_count
        self.last_error = last_error


class DBWriteError(AstakosError):
    """
    Raised when a SQLite write operation fails (e.g., locked, I/O error).
    Wrapper around sqlite3.OperationalError for context-aware handling.
    """
    def __init__(self, operation: str, original: Exception):
        super().__init__(
            t("core.exceptions.db_write_fail", op=operation),
            context={"error": str(original)[:120]}
        )
        self.operation = operation
        self.original  = original
