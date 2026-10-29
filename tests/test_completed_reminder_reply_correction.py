"""Offline exact-receipt correction tests against real dated/history stores."""
import json
from datetime import timedelta
from types import SimpleNamespace

import pytest

from tests.test_routine_feedback_store import store
from tests.test_behavioral_reply_feedback import NOW, CORRECTION


@pytest.mark.parametrize("channel", ["matrix", "telegram"])
@pytest.mark.parametrize("days_ago", [0, 1])
def test_reply_to_completed_receipt_retracts_only_that_occurrence(
    store, tmp_path, monkeypatch, offline_behavioral_io, channel, days_ago,
):
    """The production selector gets the original receipt, even after its window."""
    from memory.conversation_history import append_message
    from services.routine_completion_selector import select_dated_routine
    from services.routine_feedback_turn import PersistedRoutineFeedbackHandler
    sent = NOW-timedelta(days=days_ago, hours=1)
    day = sent.date()
    assert store.record_delivery(11, day, at=sent, receipt_id="original-reminder",
                                 question="Did you visit the park?", channel=channel)
    assert store.record_feedback(11, day, "complete", at=sent+timedelta(minutes=1))
    assert store.pending_question(now=NOW, reply_channel=channel, reply_event_id="original-reminder") is None
    path = str(tmp_path / "history.db")
    saved = append_message(role="user", content=CORRECTION, channel=channel, timestamp=NOW, db_path=path)
    calls = []

    def provider(prompt):
        data = json.loads(prompt.split("INPUT:\n", 1)[1].split("\n\nChoose", 1)[0])
        calls.append(data)
        return SimpleNamespace(text=json.dumps({"action": "retract_complete", "routine_id": 11,
                                               "occurrence_date": day.isoformat()}))

    monkeypatch.setattr("services.routine_completion_selector.safe_gemini_call", provider)
    handler = PersistedRoutineFeedbackHandler(store=store, selector=select_dated_routine,
        clock=lambda: NOW, channel=channel, conversation_db_path=path, trusted_owner=True)
    assert handler.owns_reply_target("original-reminder")
    context = handler(CORRECTION, saved, reply_event_id="original-reminder")
    assert len(calls) == 1
    assert calls[0]["pending_question"]["event_id"] == "original-reminder"
    assert calls[0]["candidates"][0]["allowed_dates"] == [day.isoformat()]
    receipt = json.loads(context.content.splitlines()[0])
    assert receipt["status"] == "applied" and receipt["action"] == "retract_complete"
    row = store.occurrences(11)[0]
    assert row.feedback is None and row.delivered_at == sent


@pytest.mark.parametrize("action", ["complete", "acknowledge", "skip_today", "pause", "defer", "draft"])
def test_completed_reply_does_not_reopen_ordinary_feedback(store, tmp_path, offline_behavioral_io, action):
    """A resolved receipt routes only corrections, never normal actions or approval."""
    from memory.conversation_history import append_message
    from services.routine_completion_helper import DatedRoutineSelection
    from services.routine_feedback_turn import PersistedRoutineFeedbackHandler
    assert store.record_delivery(11, NOW.date(), at=NOW-timedelta(minutes=10), receipt_id="receipt",
                                 question="Park?", channel="matrix")
    assert store.record_feedback(11, NOW.date(), "complete", at=NOW-timedelta(minutes=9))
    path = str(tmp_path / "history.db")
    saved = append_message(role="user", content="Owner reply", channel="matrix", timestamp=NOW, db_path=path)
    calls = []

    def selector(*args, **kwargs):
        calls.append(True)
        return DatedRoutineSelection(action, 11, NOW.date())

    context = PersistedRoutineFeedbackHandler(store=store, selector=selector, clock=lambda: NOW,
        channel="matrix", conversation_db_path=path, trusted_owner=True)("Owner reply", saved, reply_event_id="receipt")
    assert calls == [True]
    assert json.loads(context.content.splitlines()[0])["status"] == "none"
    assert store.occurrences(11)[0].feedback == "complete"


@pytest.mark.parametrize("scenario", ["unknown_receipt", "wrong_channel", "wrong_date", "new_owner", "new_ledger", "untrusted"])
def test_reply_retraction_guards_keep_completion(store, tmp_path, offline_behavioral_io, scenario):
    """Receipt/date binding, current owner turn and ledger revisions stay required."""
    from memory.conversation_history import append_message
    from services.routine_completion_helper import DatedRoutineSelection
    from services.routine_feedback_turn import PersistedRoutineFeedbackHandler
    yesterday = NOW.date()-timedelta(days=1)
    assert store.record_delivery(11, yesterday, at=NOW-timedelta(days=1), receipt_id="receipt",
                                 question="Park?", channel="matrix")
    assert store.record_feedback(11, yesterday, "complete", at=NOW-timedelta(days=1)+timedelta(minutes=1))
    assert store.record_feedback(11, NOW.date(), "complete", at=NOW-timedelta(minutes=10))
    channel = "telegram" if scenario == "wrong_channel" else "matrix"
    path = str(tmp_path / "history.db")
    saved = append_message(role="user", content=CORRECTION, channel=channel, timestamp=NOW, db_path=path,
        metadata={"untrusted_external_tool_names": ["browse_url"]} if scenario == "untrusted" else {})
    calls = []

    def selector(*args, **kwargs):
        calls.append(True)
        if scenario == "new_owner":
            append_message(role="user", content="Later report", channel="web", timestamp=NOW, db_path=path)
        if scenario == "new_ledger":
            store.record_feedback(11, NOW.date()-timedelta(days=2), "complete", at=NOW)
        return DatedRoutineSelection("retract_complete", 11, NOW.date() if scenario == "wrong_date" else yesterday)

    handler = PersistedRoutineFeedbackHandler(store=store, selector=selector, clock=lambda: NOW,
        channel=channel, conversation_db_path=path, trusted_owner=True)
    handler(CORRECTION, saved, reply_event_id="unknown" if scenario == "unknown_receipt" else "receipt")
    assert bool(calls) == (scenario in {"wrong_date", "new_owner", "new_ledger"})
    rows = store.occurrences(11)
    assert next(row for row in rows if row.occurrence_date == yesterday).feedback == "complete"
    assert next(row for row in rows if row.occurrence_date == NOW.date()).feedback == "complete"
