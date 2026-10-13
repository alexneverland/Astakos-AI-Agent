"""Mixed completion/cancellation uses isolated native ledger transactions."""
from datetime import datetime, timedelta
from types import SimpleNamespace
import json

import pytest

from services.routine_feedback import ATHENS
from tests.test_routine_feedback_runtime import store

NOW = datetime(2026, 10, 13, 15, 39, 55, tzinfo=ATHENS)
REPORT = "Σχολασα φίλε αλλά ο καιρός χάλια βρέχει πολύ ούτε ο Αλέξανδρος έχει ποδόσφαιρο"
pytestmark = pytest.mark.usefixtures("offline_behavioral_io")


@pytest.mark.parametrize("channel", ["matrix", "web", "telegram"])
def test_first_report_records_finished_work_and_cancelled_football(store, tmp_path, monkeypatch, channel):
    """No delivery/second reminder question is needed for either explicit report."""
    from memory.conversation_history import append_message
    from services import routine_completion_selector as adapter
    from services.routine_feedback_turn import PersistedRoutineFeedbackHandler
    with store.connection_factory() as connection:
        connection.execute("UPDATE routines SET event_name='σχόλασμα από τη δουλειά' WHERE id=1")
        connection.execute("INSERT INTO routines VALUES (2,'ποδόσφαιρο Αλέξανδρου',0,0,0,1,'active',1,NULL,NULL,0,'Tuesday','17:00')")
    path = str(tmp_path / "history.db")
    row = append_message(role="user", channel=channel, content=REPORT, timestamp=NOW, db_path=path)
    payload = {"selections": [
        {"action": "complete", "routine_id": 1, "occurrence_date": NOW.date().isoformat()},
        {"action": "skip_today", "routine_id": 2, "occurrence_date": NOW.date().isoformat()}]}
    monkeypatch.setattr(adapter, "safe_gemini_call", lambda _: SimpleNamespace(text=json.dumps(payload)))
    handler = PersistedRoutineFeedbackHandler(store=store, selector=adapter.select_dated_routine,
        clock=lambda: NOW, channel=channel, trusted_owner=True, conversation_db_path=path)
    result = handler(REPORT, row)
    assert [store.occurrences(rid)[0].feedback for rid in (1, 2)] == ["complete", "skip_today"]
    assert store.closed_occurrence_ids(NOW.date()) == {1, 2}
    assert result is not None
    content = json.loads(result.content.splitlines()[0])
    assert content["status"] == "applied" and [item["action"] for item in content["outcomes"]] == ["complete", "skip_today"]
    assert all(store.occurrences(rid)[0].delivered_at is None for rid in (1, 2))
    assert handler(REPORT, row) is not None
    assert [len(store.occurrences(rid)) for rid in (1, 2)] == [1, 1]


@pytest.mark.parametrize("failure", ["pause", "defer", "acknowledge", "draft", "unknown_id", "duplicate",
    "past_skip", "future_skip", "oversize", "untrusted", "history_race", "catalog_race",
    "already_complete", "write_rejected", "expired_reply"])
def test_mixed_outcomes_reject_entire_unsafe_or_stale_update(store, tmp_path, monkeypatch, failure):
    """No invalid cancellation may partially complete work or undo execution."""
    from memory.conversation_history import append_message
    from services import routine_completion_selector as adapter, routine_feedback_turn as turn
    with store.connection_factory() as connection:
        connection.execute("INSERT INTO routines VALUES (2,'Football',0,0,0,1,'active',1,NULL,NULL,0,'Tuesday','17:00')")
    if failure == "already_complete":
        assert store.record_feedback(2, NOW.date(), "complete", at=NOW-timedelta(minutes=1))
    path = str(tmp_path / "history.db")
    row = append_message(role="user", channel="matrix", content=REPORT, timestamp=NOW, db_path=path)
    items = [{"action": "complete", "routine_id": 1, "occurrence_date": NOW.date().isoformat()},
             {"action": "skip_today", "routine_id": 2, "occurrence_date": NOW.date().isoformat()}]
    if failure in {"pause", "defer", "acknowledge", "draft"}: items[1]["action"] = failure
    if failure == "unknown_id": items[1]["routine_id"] = 999
    if failure == "duplicate": items[1]["routine_id"] = 1
    if failure == "past_skip": items[1]["occurrence_date"] = (NOW-timedelta(days=1)).date().isoformat()
    if failure == "future_skip": items[1]["occurrence_date"] = (NOW+timedelta(days=1)).date().isoformat()
    if failure == "oversize": items *= 3
    if failure == "write_rejected":
        original = store._record_feedback
        monkeypatch.setattr(store, "_record_feedback", lambda connection, rid, *a, **k:
            False if rid == 2 else original(connection, rid, *a, **k))
    if failure == "expired_reply":
        monkeypatch.setattr(turn, "_feedback_conversation_reference", lambda **k: [{
            "kind": "context_question_reference", "status": "expired", "channel": "matrix",
            "external_id": "$old-context", "routine_ids": [2]}])
    def model(prompt):
        if failure == "history_race": append_message(role="user", channel="web", content="Correction",
            timestamp=NOW, db_path=path)
        if failure == "catalog_race":
            with store.connection_factory() as connection:
                connection.execute("UPDATE routines SET event_name='Different activity' WHERE id=2")
        return SimpleNamespace(text=json.dumps({"selections": items}))
    monkeypatch.setattr(adapter, "safe_gemini_call", model)
    handler = turn.PersistedRoutineFeedbackHandler(store=store, selector=adapter.select_dated_routine,
        clock=lambda: NOW, channel="matrix", trusted_owner=failure != "untrusted", conversation_db_path=path)
    result = handler(REPORT, row, **({"reply_event_id": "$old-context"} if failure == "expired_reply" else {}))
    assert store.occurrences(1) == []
    assert [o.feedback for o in store.occurrences(2)] == (["complete"] if failure == "already_complete" else [])
    assert result is None or '"status": "stale"' in result.content
    assert result is None or '"outcomes"' not in result.content


@pytest.mark.parametrize("prior", ["complete_work", "skipped_football", "delivered_football", "historical_work"])
def test_mixed_outcomes_preserve_prior_receipts_and_dates(store, tmp_path, monkeypatch, prior):
    """Previously completed work must not prevent recording today's cancellation."""
    from memory.conversation_history import append_message
    from services import routine_completion_selector as adapter
    from services.routine_feedback_turn import PersistedRoutineFeedbackHandler
    with store.connection_factory() as connection:
        connection.execute("INSERT INTO routines VALUES (2,'Football',0,0,0,1,'active',1,NULL,NULL,0,'Tuesday','17:00')")
    day = (NOW-timedelta(days=1)).date() if prior == "historical_work" else NOW.date()
    earlier = NOW-timedelta(minutes=1)
    if prior == "complete_work": assert store.record_feedback(1, day, "complete", at=earlier)
    if prior == "skipped_football": assert store.record_feedback(2, NOW.date(), "skip_today", at=earlier)
    if prior == "delivered_football":
        store.record_delivery(2, NOW.date(), at=earlier, receipt_id="$football", channel="matrix", question="Football?")
    path = str(tmp_path / "history.db")
    row = append_message(role="user", channel="web", content=REPORT, timestamp=NOW, db_path=path)
    monkeypatch.setattr(adapter, "safe_gemini_call", lambda _: SimpleNamespace(text=json.dumps({"selections": [
        {"action": "complete", "routine_id": 1, "occurrence_date": day.isoformat()},
        {"action": "skip_today", "routine_id": 2, "occurrence_date": NOW.date().isoformat()}]})))
    handler = PersistedRoutineFeedbackHandler(store=store, selector=adapter.select_dated_routine,
        clock=lambda: NOW, channel="web", trusted_owner=True, conversation_db_path=path)
    result = handler(REPORT, row)
    assert result is not None and '"status": "applied"' in result.content
    assert store.occurrences(1)[0].occurrence_date == day
    football = store.occurrences(2)[0]
    assert football.feedback == "skip_today" and football.occurrence_date == NOW.date()
    assert football.delivered_at == (earlier if prior == "delivered_football" else None)
    assert store.is_delivered_question_target(channel="matrix", event_id="$football") is (prior == "delivered_football")


@pytest.mark.parametrize("text", ["Σχόλασα αλλά βρέχει πολύ", "Σχόλασα, ίσως ακυρωθεί το ποδόσφαιρο αν βρέξει",
    "Σχόλασα αλλά ο φίλος μου είπε ότι το δικό του παιδί δεν έχει ποδόσφαιρο"])
def test_weather_or_uncertain_other_activity_does_not_create_skip(store, tmp_path, monkeypatch, text):
    """The canonical contract leaves model meaning separate from outcome validation."""
    from memory.conversation_history import append_message
    from services import routine_completion_selector as adapter
    from services.routine_feedback_turn import PersistedRoutineFeedbackHandler
    with store.connection_factory() as connection:
        connection.execute("INSERT INTO routines VALUES (2,'Football',0,0,0,1,'active',1,NULL,NULL,0,'Tuesday','17:00')")
    path = str(tmp_path / "history.db")
    row = append_message(role="user", channel="matrix", content=text, timestamp=NOW, db_path=path)
    def model(prompt):
        assert text in prompt and "Weather alone or a conditional possibility" in prompt
        assert "recording\none fulfilled activity must not discard" in prompt
        return SimpleNamespace(text=json.dumps({"action": "complete", "routine_id": 1,
            "occurrence_date": NOW.date().isoformat()}))
    monkeypatch.setattr(adapter, "safe_gemini_call", model)
    handler = PersistedRoutineFeedbackHandler(store=store, selector=adapter.select_dated_routine,
        clock=lambda: NOW, channel="matrix", trusted_owner=True, conversation_db_path=path)
    assert handler(text, row) is not None
    assert store.occurrences(1)[0].feedback == "complete" and store.occurrences(2) == []


@pytest.mark.parametrize("action,day", [("pause", NOW.date()), ("defer", NOW.date()),
    ("skip_today", (NOW-timedelta(days=1)).date())])
def test_atomic_writer_itself_rejects_unsafe_outcomes(store, action, day):
    """The native transaction validates its own boundary without a model adapter."""
    with store.connection_factory() as connection:
        connection.execute("INSERT INTO routines VALUES (2,'Football',0,0,0,1,'active',1,NULL,NULL,0,'Tuesday','17:00')")
    with pytest.raises(ValueError):
        store.record_outcomes(((1, NOW.date(), "complete"), (2, day, action)), at=NOW,
            expected_revisions={rid: store.revision(rid) for rid in (1, 2)}, is_current=lambda: True)
    assert all(store.occurrences(rid) == [] for rid in (1, 2))
