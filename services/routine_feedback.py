"""Pure, date-aware notification pressure; confidence is not a penalty target."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Iterable, Literal
from zoneinfo import ZoneInfo

ATHENS = ZoneInfo("Europe/Athens")
Feedback = Literal["complete", "acknowledge", "skip_today", "pause", "defer"]


@dataclass(frozen=True)
class Occurrence:
    """One routine's dated occurrence, receipt and latest trusted feedback."""

    occurrence_date: date
    delivered_at: datetime | None = None
    feedback: Feedback | None = None
    feedback_at: datetime | None = None


@dataclass(frozen=True)
class FeedbackPressure:
    """Derived pressure counters and an absolute backoff deadline."""

    cooldown_hours: int = 0
    cooldown_until: datetime | None = None
    unanswered_streak: int = 0
    refusal_streak: int = 0


def aware(moment: datetime) -> datetime:
    """Require an explicit instant and normalize to the owner's calendar."""
    if moment.tzinfo is None or moment.utcoffset() is None:
        raise ValueError("Feedback timestamps must be timezone-aware")
    return moment.astimezone(ATHENS)


def evaluate_feedback(
    occurrences: Iterable[Occurrence], *, now: datetime,
    baseline_at: datetime | None = None,
) -> FeedbackPressure:
    """Recompute dated pressure, so historical corrections are idempotent.

    Only closed days contribute failures. Positive feedback resets pressure.
    Nondelivery days are neutral; refusal and silence never share a streak.
    Reset boundaries discard old pressure, not occurrence delivery receipts.
    """
    now = aware(now)
    baseline = aware(baseline_at) if baseline_at else None
    if baseline and baseline > now:
        raise ValueError("Feedback baseline cannot be in the future")
    rows = sorted(occurrences, key=lambda row: row.occurrence_date)
    if len({row.occurrence_date for row in rows}) != len(rows):
        raise ValueError("Duplicate occurrence dates")
    hours = unanswered = refusals = 0
    until = None
    for row in rows:
        receipt = aware(row.delivered_at) if row.delivered_at else None
        feedback_at = aware(row.feedback_at) if row.feedback_at else None
        if row.feedback not in (None, "complete", "acknowledge", "skip_today", "pause", "defer"):
            raise ValueError("Invalid feedback")
        if (row.feedback is None) != (feedback_at is None):
            raise ValueError("Feedback must have a recorded instant")
        if any(stamp and stamp > now for stamp in (receipt, feedback_at)):
            raise ValueError("Future evidence")
        if baseline and (row.occurrence_date < baseline.date()
                         or (row.occurrence_date == baseline.date()
                             and not any(stamp and stamp > baseline
                                         for stamp in (receipt, feedback_at)))):
            continue
        if row.occurrence_date > now.date():
            continue
        if row.feedback in ("complete", "acknowledge", "defer", "pause"):
            hours = unanswered = refusals = 0
            until = None
            continue
        if row.occurrence_date == now.date():
            continue
        if row.feedback == "skip_today":
            refusals += 1
            unanswered = 0
        elif receipt:
            unanswered += 1
            refusals = 0
        else:
            continue
        if unanswered == 3 or refusals == 3:
            hours = 20 if hours == 0 else min(hours * 2, 72)
            closed_at = datetime.combine(row.occurrence_date + timedelta(days=1),
                                         time.min, ATHENS)
            until = (closed_at.astimezone(timezone.utc) + timedelta(hours=hours)).astimezone(ATHENS)
            unanswered = refusals = 0
    return FeedbackPressure(hours, until, unanswered, refusals)
