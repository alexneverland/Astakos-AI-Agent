# ================================================================
# Tests: event_log atomic write + startup_check_missed_routines
# ================================================================
import json
import os
import sqlite3
import tempfile
import threading
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest


def _make_routines_db(path, rows):
    conn = sqlite3.connect(path)
    conn.execute("""
        CREATE TABLE routines ( priority INTEGER DEFAULT 0, conflict_group TEXT, condition_type TEXT, condition_payload TEXT, condition_mode TEXT,
            id INTEGER PRIMARY KEY, event_name TEXT, confidence REAL,
            time_str TEXT, day_of_week TEXT, state TEXT, last_triggered TEXT
        )
    """)
    for r in rows:
        conn.execute(
            "INSERT INTO routines (id, event_name, confidence, time_str, day_of_week, state, last_triggered) VALUES (:id,:event_name,:confidence,"
            ":time_str,:day_of_week,:state,:last_triggered)", r
        )
    conn.commit()
    conn.close()


def _run_missed(db_rows, fixed_now, grace=90, quiet=False, muted=False, cooldown=False):
    """
    Calls startup_check_missed_routines() against a real sqlite DB
    with all external side-effects mocked.
    Returns the list of messages passed to send_telegram_msg.

    BASE_DIR and ROUTINE_MISS_GRACE_MINUTES are imported *from config*
    inside the function, so we patch them at the source module (config).
    """
    import clients.telegram_bot as bot
    import config as cfg

    class FakeDT(datetime):
        @classmethod
        def now(cls, tz=None):
            return fixed_now

    sent = []
    with tempfile.TemporaryDirectory() as tmp:
        db_path = os.path.join(tmp, "astakos_routines.db")
        _make_routines_db(db_path, db_rows)

        with (
            patch.object(bot, "is_quiet_hours",       return_value=quiet),
            patch.object(bot, "is_proactive_muted",   return_value=muted),
            patch.object(bot, "is_duplicate_routine", return_value=cooldown),
            patch.object(bot, "_craft_deferred_msg",  return_value="deferred_msg"),
            patch.object(bot, "send_telegram_msg",    side_effect=lambda m: sent.append(m)),
            patch.object(bot, "log_event"),
            patch.object(bot, "bus", MagicMock()),
            patch.object(bot, "pending_routine_confirmations", {}),
            patch.object(cfg, "BASE_DIR",                   tmp),
            patch.object(cfg, "ROUTINES_DB", db_path),
            patch.object(cfg, "ROUTINE_MISS_GRACE_MINUTES", grace),
            patch("clients.telegram_bot.datetime", FakeDT),
            patch("memory.routine_db.get_routine_notify_info",
                  return_value={"cooldown_hours": 4}),
            patch("memory.routine_db.mark_routine_notified"),
            patch("memory.routine_db.save_pending_confirmation"),
            patch("memory.routine_db.get_routine_schedule_meta",
                  return_value={"active_from": None, "active_until": None,
                                "paused_until": None, "resume_rule": None, "pause_reason": None}),
        ):
            bot.startup_check_missed_routines()

    return sent


# ────────────────────────────────────────────────────────────────
# event_log: atomic write
# ────────────────────────────────────────────────────────────────

class TestEventLogAtomicWrite:

    def setup_method(self):
        self._tmp = tempfile.mkdtemp()
        self._patcher = patch("memory.event_log.LOGS_DIR", self._tmp)
        self._patcher.start()

    def teardown_method(self):
        self._patcher.stop()

    def _log_path(self):
        return os.path.join(self._tmp, datetime.now().strftime("%Y-%m-%d") + ".json")

    def test_creates_valid_json_and_cleans_tmp(self):
        """Successful write produces valid JSON; .tmp file must not remain."""
        from memory.event_log import log_event
        log_event("test_job", "sent", routine_id=1)

        log_path = self._log_path()
        assert os.path.exists(log_path)
        assert not os.path.exists(log_path + ".tmp"), ".tmp must be removed after os.replace"

        with open(log_path) as f:
            entries = json.load(f)
        assert len(entries) == 1
        assert entries[0]["job"] == "test_job"

    def test_multiple_writes_accumulate(self):
        """Each log_event call appends — entries are ordered."""
        from memory.event_log import log_event
        log_event("job_a", "triggered")
        log_event("job_b", "sent")

        with open(self._log_path()) as f:
            entries = json.load(f)
        assert len(entries) == 2
        assert entries[0]["job"] == "job_a"
        assert entries[1]["job"] == "job_b"

    def test_corrupted_log_is_recovered(self):
        """
        If the existing log file contains invalid JSON (truncated by crash),
        log_event must not raise — resets to a fresh file with the new entry.
        """
        log_path = self._log_path()
        os.makedirs(self._tmp, exist_ok=True)
        with open(log_path, "w") as f:
            f.write("[{broken json")

        from memory.event_log import log_event
        log_event("recovery_job", "sent")

        with open(log_path) as f:
            entries = json.load(f)
        assert len(entries) == 1
        assert entries[0]["job"] == "recovery_job"

    def test_concurrent_writes_thread_safe(self):
        """
        100 threads writing simultaneously must produce exactly 100 entries
        with no JSON corruption (the _log_lock serialises writes).
        """
        from memory.event_log import log_event
        errors = []

        def write_one(i):
            try:
                log_event("concurrent", "sent", index=i)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=write_one, args=(i,)) for i in range(100)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"Thread errors: {errors}"

        with open(self._log_path()) as f:
            entries = json.load(f)
        assert len(entries) == 100


# ────────────────────────────────────────────────────────────────
# startup_check_missed_routines
# ────────────────────────────────────────────────────────────────

_MON_10_30 = datetime(2026, 6, 8, 10, 30, 0)   # Monday 10:30


class TestStartupCheckMissedRoutines:

    def _row(self, **kw):
        defaults = dict(
            id=1, event_name="πάρκο", confidence=0.8,
            time_str="10:00", day_of_week="Monday",
            state="active", last_triggered=None
        )
        defaults.update(kw)
        return defaults

    def test_missed_within_grace_sends_deferred(self):
        """Routine 30 min ago (< 90 min grace) → deferred message sent."""
        sent = _run_missed([self._row(time_str="10:00")], _MON_10_30)
        assert sent == ["deferred_msg"]

    def test_missed_outside_grace_does_not_send(self):
        """Routine 150 min ago (> 90 min grace) → nothing sent."""
        sent = _run_missed([self._row(time_str="08:00")], _MON_10_30)
        assert sent == []

    def test_already_triggered_today_skips(self):
        """If last_triggered == today, the SQL WHERE filters it out."""
        sent = _run_missed(
            [self._row(time_str="10:00", last_triggered="2026-06-08")],
            _MON_10_30
        )
        assert sent == []

    def test_quiet_hours_skips_entirely(self):
        sent = _run_missed([self._row()], _MON_10_30, quiet=True)
        assert sent == []

    def test_muted_skips_entirely(self):
        sent = _run_missed([self._row()], _MON_10_30, muted=True)
        assert sent == []

    def test_cooldown_prevents_send(self):
        sent = _run_missed([self._row()], _MON_10_30, cooldown=True)
        assert sent == []

    def test_wrong_day_routine_not_sent(self):
        """A Tuesday-only routine must not fire on Monday."""
        sent = _run_missed([self._row(day_of_week="Tuesday")], _MON_10_30)
        assert sent == []

    def test_learned_state_not_sent(self):
        """Only state='active' routines are in scope."""
        sent = _run_missed([self._row(state="learned")], _MON_10_30)
        assert sent == []

    def test_future_routine_not_sent(self):
        """Routine at 11:00 has not fired yet at 10:30."""
        sent = _run_missed([self._row(time_str="11:00")], _MON_10_30)
        assert sent == []

    def test_everyday_routine_triggers_any_day(self):
        """day_of_week='Everyday' must match on any weekday."""
        sent = _run_missed([self._row(day_of_week="Everyday")], _MON_10_30)
        assert sent == ["deferred_msg"]
