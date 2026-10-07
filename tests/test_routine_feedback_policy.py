"""Offline occurrence feedback contract; no application/runtime imports."""
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from services.routine_feedback import Occurrence, evaluate_feedback

ATHENS = ZoneInfo("Europe/Athens")


def moment(day: int, hour: int = 12) -> datetime:
    """Return an injected Athens instant."""
    return datetime(2026, 10, day, hour, tzinfo=ATHENS)


def delivered(day: int, feedback: str | None = None) -> Occurrence:
    """Represent one confirmed receipt with optional trusted feedback."""
    return Occurrence(date(2026, 10, day), moment(day, 9), feedback,
                      moment(day, 10) if feedback else None)


def test_third_unanswered_counts_only_after_athens_day_closes() -> None:
    rows = [delivered(5), delivered(6), delivered(7)]
    before = evaluate_feedback(rows, now=moment(7, 23))
    after = evaluate_feedback(rows, now=moment(8, 0))
    assert (before.cooldown_hours, before.unanswered_streak) == (0, 2)
    assert (after.cooldown_hours, after.unanswered_streak) == (20, 0)
    assert after.cooldown_until == moment(8, 0) + timedelta(hours=20)


def test_engagement_resets_pressure_without_marking_completion() -> None:
    rows = [delivered(1), delivered(2), delivered(3), delivered(4, "acknowledge")]
    result = evaluate_feedback(rows, now=moment(5))
    assert result.cooldown_hours == 0
    assert result.unanswered_streak == 0
    assert result.cooldown_until is None
    assert rows[-1].feedback == "acknowledge"


def test_three_refusals_do_not_mix_with_silence() -> None:
    rows = [delivered(1, "skip_today"), delivered(2), delivered(3, "skip_today")]
    result = evaluate_feedback(rows, now=moment(4))
    assert (result.cooldown_hours, result.refusal_streak) == (0, 1)


def test_repeated_refusal_batches_escalate_and_cap() -> None:
    rows = [delivered(day, "skip_today") for day in range(1, 13)]
    assert [evaluate_feedback(rows[:n], now=moment(14)).cooldown_hours
            for n in (3, 6, 9, 12)] == [20, 40, 72, 72]


def test_preemptive_completion_and_nondelivery_are_not_failures() -> None:
    rows = [delivered(1), Occurrence(date(2026, 10, 2)),
            Occurrence(date(2026, 10, 3), feedback="complete", feedback_at=moment(3)),
            delivered(4)]
    result = evaluate_feedback(rows, now=moment(5))
    assert (result.cooldown_hours, result.unanswered_streak) == (0, 1)


def test_historical_correction_recomputes_instead_of_subtracting_a_counter() -> None:
    rows = [delivered(1), delivered(2), delivered(3)]
    assert evaluate_feedback(rows, now=moment(4)).cooldown_hours == 20
    rows[1] = Occurrence(date(2026, 10, 2), moment(2, 9), "complete", moment(4))
    result = evaluate_feedback(rows, now=moment(4))
    assert (result.cooldown_hours, result.unanswered_streak) == (0, 1)


def test_duplicate_occurrence_and_naive_clock_fail_closed() -> None:
    with pytest.raises(ValueError):
        evaluate_feedback([delivered(1), delivered(1)], now=moment(4))
    with pytest.raises(ValueError):
        evaluate_feedback([], now=datetime(2026, 10, 4))


def test_reset_baseline_ignores_old_pressure_without_removing_receipts() -> None:
    rows = [delivered(1), delivered(2), delivered(3), delivered(4)]
    result = evaluate_feedback(rows, now=moment(5), baseline_at=moment(4, 12))
    assert (result.cooldown_hours, result.unanswered_streak) == (0, 0)
    assert len(rows) == 4


def test_athens_calendar_not_utc_date_closes_a_delivery() -> None:
    from datetime import timezone
    row = delivered(5)
    # UTC Oct 5 21:30 is Oct 6 00:30 in Athens.
    now = datetime(2026, 10, 5, 21, 30, tzinfo=timezone.utc)
    assert evaluate_feedback([row], now=now).unanswered_streak == 1


def test_backoff_is_elapsed_hours_across_dst_fallback() -> None:
    from datetime import timezone
    rows = [Occurrence(date(2026, 10, day), feedback="skip_today",
                       feedback_at=moment(day)) for day in (22, 23, 24)]
    result = evaluate_feedback(rows[:3], now=moment(29))
    closed = datetime(2026, 10, 25, tzinfo=ATHENS)
    assert result.cooldown_until.astimezone(timezone.utc) - closed.astimezone(timezone.utc) == timedelta(hours=20)


@pytest.mark.parametrize("row", [
    Occurrence(date(2026, 10, 5), feedback="complete"),
    Occurrence(date(2026, 10, 5), feedback_at=moment(5)),
    Occurrence(date(2026, 10, 5), delivered_at=moment(6)),
])
def test_invalid_or_future_evidence_never_generates_pressure(row) -> None:
    with pytest.raises(ValueError):
        evaluate_feedback([row], now=moment(5))
