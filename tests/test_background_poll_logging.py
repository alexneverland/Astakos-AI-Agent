"""Offline queue verbosity and mixed-offset reminder gate regressions."""
from datetime import datetime, timedelta, timezone
import queue
import threading

import pytest


@pytest.mark.parametrize("age,expected", [(14, True), (16, False)])
def test_recent_reminder_accepts_offset_timestamp(monkeypatch, age, expected):
    from memory import event_log
    now = datetime(2026, 10, 7, 8, 32)
    monkeypatch.setattr(event_log, "get_events", lambda *args, **kw: [
        {"job": "reminders", "timestamp":
         (now - timedelta(minutes=age)).astimezone(timezone.utc).isoformat()}])
    assert event_log.has_recent_reminder_delivery(now) is expected


@pytest.mark.parametrize("quiet,failed", [(True, False), (True, True), (False, False)])
def test_queue_quiet_task_still_executes_and_reports_errors(monkeypatch, capsys, quiet, failed):
    from clients import telegram_bot as bot
    stopped = threading.Event()
    calls = []
    def task():
        calls.append(True)
        stopped.set()
        if failed:
            raise RuntimeError("synthetic failure")
    task.quiet_queue_log = quiet
    tasks = queue.Queue()
    tasks.put((task, ()))
    monkeypatch.setattr(bot, "slow_queue", tasks)
    bot.slow_queue_worker(stopped)
    output = capsys.readouterr().out
    assert calls == [True] and tasks.unfinished_tasks == 0
    assert ("[SlowQueue]: task" in output) is (not quiet)
    assert ("Slow Queue Error" in output) is failed


def test_clarification_poll_is_marked_quiet():
    from services.routine_context_clarification_scheduler import run_context_clarification_job
    assert getattr(run_context_clarification_job, "quiet_queue_log", False)


def test_recent_activity_can_be_checked_without_terminal_noise(monkeypatch, capsys):
    from clients import telegram_bot as bot
    events = []
    monkeypatch.setattr(bot, "_seconds_since_user_activity", lambda: 30)
    monkeypatch.setattr(bot, "log_event", lambda *args, **kw: events.append(kw))
    assert bot.should_skip_proactive_for_recent_activity(quiet=True)
    assert capsys.readouterr().out == ""
    assert events[0]["reason"] == "recent_activity"
