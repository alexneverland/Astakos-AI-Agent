"""Activity outcomes use isolated canonical stores and offline provider seams."""
from datetime import datetime, timedelta
from types import SimpleNamespace
import json

import pytest

from services.routine_feedback import ATHENS

NOW = datetime(2026, 10, 12, 18, 52, tzinfo=ATHENS)
pytestmark = pytest.mark.usefixtures("offline_behavioral_io")

from tests.test_routine_feedback_runtime import store


@pytest.mark.parametrize("phase,value", [("plan", "done"), ("arrived", "in_progress"), ("returned", "done")])
def test_outing_uses_current_semantic_source_not_memory_reconciliation(tmp_path, monkeypatch, phase, value):
    """Future plans cannot be overwritten by the retired lexical outing writer."""
    from memory import conversation_history as history, routine_db as db
    from services import context_extractor as extractor, routine_reconciler as reconciler
    path = str(tmp_path / "history.db")
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "routines.db"))
    db.setup_db()
    texts = {"plan": "σπιτι ειμαι φιλε ολα καλα καλα και το κουνελακι τωρα παιζω roblox με τον αλεξανδρο και ποιο μετα θα παμε παρκο",
        "arrived": "Βρε αφού παίξαμε νωρίτερα σήμερα Roblox τώρα ήρθαμε πάρκο",
        "returned": "Γυρίσαμε σπίτι από τη βόλτα με τον μικρό"}
    row = history.append_message(role="user", channel="web", content=texts[phase], timestamp=NOW, db_path=path)
    monkeypatch.setattr(extractor, "safe_gemini_call", lambda _: SimpleNamespace(text=json.dumps({
        "flags": {"state:kid1:outing": value, "user_out_of_home": phase == "arrived"},
        "event_rowid": row["rowid"], "support_rowids": [row["rowid"]]})))
    monkeypatch.setattr(reconciler, "_infer_llm_reconciliation_candidates", lambda *a, **k: [])
    extractor.extract_and_update_context_flags(texts[phase], now=NOW, conversation_db_path=path)
    state = db.get_context_state("state:kid1:outing")
    assert state is not None and state["value"] == value and state["updated_at"] == NOW.isoformat()
    candidates = reconciler.infer_routine_reconciliation_candidates(texts[phase], category="family",
        reason="user_stated", now=NOW.replace(tzinfo=None))
    assert not any(item.get("key") == "state:kid1:outing"
        or item.get("rule_name") in {"family_outing_in_progress", "return_home_from_outing"}
        for item in candidates)
    monkeypatch.setattr(reconciler, "_infer_llm_reconciliation_candidates", lambda *a, **k: [
        {"kind": "context_state_set", "key": "state:kid1:outing", "value": "in_progress"},
        {"kind": "routine_condition_add", "condition_payload": {"flag": "state:kid1:outing", "equals": "in_progress"}}])
    assert not any(item.get("key") == "state:kid1:outing"
        or (isinstance(item.get("condition_payload"), dict)
            and item["condition_payload"].get("flag") == "state:kid1:outing")
        for item in reconciler.infer_routine_reconciliation_candidates(texts[phase],
            category="family", reason="user_stated", now=NOW.replace(tzinfo=None)))


@pytest.mark.parametrize("channel", ["web", "matrix", "telegram"])
@pytest.mark.parametrize("prior", [None, "skip_today", "complete"])
def test_two_actual_activities_persist_and_acknowledge_both(store, tmp_path, monkeypatch, channel, prior):
    """Correcting earlier play and reporting arrival must retain both outcomes."""
    from memory.conversation_history import append_message
    from services.routine_completion_selector import select_dated_routine
    from services.routine_feedback_turn import PersistedRoutineFeedbackHandler
    from services import routine_completion_selector as adapter
    with store.connection_factory() as connection:
        connection.execute("UPDATE routines SET event_name='Roblox με τον Αλέξανδρο' WHERE id=1")
        connection.execute("INSERT INTO routines VALUES (2,'Πάρκο με τον Αλέξανδρο',0,0,0,1,'active',1,NULL,NULL,0,'Everyday','19:30')")
    if prior is not None:
        store.record_delivery(1, NOW.date(), at=NOW-timedelta(minutes=40), receipt_id="earlier-receipt",
            channel="matrix", question="Roblox reminder")
        assert store.record_feedback(1, NOW.date(), prior, at=NOW-timedelta(minutes=30))
    path = str(tmp_path / "history.db")
    append_message(role="user", channel="web", content="τώρα παίζω Roblox με τον Αλέξανδρο",
        timestamp=NOW-timedelta(minutes=89), db_path=path)
    text = "Βρε αφού παίξαμε νωρίτερα σήμερα Roblox τώρα ήρθαμε πάρκο"
    row = append_message(role="user", channel=channel, content=text, timestamp=NOW, db_path=path)
    def model(prompt):
        assert "τώρα παίζω Roblox" in prompt
        return SimpleNamespace(text=json.dumps({"selections": [
            {"action": "complete", "routine_id": 1, "occurrence_date": NOW.date().isoformat()},
            {"action": "complete", "routine_id": 2, "occurrence_date": NOW.date().isoformat()}]}))
    monkeypatch.setattr(adapter, "safe_gemini_call", model)
    handler = PersistedRoutineFeedbackHandler(store=store, selector=select_dated_routine,
        clock=lambda: NOW, channel=channel, conversation_db_path=path, trusted_owner=True)
    result = handler(text, row)
    assert [store.occurrences(rid)[0].feedback for rid in (1, 2)] == ["complete", "complete"]
    assert result is not None and '"routine_id": 1' in result.content and '"routine_id": 2' in result.content
    assert "Roblox" in result.content and "Πάρκο" in result.content
    assert handler(text, row) is not None  # Replay is truthful, never another send.
    assert store.occurrences(2)[0].delivered_at is None
    assert store.occurrences(1)[0].delivered_at == (NOW-timedelta(minutes=40) if prior else None)


@pytest.mark.parametrize("failure", ["unknown_id", "duplicate", "mixed_action", "future", "oversize",
    "history_race", "catalog_race", "rollback", "untrusted"])
def test_batch_rejects_whole_unsafe_or_stale_update(store, tmp_path, monkeypatch, failure):
    """Invalid members/races never partially complete or falsely acknowledge."""
    from memory.conversation_history import append_message
    from services import routine_completion_selector as adapter
    from services.routine_feedback_turn import PersistedRoutineFeedbackHandler
    with store.connection_factory() as connection:
        connection.execute("INSERT INTO routines VALUES (2,'Park activity',0,0,0,1,'active',1,NULL,NULL,0,'Everyday','19:30')")
    if failure == "rollback":
        assert store.record_feedback(2, NOW.date(), "skip_today", at=NOW)
    path = str(tmp_path / "history.db")
    text = "Παίξαμε νωρίτερα, τώρα ήρθαμε πάρκο"
    row = append_message(role="user", channel="web", timestamp=NOW, content=text, db_path=path)
    items = [{"action": "complete", "routine_id": rid, "occurrence_date": NOW.date().isoformat()} for rid in (1, 2)]
    if failure == "unknown_id": items[1]["routine_id"] = 999
    if failure == "duplicate": items[1]["routine_id"] = 1
    if failure == "mixed_action": items[1]["action"] = "pause"
    if failure == "future": items[1]["occurrence_date"] = (NOW+timedelta(days=1)).date().isoformat()
    if failure == "oversize": items *= 3
    def model(_):
        if failure == "history_race": append_message(role="user", channel="matrix",
            content="Δεν πήγαμε τελικά", timestamp=NOW, db_path=path)
        if failure == "catalog_race":
            with store.connection_factory() as connection:
                connection.execute("UPDATE routines SET event_name='Other activity' WHERE id=2")
        return SimpleNamespace(text=json.dumps({"selections": items}))
    monkeypatch.setattr(adapter, "safe_gemini_call", model)
    handler = PersistedRoutineFeedbackHandler(store=store, selector=adapter.select_dated_routine,
        clock=lambda: NOW, channel="web", conversation_db_path=path, trusted_owner=failure != "untrusted")
    result = handler(text, row)
    assert store.occurrences(1) == []
    if failure == "rollback":
        assert store.occurrences(2)[0].feedback == "skip_today"
    else:
        assert store.occurrences(2) == []
    if result is not None:
        receipt = json.loads(result.content.splitlines()[0])
        assert receipt["status"] in {"none", "stale"}
        assert receipt["action"] == "none" and receipt["routine_id"] is None
        assert receipt["occurrence_date"] is None
    assert result is None or '"outcomes"' not in result.content


@pytest.mark.parametrize("phase", ["playing_then_plan", "studied_then_park_plan"])
def test_current_activity_does_not_skip_prior_play_or_complete_future_visit(store, tmp_path, monkeypatch, phase):
    """The 71-minute old owner report reaches the actual production selector."""
    from memory.conversation_history import append_message
    from services import routine_completion_selector as adapter
    from services.routine_feedback_turn import PersistedRoutineFeedbackHandler
    with store.connection_factory() as connection:
        connection.execute("UPDATE routines SET event_name='Roblox με τον Αλέξανδρο' WHERE id=1")
        connection.execute("INSERT INTO routines VALUES (2,'Πάρκο με τον Αλέξανδρο',0,0,0,1,'active',1,NULL,NULL,0,'Everyday','19:30')")
    path = str(tmp_path / "history.db")
    append_message(role="user", channel="matrix", timestamp=NOW-timedelta(minutes=71),
        content="τώρα παίζω Roblox με τον Αλέξανδρο", db_path=path)
    text = ("σπιτι ειμαι φιλε τωρα παιζω roblox με τον αλεξανδρο και ποιο μετα θα παμε παρκο"
        if phase == "playing_then_plan" else "διαβασαμε λιγο θελει πολυ υπομονη τωρα παμε παρκο")
    row = append_message(role="user", channel="web", timestamp=NOW, content=text, db_path=path)
    def model(prompt):
        assert "τώρα παίζω Roblox" in prompt and "skip_today requires a clear" in prompt
        return SimpleNamespace(text=json.dumps({"action": "complete" if phase == "playing_then_plan" else "none",
            "routine_id": 1 if phase == "playing_then_plan" else None,
            "occurrence_date": NOW.date().isoformat() if phase == "playing_then_plan" else None}))
    monkeypatch.setattr(adapter, "safe_gemini_call", model)
    handler = PersistedRoutineFeedbackHandler(store=store, selector=adapter.select_dated_routine,
        clock=lambda: NOW, channel="web", conversation_db_path=path, trusted_owner=True)
    result = handler(text, row)
    assert store.occurrences(2) == []
    if phase == "playing_then_plan":
        assert store.occurrences(1)[0].feedback == "complete" and result is not None
    else:
        assert store.occurrences(1) == [] and result is not None
        assert json.loads(result.content.splitlines()[0]) == {
            "status": "none", "action": "none", "routine_id": None, "occurrence_date": None}
