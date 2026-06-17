"""
Tests για το tools.system.control_routine_schedule (pause/resume/set_window/clear_window).
Ίδιο στυλ με test_routine_control_notifications.py: monkeypatch στο πραγματικό
memory.routine_db module, κλήση μέσω .func(...) στο underlying function του @tool.
"""


def _two_routines():
    """Fixture: 2 ρουτίνες με το ίδιο όνομα (ποδόσφαιρο Αλέξανδρου, ids 13/14) —
    το ίδιο fixture pattern με test_routine_control_notifications.py / live DB."""
    return [
        {"id": 13, "event": "ποδόσφαιρο Αλέξανδρου", "day": "Monday"},
        {"id": 14, "event": "ποδόσφαιρο Αλέξανδρου", "day": "Thursday"},
    ]


# ─────────────────────────────────────────────────────────────
# G: πολλαπλές ρουτίνες με το ίδιο όνομα → action εφαρμόζεται σε ΟΛΕΣ
# ─────────────────────────────────────────────────────────────

def test_pause_applies_to_all_exact_name_matches(monkeypatch):
    import tools.system as system
    import memory.routine_db as rdb

    monkeypatch.setattr(rdb, "find_routines_by_name", lambda event_name: _two_routines())
    monkeypatch.setattr(rdb, "get_routine_schedule_meta", lambda routine_id: {
        "active_from": None, "active_until": None, "paused_until": None,
        "resume_rule": None, "pause_reason": None,
    })
    paused = []
    resume_rules = []
    monkeypatch.setattr(
        rdb, "set_routine_paused_until",
        lambda routine_id, until, reason=None: paused.append((routine_id, until, reason)),
    )
    monkeypatch.setattr(
        rdb, "set_routine_resume_rule",
        lambda routine_id, resume_rule=None: resume_rules.append((routine_id, resume_rule)),
    )

    result = system.control_routine_schedule.func(
        event_name="ποδόσφαιρο Αλέξανδρου",
        action="pause",
        until_date="2026-09-01",
        reason="summer_break",
        resume_rule="every_september",
    )

    assert paused == [
        (13, "2026-09-01", "summer_break"),
        (14, "2026-09-01", "summer_break"),
    ]
    assert resume_rules == [
        (13, "every_september"),
        (14, "every_september"),
    ]
    assert "[Monday]" in result
    assert "[Thursday]" in result


def test_pause_is_idempotent_when_already_paused_later(monkeypatch):
    """Αν είναι ήδη παγωμένη μέχρι ΜΕΤΑγενέστερη ημερομηνία, δεν κάνει τίποτα."""
    import tools.system as system
    import memory.routine_db as rdb

    monkeypatch.setattr(rdb, "find_routines_by_name", lambda event_name: _two_routines())
    monkeypatch.setattr(rdb, "get_routine_schedule_meta", lambda routine_id: {
        "active_from": None, "active_until": None, "paused_until": "2026-12-01",
        "resume_rule": None, "pause_reason": "already_set",
    })
    called = []
    monkeypatch.setattr(rdb, "set_routine_paused_until", lambda routine_id, until, reason=None: called.append(routine_id))

    result = system.control_routine_schedule.func(
        event_name="ποδόσφαιρο Αλέξανδρου",
        action="pause",
        until_date="2026-09-01",
    )

    assert called == []
    assert "δεν έκανα τίποτα" in result


# ─────────────────────────────────────────────────────────────
# H: resume αφαιρεί την παύση
# ─────────────────────────────────────────────────────────────

def test_resume_clears_paused_state_for_all_matches(monkeypatch):
    import tools.system as system
    import memory.routine_db as rdb

    monkeypatch.setattr(rdb, "find_routines_by_name", lambda event_name: _two_routines())
    cleared = []
    monkeypatch.setattr(rdb, "clear_routine_paused_until", lambda routine_id: cleared.append(routine_id))

    result = system.control_routine_schedule.func(
        event_name="ποδόσφαιρο Αλέξανδρου",
        action="resume",
    )

    assert cleared == [13, 14]
    assert "[Monday]" in result
    assert "[Thursday]" in result


# ─────────────────────────────────────────────────────────────
# set_window / clear_window
# ─────────────────────────────────────────────────────────────

def test_set_window_applies_to_all_matches(monkeypatch):
    import tools.system as system
    import memory.routine_db as rdb

    monkeypatch.setattr(rdb, "find_routines_by_name", lambda event_name: _two_routines())
    windows = []
    monkeypatch.setattr(
        rdb, "set_routine_active_window",
        lambda routine_id, active_from=None, active_until=None, reason=None:
            windows.append((routine_id, active_from, active_until, reason)),
    )

    result = system.control_routine_schedule.func(
        event_name="ποδόσφαιρο Αλέξανδρου",
        action="set_window",
        active_from="2026-09-01",
        active_until="2027-06-15",
        reason="school_year",
    )

    assert windows == [
        (13, "2026-09-01", "2027-06-15", "school_year"),
        (14, "2026-09-01", "2027-06-15", "school_year"),
    ]
    assert "[Monday]" in result
    assert "[Thursday]" in result


def test_set_window_accepts_only_active_from(monkeypatch):
    import tools.system as system
    import memory.routine_db as rdb

    monkeypatch.setattr(rdb, "find_routines_by_name", lambda event_name: _two_routines())
    windows = []
    monkeypatch.setattr(
        rdb, "set_routine_active_window",
        lambda routine_id, active_from=None, active_until=None, reason=None:
            windows.append((routine_id, active_from, active_until)),
    )

    result = system.control_routine_schedule.func(
        event_name="ποδόσφαιρο Αλέξανδρου",
        action="set_window",
        active_from="2026-09-01",
    )

    assert windows == [(13, "2026-09-01", None), (14, "2026-09-01", None)]


def test_set_window_without_any_date_is_rejected(monkeypatch):
    import tools.system as system
    import memory.routine_db as rdb

    monkeypatch.setattr(rdb, "find_routines_by_name", lambda event_name: _two_routines())

    result = system.control_routine_schedule.func(
        event_name="ποδόσφαιρο Αλέξανδρου",
        action="set_window",
    )

    assert "❌" in result


def test_clear_window_applies_to_all_matches(monkeypatch):
    import tools.system as system
    import memory.routine_db as rdb

    monkeypatch.setattr(rdb, "find_routines_by_name", lambda event_name: _two_routines())
    windows = []
    monkeypatch.setattr(
        rdb, "set_routine_active_window",
        lambda routine_id, active_from=None, active_until=None, reason=None:
            windows.append((routine_id, active_from, active_until)),
    )

    result = system.control_routine_schedule.func(
        event_name="ποδόσφαιρο Αλέξανδρου",
        action="clear_window",
    )

    assert windows == [(13, None, None), (14, None, None)]
    assert "[Monday]" in result
    assert "[Thursday]" in result


# ─────────────────────────────────────────────────────────────
# Validation / error paths
# ─────────────────────────────────────────────────────────────

def test_invalid_action_is_rejected(monkeypatch):
    import tools.system as system
    import memory.routine_db as rdb

    monkeypatch.setattr(rdb, "find_routines_by_name", lambda event_name: _two_routines())

    result = system.control_routine_schedule.func(
        event_name="ποδόσφαιρο Αλέξανδρου",
        action="delete_everything",
    )

    assert "❌" in result
    assert "Μη έγκυρο action" in result


def test_pause_without_until_date_is_rejected(monkeypatch):
    import tools.system as system
    import memory.routine_db as rdb

    monkeypatch.setattr(rdb, "find_routines_by_name", lambda event_name: _two_routines())

    result = system.control_routine_schedule.func(
        event_name="ποδόσφαιρο Αλέξανδρου",
        action="pause",
    )

    assert "❌" in result


def test_pause_with_bad_date_format_is_rejected(monkeypatch):
    import tools.system as system
    import memory.routine_db as rdb

    monkeypatch.setattr(rdb, "find_routines_by_name", lambda event_name: _two_routines())

    result = system.control_routine_schedule.func(
        event_name="ποδόσφαιρο Αλέξανδρου",
        action="pause",
        until_date="01/09/2026",
    )

    assert "❌" in result
    assert "format" in result.lower() or "Λάθος" in result


def test_set_window_with_bad_date_format_is_rejected(monkeypatch):
    import tools.system as system
    import memory.routine_db as rdb

    monkeypatch.setattr(rdb, "find_routines_by_name", lambda event_name: _two_routines())

    result = system.control_routine_schedule.func(
        event_name="ποδόσφαιρο Αλέξανδρου",
        action="set_window",
        active_from="Σεπτέμβριος 2026",
    )

    assert "❌" in result


def test_no_matching_routine_returns_error(monkeypatch):
    import tools.system as system
    import memory.routine_db as rdb

    monkeypatch.setattr(rdb, "find_routines_by_name", lambda event_name: [])

    result = system.control_routine_schedule.func(
        event_name="ανύπαρκτη ρουτίνα",
        action="pause",
        until_date="2026-09-01",
    )

    assert "❌" in result
    assert "Δεν βρήκα" in result
