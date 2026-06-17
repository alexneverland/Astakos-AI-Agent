import os
import sqlite3
import tempfile
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest


def _make_routines_db(path, rows):
    conn = sqlite3.connect(path)
    conn.execute("""
        CREATE TABLE routines ( priority INTEGER DEFAULT 0, conflict_group TEXT, condition_type TEXT, condition_payload TEXT, condition_mode TEXT, source_memory_ref TEXT,
            id INTEGER PRIMARY KEY, event_name TEXT, confidence REAL,
            time_str TEXT, day_of_week TEXT, state TEXT, last_triggered TEXT,
            muted_until TEXT DEFAULT NULL
        )
    """)
    for r in rows:
        conn.execute(
            "INSERT INTO routines (id, event_name, confidence, time_str, day_of_week, state, last_triggered, priority) VALUES (:id,:event_name,:confidence,"
            ":time_str,:day_of_week,:state,:last_triggered,:priority)", r
        )
    conn.commit()
    conn.close()


_FIXED_NOW = datetime(2026, 6, 17, 12, 0, 0)

def _due_row(rid=14, name="ρουτίνα", priority=0):
    return {
        "id": rid, "event_name": name, "confidence": 0.85,
        "time_str": "12:30", "day_of_week": "Everyday", "state": "active",
        "last_triggered": None, "priority": priority
    }


def _run_job(db_rows, routine_conditions=None, context_state=None, craft_return="κανονικό μήνυμα"):
    import clients.telegram_bot as bot
    import config as cfg

    class FakeDT(datetime):
        @classmethod
        def now(cls, tz=None):
            return _FIXED_NOW

    sent = []
    logged = []

    if routine_conditions is None:
        routine_conditions = {}
        
    if context_state is None:
        context_state = {}

    with tempfile.TemporaryDirectory() as tmp:
        db_path = os.path.join(tmp, "astakos_routines.db")
        _make_routines_db(db_path, db_rows)

        import contextlib
        with contextlib.ExitStack() as stack:
            stack.enter_context(patch.object(bot, "is_quiet_hours", return_value=False))
            stack.enter_context(patch.object(bot, "is_proactive_muted", return_value=False))
            stack.enter_context(patch.object(bot, "is_duplicate_routine", return_value=False))
            stack.enter_context(patch.object(bot, "can_send_proactive", return_value=True))
            stack.enter_context(patch.object(bot, "should_skip_proactive_for_recent_activity", return_value=False))
            stack.enter_context(patch.object(bot, "_craft_proactive_msg", return_value=craft_return))
            stack.enter_context(patch.object(bot, "send_telegram_msg", side_effect=lambda m: sent.append(m)))
            stack.enter_context(patch.object(bot, "log_event", side_effect=lambda cat, action, **kw: logged.append((cat, action, kw))))
            stack.enter_context(patch.object(bot, "bus", MagicMock()))
            stack.enter_context(patch.object(bot, "pending_routine_confirmations", {}))
            stack.enter_context(patch.object(cfg, "BASE_DIR", tmp))
            stack.enter_context(patch("clients.telegram_bot.datetime", FakeDT))
            stack.enter_context(patch("memory.routine_db.get_routine_notify_info", return_value={"cooldown_hours": 4}))
            stack.enter_context(patch("memory.routine_db.mark_routine_notified"))
            stack.enter_context(patch("memory.routine_db.save_pending_confirmation"))
            stack.enter_context(patch("memory.routine_db.get_routine_schedule_meta", return_value={"active_from": None, "active_until": None, "paused_until": None, "resume_rule": None, "pause_reason": None}))
            stack.enter_context(patch("memory.routine_db.get_routine_muted_until", return_value=None))
            stack.enter_context(patch("memory.routine_db.get_sentimental_info", return_value={"sentimental": 0, "muted_from": None, "muted_until": None, "sentimental_send_every": 2, "sentimental_last_sent": None, "sentimental_silenced": False}))
            stack.enter_context(patch("memory.routine_db.get_routine_condition", side_effect=lambda rid: routine_conditions.get(rid, {})))
            stack.enter_context(patch("services.routine_context.build_runtime_routine_context", return_value=context_state))
            stack.enter_context(patch("core.brain.safe_llm_invoke", return_value=MagicMock(content=craft_return)))
            
            bot.job_check_routines()
            
    return sent, logged


def test_require_true_allows_when_context_true():
    conditions = {
        1: {"condition_type": "context_flag", "condition_payload": '{"flag": "school_open", "equals": true}', "condition_mode": "allow_when_true"}
    }
    context = {"school_open": True}
    
    sent, logged = _run_job([_due_row(rid=1)], routine_conditions=conditions, context_state=context)
    
    assert len(sent) == 1
    assert not any(action == "routine_condition_blocked" for _, action, _ in logged)


def test_require_true_skips_when_context_false():
    conditions = {
        1: {"condition_type": "context_flag", "condition_payload": '{"flag": "school_open", "equals": true}', "condition_mode": "allow_when_true"}
    }
    context = {"school_open": False}
    
    sent, logged = _run_job([_due_row(rid=1)], routine_conditions=conditions, context_state=context)
    
    assert len(sent) == 0
    assert any(action == "routine_condition_blocked" for _, action, _ in logged)


def test_suppress_when_true_skips_when_context_true():
    conditions = {
        1: {"condition_type": "context_flag", "condition_payload": '{"flag": "alexandros_at_camp", "equals": true}', "condition_mode": "suppress_when_true"}
    }
    context = {"alexandros_at_camp": True}
    
    sent, logged = _run_job([_due_row(rid=1)], routine_conditions=conditions, context_state=context)
    
    assert len(sent) == 0
    assert any(action == "routine_condition_blocked" for _, action, _ in logged)


def test_suppress_when_true_allows_when_context_false():
    conditions = {
        1: {"condition_type": "context_flag", "condition_payload": '{"flag": "alexandros_at_camp", "equals": true}', "condition_mode": "suppress_when_true"}
    }
    context = {"alexandros_at_camp": False}
    
    sent, logged = _run_job([_due_row(rid=1)], routine_conditions=conditions, context_state=context)
    
    assert len(sent) == 1
    assert not any(action == "routine_condition_blocked" for _, action, _ in logged)


def test_shift_mode_require_true():
    conditions = {
        1: {"condition_type": "shift_mode", "condition_payload": '{"flag": "current_shift", "equals": "morning"}', "condition_mode": "allow_when_true"}
    }
    context = {"current_shift": "morning"}
    sent, _ = _run_job([_due_row(rid=1)], routine_conditions=conditions, context_state=context)
    assert len(sent) == 1
    
    context2 = {"current_shift": "afternoon"}
    sent2, _ = _run_job([_due_row(rid=1)], routine_conditions=conditions, context_state=context2)
    assert len(sent2) == 0


def test_conflict_resolution_priority_higher_wins():
    # Δύο ρουτίνες με ίδιο keyword ('Σχολείο'), οπότε πέφτουν στο ίδιο conflict group
    rows = [
        _due_row(rid=1, name="Σχολείο Αλέξανδρου", priority=10),
        _due_row(rid=2, name="Σχολείο Πρωινή Προετοιμασία", priority=20), # Υψηλότερο priority
    ]
    
    sent, logged = _run_job(rows)
    
    # Πρέπει να σταλεί μόνο ΜΙΑ ειδοποίηση (η #2)
    assert len(sent) == 1
    
    # Η χαμηλότερη priority ΔΕΝ κάνει log event (απλά τυπώνει στο stdout).
    # Ελέγχουμε απλά ότι η ειδοποίηση εστάλη για την 1.
    # Θα μπορούσαμε να ελέγξουμε το arguments του craft function αλλά το mock είναι generic.


def test_conflict_resolution_with_conditions_skips_lower_priority_only_if_higher_is_allowed():
    # Αν η high priority γίνει routine_condition_blocked επειδή το condition της απέτυχε, 
    # τότε η χαμηλότερη priority ΔΕΝ πρέπει να κοπεί λόγω priority (αφού η άλλη δεν έπαιξε!).
    rows = [
        _due_row(rid=1, name="Μπάσκετ Αλέξανδρου", priority=10),
        _due_row(rid=2, name="Μπάσκετ Κατασκήνωση", priority=20),
    ]
    
    conditions = {
        # Η #2 απαιτεί camp=True
        2: {"condition_type": "context_flag", "condition_payload": '{"flag": "alexandros_at_camp", "equals": true}', "condition_mode": "allow_when_true"}
    }
    
    # Περίπτωση 1: Δεν είμαστε camp
    # Η #2 κόβεται λόγω condition. Η #1 πρέπει να περάσει κανονικά (αφού δεν προστέθηκε στο triggered_conflict_groups η #2).
    context1 = {"alexandros_at_camp": False}
    sent1, logged1 = _run_job(rows, routine_conditions=conditions, context_state=context1)
    
    assert len(sent1) == 1
    
    skips = [kw for cat, action, kw in logged1 if action == "routine_condition_blocked"]
    assert len(skips) == 1
    assert skips[0]["routine_id"] == 2 # Η #2 κόπηκε
    
    # Περίπτωση 2: Είμαστε camp
    # Η #2 επιτρέπεται λόγω condition. Η #1 κόβεται επειδή έχει μικρότερο priority.
    context2 = {"alexandros_at_camp": True}
    sent2, logged2 = _run_job(rows, routine_conditions=conditions, context_state=context2)
    
    assert len(sent2) == 1
    skips2 = [kw for cat, action, kw in logged2 if action == "routine_condition_blocked"]
    assert len(skips2) == 0 # Δεν υπάρχει condition block. Η #1 κόπηκε αθόρυβα λόγω priority.
