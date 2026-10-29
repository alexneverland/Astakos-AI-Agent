"""Delayed conversation answers and explicit completion corrections stay dated."""
import json
from datetime import datetime, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from tests.test_routine_feedback_store import store

NOW = datetime(2026, 10, 29, 8, 26, 57, tzinfo=ZoneInfo("Europe/Athens"))
OPENER = "Παρεμπιπτόντως, βλέπω ξεκλέβεις χρόνο για καμιά μπαλίτσα πού και πού τον τελευταίο καιρό. Μαζεύεστε σταθερή παρέα και το ευχαριστιέστε;"
ANSWER = "στο παρκο φιλε παιζουμε μπαλα εγω και ο αλεξανδροσ και αλλα παιδακια"
CORRECTION = "αυτο ηταν απαντηση στην ερωτηση σου αν αμαζευομαστε για μπαλα οχι οτι ειμαι τωρα. τωρα ειμαι εγω δουλεια και ο αλεξανδροσ σχολειο"


@pytest.mark.parametrize("channel", ["web", "matrix", "telegram"])
@pytest.mark.parametrize("action,text", [("none", ANSWER), ("complete", "Τώρα φτάσαμε πάρκο και παίζουμε μπάλα.")])
def test_delayed_answer_keeps_original_question(store, tmp_path, monkeypatch, offline_behavioral_io, channel, action, text):
    """Briefings and a channel change must not hide the question from selection."""
    from memory.conversation_history import append_message
    from services.routine_completion_selector import select_dated_routine
    from services.routine_feedback_turn import PersistedRoutineFeedbackHandler
    path = str(tmp_path / "history.db")
    append_message(role="assistant", content=OPENER, channel="matrix", agent="Behavioral_Agent",
                   timestamp=NOW-timedelta(minutes=18, seconds=26), db_path=path)
    for index in range(3):
        append_message(role="assistant", content=f"Briefing {index}", channel="matrix",
                       timestamp=NOW-timedelta(minutes=8, seconds=3-index), db_path=path)
    saved = append_message(role="user", content=text, channel=channel, timestamp=NOW, db_path=path)
    seen = []

    def provider(prompt):
        data = json.loads(prompt.split("INPUT:\n", 1)[1].split("\n\nChoose", 1)[0])
        assert any(item["content"] == OPENER for item in data["conversation_context"])
        assert "habitual" in prompt
        seen.append(data)
        return SimpleNamespace(text=json.dumps({"action": action, "routine_id": 11 if action == "complete" else None,
            "occurrence_date": NOW.date().isoformat() if action == "complete" else None}))

    monkeypatch.setattr("services.routine_completion_selector.safe_gemini_call", provider)
    handler = PersistedRoutineFeedbackHandler(store=store, selector=select_dated_routine,
        clock=lambda: NOW, channel=channel, conversation_db_path=path, trusted_owner=True)
    context = handler(text, saved)
    assert len(seen) == 1  # Provider assertions cannot be swallowed into a false pass.
    receipt = json.loads(context.content.splitlines()[0])
    assert receipt["action"] == action
    assert [row.feedback for row in store.occurrences(11)] == (["complete"] if action == "complete" else [])


@pytest.mark.parametrize("channel", ["web", "matrix", "telegram"])
def test_explicit_correction_retracts_persisted_completion(store, tmp_path, monkeypatch, offline_behavioral_io, channel):
    """Real selection, write and graph receipt agree; delivery survives correction."""
    from memory.conversation_history import append_message
    from services.routine_completion_selector import select_dated_routine
    from services.routine_feedback_turn import PersistedRoutineFeedbackHandler
    path = str(tmp_path / "history.db")
    delivered = NOW-timedelta(minutes=25)
    assert store.record_delivery(11, NOW.date(), at=delivered, receipt_id="test-delivery")
    assert store.record_feedback(11, NOW.date(), "complete", at=NOW)
    append_message(role="user", content=ANSWER, channel=channel, timestamp=NOW, db_path=path)
    append_message(role="assistant", content="Σημείωσα ολοκληρωμένη τη βόλτα στο πάρκο για σήμερα.",
                   channel=channel, timestamp=NOW+timedelta(minutes=1), db_path=path)
    correction_at = NOW+timedelta(minutes=3)
    saved = append_message(role="user", content=CORRECTION, channel=channel, timestamp=correction_at, db_path=path)
    seen = []

    def provider(prompt):
        data = json.loads(prompt.split("INPUT:\n", 1)[1].split("\n\nChoose", 1)[0])
        occurrence = data["candidates"][0]["identity_evidence"]["occurrences"][0]
        assert occurrence["feedback"] == "complete"
        seen.append(data)
        return SimpleNamespace(text=json.dumps({"action": "retract_complete", "routine_id": 11,
                                               "occurrence_date": NOW.date().isoformat()}))

    monkeypatch.setattr("services.routine_completion_selector.safe_gemini_call", provider)
    context = PersistedRoutineFeedbackHandler(store=store, selector=select_dated_routine,
        clock=lambda: correction_at, channel=channel, conversation_db_path=path,
        trusted_owner=True)(CORRECTION, saved)
    assert len(seen) == 1
    assert json.loads(context.content.splitlines()[0])["action"] == "retract_complete"
    row = store.occurrences(11)[0]
    assert row.feedback is None and row.feedback_at is None
    assert row.delivered_at == delivered
    assert "retract_complete" in context.content


@pytest.mark.parametrize("guard", ["valid", "no_completion", "stale_revision", "stale_turn", "future", "same_time"])
def test_retraction_requires_exact_existing_completion(store, guard, offline_behavioral_io):
    """A separate guarded API never weakens the normal completion overwrite rule."""
    if guard != "no_completion":
        assert store.record_feedback(11, NOW.date(), "complete", at=NOW)
    revision = store.revision(11)
    if guard == "stale_revision":
        assert store.record_feedback(11, NOW.date()-timedelta(days=1), "complete", at=NOW)
    at = NOW if guard == "same_time" else NOW+timedelta(minutes=3)
    day = NOW.date()+timedelta(days=1) if guard == "future" else NOW.date()
    if guard == "future":
        with pytest.raises(ValueError):
            store.retract_completion(11, day, at=at, expected_revision=revision, is_current=lambda: True)
        assert store.occurrences(11)[0].feedback == "complete"
        return
    result = store.retract_completion(11, day, at=at, expected_revision=revision,
                                      is_current=lambda: guard != "stale_turn")
    assert result is (guard == "valid")
    rows = [row for row in store.occurrences(11) if row.occurrence_date == NOW.date()]
    if guard not in {"valid", "no_completion"}:
        assert rows[0].feedback == "complete"


def test_plain_skip_still_cannot_undo_completion(store, offline_behavioral_io):
    """An unrelated current location or cancellation cannot clear prior execution."""
    assert store.record_feedback(11, NOW.date(), "complete", at=NOW)
    assert not store.record_feedback(11, NOW.date(), "skip_today", at=NOW+timedelta(minutes=3))
    assert store.occurrences(11)[0].feedback == "complete"


@pytest.mark.parametrize("scenario", ["new_owner_turn", "new_completion", "untrusted", "missing_completion"])
def test_handler_retraction_cannot_clear_changed_or_untrusted_state(
    store, tmp_path, monkeypatch, offline_behavioral_io, scenario,
):
    """Changed history/ledger and non-owner input cannot authorize a retraction."""
    from memory.conversation_history import append_message
    from services.routine_completion_helper import DatedRoutineSelection
    from services.routine_feedback_turn import PersistedRoutineFeedbackHandler
    path = str(tmp_path / "guard-history.db")
    if scenario != "missing_completion":
        assert store.record_feedback(11, NOW.date(), "complete", at=NOW)
    current = NOW+timedelta(minutes=3)
    saved = append_message(role="user", content=CORRECTION, channel="web", timestamp=current,
        metadata={"untrusted_external_tool_names": ["browse_url"]} if scenario == "untrusted" else {}, db_path=path)
    seen = []

    def selector(*args, **kwargs):
        seen.append(True)
        if scenario == "new_owner_turn":
            append_message(role="user", content="Actually I just did it.", channel="matrix",
                           timestamp=current, db_path=path)
        if scenario == "new_completion":
            assert store.record_feedback(11, NOW.date()-timedelta(days=1), "complete", at=current)
        return DatedRoutineSelection("retract_complete", 11, NOW.date())

    context = PersistedRoutineFeedbackHandler(store=store, selector=selector,
        clock=lambda: current, channel="web", conversation_db_path=path,
        trusted_owner=True)(CORRECTION, saved)
    if scenario == "untrusted":
        assert context is None and not seen
    else:
        assert seen
        assert json.loads(context.content.splitlines()[0])["status"] == "stale"
    rows = store.occurrences(11)
    if scenario == "missing_completion":
        assert rows == []
    else:
        assert next(row for row in rows if row.occurrence_date == NOW.date()).feedback == "complete"


def test_retraction_protocol_requires_known_date_and_single_action(offline_behavioral_io):
    """Retractions never invent a past row or enter multi-outcome transactions."""
    from services.routine_completion_helper import validate_dated_feedback
    day = NOW.date()-timedelta(days=1)
    payload = {"action": "retract_complete", "routine_id": 11, "occurrence_date": day.isoformat()}
    dates = {11: frozenset({NOW.date()})}
    assert validate_dated_feedback(payload, dates, today=NOW.date()).action == "none"
    dates[11] = frozenset({NOW.date(), day})
    assert validate_dated_feedback(payload, dates, today=NOW.date()).action == "retract_complete"
    assert validate_dated_feedback({"selections": [payload, {**payload, "routine_id": 12}]},
        {**dates, 12: dates[11]}, today=NOW.date()).action == "none"


def test_historical_retraction_preserves_receipt_and_other_occurrences(store, offline_behavioral_io):
    """Correcting yesterday does not clear today's real completion or reset policy."""
    from memory.event_log import get_events
    day = NOW.date()-timedelta(days=1)
    earlier = NOW-timedelta(days=1)
    assert store.record_delivery(11, day, at=earlier-timedelta(minutes=10), receipt_id="yesterday-receipt")
    assert store.record_feedback(11, day, "complete", at=earlier)
    assert store.record_feedback(11, NOW.date(), "complete", at=NOW)
    assert store.retract_completion(11, day, at=NOW+timedelta(minutes=3),
        expected_revision=store.revision(11), is_current=lambda: True)
    previous, today = store.occurrences(11)
    assert previous.feedback is None and previous.delivered_at == earlier-timedelta(minutes=10)
    assert today.feedback == "complete"
    events = get_events(action="completion_retracted")
    assert len(events) == 1 and events[0]["occurrence_date"] == day.isoformat()
