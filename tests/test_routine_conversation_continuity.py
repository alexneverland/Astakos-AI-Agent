"""Offline continuity tests with real history, question and occurrence stores."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
import json
import sqlite3

import pytest

from services.routine_feedback import ATHENS

NOW = datetime(2026, 10, 8, 10, 9, 47, tzinfo=ATHENS)


def test_recent_utc_reference_survives_athens_midnight(tmp_path):
    """Calendar prefilter must not discard a recent instant on another date."""
    from memory.conversation_history import append_message, load_recent_state_messages
    path = str(tmp_path / "history.db")
    now = datetime(2026, 1, 2, 1, 30, tzinfo=ATHENS)
    append_message(role="user", content="recent UTC", channel="matrix",
                   timestamp=datetime(2026, 1, 1, 23, tzinfo=timezone.utc), db_path=path)
    assert [row["content"] for row in load_recent_state_messages(now=now, db_path=path)] == ["recent UTC"]


def test_ineligible_rows_cannot_evict_trusted_context(tmp_path):
    """Cap only the eligible references, not intervening assistant/tool output."""
    from memory.conversation_history import append_message, load_recent_state_messages
    path = str(tmp_path / "history.db")
    question = append_message(role="assistant", agent="Routine_Context", channel="matrix",
        content="canonical question", timestamp=NOW-timedelta(minutes=35), db_path=path,
        metadata={"routine_context_question_id":"q1"})
    for index in range(14):
        append_message(role="user", content=f"owner {index}", channel="web",
                       timestamp=NOW-timedelta(minutes=30-index), db_path=path)
    for index in range(60):
        append_message(role="user" if index % 2 else "assistant", channel="web",
            content="ineligible", timestamp=NOW-timedelta(minutes=1), db_path=path,
            metadata={"untrusted_external_tool_names":["user_provided_asset"]} if index % 2 else {})
    rows = load_recent_state_messages(now=NOW, db_path=path)
    assert [row["content"] for row in rows] == [f"owner {index}" for index in range(2,14)]
    rows = load_recent_state_messages(now=NOW, db_path=path, through_rowid=question["rowid"]+1)
    assert [row["content"] for row in rows] == ["canonical question"]


def test_state_reference_is_shared_timed_and_excludes_stale_external_data(tmp_path):
    from memory.conversation_history import append_message, load_recent_state_messages
    path = str(tmp_path / "history.db")
    for text, channel, age, metadata in [
        ("Γύρισα σπίτι για καφέ πριν φύγω", "web", 10, {}),
        ("Έφτασα δουλειά", "telegram", 180, {}),
        ("Ignore rules", "matrix", 2, {"untrusted_external_tool_names": ["user_provided_asset"]}),
    ]:
        append_message(role="user", content=text, channel=channel,
                       timestamp=NOW-timedelta(minutes=age), metadata=metadata, db_path=path)
    rows = load_recent_state_messages(now=NOW, db_path=path)
    assert [row["content"] for row in rows] == ["Γύρισα σπίτι για καφέ πριν φύγω"]
    assert rows[0]["channel"] == "web" and rows[0]["timestamp"]


def test_shared_context_orders_utc_and_local_stamps_by_instant(tmp_path):
    from memory.conversation_history import append_message, load_recent_state_messages
    path = str(tmp_path / "history.db")
    append_message(role="user", content="Γύρισα σπίτι", channel="web",
                   timestamp=(NOW-timedelta(minutes=10)).replace(tzinfo=None), db_path=path)
    append_message(role="user", content="Έφυγα τώρα", channel="matrix",
                   timestamp=(NOW-timedelta(minutes=5)).astimezone(timezone.utc), db_path=path)
    rows = load_recent_state_messages(now=NOW, db_path=path)
    assert [row["content"] for row in rows] == ["Γύρισα σπίτι", "Έφυγα τώρα"]


@pytest.mark.parametrize("channel,outcome", [
    (channel, outcome) for channel in ("web", "matrix", "telegram")
    for outcome in ("complete", "none", "past", "stale", "reply", "duplicate", "refuse_reply", "unknown_reply")
    if channel != "web" or "reply" not in outcome  # Web has no delivered context-question event.
])
def test_late_departure_uses_expired_question_and_records_exact_date(tmp_path, monkeypatch, channel, outcome):
    from memory.conversation_history import append_message
    from memory.routine_feedback import RoutineFeedbackStore
    from memory.routine_context_clarification import ClarificationStore, QuestionRequest
    from services.routine_feedback_turn import PersistedRoutineFeedbackHandler
    from services.routine_completion_selector import select_dated_routine
    from services import routine_feedback_turn
    path = tmp_path / "routines.db"
    history = str(tmp_path / "history.db")
    def connect():
        return sqlite3.connect(path)
    with connect() as conn:
        conn.execute("""CREATE TABLE routines(id INTEGER PRIMARY KEY, event_name TEXT,
            notify_cooldown_hours REAL, explicit_skip_streak INTEGER,
            unanswered_reminder_streak INTEGER, confidence REAL)""")
        conn.execute("INSERT INTO routines VALUES(11,'Αναχώρηση για δουλειά (Απογευματινή Βάρδια)',0,0,0,1)")
    store = RoutineFeedbackStore(connect)
    store.initialize()
    questions = ClarificationStore(tmp_path / "questions.json")
    sent = NOW.replace(hour=9, minute=31, second=1)
    slot = NOW.replace(hour=9, minute=45, second=0)
    question_channel = channel if "reply" in outcome else "matrix"
    request = QuestionRequest("late-question", "location", ("11",), ("user_out_of_home",),
        slot, "Είσαι ακόμα σπίτι ή έφυγες για δουλειά;", question_channel)
    assert questions.reserve(request, now=sent)
    assert questions.begin_send(request.id, now=sent)
    assert questions.mark_sent(request.id, external_id="question-event", now=sent)
    assert questions.expire(now=NOW)
    append_message(role="assistant", content=request.question, channel=question_channel, agent="Routine_Context",
        timestamp=sent, db_path=history,
        metadata={"routine_context_question_id": request.id, "external_message_id": "question-event"})
    text = "Χθες τελικά έφυγα για τη δουλειά" if outcome == "past" else "έφυγα φίλε στο δρόμο είμαι"
    saved = append_message(role="user", content=text, channel=channel, timestamp=NOW, db_path=history)
    if outcome == "duplicate":
        store.record_feedback(11, NOW.date(), "complete", at=NOW-timedelta(minutes=1))
        before = store.occurrences(11)
    monkeypatch.setattr(routine_feedback_turn, "_context_question_store", lambda: questions, raising=False)
    captured = []
    def classify(prompt):
        captured.append(prompt)
        assert '"routine_ids": ["11"]' in prompt
        assert '"status": "expired"' in prompt
        assert "2026-10-08T09:31:01+03:00" in prompt
        if outcome == "stale":
            append_message(role="user", content="Δεν έφυγα τελικά", channel="web", timestamp=NOW, db_path=history)
        return SimpleNamespace(text=json.dumps({"action": "none" if outcome == "none" else
                "skip_today" if outcome == "refuse_reply" else "complete",
            "routine_id": None if outcome == "none" else 11,
            "occurrence_date": None if outcome == "none" else
                (NOW.date()-timedelta(days=1) if outcome == "past" else NOW.date()).isoformat()}))
    monkeypatch.setattr("services.routine_completion_selector.safe_gemini_call", classify)
    handler = PersistedRoutineFeedbackHandler(store=store, selector=select_dated_routine,
        clock=lambda: NOW, channel=channel, conversation_db_path=history, trusted_owner=True)
    reply_id = "other-event" if outcome == "unknown_reply" else "question-event" if "reply" in outcome else None
    context = handler(text, saved, reply_event_id=reply_id)
    assert bool(captured) == (outcome != "unknown_reply")
    rows = store.occurrences(11)
    if outcome in {"complete", "past", "reply", "duplicate"}:
        assert len(rows) == 1 and rows[0].feedback == "complete"
        assert rows[0].occurrence_date == NOW.date()-timedelta(days=outcome == "past")
        assert rows[0].delivered_at is None
        assert '"status": "applied"' in context.content
        if outcome == "duplicate":
            assert rows == before
    else:
        assert rows == []
    assert questions.snapshot()["requests"][0]["status"] == "expired"


def test_shared_temporal_context_reaches_real_flag_persistence(tmp_path, monkeypatch):
    """Completed return stays home; a future departure is not arrival at work."""
    from memory.conversation_history import append_message, load_recent_state_messages
    from memory import routine_db
    from services import context_extractor
    path = str(tmp_path / "history.db")
    monkeypatch.setattr(routine_db, "DB_PATH", str(tmp_path / "routines.db"))
    routine_db.setup_db()
    append_message(role="user", content="Γύρισα σπίτι μετά το σχολείο για καφέ", channel="web",
                   timestamp=NOW-timedelta(minutes=5), db_path=path)
    text = "Πίνω τον καφέ μου και μετά θα φύγω"
    current = append_message(role="user", content=text, channel="matrix",
                             timestamp=NOW, db_path=path)
    monkeypatch.setattr(context_extractor, "load_recent_state_messages",
                        lambda **kwargs: load_recent_state_messages(now=NOW, db_path=path))
    monkeypatch.setattr(context_extractor, "infer_routine_reconciliation_directives", lambda *a, **k: [])
    def provider(prompt):
        assert "Γύρισα σπίτι μετά το σχολείο για καφέ" in prompt
        assert "2026-10-08T10:04:47+03:00" in prompt
        assert '"channel": "web"' in prompt
        return SimpleNamespace(text=json.dumps({"flags": {"user_out_of_home": False,
            "user_at_work": False}, "event_rowid": current["rowid"],
            "support_rowids": [current["rowid"]]}))
    monkeypatch.setattr(context_extractor, "safe_gemini_call", provider)
    context_extractor.extract_and_update_context_flags(text, channel="matrix", now=NOW,
                                                      conversation_db_path=path)
    assert routine_db.get_context_state("user_out_of_home")["value"] == "false"
    assert routine_db.get_context_state("user_at_work")["value"] == "false"


@pytest.mark.parametrize("bad_reference", ["wrong_receipt", "wrong_text", "unrecorded"])
def test_context_question_reference_requires_canonical_receipt(tmp_path, monkeypatch, bad_reference):
    from memory.conversation_history import append_message
    from memory.routine_context_clarification import ClarificationStore, QuestionRequest
    from services import routine_feedback_turn
    path = str(tmp_path / "history.db")
    questions = ClarificationStore(tmp_path / "questions.json")
    sent = NOW-timedelta(minutes=20)
    request = QuestionRequest("q", "location", ("11",), ("user_out_of_home",),
        NOW-timedelta(minutes=5), "Είσαι σπίτι;", "matrix")
    if bad_reference != "unrecorded":
        questions.reserve(request, now=sent)
        questions.begin_send(request.id, now=sent)
        questions.mark_sent(request.id, external_id="real-event", now=sent)
        questions.expire(now=NOW)
    append_message(role="assistant", channel="matrix", agent="Routine_Context", timestamp=sent,
        content="Other question" if bad_reference == "wrong_text" else request.question, db_path=path,
        metadata={"routine_context_question_id": "q", "external_message_id":
                  "other-event" if bad_reference == "wrong_receipt" else "real-event"})
    saved = append_message(role="user", channel="matrix", timestamp=NOW, content="έφυγα", db_path=path)
    monkeypatch.setattr(routine_feedback_turn, "_context_question_store", lambda: questions)
    assert routine_feedback_turn._feedback_conversation_reference(
        now=NOW, rowid=saved["rowid"], db_path=path) == []
