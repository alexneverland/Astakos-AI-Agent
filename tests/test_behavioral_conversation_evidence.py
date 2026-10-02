"""Offline contracts for reusing existing patterns as conversation evidence."""

from datetime import date

import pytest

from services import behavioral_conversation_evidence as evidence
from services.behavioral_pattern_aggregator import aggregate_behavioral_pattern_candidates


def event(day: int, channel: str = "web", **overrides) -> dict:
    """Build a synthetic confirmed observation with source identity."""
    result = dict(
        event_type="drink", action_kind="consume", category="food",
        subject="user", item="beer", status="consumed", record_state="confirmed",
        event_date=f"2026-09-{day:02}", confidence=0.95, negated=0,
        hypothetical=0, reported_by_user=1, source_message_id=f"{channel}:{day}",
        source_rowid=day, source_channel=channel, created_at="2026-10-02T12:00:00",
    )
    result.update(overrides)
    return result


def test_reuses_detector_with_dates_and_cross_channel_sources():
    rows = [event(20), event(22, "telegram"), event(24, "matrix"), event(24)]
    result = evidence.build_behavioral_evidence(rows, today=date(2026, 10, 2), window_days=30)
    assert len(result) == 1
    assert result[0]["distinct_date_count"] == 3
    assert result[0]["event_dates"] == ["2026-09-20", "2026-09-22", "2026-09-24"]
    assert result[0]["occurrence_count"] == 4
    assert {ref["channel"] for ref in result[0]["source_refs"]} == {"web", "telegram", "matrix"}
    assert "created_at" not in str(result)
    assert "event_time" not in str(result)
    # The established Debug contract must remain unchanged by default.
    assert "source_refs" not in aggregate_behavioral_pattern_candidates(rows)[0]


def test_window_filters_before_detection_and_rejects_future_dates():
    rows = [event(1), event(2), event(24), event(25, event_date="2026-10-03")]
    assert evidence.build_behavioral_evidence(rows, today=date(2026, 10, 2), window_days=10) == []


def test_exact_inclusive_window_and_same_day_repetition():
    rows = [event(23), event(24), event(25)]
    assert len(evidence.build_behavioral_evidence(rows, today=date(2026, 10, 2), window_days=10)) == 1
    assert evidence.build_behavioral_evidence([event(23)] * 5, today=date(2026, 10, 2), window_days=10) == []


@pytest.mark.parametrize("override", [
    {"negated": 1}, {"hypothetical": 1}, {"reported_by_user": 0},
    {"subject": "partner"}, {"status": "planned"}, {"confidence": 0.5},
    {"reported_by_user": "true"}, {"source_channel": "external"},
    {"source_rowid": True}, {"source_message_id": ""},
    {"metadata": {"untrusted_external_tool_names": ["browse_url"]}},
])
def test_unusable_evidence_cannot_complete_a_pattern(override):
    rows = [event(20), event(22), event(24, **override)]
    assert evidence.build_behavioral_evidence(rows, today=date(2026, 10, 2), window_days=30) == []


def test_source_replay_does_not_increase_raw_counts():
    rows = [event(20), event(22), event(24), event(24)]
    result = evidence.build_behavioral_evidence(rows, today=date(2026, 10, 2), window_days=30)
    assert result[0]["occurrence_count"] == 3


def test_read_only_loader_failure_is_a_safe_empty_result(monkeypatch):
    from memory import behavioral_event_state

    def broken(**kwargs):
        assert kwargs == {"record_state": "confirmed", "initialize": False}
        raise RuntimeError("storage unavailable")

    monkeypatch.setattr(behavioral_event_state, "list_events", broken)
    assert evidence.load_behavioral_evidence(today=date(2026, 10, 2), window_days=30) == []


def test_real_temporary_store_loads_without_initialization(tmp_path, monkeypatch):
    from memory import behavioral_event_state as store

    path = str(tmp_path / "observations.db")
    for day, channel in ((20, "web"), (22, "telegram"), (24, "matrix")):
        store.record_event(event(day, channel, negated=False, hypothetical=False, reported_by_user=True), db_path=path)
    monkeypatch.setattr(store, "init_db", lambda *_: pytest.fail("evidence must not initialize a database"))
    result = evidence.load_behavioral_evidence(today=date(2026, 10, 2), window_days=30, db_path=path)
    assert result[0]["distinct_date_count"] == 3
    assert evidence.load_behavioral_evidence(today=date(2026, 10, 2), window_days=30, db_path=str(tmp_path / "missing.db")) == []
    assert not (tmp_path / "missing.db").exists()


def test_packet_limits_sources_without_fabricating_frequency():
    rows = [event(day) for day in range(1, 29)]
    result = evidence.build_behavioral_evidence(rows, today=date(2026, 10, 2), window_days=40)
    assert result[0]["distinct_date_count"] == 28
    assert len(result[0]["source_refs"]) == 12
    assert len(result[0]["event_dates"]) == 28
    assert result[0]["window_start"] == "2026-08-24"
    assert result[0]["window_end"] == "2026-10-02"


@pytest.mark.parametrize("window", [0, -1, True, 1.5, 367])
def test_explicit_window_is_validated(window):
    with pytest.raises(ValueError):
        evidence.build_behavioral_evidence([], today=date(2026, 10, 2), window_days=window)
