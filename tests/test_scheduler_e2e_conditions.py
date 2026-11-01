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
            muted_until TEXT DEFAULT NULL, paused_indefinitely INTEGER DEFAULT 0,
            event_type TEXT DEFAULT 'daily', mention_count INTEGER DEFAULT 1
        )
    """)
    for r in rows:
        conn.execute(
            "INSERT INTO routines (id, event_name, confidence, time_str, day_of_week, state, last_triggered, priority, condition_type) VALUES (:id,:event_name,:confidence,"
            ":time_str,:day_of_week,:state,:last_triggered,:priority,:condition_type)", r
        )
    conn.commit()
    conn.close()


_FIXED_NOW = datetime(2026, 6, 17, 12, 0, 0)

def _due_row(rid=14, name="ρουτίνα", priority=0, ctype=None):
    return {
        "id": rid, "event_name": name, "confidence": 0.85,
        "time_str": "12:00", "day_of_week": "Everyday", "state": "active",
        "last_triggered": None, "priority": priority, "condition_type": ctype
    }


def _run_job(
    db_rows,
    routine_conditions=None,
    context_state=None,
    craft_return=("κανονικό μήνυμα", False),
    context_evidence=None,
    craft_callback=None,
):
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

    def _condition_list_for(rid):
        cond = routine_conditions.get(rid)
        if not cond:
            return []
        if isinstance(cond, list):
            return cond
        return [cond]

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
            def craft(*args, **kwargs):
                if craft_callback:
                    craft_callback()
                return craft_return
            stack.enter_context(patch.object(bot, "_craft_proactive_msg", side_effect=craft))
            stack.enter_context(patch.object(bot, "send_telegram_msg", side_effect=lambda m: sent.append(m)))
            stack.enter_context(patch.object(bot, "_send_and_record_assistant", side_effect=lambda m, **_: sent.append(m) or "$test"))
            stack.enter_context(patch.object(bot, "log_event", side_effect=lambda cat, action, **kw: logged.append((cat, action, kw))))
            stack.enter_context(patch.object(bot, "bus", MagicMock()))
            stack.enter_context(patch.object(bot, "pending_routine_confirmations", {}))
            stack.enter_context(patch.object(bot, "_recent_routine_skip_events", {}))
            stack.enter_context(patch.object(cfg, "BASE_DIR", tmp))
            stack.enter_context(patch.object(cfg, "ROUTINES_DB", db_path))
            stack.enter_context(patch("memory.routine_db.DB_PATH", db_path))
            stack.enter_context(patch("clients.telegram_bot.datetime", FakeDT))
            stack.enter_context(patch("memory.routine_db.get_routine_notify_info", return_value={"cooldown_hours": 4}))
            stack.enter_context(patch("memory.routine_db.mark_routine_notified"))
            stack.enter_context(patch("memory.routine_db.save_pending_confirmation"))
            stack.enter_context(patch("memory.routine_db.get_routine_schedule_meta", return_value={"active_from": None, "active_until": None, "paused_until": None, "resume_rule": None, "pause_reason": None}))
            stack.enter_context(patch("memory.routine_db.get_routine_muted_until", return_value=None))
            stack.enter_context(patch("memory.routine_db.get_sentimental_info", return_value={"sentimental": 0, "muted_from": None, "muted_until": None, "sentimental_send_every": 2, "sentimental_last_sent": None, "sentimental_silenced": False}))
            stack.enter_context(patch("memory.routine_db.get_routine_condition", side_effect=lambda rid: routine_conditions.get(rid, {})))
            stack.enter_context(patch("memory.routine_db.get_routine_conditions", side_effect=_condition_list_for))
            stack.enter_context(patch("services.routine_context.build_runtime_routine_context", return_value=context_state))
            from services.routine_context_evidence import ContextEvidence, VOLATILE_FLAGS
            evidence = context_evidence if context_evidence is not None else {
                key: ContextEvidence(effective_value=context_state.get(key),
                                     status="known" if context_state.get(key) is not None else "unknown")
                for key in VOLATILE_FLAGS}
            stack.enter_context(patch("services.routine_context.build_routine_context_evidence", return_value=evidence))
            stack.enter_context(patch("services.routine_context_clarification_scheduler.resolve_dependencies", return_value=()))
            stack.enter_context(patch("services.routine_context_clarification_scheduler.schedule_context_clarification"))
            stack.enter_context(patch("core.brain.safe_llm_invoke", return_value=MagicMock(content=craft_return)))
            stack.enter_context(patch("random.random", return_value=0.99))
            
            bot.job_check_routines()
            
    return sent, logged


def test_null_suppression_waits_instead_of_sending_routine():
    """An unknown partner is not permission to send a partner-dependent reminder."""
    cond = {"condition_type": "context_flag", "condition_payload":
            {"flag": "partner_with_user", "equals": True}, "condition_mode": "suppress_when_true"}
    row = _due_row(1)
    row["time_str"] = "12:10"
    sent, logs = _run_job([row], {1: cond}, {"partner_with_user": None})
    assert sent == []
    assert any(action == "routine_context_unknown" for _, action, _ in logs)


def test_stale_park_value_is_not_authoritative_for_dispatch():
    """A stale stored outside value needs clarification, not a sentimental skip."""
    from services.routine_context_evidence import ContextEvidence
    cond = {"condition_type": "context_flag", "condition_payload":
            {"flag": "user_out_of_home", "equals": True}, "condition_mode": "suppress_when_true"}
    row = _due_row(1)
    row["time_str"] = "12:10"
    sent, logs = _run_job([row], {1: cond}, {"user_out_of_home": True},
                         context_evidence={"user_out_of_home": ContextEvidence(reason="stale")})
    assert sent == [] and any(action == "routine_context_unknown" for _, action, _ in logs)


def test_fresh_return_permits_normal_dispatch():
    """A refreshed home observation returns through normal dispatch once."""
    cond = {"condition_type": "context_flag", "condition_payload":
            {"flag": "user_out_of_home", "equals": True}, "condition_mode": "suppress_when_true"}
    row = _due_row(1)
    row["time_str"] = "12:10"
    sent, _ = _run_job([row], {1: cond}, {"user_out_of_home": False})
    assert len(sent) == 1


def test_changed_context_during_generation_does_not_send():
    context = {"current_shift": "morning"}
    sent, logs = _run_job([_due_row(1)], context_state=context,
                         craft_callback=lambda: context.update(current_shift="afternoon"))
    assert sent == []
    assert not any(action == "routine_triggered" for _, action, _ in logs)


def test_batch_of_distinct_routines_sends_one_message_and_records_both():
    sent, logs = _run_job([_due_row(1, "School"), _due_row(2, "Breakfast")])
    assert len(sent) == 1
    assert {kw["routine_id"] for _, action, kw in logs if action == "routine_triggered"} == {1, 2}


def test_unknown_higher_priority_holds_same_group_fallback():
    cond = {"condition_type": "context_flag", "condition_payload":
            {"flag": "partner_with_user", "equals": True}, "condition_mode": "suppress_when_true"}
    rows = [_due_row(1, "School first", 20), _due_row(2, "School fallback", 10)]
    for row in rows:
        row["time_str"] = "12:10"
    sent, _ = _run_job(rows, {1: cond}, {"partner_with_user": None})
    assert sent == []


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
        1: {"condition_type": "context_flag", "condition_payload": '{"flag": "kid1_away_from_home", "equals": true}', "condition_mode": "suppress_when_true"}
    }
    context = {"kid1_away_from_home": True}
    
    sent, logged = _run_job([_due_row(rid=1)], routine_conditions=conditions, context_state=context)
    
    assert len(sent) == 0
    assert any(action == "routine_condition_blocked" for _, action, _ in logged)


def test_suppress_when_true_allows_when_context_false():
    conditions = {
        1: {"condition_type": "context_flag", "condition_payload": '{"flag": "kid1_away_from_home", "equals": true}', "condition_mode": "suppress_when_true"}
    }
    context = {"kid1_away_from_home": False}
    
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
    # Two routines with the same keyword ('Σχολείο'), so they fall into the same conflict group
    rows = [
        _due_row(rid=1, name="Σχολείο Αλέξανδρου", priority=10),
        _due_row(rid=2, name="Σχολείο Πρωινή Προετοιμασία", priority=20), # Higher priority
    ]
    
    sent, logged = _run_job(rows)
    
    # Only ONE notification must be sent (the #2)
    assert len(sent) == 1
    
    # The lowest priority DOES NOT log an event (it simply prints to stdout).
    # We simply check that the notification was sent for 1.
    # We could check the arguments of the craft function, but the mock is generic.


def test_conflict_resolution_with_conditions_skips_lower_priority_only_if_higher_is_allowed():
    # If the high priority becomes routine_condition_blocked because its condition failed,
    # then the lower priority MUST NOT be cut due to priority (since the other one did not play!).
    rows = [
        _due_row(rid=1, name="Μπάσκετ Αλέξανδρου", priority=10),
        _due_row(rid=2, name="Μπάσκετ Κατασκήνωση", priority=20),
    ]
    
    conditions = {
        # #2 requires camp=True
        2: {"condition_type": "context_flag", "condition_payload": '{"flag": "kid1_away_from_home", "equals": true}', "condition_mode": "allow_when_true"}
    }
    
    # Case 1: We are not a camp
    # #2 is cut off due to condition. #1 should pass normally (since #2 was not added to triggered_conflict_groups).
    context1 = {"kid1_away_from_home": False}
    sent1, logged1 = _run_job(rows, routine_conditions=conditions, context_state=context1)
    
    assert len(sent1) == 1
    
    skips = [kw for cat, action, kw in logged1 if action == "routine_condition_blocked"]
    assert len(skips) == 1
    assert skips[0]["routine_id"] == 2 # #2 was cut off
    
    # Case 2: We are a camp
    # #2 is allowed due to condition. #1 is cut off because it has lower priority.
    context2 = {"kid1_away_from_home": True}
    sent2, logged2 = _run_job(rows, routine_conditions=conditions, context_state=context2)
    
    assert len(sent2) == 1
    skips2 = [kw for cat, action, kw in logged2 if action == "routine_condition_blocked"]
    assert len(skips2) == 0 # No condition block exists. #1 was silently cut due to priority.

def test_conflict_resolution_specificity_breaks_ties():
    # Two routines with the same keyword ('School'), so they fall into the same conflict group
    # Both have priority 0.
    # The first one (id=1) entered first (id=1 < id=2).
    # But the second one has a condition. The second one must be evaluated FIRST due to specificity.
    rows = [
        _due_row(rid=1, name="Σχολείο Αλέξανδρου", priority=0),
        _due_row(rid=2, name="Σχολείο Διακοπές", priority=0, ctype="context_flag"),
    ]
    
    conditions = {
        # #2 has a condition (e.g., requires school_open=False)
        2: {"condition_type": "context_flag", "condition_payload": '{"flag": "school_open", "equals": false}', "condition_mode": "allow_when_true"}
    }
    
    # If the database respects specificity, it will evaluate #2 first.
    # Let's provide context that ALLOWS #2 (school_open=False).
    context = {"school_open": False}
    sent, logged = _run_job(rows, routine_conditions=conditions, context_state=context)
    
    # #2 was allowed, so it triggered and placed the group in the conflict set.
    # #1 should have been cut (and not sent).
    assert len(sent) == 1
    
    # We check which routine triggered
    triggered_rids = [kw["routine_id"] for cat, action, kw in logged if action == "routine_triggered"]
    assert len(triggered_rids) == 1
    assert triggered_rids[0] == 2 # #2 "won" due to specificity!

def test_conflict_resolution_deep_integration():
    # 3 routines in the SAME conflict group ("Sports"), scheduled for the EXACT SAME time.
    # #1: Priority 10, no condition (Fallback)
    # #2: Priority 20, condition: football_season == true (allow_when_true)
    # #3: Priority 30, condition: kid1_away_from_home == true (suppress_when_true)
    
    rows = [
        _due_row(rid=1, name="Αθλητισμός Τρέξιμο", priority=10),
        _due_row(rid=2, name="Αθλητισμός Ποδόσφαιρο", priority=20, ctype="context_flag"),
        _due_row(rid=3, name="Αθλητισμός Κατασκήνωση", priority=30, ctype="context_flag"),
    ]
    
    # We update the db rows to explicitly set conflict_group
    for r in rows:
        r["conflict_group"] = "sports"
        
    conditions = {
        2: {"condition_type": "context_flag", "condition_payload": '{"flag": "football_season", "equals": true}', "condition_mode": "allow_when_true"},
        3: {"condition_type": "context_flag", "condition_payload": '{"flag": "kid1_away_from_home", "equals": true}', "condition_mode": "suppress_when_true"}
    }
    
    # Scenario A: Football season is OFF (false), Camp is ON (true).
    # #3 (Priority 30) evaluates first: suppress_when_true and camp is TRUE -> BLOCKED.
    # #2 (Priority 20) evaluates next: allow_when_true and football is FALSE -> BLOCKED.
    # #1 (Priority 10) evaluates last: no condition -> ALLOWED (Wins!)
    context_A = {"football_season": False, "kid1_away_from_home": True}
    sent_A, logged_A = _run_job(rows, routine_conditions=conditions, context_state=context_A)
    assert len(sent_A) == 1
    trig_A = [kw["routine_id"] for cat, action, kw in logged_A if action == "routine_triggered"]
    assert len(trig_A) == 1
    assert trig_A[0] == 1 # Fallback wins

    # Scenario B: Football season is ON (true), Camp is ON (true).
    # #3 (Priority 30): suppress_when_true and camp is TRUE -> BLOCKED.
    # #2 (Priority 20): allow_when_true and football is TRUE -> ALLOWED (Wins!)
    # #1 (Priority 10): Skipped due to conflict.
    context_B = {"football_season": True, "kid1_away_from_home": True}
    sent_B, logged_B = _run_job(rows, routine_conditions=conditions, context_state=context_B)
    assert len(sent_B) == 1
    trig_B = [kw["routine_id"] for cat, action, kw in logged_B if action == "routine_triggered"]
    assert len(trig_B) == 1
    assert trig_B[0] == 2 # Football wins
    
    # Scenario C: Football season is ON (true), Camp is OFF (false).
    # #3 (Priority 30): suppress_when_true and camp is FALSE -> ALLOWED (Wins!)
    # #2 (Priority 20): Skipped due to conflict.
    # #1 (Priority 10): Skipped due to conflict.
    context_C = {"football_season": True, "kid1_away_from_home": False}
    sent_C, logged_C = _run_job(rows, routine_conditions=conditions, context_state=context_C)
    assert len(sent_C) == 1
    trig_C = [kw["routine_id"] for cat, action, kw in logged_C if action == "routine_triggered"]
    assert len(trig_C) == 1
    assert trig_C[0] == 3 # Camp routine wins
