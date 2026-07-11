# ================================================================
# Tests: Case F — one inactive (paused / outside active window) routine
# MUST NOT produce missed/failure side effects.
#
# Style: real-module patching (like test_event_log_and_missed_routines.py).
# Important: We do NOT mock is_routine_temporarily_inactive_meta —
# runs the ACTUAL function (genuine integration test of the date-based
# logic), only get_routine_schedule_meta is mocked so that we do not_
# touch the real DB.
# ================================================================
import os
import sqlite3
import tempfile
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


_FIXED_NOW = datetime(2026, 6, 17, 12, 0, 0)  # Wednesday — same "today" as test_routine_schedule_meta.py

_PAUSED_META = {
    "active_from": None, "active_until": None,
    "paused_until": "2026-09-01", "resume_rule": "every_september",
    "pause_reason": "summer_break",
}
_BEFORE_ACTIVE_FROM_META = {
    "active_from": "2026-09-01", "active_until": None,
    "paused_until": None, "resume_rule": None, "pause_reason": None,
}
_ACTIVE_META = {
    "active_from": None, "active_until": None,
    "paused_until": None, "resume_rule": None, "pause_reason": None,
}


# ────────────────────────────────────────────────────────────────
# startup_check_missed_routines()
# ────────────────────────────────────────────────────────────────

def _run_missed(db_rows, schedule_meta, grace=90, craft_return="deferred_msg"):
    """
    Runs the actual startup_check_missed_routines() on a real sqlite DB,
    with only get_routine_schedule_meta mocked (is_routine_temporarily_inactive_meta
    is the REAL one).
    Returns: (sent, logged, mark_notified_calls, save_pending_calls)
    """
    import clients.telegram_bot as bot
    import config as cfg

    class FakeDT(datetime):
        @classmethod
        def now(cls, tz=None):
            return _FIXED_NOW

    sent = []
    logged = []
    mark_notified_calls = []
    save_pending_calls = []

    with tempfile.TemporaryDirectory() as tmp:
        db_path = os.path.join(tmp, "astakos_routines.db")
        _make_routines_db(db_path, db_rows)

        with (
            patch.object(bot, "is_quiet_hours",       return_value=False),
            patch.object(bot, "is_proactive_muted",   return_value=False),
            patch.object(bot, "is_duplicate_routine", return_value=False),
            patch.object(bot, "_craft_deferred_msg",  return_value=craft_return),
            patch.object(bot, "send_telegram_msg",    side_effect=lambda m: sent.append(m)),
            patch.object(bot, "log_event",
                          side_effect=lambda cat, action, **kw: logged.append((cat, action, kw))),
            patch.object(bot, "bus", MagicMock()),
            patch.object(bot, "pending_routine_confirmations", {}),
            patch.object(cfg, "BASE_DIR",                   tmp),
            patch.object(cfg, "ROUTINE_MISS_GRACE_MINUTES", grace),
            patch("clients.telegram_bot.datetime", FakeDT),
            patch("memory.routine_db.get_routine_notify_info",
                  return_value={"cooldown_hours": 4}),
            patch("memory.routine_db.mark_routine_notified",
                  side_effect=lambda rid: mark_notified_calls.append(rid)),
            patch("memory.routine_db.save_pending_confirmation",
                  side_effect=lambda *a, **kw: save_pending_calls.append(a)),
            patch("memory.routine_db.get_routine_schedule_meta",
                  return_value=schedule_meta),
        ):
            bot.startup_check_missed_routines()

    return sent, logged, mark_notified_calls, save_pending_calls


def _missed_row(**kw):
    defaults = dict(
        id=13, event_name="ποδόσφαιρο Αλέξανδρου", confidence=0.8,
        time_str="11:30", day_of_week="Everyday", state="active", last_triggered=None,
    )
    defaults.update(kw)
    return defaults


def test_missed_paused_routine_sends_no_message():
    sent, _, _, _ = _run_missed([_missed_row()], _PAUSED_META)
    assert sent == []


def test_missed_paused_routine_logs_inactive_skip_with_reason():
    _, logged, _, _ = _run_missed([_missed_row()], _PAUSED_META)
    inactive_events = [(cat, action, kw) for cat, action, kw in logged if action == "routine_inactive_skip"]
    assert len(inactive_events) == 1
    _, _, kw = inactive_events[0]
    assert kw["reason"] == "paused_until"
    assert kw["paused_until"] == "2026-09-01"
    assert kw["routine_id"] == 13


def test_missed_paused_routine_does_not_mark_notified_or_pending():
    """Case F: no missed/failure side effect — it is not considered 'lost'."""
    _, _, mark_notified_calls, save_pending_calls = _run_missed([_missed_row()], _PAUSED_META)
    assert mark_notified_calls == []
    assert save_pending_calls == []


def test_missed_paused_routine_does_not_update_last_triggered():
    """Case F: last_triggered does NOT change for an inactive routine (proceed with continue before the UPDATE)."""
    with tempfile.TemporaryDirectory() as tmp:
        db_path = os.path.join(tmp, "astakos_routines.db")
        _make_routines_db(db_path, [_missed_row(last_triggered=None)])

        import clients.telegram_bot as bot
        import config as cfg

        class FakeDT(datetime):
            @classmethod
            def now(cls, tz=None):
                return _FIXED_NOW

        with (
            patch.object(bot, "is_quiet_hours",       return_value=False),
            patch.object(bot, "is_proactive_muted",   return_value=False),
            patch.object(bot, "is_duplicate_routine", return_value=False),
            patch.object(bot, "send_telegram_msg",    return_value=None),
            patch.object(bot, "log_event",            return_value=None),
            patch.object(bot, "bus", MagicMock()),
            patch.object(bot, "pending_routine_confirmations", {}),
            patch.object(cfg, "BASE_DIR",                   tmp),
            patch.object(cfg, "ROUTINE_MISS_GRACE_MINUTES", 90),
            patch("clients.telegram_bot.datetime", FakeDT),
            patch("memory.routine_db.get_routine_schedule_meta", return_value=_PAUSED_META),
        ):
            bot.startup_check_missed_routines()

        conn = sqlite3.connect(db_path)
        row_after = conn.execute("SELECT last_triggered FROM routines WHERE id=13").fetchone()
        conn.close()

    assert row_after[0] is None, f"last_triggered δεν έπρεπε να αλλάξει, είναι: {row_after[0]}"


def test_missed_before_active_from_also_skips():
    """Another reason (before_active_from) — also not considered missed."""
    sent, logged, mark_notified_calls, save_pending_calls = _run_missed(
        [_missed_row()], _BEFORE_ACTIVE_FROM_META
    )
    assert sent == []
    assert mark_notified_calls == []
    assert save_pending_calls == []
    assert any(action == "routine_inactive_skip" and kw["reason"] == "before_active_from"
               for _, action, kw in logged)


def test_missed_active_routine_still_processed_normally_baseline():
    """Regression baseline: an ACTIVE routine continues to work as before."""
    sent, logged, mark_notified_calls, save_pending_calls = _run_missed(
        [_missed_row()], _ACTIVE_META, craft_return="Πάμε ποδόσφαιρο;"
    )
    assert sent == ["Πάμε ποδόσφαιρο;"]
    assert mark_notified_calls == [13]
    assert len(save_pending_calls) == 1
    assert not any(action == "routine_inactive_skip" for _, action, _ in logged)


# ────────────────────────────────────────────────────────────────
# job_check_routines()
# ────────────────────────────────────────────────────────────────

def _run_job(db_rows, schedule_meta, cooldown=False):
    """
    Runs the actual job_check_routines() on a real sqlite DB,
    with only get_routine_schedule_meta mocked.
    Returns: (sent, logged, mark_notified_calls, save_pending_calls)
    """
    import clients.telegram_bot as bot
    import config as cfg

    class FakeDT(datetime):
        @classmethod
        def now(cls, tz=None):
            return _FIXED_NOW

    sent = []
    logged = []
    mark_notified_calls = []
    save_pending_calls = []

    with tempfile.TemporaryDirectory() as tmp:
        db_path = os.path.join(tmp, "astakos_routines.db")
        _make_routines_db(db_path, db_rows)

        with (
            patch.object(bot, "is_quiet_hours",        return_value=False),
            patch.object(bot, "is_proactive_muted",    return_value=False),
            patch.object(bot, "is_duplicate_routine",  return_value=cooldown),
            patch.object(bot, "can_send_proactive",    return_value=True),
            patch.object(bot, "send_telegram_msg",     side_effect=lambda m: sent.append(m)),
            patch.object(bot, "log_event",
                          side_effect=lambda cat, action, **kw: logged.append((cat, action, kw))),
            patch.object(bot, "_should_log_routine_skip", return_value=True),
            patch.object(bot, "bus", MagicMock()),
            patch.object(bot, "pending_routine_confirmations", {}),
            patch.object(cfg, "BASE_DIR", tmp),
            patch("clients.telegram_bot.datetime", FakeDT),
            patch("memory.routine_db.get_routine_notify_info",
                  return_value={"cooldown_hours": 4}),
            patch("memory.routine_db.get_routine_muted_until", return_value=None),
            patch("memory.routine_db.mark_routine_notified",
                  side_effect=lambda rid: mark_notified_calls.append(rid)),
            patch("memory.routine_db.save_pending_confirmation",
                  side_effect=lambda *a, **kw: save_pending_calls.append(a)),
            patch("memory.routine_db.get_routine_schedule_meta",
                  return_value=schedule_meta),
            patch("memory.routine_db.get_routine_condition", return_value={}),
            patch("memory.routine_db.get_routine_conditions", return_value=[]),
        ):
            bot.job_check_routines()

    return sent, logged, mark_notified_calls, save_pending_calls


def _due_row(**kw):
    """Routine at target_time = _FIXED_NOW + 10min, i.e., time_str = '12:10'."""
    target = _FIXED_NOW + timedelta(minutes=10)
    defaults = dict(
        id=14, event_name="ποδόσφαιρο Αλέξανδρου", confidence=0.85,
        time_str=target.strftime("%H:%M"), day_of_week="Everyday",
        state="active", last_triggered=None,
    )
    defaults.update(kw)
    return defaults


def test_job_paused_routine_sends_no_message():
    sent, _, _, _ = _run_job([_due_row()], _PAUSED_META)
    assert sent == []


def test_job_paused_routine_logs_inactive_skip():
    _, logged, _, _ = _run_job([_due_row()], _PAUSED_META)
    inactive_events = [(cat, action, kw) for cat, action, kw in logged if action == "routine_inactive_skip"]
    assert len(inactive_events) == 1
    _, _, kw = inactive_events[0]
    assert kw["reason"] == "paused_until"
    assert kw["routine_id"] == 14


def test_job_paused_routine_does_not_mark_notified_or_pending():
    """Case F: no missed/failure side effects in the proactive scheduler."""
    _, _, mark_notified_calls, save_pending_calls = _run_job([_due_row()], _PAUSED_META)
    assert mark_notified_calls == []
    assert save_pending_calls == []


def test_job_paused_routine_does_not_update_last_triggered():
    """Case F: last_triggered remains unchanged — the inactive routine continues before any UPDATE."""
    with tempfile.TemporaryDirectory() as tmp:
        db_path = os.path.join(tmp, "astakos_routines.db")
        _make_routines_db(db_path, [_due_row(last_triggered=None)])

        import clients.telegram_bot as bot
        import config as cfg

        class FakeDT(datetime):
            @classmethod
            def now(cls, tz=None):
                return _FIXED_NOW

        with (
            patch.object(bot, "is_quiet_hours",       return_value=False),
            patch.object(bot, "is_proactive_muted",   return_value=False),
            patch.object(bot, "is_duplicate_routine", return_value=False),
            patch.object(bot, "can_send_proactive",   return_value=True),
            patch.object(bot, "send_telegram_msg",    return_value=None),
            patch.object(bot, "log_event",            return_value=None),
            patch.object(bot, "bus", MagicMock()),
            patch.object(bot, "pending_routine_confirmations", {}),
            patch.object(cfg, "BASE_DIR", tmp),
            patch("clients.telegram_bot.datetime", FakeDT),
            patch("memory.routine_db.get_routine_muted_until", return_value=None),
            patch("memory.routine_db.get_routine_schedule_meta", return_value=_PAUSED_META),
        ):
            bot.job_check_routines()

        conn = sqlite3.connect(db_path)
        row_after = conn.execute("SELECT last_triggered FROM routines WHERE id=14").fetchone()
        conn.close()

    assert row_after[0] is None, f"last_triggered δεν έπρεπε να αλλάξει, είναι: {row_after[0]}"


def test_job_active_routine_still_reaches_cooldown_check_baseline():
    """
    Regression baseline: an active routine is NOT blocked by inactive-check —
    it proceeds normally to cooldown filtering (which we force to succeed here,
    simply to prove that the flow continued after is_routine_temporarily_inactive_meta).
    """
    _, logged, _, _ = _run_job([_due_row()], _ACTIVE_META, cooldown=True)
    assert not any(action == "routine_inactive_skip" for _, action, _ in logged)
    assert any(action == "routine_cooldown_skip" for _, action, kw in logged)


if __name__ == "__main__":
    import traceback
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    passed = failed = 0
    for fn in tests:
        try:
            fn()
            print(f"  PASS  {fn.__name__}")
            passed += 1
        except Exception as e:
            print(f"  FAIL  {fn.__name__}: {e}")
            traceback.print_exc()
            failed += 1
    print(f"\n{passed} passed, {failed} failed")
