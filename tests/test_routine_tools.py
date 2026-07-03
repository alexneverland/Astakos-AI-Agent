from unittest.mock import patch

from tools.system import control_routine_notifications, control_routine_schedule


def test_control_routine_schedule_ignores_context_fact():
    result = control_routine_schedule.invoke(
        {
            "event_name": "ποδόσφαιρο Αλέξανδρου",
            "action": "pause",
            "until_date": "2026-09-01",
            "source_text": "Είναι καλοκαίρι ο Αλέξανδρος δεν έχει ποδόσφαιρο ξανά τον Σεπτέμβριο"
        }
    )
    normalized = result.lower()
    assert "fact update" in normalized or "δεν έγινε" in normalized or "δεν βρέθηκε" in normalized


def test_control_routine_notifications_ignores_context_fact():
    result = control_routine_notifications.invoke(
        {
            "event_name": "εκτός σπιτιού",
            "action": "mute",
            "until_date": "2026-09-01",
            "source_text": "Ο Αλέξανδρος γύρισε σπίτι και δεν είναι πια εκτός σπιτιού"
        }
    )
    normalized = result.lower()
    assert (
        "fact update" in normalized
        or "δεν έγινε" in normalized
        or "δεν βρέθηκε" in normalized
    )


@patch(
    "memory.routine_db.find_routines_for_schedule_control",
    return_value=[
        {
            "id": 99,
            "event": "ποδόσφαιρο Αλέξανδρου",
            "day": "Monday",
        }
    ],
)
@patch("memory.routine_db.get_routine_schedule_meta", return_value={})
@patch("memory.routine_db.set_routine_paused_until", return_value=None)
def test_control_routine_schedule_allows_explicit_manual_command(mock_set, mock_get, mock_find):
    result = control_routine_schedule.invoke(
        {
            "event_name": "ποδόσφαιρο Αλέξανδρου",
            "action": "pause",
            "until_date": "2026-09-01",
            "source_text": "Πάγωσε το ποδόσφαιρο του Αλέξανδρου μέχρι 1 Σεπτεμβρίου"
        }
    )
    normalized = result.lower()
    assert "2026-09-01" in result or "πάγω" in normalized or "paused" in normalized


def test_control_routine_cooldown_resets_matching_routine(monkeypatch):
    from tools import system
    
    monkeypatch.setattr(
        system,
        "classify_routine_intent",
        lambda source_text, routine_names=None: type(
            "X", (), {"intent": "manual_routine_control"}
        )()
    )

    monkeypatch.setattr(
        system,
        "_get_routine_names_for_intent_classification",
        lambda: ["καθάρισμα κλουβιού κουνελιού"]
    )

    with patch("memory.routine_db.find_routines_for_schedule_control") as mock_find, \
         patch("memory.routine_db.reset_routine_cooldown") as mock_reset, \
         patch("memory.routine_db.get_routine_notify_info") as mock_info:

        mock_find.return_value = [
            {"id": 96, "event": "καθάρισμα κλουβιού κουνελιού", "day": "Everyday", "time": "09:00"}
        ]
        mock_info.side_effect = [
            {"cooldown_hours": 40.0, "last_notified_ts": "2026-07-03T08:00:30"},
            {"cooldown_hours": 20.0, "last_notified_ts": None},
        ]

        # The tool function is bound to the `.func` property in some tool frameworks like LangChain,
        # but if we're invoking it directly in tests, we can just call it (or use .invoke as in the other tests).
        # Let's use invoke like the other tests or `.func` if explicitly requested by the user.
        # The user requested system.control_routine_cooldown.func, so we'll use that if it exists, otherwise invoke.
        if hasattr(system.control_routine_cooldown, "func"):
            result = system.control_routine_cooldown.func(
                event_name="καθάρισμα κλουβιού κουνελιού",
                action="reset",
                source_text="Μηδένισε το cooldown της ρουτίνας καθάρισμα κλουβιού κουνελιού",
            )
        else:
            result = system.control_routine_cooldown(
                event_name="καθάρισμα κλουβιού κουνελιού",
                action="reset",
                source_text="Μηδένισε το cooldown της ρουτίνας καθάρισμα κλουβιού κουνελιού",
            )

        mock_reset.assert_called_once_with(96, clear_last_notified=True)
        assert "βγήκε από cooldown" in result


def test_control_routine_cooldown_ignores_context_fact():
    from tools import system

    result = system.control_routine_cooldown.invoke(
        {
            "event_name": "καθάρισμα κλουβιού κουνελιού",
            "action": "reset",
            "source_text": "Αύριο θα είμαστε σπίτι πιο νωρίς και θα το κάνω εγώ",
        }
    )

    normalized = result.lower()
    assert "context/fact update" in normalized or "δεν έγινε cooldown reset" in normalized


def test_control_pending_followup_deletes_matching_row(monkeypatch):
    from tools import system

    monkeypatch.setattr(system, "_looks_like_manual_followup_control", lambda text: True)

    with patch("memory.pending_followups.find_followups_for_control") as mock_find, \
         patch("memory.pending_followups.delete_followup") as mock_delete:
        mock_find.return_value = [
            {"id": 4, "subject": "ψήσιμο μπριζόλας", "topic": "food_purchase", "status": "pending"}
        ]
        mock_delete.return_value = True

        result = system.control_pending_followup.func(
            subject_query="μπριζόλες",
            action="delete",
            source_text="σβήσε το pending followup για τις μπριζόλες",
        )

        mock_delete.assert_called_once_with(4, reason="manual_delete")
        assert "Διαγράφηκε" in result


def test_control_pending_followup_repairs_legacy_rows(monkeypatch):
    from tools import system

    with patch("memory.pending_followups.backfill_legacy_followups") as mock_backfill, \
         patch("memory.pending_followups.find_pending_followups") as mock_find_pending:
        mock_backfill.return_value = 1
        mock_find_pending.return_value = [
            {"id": 4, "subject": "ψήσιμο μπριζόλας", "followup_after_ts": "2030-01-02T11:30:00+02:00"}
        ]

        result = system.control_pending_followup.func(
            subject_query="legacy",
            action="repair_legacy",
            source_text="στρώσε τα παλιά pending followups",
        )

        assert "repair" in result.lower()
        assert "#4" in result
