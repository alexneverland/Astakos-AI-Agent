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
