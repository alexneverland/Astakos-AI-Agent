# ================================================================
# Project: Astakos AI Agent 🦞
# Developer: Lazaros (Piston-7)
# Description: Structured Exception Classes
# Copyright (c) 2026 - All Rights Reserved
# ================================================================


class AstakosError(Exception):
    """Base class για όλα τα custom exceptions του Αστακού."""
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
    Raised όταν ανιχνεύεται σύγκρουση κατά το upsert ρουτίνας.
    Π.χ. fingerprint collision με ασύμβατα δεδομένα, ή DB corruption.
    """
    pass


class DuplicateEventError(AstakosError):
    """
    Raised όταν ένα event/notification προσπαθεί να σταλεί εντός cooldown.
    Χρησιμοποιείται ως signal — δεν propagate, απλά log & skip.
    """
    def __init__(self, routine_id: int, cooldown_hours: float, remaining_hours: float):
        super().__init__(
            f"Routine #{routine_id} σε cooldown",
            context={"cooldown_h": cooldown_hours, "remaining_h": round(remaining_hours, 1)}
        )
        self.routine_id    = routine_id
        self.cooldown_hours = cooldown_hours
        self.remaining_hours = remaining_hours


class PendingTimeoutError(AstakosError):
    """
    Raised όταν μια εκκρεμής επιβεβαίωση ρουτίνας λήξει χωρίς απάντηση.
    Trigger για decay + ignore_count increment.
    """
    def __init__(self, routine_id: int, event_name: str, elapsed_seconds: float):
        super().__init__(
            f"Timeout για '{event_name}' χωρίς απάντηση",
            context={"routine_id": routine_id, "elapsed_s": int(elapsed_seconds)}
        )
        self.routine_id   = routine_id
        self.event_name   = event_name
        self.elapsed_seconds = elapsed_seconds


class SchedulerCrashError(AstakosError):
    """
    Raised όταν ένα scheduler job αποτύχει πάνω από MAX_FAILURES φορές.
    Trigger για auto-disable του job + alert στον χρήστη.
    """
    def __init__(self, job_name: str, fail_count: int, last_error: str):
        super().__init__(
            f"Job '{job_name}' disabled μετά από {fail_count} αποτυχίες",
            context={"job": job_name, "fails": fail_count, "last_error": last_error[:100]}
        )
        self.job_name   = job_name
        self.fail_count = fail_count
        self.last_error = last_error


class DBWriteError(AstakosError):
    """
    Raised όταν μια εγγραφή στη SQLite αποτύχει (π.χ. locked, I/O error).
    Wrapper γύρω από sqlite3.OperationalError για context-aware handling.
    """
    def __init__(self, operation: str, original: Exception):
        super().__init__(
            f"DB write απέτυχε κατά '{operation}'",
            context={"error": str(original)[:120]}
        )
        self.operation = operation
        self.original  = original
