"""Daily owner context uses real isolated stores and mocked provider boundaries."""
from datetime import datetime, timedelta
from types import SimpleNamespace
import json

import pytest

from services.routine_feedback import ATHENS

NOW = datetime(2026, 10, 8, 10, 9, 47, tzinfo=ATHENS)


@pytest.mark.parametrize("noise", ["yesterday", "external"])
def test_daily_bound_counts_only_eligible_athens_day_sources(tmp_path, noise):
    """Unrelated rows must not disable an otherwise complete owner-day view."""
    from memory import conversation_history as history
    path = str(tmp_path / "history.db")
    for index in range(258):
        history.append_message(role="user", channel="web", content=f"noise {index}",
            timestamp=NOW-timedelta(days=1) if noise == "yesterday" else NOW,
            metadata={"untrusted_external_tool_names":["user_provided_asset"]} if noise == "external" else {},
            db_path=path)
    history.append_message(role="user", channel="matrix", content="today plan", timestamp=NOW, db_path=path)
    assert [row["content"] for row in history.load_daily_state_messages(now=NOW, db_path=path)] == ["today plan"]


@pytest.mark.parametrize("mode", ["ordinary", "resolution"])
@pytest.mark.parametrize("noise", ["assistant", "external"])
def test_unrelated_history_during_model_does_not_lose_owner_update(tmp_path, monkeypatch, mode, noise):
    """Only a newer trusted owner source may invalidate source freshness."""
    from memory import conversation_history as history, routine_db as db
    from services import context_extractor as extractor
    path = str(tmp_path / "history.db")
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "routines.db"))
    db.setup_db()
    source = history.append_message(role="user", channel="matrix", content="Έφυγα μόνος",
                                    timestamp=NOW, db_path=path)
    def model(_):
        history.append_message(role="assistant" if noise == "assistant" else "user",
            channel="web", content="unrelated notification", timestamp=NOW, db_path=path,
            metadata={"untrusted_external_tool_names":["user_provided_asset"]} if noise == "external" else {})
        payload = {
            "flags":{"partner_with_user":False}, "event_rowid":source["rowid"],
            "support_rowids":[source["rowid"]]}
        return SimpleNamespace(text=json.dumps(payload))
    monkeypatch.setattr(extractor, "safe_gemini_call", model)
    monkeypatch.setattr(extractor, "reconcile_context_message", lambda _:None)
    if mode == "ordinary":
        extractor.extract_and_update_context_flags("Έφυγα μόνος", now=NOW, conversation_db_path=path)
    else:
        assert extractor.resolve_daily_context_before_question(("partner_with_user",), now=NOW,
            still_current=lambda:True, channel="matrix", conversation_db_path=path)
    assert db.get_context_state("partner_with_user")["value"] == "false"


@pytest.mark.parametrize("channel", ["web", "matrix", "telegram"])
@pytest.mark.parametrize("text,payload,expected_mode", [
    ("Εγώ φτάνω στη δουλειά, η Σοφία ήτανε σπίτι πριν φύγω",
     {"user_out_of_home": True, "partner_with_user": False}, "office"),
    ("Η Σοφία δουλεύει από το σπίτι σήμερα",
     {"partner_at_work": True, "partner_work_mode": "remote"}, "remote"),
])
def test_partner_work_mode_uses_semantic_subject_not_word_cooccurrence(
    tmp_path, monkeypatch, channel, text, payload, expected_mode,
):
    """Real reconciliation must not overwrite subject-aware canonical writes."""
    from memory import conversation_history as history, routine_db as db
    from services import context_extractor as extractor, routine_reconciler as reconciler
    path = str(tmp_path / "history.db")
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "routines.db"))
    db.setup_db()
    db.set_context_states_if_unchanged({"partner_work_mode": ("office", "2026-10-08")},
        {"partner_work_mode": None}, recorded_at=NOW - timedelta(minutes=1))
    source = history.append_message(role="user", channel=channel, timestamp=NOW, content=text, db_path=path)
    monkeypatch.setattr(extractor, "safe_gemini_call",
                        lambda _: SimpleNamespace(text=json.dumps({"flags": payload,
                            "event_rowid": source["rowid"], "support_rowids": [source["rowid"]]})))
    monkeypatch.setattr(reconciler, "_infer_llm_reconciliation_candidates", lambda *a, **k: [])
    extractor.extract_and_update_context_flags(text, channel=channel, now=NOW,
                                               conversation_db_path=path)
    assert db.get_context_state("partner_work_mode")["value"] == expected_mode
    if expected_mode == "remote":
        assert db.get_context_state("partner_at_work")["value"] == "true"
    else:
        assert db.get_context_state("partner_with_user")["value"] == "false"


@pytest.mark.parametrize("channel", ["web", "matrix", "telegram"])
def test_daily_plan_combines_with_departure_before_question(tmp_path, monkeypatch, channel):
    from memory import conversation_history as history, routine_db as db
    from services import context_extractor as extractor
    path = str(tmp_path / "history.db")
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "routines.db"))
    db.setup_db()
    history.append_message(role="user", channel="web", timestamp=NOW.replace(hour=8, minute=39),
        content="Σήμερα η Σοφία δεν δουλεύει, θα είναι σπίτι για την παράδοση", db_path=path)
    text = "Έφυγα για δουλειά, στον δρόμο είμαι"
    source = history.append_message(role="user", channel=channel, timestamp=NOW, content=text, db_path=path)
    def model(prompt):
        assert "Σήμερα η Σοφία δεν δουλεύει" in prompt
        assert "2026-10-08T08:39" in prompt
        assert "daily" in prompt.lower()
        return SimpleNamespace(text=json.dumps({"flags": {"partner_with_user": False,
            "user_out_of_home": True}, "event_rowid": source["rowid"],
            "support_rowids": [source["rowid"]]}))
    monkeypatch.setattr(extractor, "safe_gemini_call", model)
    monkeypatch.setattr(extractor, "reconcile_context_message", lambda _: None)
    extractor.extract_and_update_context_flags(text, channel=channel, now=NOW, conversation_db_path=path)
    assert db.get_context_state("partner_with_user")["value"] == "false"
    assert db.get_context_state("user_out_of_home")["value"] == "true"
    assert db.get_context_state("user_at_work") is None
    assert db.get_context_state("partner_work_mode") is None


def test_daily_reference_excludes_other_days_external_and_future(tmp_path):
    from memory import conversation_history as history
    path = str(tmp_path / "history.db")
    for text, stamp, metadata in [
        ("today", NOW.replace(hour=8), {}),
        ("yesterday", NOW-timedelta(days=1), {}),
        ("future", NOW+timedelta(minutes=1), {}),
        ("external", NOW, {"untrusted_external_tool_names": ["user_provided_asset"]}),
    ]:
        history.append_message(role="user", channel="web", content=text,
            timestamp=stamp, metadata=metadata, db_path=path)
    rows = history.load_daily_state_messages(now=NOW, db_path=path)
    assert [row["content"] for row in rows] == ["today"]


def test_new_user_message_during_inference_cannot_commit(tmp_path, monkeypatch):
    from memory import conversation_history as history, routine_db as db
    from services import context_extractor as extractor
    path = str(tmp_path / "history.db")
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "routines.db"))
    db.setup_db()
    text = "Έφυγα μόνος για δουλειά"
    source = history.append_message(role="user", channel="matrix", timestamp=NOW, content=text, db_path=path)
    def model(_):
        history.append_message(role="user", channel="web", timestamp=NOW,
                               content="Τελικά δεν έφυγα", db_path=path)
        return SimpleNamespace(text=json.dumps({"flags": {"partner_with_user": False,
            "user_out_of_home": True}, "event_rowid": source["rowid"],
            "support_rowids": [source["rowid"]]}))
    monkeypatch.setattr(extractor, "safe_gemini_call", model)
    monkeypatch.setattr(extractor, "reconcile_context_message", lambda _: None)
    extractor.extract_and_update_context_flags(text, now=NOW, conversation_db_path=path)
    assert db.get_context_state("user_out_of_home") is None


@pytest.mark.parametrize("channel", ["matrix", "telegram"])
def test_pre_question_resolution_persists_event_time_and_avoids_send(tmp_path, monkeypatch, channel):
    from memory import conversation_history as history, routine_db as db
    from memory.routine_context_clarification import ClarificationStore
    from services import context_extractor as extractor
    from services.routine_context_clarification import RoutineCandidate
    from services.routine_context_clarification_poll import PollSnapshot, run_clarification_poll
    from services.routine_context_evidence import evaluate_stored_evidence
    path = str(tmp_path / "history.db")
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "routines.db"))
    db.setup_db()
    plan = history.append_message(role="user", channel="web", timestamp=NOW.replace(hour=8, minute=39),
        content="Σήμερα η Σοφία δεν δουλεύει, μένει σπίτι", db_path=path)
    departure = history.append_message(role="user", channel="matrix", timestamp=NOW,
        content="Έφυγα για δουλειά", db_path=path)
    check = NOW.replace(hour=10, minute=46)
    condition = {"condition_type":"context_flag", "condition_mode":"suppress_when_true",
                 "condition_payload":{"flag":"partner_with_user","equals":True}}
    routine = RoutineCandidate("4", "Μήνυμα στη Σοφία", check+timedelta(minutes=14), (condition,))
    def snapshot(_):
        return PollSnapshot((routine,), {}, {"partner_with_user":evaluate_stored_evidence(
            db.get_context_state("partner_with_user"), now=check)}, str(history.get_max_rowid(db_path=path)))
    calls = []
    def model(prompt):
        calls.append(prompt)
        return SimpleNamespace(text=json.dumps({"flags":{"partner_with_user":False},
            "event_rowid":departure["rowid"], "support_rowids":[plan["rowid"],departure["rowid"]]}))
    monkeypatch.setattr(extractor, "safe_gemini_call", model)
    args = dict(store=ClarificationStore(tmp_path/"questions.json"), clock=lambda:check,
        selected_channel=lambda:channel, snapshot_loader=snapshot, unavailable=lambda:False,
        classify=lambda _: pytest.fail("Resolved context must not generate a question"),
        budget=lambda:True, sender=lambda *args:pytest.fail("No redundant question"), record=lambda **kwargs:None,
        resolve_context=lambda state, now, fresh: extractor.resolve_daily_context_before_question(
            ("partner_with_user",), now=now, still_current=fresh, channel=channel, conversation_db_path=path))
    assert run_clarification_poll(**args) == "not_due"
    state = db.get_context_state("partner_with_user")
    assert state["value"] == "false" and state["updated_at"] == NOW.isoformat()
    assert run_clarification_poll(**args) == "not_due"
    assert len(calls) == 1


@pytest.mark.parametrize("scenario", ["old_event", "canonical_race", "history_race", "gps_race",
    "newer_state", "bad_source", "future_intent", "contradiction", "provider_failure"])
def test_pre_question_safety_never_commits_unsupported_or_stale_inference(tmp_path, monkeypatch, scenario):
    from memory import conversation_history as history, routine_db as db
    from services import context_extractor as extractor
    path = str(tmp_path / "history.db")
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "routines.db"))
    db.setup_db()
    when = NOW-timedelta(hours=3) if scenario == "old_event" else NOW
    source = history.append_message(role="user", channel="matrix", timestamp=when,
        content="Θα φύγω αργότερα" if scenario == "future_intent" else "Έφυγα μόνος για δουλειά", db_path=path)
    if scenario == "contradiction":
        history.append_message(role="user", channel="web", timestamp=NOW,
            content="Τελικά πάμε μαζί με τη Σοφία", db_path=path)
    if scenario == "newer_state":
        db.set_context_state("partner_with_user", "true", NOW.date().isoformat())
    fresh = {"value":True}
    def model(prompt):
        assert "Future intention does not establish completed travel" in prompt
        assert "Newer clear contrary events supersede plans" in prompt
        if scenario == "canonical_race":
            db.set_context_state("partner_with_user", "true", NOW.date().isoformat())
        if scenario == "history_race":
            history.append_message(role="user", channel="web", timestamp=NOW+timedelta(seconds=1),
                content="Δεν έφυγα τελικά", db_path=path)
        if scenario == "gps_race":
            fresh["value"] = False
        if scenario == "provider_failure":
            raise RuntimeError("offline injected provider failure")
        return SimpleNamespace(text=json.dumps({
            "flags":{} if scenario in {"future_intent","contradiction"} else {"partner_with_user":False},
            "event_rowid":999 if scenario == "bad_source" else source["rowid"],
            "support_rowids":[source["rowid"]]}))
    monkeypatch.setattr(extractor, "safe_gemini_call", model)
    assert not extractor.resolve_daily_context_before_question(("partner_with_user",), now=NOW,
        still_current=lambda:fresh["value"], channel="matrix", conversation_db_path=path)
    state = db.get_context_state("partner_with_user")
    assert state is None or state["value"] == "true"


@pytest.mark.parametrize("oversize", ["row", "day"])
def test_daily_reference_does_not_silently_drop_context(tmp_path, oversize):
    from memory import conversation_history as history
    path = str(tmp_path / "history.db")
    for index in range(129 if oversize == "day" else 1):
        history.append_message(role="user", channel="web", timestamp=NOW,
            content=str(index)+("x"*4001 if oversize == "row" else ""), db_path=path)
    with pytest.raises(ValueError):
        history.load_daily_state_messages(now=NOW, db_path=path)


def test_failed_daily_resolution_is_bounded_and_keeps_normal_question(tmp_path):
    from tests.test_routine_context_clarification_poll import harness
    from services.routine_context_clarification_poll import run_clarification_poll
    store, sends, _, _, args = harness(tmp_path)
    calls = []
    args["resolve_context"] = lambda *a: calls.append(True) or False
    assert run_clarification_poll(**args) == "delivered"
    assert run_clarification_poll(**args) == "waiting_answer"
    assert len(calls) == 1 and len(sends) == 1


def test_unavailable_daily_context_preserves_explicit_current_report(tmp_path, monkeypatch):
    from memory import routine_db as db
    from services import context_extractor as extractor
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "routines.db"))
    db.setup_db()
    def unavailable(**kwargs):
        raise ValueError("bounded source view unavailable")
    monkeypatch.setattr(extractor, "load_daily_state_messages", unavailable)
    monkeypatch.setattr(extractor, "safe_gemini_call", lambda _:SimpleNamespace(text='{"partner_with_user":false}'))
    monkeypatch.setattr(extractor, "reconcile_context_message", lambda _:None)
    extractor.extract_and_update_context_flags("Δεν είμαι με τη Σοφία τώρα", now=NOW,
        conversation_db_path=str(tmp_path/"history.db"))
    assert db.get_context_state("partner_with_user")["value"] == "false"


@pytest.mark.parametrize("payload", [
    {"flags":{"partner_with_user":"false"},"event_rowid":1,"support_rowids":[1]},
    {"flags":{"user_at_work":True},"event_rowid":1,"support_rowids":[1]},
    {"flags":{"partner_with_user":False},"event_rowid":True,"support_rowids":[1]},
    {"flags":{"partner_with_user":False},"event_rowid":1,"support_rowids":[]},
    {"flags":{"partner_with_user":False},"event_rowid":1,"support_rowids":[1,1]},
])
def test_invalid_resolution_cannot_write_flags(tmp_path, monkeypatch, payload):
    from memory import conversation_history as history, routine_db as db
    from services import context_extractor as extractor
    path = str(tmp_path / "history.db")
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "routines.db"))
    db.setup_db()
    history.append_message(role="user", channel="web", timestamp=NOW, content="Έφυγα μόνος", db_path=path)
    monkeypatch.setattr(extractor, "safe_gemini_call", lambda _:SimpleNamespace(text=json.dumps(payload)))
    assert not extractor.resolve_daily_context_before_question(("partner_with_user",), now=NOW,
        still_current=lambda:True, channel="matrix", conversation_db_path=path)
    assert db.get_context_state("partner_with_user") is None
    assert db.get_context_state("user_at_work") is None
