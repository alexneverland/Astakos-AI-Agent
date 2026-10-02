"""Temporary event-log coverage for reminder activity outside chat history."""
from datetime import datetime, timedelta

import pytest

from memory import event_log


@pytest.mark.parametrize("minutes, expected", [(1, True), (14, True), (15, False), (16, False)])
def test_reminder_quiet_interval_includes_midnight(tmp_path, monkeypatch, minutes, expected):
    """Yesterday's sent reminder still blocks inside the fifteen-minute window."""
    now = datetime(2026, 10, 2, 0, 5)
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return now - timedelta(minutes=minutes)
    monkeypatch.setattr(event_log, "LOGS_DIR", str(tmp_path))
    monkeypatch.setattr(event_log, "datetime", Clock)
    event_log.log_event("reminders", "sent", task="Synthetic reminder")
    assert event_log.has_recent_reminder_delivery(now) is expected


def test_unrelated_or_unsent_events_do_not_block(tmp_path, monkeypatch):
    monkeypatch.setattr(event_log, "LOGS_DIR", str(tmp_path))
    event_log.log_event("reminders", "start")
    event_log.log_event("other", "sent")
    assert not event_log.has_recent_reminder_delivery(datetime.now())


def test_missing_event_logs_are_read_only(tmp_path, monkeypatch):
    monkeypatch.setattr(event_log, "LOGS_DIR", str(tmp_path))
    assert not event_log.has_recent_reminder_delivery(datetime(2026, 10, 2, 12))
    assert list(tmp_path.iterdir()) == []


def test_corrupt_event_log_fails_closed_without_changing_legacy_reader(tmp_path, monkeypatch):
    monkeypatch.setattr(event_log, "LOGS_DIR", str(tmp_path))
    (tmp_path / "2026-10-02.json").write_text("broken", encoding="utf-8")
    with pytest.raises(ValueError):
        event_log.has_recent_reminder_delivery(datetime(2026, 10, 2, 12))
    assert event_log.get_events("2026-10-02") == []
