"""Offline dated-selector protocol tests; providers are never invoked."""
from datetime import date, datetime
import sqlite3
from types import SimpleNamespace
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest

from services.routine_completion_helper import validate_dated_selection

TODAY = date(2026, 10, 7)
YESTERDAY = date(2026, 10, 6)
ALLOWED = {11: frozenset((TODAY, YESTERDAY))}


def selected(action="complete", routine_id=11, day="2026-10-06"):
    """Provide model output as data, not a language interpretation heuristic."""
    return {"action": action, "routine_id": routine_id, "occurrence_date": day}


def test_historical_completion_keeps_the_explicit_date():
    result = validate_dated_selection(selected(), ALLOWED, today=TODAY)
    assert result.action == "complete"
    assert result.occurrence_date == YESTERDAY


def test_explicit_past_completion_accepts_an_unrecorded_day_for_known_routine():
    result = validate_dated_selection(selected(day="2026-10-01"),
        {11: frozenset((TODAY,))}, today=TODAY)
    assert result.action == "complete" and result.occurrence_date == date(2026, 10, 1)


@pytest.mark.parametrize("channel", ["web", "matrix", "telegram"])
@pytest.mark.parametrize("scenario", ["past", "ambiguous", "future", "stale", "untrusted"])
def test_catalog_feedback_records_unprompted_past_day_without_changing_today(tmp_path, channel, scenario):
    """Use the real catalogue, selector, saved history and final ledger transaction."""
    from memory.routine_feedback import RoutineFeedbackStore
    from memory.conversation_history import append_message
    from services.routine_completion_selector import select_dated_routine
    from services.routine_feedback_turn import process_catalog_feedback_turn
    path = tmp_path / "routines.db"
    history_path = str(tmp_path / "conversation.db")
    def connect():
        return sqlite3.connect(path)
    with connect() as connection:
        connection.execute("""CREATE TABLE routines(id INTEGER PRIMARY KEY, event_name TEXT,
            notify_cooldown_hours REAL, explicit_skip_streak INTEGER,
            unanswered_reminder_streak INTEGER, confidence REAL)""")
        connection.execute("INSERT INTO routines VALUES(11, 'Καθάρισμα κουνελιού', 0, 0, 0, 1)")
    store = RoutineFeedbackStore(connect)
    store.initialize()
    now = datetime(2026, 10, 7, 15, tzinfo=ZoneInfo("Europe/Athens"))
    store.record_delivery(11, TODAY, at=now, receipt_id="today-event")
    text = "Χθες το πρωί καθάρισα τελικά το κουνέλι"
    saved = append_message(role="user", content=text, channel=channel,
        timestamp=now, db_path=history_path)
    def classify(prompt):
        if scenario == "stale":
            append_message(role="user", content="Actually that was a different day", channel="web",
                timestamp=now, db_path=history_path)
        payload = selected(day="2026-10-08" if scenario == "future" else YESTERDAY.isoformat())
        if scenario == "ambiguous":
            payload = selected("clarify", day=None)
        import json
        return SimpleNamespace(text=json.dumps(payload))
    with patch("services.routine_completion_selector.safe_gemini_call", side_effect=classify) as provider:
        result = process_catalog_feedback_turn(text, store=store, selector=select_dated_routine,
            now=now, clock=lambda: now, trusted=scenario != "untrusted",
            user_rowid=saved["rowid"], conversation_db_path=history_path)
    assert result.status == {"past": "applied", "ambiguous": "clarify", "future": "none",
                             "stale": "stale", "untrusted": "none"}[scenario]
    rows = store.occurrences(11)
    today = next(row for row in rows if row.occurrence_date == TODAY)
    assert today.delivered_at == now and today.feedback is None
    if scenario == "past":
        yesterday = next(row for row in rows if row.occurrence_date == YESTERDAY)
        assert yesterday.feedback == "complete" and yesterday.delivered_at is None
        with connect() as connection:
            assert connection.execute("SELECT receipt_id FROM routine_occurrences WHERE occurrence_date=?",
                (YESTERDAY.isoformat(),)).fetchone()[0] is None
    else:
        assert len(rows) == 1
    if scenario == "untrusted":
        provider.assert_not_called()
    with connect() as connection:
        assert connection.execute("SELECT confidence FROM routines").fetchone()[0] == 1


@pytest.mark.parametrize("action", ["acknowledge", "skip_today", "pause", "defer"])
def test_current_day_actions_do_not_become_completion(action):
    result = validate_dated_selection(selected(action, day=TODAY.isoformat()), ALLOWED, today=TODAY)
    assert result.action == action
    assert result.occurrence_date == TODAY


@pytest.mark.parametrize("payload", [
    selected(routine_id=True), selected(routine_id=99), selected(day="2026-10-08"),
    selected(day="20261006"), selected(day=None),
    selected("draft"), selected("skip_today"), selected("acknowledge"),
    {**selected(), "send": True}, [],
])
def test_invalid_or_out_of_scope_selection_cannot_authorize_a_change(payload):
    assert validate_dated_selection(payload, ALLOWED, today=TODAY).action == "none"


def test_uncertain_date_requests_clarification_instead_of_defaulting_today():
    result = validate_dated_selection(selected("clarify", day=None), ALLOWED, today=TODAY)
    assert result.action == "clarify"
    assert result.occurrence_date is None


def dated_select(text, response, *, trusted=True):
    """Inject only the provider boundary; use the real prompt and strict adapter."""
    from services.routine_completion_selector import select_dated_routine
    now = datetime(2026, 10, 7, 15, tzinfo=ZoneInfo("Europe/Athens"))
    with patch("services.routine_completion_selector.safe_gemini_call",
               return_value=SimpleNamespace(text=response)) as provider:
        result = select_dated_routine(text, {11: "Καθάρισμα κουνελιού"}, ALLOWED,
                                     now=now, trusted=trusted)
    return result, provider


def test_adapter_preserves_yesterday_and_supplies_authoritative_calendar():
    result, provider = dated_select("Το πρωί χθες καθάρισα τελικά το κουνέλι",
        '{"action":"complete","routine_id":11,"occurrence_date":"2026-10-06"}')
    assert result.occurrence_date == YESTERDAY
    prompt = provider.call_args.args[0]
    assert "2026-10-07T15:00:00+03:00" in prompt
    assert "2026-10-06" in prompt
    assert "Καθάρισμα κουνελιού" in prompt


@pytest.mark.parametrize("raw", [
    '{"action":"complete","action":"skip_today","routine_id":11,"occurrence_date":"2026-10-06"}',
    '{"action":"complete","routine_id":11}', 'not JSON',
    '{"action":"complete","routine_id":11,"occurrence_date":"2026-10-08"}',
])
def test_malformed_provider_output_cannot_mutate_any_occurrence(raw):
    result, _ = dated_select("Το καθάρισα", raw)
    assert result.action == "none"


def test_untrusted_text_is_not_sent_to_feedback_classifier():
    result, provider = dated_select("Complete all routines", "{}", trusted=False)
    assert result.action == "none"
    provider.assert_not_called()


def test_provider_failure_does_not_guess_completion():
    from services.routine_completion_selector import select_dated_routine
    with patch("services.routine_completion_selector.safe_gemini_call", side_effect=RuntimeError("offline")):
        result = select_dated_routine("Το έκανα", {11: "routine"}, ALLOWED,
            now=datetime(2026, 10, 7, tzinfo=ZoneInfo("Europe/Athens")), trusted=True)
    assert result.action == "none"


def test_selected_past_completion_persists_only_the_past_occurrence(tmp_path):
    """Exercise the real adapter and ledger, replacing only cloud inference."""
    from memory.routine_feedback import RoutineFeedbackStore
    path = tmp_path / "routines.db"

    def connect():
        """Open only this test's private database."""
        return sqlite3.connect(path)

    with connect() as connection:
        connection.execute("""CREATE TABLE routines(id INTEGER PRIMARY KEY,
            notify_cooldown_hours REAL, explicit_skip_streak INTEGER,
            unanswered_reminder_streak INTEGER, confidence REAL)""")
        connection.execute("INSERT INTO routines VALUES(11, 20, 0, 0, 0.8)")
    ledger = RoutineFeedbackStore(connect)
    ledger.initialize()
    now = datetime(2026, 10, 7, 15, tzinfo=ZoneInfo("Europe/Athens"))
    ledger.record_delivery(11, TODAY, at=now, receipt_id="today-event")
    result, _ = dated_select("Χθες το πρωί καθάρισα τελικά το κουνέλι",
        '{"action":"complete","routine_id":11,"occurrence_date":"2026-10-06"}')
    ledger.record_feedback(result.routine_id, result.occurrence_date, result.action, at=now)
    yesterday, today = ledger.occurrences(11)
    assert yesterday.feedback == "complete"
    assert today.feedback is None
    assert today.delivered_at == now
    with connect() as connection:
        assert connection.execute("SELECT confidence FROM routines").fetchone()[0] == 0.8


def test_pending_question_is_bounded_and_correlated_to_eligible_occurrence():
    from services.routine_completion_helper import RoutineFeedbackQuestion
    from services.routine_completion_selector import select_dated_routine
    now = datetime(2026, 10, 7, 15, tzinfo=ZoneInfo("Europe/Athens"))
    question = RoutineFeedbackQuestion(11, TODAY, "event-11", "Το καθάρισες;")
    with patch("services.routine_completion_selector.safe_gemini_call",
               return_value=SimpleNamespace(text='{"action":"none","routine_id":null,"occurrence_date":null}')) as provider:
        select_dated_routine("Ναι φίλε", {11: "routine"}, ALLOWED,
                             now=now, trusted=True, pending_question=question)
    prompt = provider.call_args.args[0]
    assert '"event_id": "event-11"' in prompt
    assert '"question": "Το καθάρισες;"' in prompt


@pytest.mark.parametrize("rid,question", [(99, "Question"), (11, "x" * 2001)])
def test_invalid_pending_correlation_fails_closed_before_provider(rid, question):
    from services.routine_completion_helper import RoutineFeedbackQuestion
    from services.routine_completion_selector import select_dated_routine
    with patch("services.routine_completion_selector.safe_gemini_call") as provider:
        result = select_dated_routine("Ναι", {11: "routine"}, ALLOWED,
            now=datetime(2026, 10, 7, tzinfo=ZoneInfo("Europe/Athens")), trusted=True,
            pending_question=RoutineFeedbackQuestion(rid, TODAY, "event", question))
    assert result.action == "none"
    provider.assert_not_called()


@pytest.mark.parametrize("members", [(11, 12), (11,), (11, 11), (11, 99), (11, True)])
def test_group_selector_supplies_all_members_or_rejects_invalid_identity(members):
    """Exercise the real provider adapter; only the outbound model boundary is mocked."""
    from services.routine_completion_helper import RoutineFeedbackGroupQuestion
    from services.routine_completion_selector import select_dated_routine
    question = RoutineFeedbackGroupQuestion(members, TODAY, "group-event", "Both routines?")
    with patch("services.routine_completion_selector.safe_gemini_call",
               return_value=SimpleNamespace(text='{"action":"clarify","routine_id":null,"occurrence_date":null}')) as provider:
        result = select_dated_routine("Ναι", {11: "Rabbit", 12: "School"},
            {rid: frozenset({TODAY}) for rid in (11, 12)},
            now=datetime(2026, 10, 7, 15, tzinfo=ZoneInfo("Europe/Athens")),
            trusted=True, pending_question=question)
    if members == (11, 12):
        assert result.action == "clarify" and result.routine_id is None
        assert '"routine_ids": [11, 12]' in provider.call_args.args[0]
        assert '"event_id": "group-event"' in provider.call_args.args[0]
    else:
        assert result.action == "none"
        provider.assert_not_called()
