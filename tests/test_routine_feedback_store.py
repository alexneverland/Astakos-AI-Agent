"""Real temporary SQLite ledger tests without production application imports."""
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime
from multiprocessing import get_context
from zoneinfo import ZoneInfo

import pytest

from memory.routine_feedback import RoutineFeedbackStore
from services.routine_feedback import evaluate_feedback

ATHENS = ZoneInfo("Europe/Athens")


@pytest.fixture(autouse=True)
def isolate_messenger_draft(tmp_path, monkeypatch):
    """Never inspect or overwrite the owner's real local draft."""
    from core import messenger_draft
    monkeypatch.setattr(messenger_draft, "_settings",
                        lambda: (str(tmp_path / "isolated-draft.json"), 1800))


@pytest.fixture
def store(tmp_path):
    """Initialize only a temporary routine database and additive ledger."""
    path = tmp_path / "routines.db"

    def connect():
        connection = sqlite3.connect(path, timeout=5)
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    with connect() as connection:
        connection.execute("""CREATE TABLE routines (id INTEGER PRIMARY KEY,
            event_name TEXT DEFAULT 'Καθάρισμα κουνελιού',
            notify_cooldown_hours REAL DEFAULT 72, explicit_skip_streak INTEGER DEFAULT 0,
            unanswered_reminder_streak INTEGER DEFAULT 0, confidence REAL DEFAULT 0.6,
            last_triggered TEXT DEFAULT '2026-09-30', last_notified_ts REAL DEFAULT 123,
            state TEXT DEFAULT 'paused', is_active INTEGER DEFAULT 1,
            paused_until TEXT DEFAULT '2026-10-09', paused_indefinitely INTEGER DEFAULT 0,
            pause_reason TEXT DEFAULT 'temporary')""")
        connection.execute("INSERT INTO routines (id) VALUES (11)")
    ledger = RoutineFeedbackStore(connect)
    ledger.initialize()
    return ledger


def stamp(day, hour=9):
    """Return a deterministic instant for the ledger tests."""
    return datetime(2026, 10, day, hour, tzinfo=ATHENS)


@pytest.mark.parametrize("channel,target,expected", [
    ("matrix", "$routine", True), ("telegram", "$routine", False),
    ("matrix", "$unknown-approval", False), ("matrix", "", False),
])
def test_delivered_reply_ownership_preserves_identity_not_action_permission(store, channel, target, expected):
    """Only exact channel/receipt proof owns a reply, even after resolution."""
    store.record_delivery(11, stamp(7).date(), at=stamp(7), receipt_id="$routine",
        channel="matrix", question="Το έκανες;")
    assert store.is_delivered_question_target(channel=channel, event_id=target) is expected
    assert store.record_feedback(11, stamp(7).date(), "acknowledge", at=stamp(7))
    assert store.pending_question(now=stamp(7), reply_channel="matrix", reply_event_id="$routine") is None
    assert store.is_delivered_question_target(channel=channel, event_id=target) is expected


def test_draft_receipt_is_not_an_ordinary_routine_reply_target(store):
    """A separate draft receipt cannot suppress tool approval routing."""
    store.record_delivery(11, stamp(7).date(), at=stamp(7), receipt_id="$draft")
    assert not store.is_delivered_question_target(channel="matrix", event_id="$draft")


@pytest.mark.parametrize("scenario", ["accepted", "different_offer", "not_draft",
                                     "expired", "complete", "newer", "rollback", "naive"])
def test_draft_consumption_and_dated_engagement_commit_together(store, monkeypatch, scenario):
    """Canonical offer matching and ledger feedback share one real transaction."""
    from datetime import timedelta
    from memory import routine_db as db
    from core.exceptions import DBWriteError
    offered = stamp(7)
    now = offered + timedelta(minutes=5 if scenario != "expired" else 31)
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return now
    offered = Clock.fromtimestamp(offered.timestamp(), ATHENS)
    now = Clock.fromtimestamp(now.timestamp(), ATHENS)
    if scenario == "naive":
        offered, now = offered.replace(tzinfo=None), now.replace(tzinfo=None)
    monkeypatch.setattr(db, "datetime", Clock)
    monkeypatch.setattr(db, "get_connection", store.connection_factory)
    monkeypatch.setattr(db, "_dated_draft_feedback_recorder", store.record_draft_acknowledgement)
    for day in (4, 5, 6):
        store.record_delivery(11, stamp(day).date(), at=stamp(day), receipt_id=f"receipt-{day}")
    with store.connection_factory() as connection:
        connection.execute("""CREATE TABLE pending_confirmations (routine_id INTEGER PRIMARY KEY,
            event_name TEXT, sent_at TEXT, draft_offer INTEGER)""")
        connection.execute("INSERT INTO pending_confirmations VALUES (11,'Message Sofia',?,?)",
                           (offered.isoformat(), int(scenario != "not_draft")))
        connection.execute("UPDATE routines SET state='trigger_pending'")
    if scenario in {"complete", "newer"}:
        store.record_feedback(11, offered.date(), "complete" if scenario == "complete" else "skip_today",
                              at=now + timedelta(minutes=1) if scenario == "newer" else offered)
    if scenario == "rollback":
        with store.connection_factory() as connection:
            connection.execute("""CREATE TRIGGER reject_consumption BEFORE DELETE ON pending_confirmations
                BEGIN SELECT RAISE(ABORT, 'offline failure'); END""")
    if scenario == "rollback":
        with pytest.raises(DBWriteError):
            db.acknowledge_pending_draft_offer(11, offered)
    else:
        assert db.acknowledge_pending_draft_offer(11,
            offered + timedelta(seconds=1) if scenario == "different_offer" else offered) == (scenario in {"accepted", "naive"})
    with store.connection_factory() as connection:
        pending = connection.execute("SELECT COUNT(*) FROM pending_confirmations").fetchone()[0]
        state, last, confidence, cooldown = connection.execute(
            "SELECT state,last_triggered,confidence,notify_cooldown_hours FROM routines WHERE id=11").fetchone()
    assert pending == int(scenario not in {"accepted", "naive"})
    assert last == "2026-09-30" and confidence == 0.6
    assert state == ("active" if scenario in {"accepted", "naive"} else "trigger_pending")
    today = [row for row in store.occurrences(11) if row.occurrence_date == offered.date()]
    if scenario in {"accepted", "naive"}:
        assert cooldown == 0 and today[0].feedback == "acknowledge"
        assert today[0].delivered_at is None
        assert not db.acknowledge_pending_draft_offer(11, offered)
    elif scenario not in {"complete", "newer"}:
        assert not today


@pytest.mark.parametrize("channel", ["web", "telegram", "matrix"])
def test_saved_deferral_clears_pressure_without_completion_or_new_time(store, tmp_path, channel):
    """Every persisted channel bridge records deferral, not silence or rescheduling."""
    import json
    from datetime import timedelta
    from memory.conversation_history import append_message
    from services.routine_completion_helper import DatedRoutineSelection
    from services.routine_feedback_turn import PersistedRoutineFeedbackHandler
    now = stamp(7)
    for day in (4, 5, 6):
        store.record_delivery(11, stamp(day).date(), at=stamp(day), receipt_id=str(day))
    store.reconcile(11, now=now)
    assert routine_fields(store)[1] == 20
    store.record_delivery(11, now.date(), at=now - timedelta(minutes=1),
                          receipt_id="today-prompt", question="Shall we do this now?", channel=channel)
    before = routine_fields(store)
    path = str(tmp_path / "deferral-history.db")
    saved = append_message(role="user", content="Αργότερα φίλε, έχω δουλειά τώρα",
                           channel=channel, db_path=path)
    handler = PersistedRoutineFeedbackHandler(store=store,
        selector=lambda *args, **kw: DatedRoutineSelection("defer", 11, now.date()),
        clock=lambda: now, channel=channel, conversation_db_path=path, trusted_owner=True)
    result = handler(saved["content"], saved)
    outcome = json.loads(result.content.splitlines()[0])
    assert outcome["status"] == "clarify" and outcome["action"] == "defer"
    after = routine_fields(store)
    assert after[1:4] == (0, 0, 0)
    assert after[4:] == before[4:]
    today = store.occurrences(11)[-1]
    assert today.feedback == "defer" and today.delivered_at == now - timedelta(minutes=1)
    with store.connection_factory() as connection:
        assert connection.execute("SELECT receipt_id FROM routine_occurrences WHERE routine_id=11 AND occurrence_date=?",
                                  (now.date().isoformat(),)).fetchone()[0] == "today-prompt"
    assert store.pending_question(now=now) is None


@pytest.mark.parametrize("channel", ["matrix", "telegram"])
@pytest.mark.parametrize("answer", ["one", "ambiguous", "outside", "stale"])
def test_group_exact_reply_preserves_member_scope(store, tmp_path, channel, answer):
    """Real grouped correlation and saved-turn persistence, not an intermediate mock."""
    from memory.conversation_history import append_message
    from services.routine_completion_helper import DatedRoutineSelection, RoutineFeedbackGroupQuestion
    from services.routine_feedback_turn import process_stored_feedback_turn
    now = stamp(7)
    with store.connection_factory() as connection:
        connection.executemany("INSERT INTO routines (id) VALUES (?)", [(12,), (13,)])
    for rid in (11, 12):
        store.record_delivery(rid, now.date(), at=now, receipt_id="group-event",
            question="Rabbit care and school preparation?", channel=channel)
    pending = store.pending_question(now=now, reply_channel=channel, reply_event_id="group-event")
    assert isinstance(pending, RoutineFeedbackGroupQuestion)
    assert pending.routine_ids == (11, 12)
    path = str(tmp_path / "group-history.db")
    saved = append_message(role="user", content="Το σχολείο το ετοίμασα", channel=channel, db_path=path)
    def selector(text, candidates, dates, **kwargs):
        assert set(candidates) == {11, 12} and kwargs["pending_question"] == pending
        if answer == "ambiguous":
            return DatedRoutineSelection("clarify")
        if answer == "outside":
            return DatedRoutineSelection("complete", 13, now.date())
        if answer == "stale":
            store.record_feedback(11, now.date(), "complete", at=now)
        return DatedRoutineSelection("complete", 12, now.date())
    result = process_stored_feedback_turn(saved["content"],
        {11: "Rabbit care", 12: "School preparation", 13: "Unrelated routine"},
        {rid: frozenset({now.date()}) for rid in (11, 12, 13)},
        store=store, selector=selector, now=now, clock=lambda: now, trusted=True,
        user_rowid=saved["rowid"], conversation_db_path=path,
        reply_channel=channel, reply_event_id="group-event")
    assert result.status == {"one": "applied", "ambiguous": "clarify", "outside": "none", "stale": "stale"}[answer]
    assert store.occurrences(12)[0].feedback == ("complete" if answer == "one" else None)
    assert store.occurrences(11)[0].feedback == ("complete" if answer == "stale" else None)
    assert not store.occurrences(13)


def test_unrelated_pending_messages_do_not_become_one_group(store):
    """A shared-looking prompt is not group identity without matching transport evidence."""
    now = stamp(7)
    with store.connection_factory() as connection:
        connection.execute("INSERT INTO routines (id) VALUES (12)")
    store.record_delivery(11, now.date(), at=now, receipt_id="a", question="Do these?", channel="matrix")
    store.record_delivery(12, now.date(), at=now, receipt_id="b", question="Do these?", channel="matrix")
    assert store.pending_question(now=now) is None
    assert store.pending_question(now=now, reply_channel="matrix", reply_event_id="a").routine_id == 11


@pytest.mark.parametrize("difference", ["channel", "time", "question"])
def test_same_receipt_without_shared_delivery_proof_is_not_group(store, difference):
    """Receipt text alone must not combine separate channels or inconsistent evidence."""
    from datetime import timedelta
    now = stamp(7)
    with store.connection_factory() as connection:
        connection.execute("INSERT INTO routines (id) VALUES (12)")
    store.record_delivery(11, now.date(), at=now, receipt_id="shared", question="Both?", channel="matrix")
    store.record_delivery(12, now.date(),
        at=now - timedelta(seconds=1) if difference == "time" else now,
        receipt_id="shared", question="Other?" if difference == "question" else "Both?",
        channel="telegram" if difference == "channel" else "matrix")
    assert store.pending_question(now=now) is None


def test_partial_group_answer_leaves_other_member_pending(store):
    """Resolving one member never consumes the remaining routine's question."""
    from services.routine_completion_helper import RoutineFeedbackGroupQuestion, RoutineFeedbackQuestion
    now = stamp(7)
    with store.connection_factory() as connection:
        connection.execute("INSERT INTO routines (id) VALUES (12)")
    for rid in (11, 12):
        store.record_delivery(rid, now.date(), at=now, receipt_id="group", question="Both?", channel="matrix")
    assert isinstance(store.pending_question(now=now), RoutineFeedbackGroupQuestion)
    assert store.record_feedback(12, now.date(), "complete", at=now)
    pending = store.pending_question(now=now, reply_channel="matrix", reply_event_id="group")
    assert isinstance(pending, RoutineFeedbackQuestion) and pending.routine_id == 11
    assert store.occurrences(11)[0].feedback is None


@pytest.mark.parametrize("channel", ["web", "telegram", "matrix"])
def test_feedback_handler_prepares_draft_without_completing_routine(store, tmp_path, channel):
    """Accepting a structured offer creates local authorization, not completion."""
    from memory.conversation_history import append_message
    from services.routine_completion_helper import RoutineSelection
    from services.routine_feedback_turn import PersistedRoutineFeedbackHandler
    from services.matrix_routine_completion import MatrixRoutineDraftOffer

    path = str(tmp_path / "history.db")
    saved = append_message(role="user", content="Ετοίμασέ το", channel=channel, db_path=path)
    pending = {11: {"draft_offer": True, "event": "Message Sofia", "sent_at": stamp(7)}}
    def no_feedback(*a, **kw):
        pytest.fail("draft acceptance must not enter dated completion")
    handler = PersistedRoutineFeedbackHandler(store=store, selector=no_feedback,
        clock=lambda: stamp(7), channel=channel, conversation_db_path=path, trusted_owner=True,
        draft_loader=lambda: pending, draft_selector=lambda *a: RoutineSelection("draft", 11))
    result = handler("Ετοίμασέ το", saved)
    assert isinstance(result, MatrixRoutineDraftOffer)
    assert result.routine_id == 11
    assert result.sent_at == stamp(7)
    assert "MESSENGER_ROUTINE_DRAFT_OFFER" in result.context.content
    assert store.occurrences(11) == []
    assert pending[11]["draft_offer"] is True


@pytest.mark.parametrize("change", ["newer_owner", "replaced_offer", "expired", "expired_during_inference", "complete_not_draft"])
def test_draft_offer_handler_does_not_authorize_stale_or_non_draft_selection(store, tmp_path, change):
    """Only fresh semantic draft acceptance grants the existing local-draft scope."""
    from datetime import timedelta
    from memory.conversation_history import append_message
    from services.routine_completion_helper import RoutineSelection, DatedRoutineSelection
    from services.routine_feedback_turn import PersistedRoutineFeedbackHandler
    from services.matrix_routine_completion import MatrixRoutineDraftOffer

    path = str(tmp_path / "history.db")
    saved = append_message(role="user", content="owner reply", channel="matrix", db_path=path)
    clock = [stamp(7)]
    pending = {11: {"draft_offer": True, "event": "Message Sofia", "sent_at": stamp(7)}}
    if change == "expired":
        pending[11]["sent_at"] = stamp(7) - timedelta(minutes=31)
    def select(*a):
        if change == "newer_owner":
            append_message(role="user", content="cancel", channel="web", db_path=path)
        if change == "replaced_offer":
            pending[11] = {**pending[11], "sent_at": stamp(7) + timedelta(seconds=1)}
        if change == "expired_during_inference":
            clock[0] += timedelta(minutes=31)
        return RoutineSelection("complete" if change == "complete_not_draft" else "draft", 11)
    handler = PersistedRoutineFeedbackHandler(store=store,
        selector=lambda *a, **kw: DatedRoutineSelection("none"),
        clock=lambda: clock[0], channel="matrix", conversation_db_path=path, trusted_owner=True,
        draft_loader=lambda: pending, draft_selector=select)
    assert not isinstance(handler("owner reply", saved), MatrixRoutineDraftOffer)
    assert store.occurrences(11) == []


@pytest.mark.parametrize("channel", ["web", "telegram", "matrix"])
@pytest.mark.parametrize("created_during_inference", [False, True])
def test_existing_local_draft_prevents_routine_draft_authorization(
    store, tmp_path, monkeypatch, channel, created_during_inference,
):
    """Real staged content survives even when it appears during classification."""
    from core import messenger_draft
    from memory.conversation_history import append_message
    from services.routine_completion_helper import RoutineSelection, DatedRoutineSelection
    from services.routine_feedback_turn import PersistedRoutineFeedbackHandler
    from services.matrix_routine_completion import MatrixRoutineDraftOffer

    draft_path = tmp_path / "draft.json"
    monkeypatch.setattr(messenger_draft, "_settings", lambda: (str(draft_path), 1800))
    history = str(tmp_path / "history.db")
    saved = append_message(role="user", content="prepare it", channel=channel, db_path=history)
    pending = {11: {"draft_offer": True, "event": "Message Sofia", "sent_at": stamp(7)}}
    if not created_during_inference:
        messenger_draft.save_draft("Sofia", "Keep this existing message")

    def select(*args):
        if created_during_inference:
            messenger_draft.save_draft("Sofia", "Keep this existing message")
        else:
            pytest.fail("Do not classify a replacement offer while a draft is active")
        return RoutineSelection("draft", 11)

    handler = PersistedRoutineFeedbackHandler(store=store,
        selector=lambda *a, **kw: DatedRoutineSelection("none"), clock=lambda: stamp(7),
        channel=channel, conversation_db_path=history, trusted_owner=True,
        draft_loader=lambda: pending, draft_selector=select)
    assert not isinstance(handler("prepare it", saved), MatrixRoutineDraftOffer)
    assert messenger_draft.load_draft()["message"] == "Keep this existing message"
    assert store.occurrences(11) == []
    assert pending[11]["draft_offer"] is True


@pytest.mark.parametrize("channel", ["web", "telegram", "matrix"])
@pytest.mark.parametrize("change", ["replaced_offer", "expired", "active_draft", "newer_owner"])
def test_stale_draft_classification_cannot_fall_through_to_routine_feedback(
    store, tmp_path, channel, change,
):
    """A losing draft classification ends arbitration without a second mutation."""
    import json
    from datetime import timedelta
    from core import messenger_draft
    from memory.conversation_history import append_message
    from services.routine_completion_helper import RoutineSelection, DatedRoutineSelection
    from services.routine_feedback_turn import PersistedRoutineFeedbackHandler

    history = str(tmp_path / "history.db")
    saved = append_message(role="user", content="Ετοίμασέ το", channel=channel, db_path=history)
    pending = {11: {"draft_offer": True, "event": "Message Sofia", "sent_at": stamp(7)}}
    clock = [stamp(7)]
    calls = []

    def draft_select(*args):
        if change == "replaced_offer":
            pending[11] = {**pending[11], "sent_at": stamp(7) + timedelta(seconds=1)}
        elif change == "expired":
            clock[0] += timedelta(minutes=31)
        elif change == "active_draft":
            messenger_draft.save_draft("Sofia", "Keep the newer draft")
        else:
            append_message(role="user", content="cancel", channel="web", db_path=history)
        return RoutineSelection("draft", 11)

    def feedback_select(*args, **kwargs):
        calls.append("feedback")
        return DatedRoutineSelection("acknowledge", 11, stamp(7).date())

    handler = PersistedRoutineFeedbackHandler(store=store, selector=feedback_select,
        clock=lambda: clock[0], channel=channel, conversation_db_path=history, trusted_owner=True,
        draft_loader=lambda: pending, draft_selector=draft_select)
    result = handler("Ετοίμασέ το", saved)
    assert store.occurrences(11) == []
    assert calls == []
    assert json.loads(result.content.splitlines()[0])["status"] == "stale"
    assert pending[11]["draft_offer"] is True
    if change == "active_draft":
        assert messenger_draft.load_draft()["message"] == "Keep the newer draft"


def test_feedback_handler_exact_reply_does_not_use_another_implicit_question(store, tmp_path):
    """A reply to yesterday's receipt is not silently converted into today's yes."""
    from memory.conversation_history import append_message
    from services.routine_completion_helper import DatedRoutineSelection
    from services.routine_feedback_turn import PersistedRoutineFeedbackHandler

    path = str(tmp_path / "history.db")
    store.record_delivery(11, stamp(6).date(), at=stamp(6), receipt_id="old-event",
                          question="Did you clean it yesterday?", channel="matrix")
    store.record_delivery(11, stamp(7).date(), at=stamp(7), receipt_id="new-event",
                          question="Did you clean it today?", channel="matrix")
    saved = append_message(role="user", content="yes", channel="matrix", db_path=path)
    def select(*args, **kwargs):
        assert kwargs["pending_question"].event_id == "old-event"
        return DatedRoutineSelection("complete", 11, stamp(6).date())
    handler = PersistedRoutineFeedbackHandler(store=store, selector=select,
        clock=lambda: stamp(7), channel="matrix", conversation_db_path=path, trusted_owner=True)
    handler("yes", saved, reply_event_id="old-event")
    assert [row.feedback for row in store.occurrences(11)] == ["complete", None]


@pytest.mark.parametrize("channel", ["web", "telegram", "matrix"])
@pytest.mark.parametrize("action", ["complete", "acknowledge", "skip_today", "defer", "pause", "clarify", "none"])
def test_persisted_feedback_handler_carries_verified_outcome_to_graph(store, tmp_path, channel, action):
    """All adapters can reuse one outcome/context bridge without another mutation."""
    import json
    from memory.conversation_history import append_message
    from services.routine_completion_helper import DatedRoutineSelection
    from services.routine_feedback_turn import PersistedRoutineFeedbackHandler

    now = stamp(7)
    path = str(tmp_path / "conversation.db")
    saved = append_message(role="user", content="owner feedback", channel=channel, db_path=path)
    selection = DatedRoutineSelection(action, None if action == "none" else 11,
        None if action in {"none", "clarify"} else now.date())
    handler = PersistedRoutineFeedbackHandler(store=store, selector=lambda *a, **kw: selection,
        clock=lambda: now, channel=channel, conversation_db_path=path, trusted_owner=True)
    context = handler("owner feedback", saved)
    if action == "none":
        assert context is None
        assert store.occurrences(11) == []
        return
    outcome = json.loads(context.content.split("\n", 1)[0])
    assert outcome["status"] == ("clarify" if action in {"defer", "clarify"} else "applied")
    assert outcome["action"] == action
    assert "not an approval" in context.content
    assert "Do not repeat" in context.content
    if action == "clarify":
        assert store.occurrences(11) == []
    else:
        assert store.occurrences(11)[0].feedback == action


@pytest.mark.parametrize("change", ["untrusted", "rowid", "content", "channel", "role", "external"])
def test_feedback_context_bridge_rejects_invalid_owner_envelope(store, tmp_path, change):
    """Persisted identity is required; saved prose does not authenticate the owner."""
    from memory.conversation_history import append_message
    from services.routine_feedback_turn import PersistedRoutineFeedbackHandler

    path = str(tmp_path / "conversation.db")
    saved = append_message(role="user", content="done", channel="matrix", db_path=path)
    if change == "external":
        saved["metadata"] = {"untrusted_external_tool_names": ["user_provided_asset"]}
    elif change != "untrusted":
        saved[change] = {"rowid": True, "content": "different", "channel": "web", "role": "assistant"}[change]
    def forbidden(*a, **kw):
        pytest.fail("invalid envelope reached classification")
    handler = PersistedRoutineFeedbackHandler(store=store, selector=forbidden,
        clock=lambda: stamp(7), channel="matrix", conversation_db_path=path,
        trusted_owner=change != "untrusted")
    assert handler("done", saved) is None
    assert store.occurrences(11) == []


@pytest.mark.asyncio
async def test_matrix_feedback_bridge_preserves_yesterday_and_reports_date(store, tmp_path, monkeypatch):
    """Exercise the real adapter, common selector bridge, ledger and graph context."""
    import json
    from langchain_core.messages import AIMessage, SystemMessage
    from services.matrix_turn import MatrixTurnService
    from services.routine_completion_helper import DatedRoutineSelection
    from services.routine_feedback_turn import PersistedRoutineFeedbackHandler
    from services import routine_context_clarification as clarification
    from memory.conversation_history import load_messages

    monkeypatch.setattr(clarification, "try_context_question_reply", lambda *a, **kw: clarification.QuestionAnswer())
    now = stamp(7)
    store.record_delivery(11, stamp(6).date(), at=stamp(6), receipt_id="old-receipt")
    store.record_delivery(11, now.date(), at=now, receipt_id="today-receipt")
    path = str(tmp_path / "conversation.db")
    states = []
    class Graph:
        def stream(self, state, config):
            states.append(state)
            yield {"Chat_Agent": {"messages": [AIMessage(content="Noted for yesterday.")]}}
    handler = PersistedRoutineFeedbackHandler(store=store,
        selector=lambda *a, **kw: DatedRoutineSelection("complete", 11, stamp(6).date()),
        clock=lambda: now, channel="matrix", conversation_db_path=path, trusted_owner=True)
    service = MatrixTurnService(graph=Graph(), conversation_db_path=path,
        select_tool_channel=lambda channel: None, persisted_routine_confirmation_handler=handler)
    assert await service("Χθες το πρωί καθάρισα το κουνέλι", "$yesterday-completed") == "Noted for yesterday."
    assert [row.feedback for row in store.occurrences(11)] == ["complete", None]
    outcomes = [json.loads(message.content.split("\n", 1)[0]) for message in states[0]["messages"]
                if isinstance(message, SystemMessage) and message.content.startswith('{"status"')]
    assert outcomes == [{"status": "applied", "action": "complete", "routine_id": 11, "occurrence_date": "2026-10-06"}]
    assert [row["role"] for row in load_messages(db_path=path)] == ["user", "assistant"]


@pytest.mark.parametrize("failure", ["newer_owner", "provider_error"])
def test_feedback_bridge_reports_failure_without_claiming_completion(store, tmp_path, failure):
    """Structured graph context cannot report an uncommitted model decision."""
    import json
    from memory.conversation_history import append_message
    from services.routine_completion_helper import DatedRoutineSelection
    from services.routine_feedback_turn import PersistedRoutineFeedbackHandler

    path = str(tmp_path / "conversation.db")
    saved = append_message(role="user", content="done", channel="matrix", db_path=path)
    def select(*args, **kwargs):
        if failure == "provider_error":
            raise OSError("provider unavailable")
        append_message(role="user", content="actually not done", channel="web", db_path=path)
        return DatedRoutineSelection("complete", 11, stamp(7).date())
    handler = PersistedRoutineFeedbackHandler(store=store, selector=select,
        clock=lambda: stamp(7), channel="matrix", conversation_db_path=path, trusted_owner=True)
    outcome = json.loads(handler("done", saved).content.split("\n", 1)[0])
    assert outcome == {"status": "error" if failure == "provider_error" else "stale",
                       "action": "none", "routine_id": None, "occurrence_date": None}
    assert store.occurrences(11) == []


def test_web_dated_feedback_real_history_and_ledger_preserve_today(store, tmp_path, monkeypatch):
    """Actual authenticated /chat uses the shared bridge, not legacy 'today'."""
    import json
    from unittest.mock import patch
    from fastapi.testclient import TestClient
    from langchain_core.messages import SystemMessage
    from api.server import server
    from tests.test_routine_completion_web import _post_chat
    from memory.conversation_history import append_message, load_messages
    from services.routine_completion_helper import DatedRoutineSelection
    from services.routine_feedback_turn import PersistedRoutineFeedbackHandler
    from services import routine_context_clarification as clarification

    monkeypatch.setattr(clarification, "try_context_question_reply", lambda *a, **kw: clarification.QuestionAnswer())
    path = str(tmp_path / "conversation.db")
    now = stamp(7)
    store.record_delivery(11, stamp(6).date(), at=stamp(6), receipt_id="yesterday")
    store.record_delivery(11, now.date(), at=now, receipt_id="today")
    def save(role, content, agent=None, **kwargs):
        saved = append_message(role=role, content=content, agent=agent, channel="web", db_path=path)
        return saved if kwargs.get("return_saved") else saved["id"]
    handler = PersistedRoutineFeedbackHandler(store=store,
        selector=lambda *a, **kw: DatedRoutineSelection("complete", 11, stamp(6).date()),
        clock=lambda: now, channel="web", conversation_db_path=path, trusted_owner=True)
    with patch.object(server.state, "persisted_routine_feedback_handler", handler, create=True):
        response, mocks = _post_chat(TestClient(server), message="Χθες καθάρισα το κουνέλι", history_writer=save)
    assert response.status_code == 200
    assert [row.feedback for row in store.occurrences(11)] == ["complete", None]
    mocks["triggered"].assert_not_called()
    outcomes = [json.loads(msg.content.split("\n", 1)[0]) for msg in mocks["graph"].call_args.args[0]
                if isinstance(msg, SystemMessage) and msg.content.startswith('{"status"')]
    assert outcomes[0]["occurrence_date"] == "2026-10-06"
    assert [row["role"] for row in load_messages(db_path=path)] == ["user", "assistant"]


def test_debug_snapshot_is_read_only_and_keeps_today_distinct(store):
    """Inspect dated outcomes and derived pressure without reconciliation writes."""
    for day in (3, 4, 5):
        store.record_delivery(11, stamp(day).date(), at=stamp(day), receipt_id=f"event-{day}")
    original = store.revision(11)
    fields = store.debug_snapshot([11], now=stamp(7))[11]
    assert fields["status"] == "recorded"
    assert fields["derived_cooldown_hours"] == 20
    assert fields["backoff_remaining_h"] == 0
    assert fields["today"] is None
    assert fields["latest_occurrence"]["date"] == "2026-10-05"
    assert store.revision(11) == original


def test_debug_snapshot_does_not_initialize_missing_ledger(tmp_path):
    """Observability never activates a schema or claims absent data means zero."""
    path = tmp_path / "legacy.db"
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE routines (id INTEGER PRIMARY KEY)")
        connection.execute("INSERT INTO routines VALUES (11)")
    ledger = RoutineFeedbackStore(lambda: sqlite3.connect(path))
    assert ledger.debug_snapshot([11], now=stamp(7))[11] == {"status": "uninitialized"}
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT name FROM sqlite_master WHERE name='routine_occurrences'").fetchone() is None


def test_debug_reader_never_creates_a_missing_database(tmp_path):
    """The API-facing reader opens only existing storage in read-only mode."""
    from memory.routine_feedback import read_feedback_debug_snapshot

    missing = tmp_path / "missing.db"
    with pytest.raises(sqlite3.OperationalError):
        read_feedback_debug_snapshot(str(missing), [11], now=stamp(7))
    assert not missing.exists()


def test_catalog_feedback_uses_recorded_yesterday_without_completing_today(store, tmp_path):
    """Shared composition retains actual historical occurrences and their dates."""
    from memory.conversation_history import append_message
    from services.routine_completion_helper import DatedRoutineSelection
    from services.routine_feedback_turn import process_catalog_feedback_turn

    now = stamp(7)
    store.record_delivery(11, stamp(6).date(), at=stamp(6), receipt_id="yesterday")
    path = str(tmp_path / "conversation.db")
    row = append_message(role="user", content="Χθες καθάρισα το κουνέλι", channel="web", db_path=path)

    def selector(text, candidates, dates, **kwargs):
        assert candidates == {11: "Καθάρισμα κουνελιού"}
        assert dates[11] == frozenset({stamp(6).date(), now.date()})
        return DatedRoutineSelection("complete", 11, stamp(6).date())

    result = process_catalog_feedback_turn("Χθες καθάρισα το κουνέλι", store=store,
        selector=selector, now=now, clock=lambda: now, trusted=True,
        user_rowid=row["rowid"], conversation_db_path=path)
    assert result.status == "applied"
    assert [(item.occurrence_date, item.feedback) for item in store.occurrences(11)] == [(stamp(6).date(), "complete")]


def test_catalog_snapshot_rename_before_classification_is_rejected(store):
    """An old candidate name cannot acquire a new revision after it was loaded."""
    from services.routine_feedback_turn import process_feedback_turn

    now = stamp(7)
    snapshot = store.feedback_candidates(now=now)
    with store.connection_factory() as connection:
        connection.execute("UPDATE routines SET event_name='Different routine' WHERE id=11")

    def forbidden(*args, **kwargs):
        pytest.fail("Stale candidate data must not reach inference")

    result = process_feedback_turn("το έκανα", {item.routine_id: item.name for item in snapshot},
        {item.routine_id: item.allowed_dates for item in snapshot}, store=store,
        selector=forbidden, now=now, trusted=True, is_current=lambda: True,
        expected_revisions={item.routine_id: item.revision for item in snapshot})
    assert result.status == "stale"
    assert store.occurrences(11) == []


def test_untrusted_catalog_feedback_does_not_open_storage():
    """External-derived text cannot trigger even catalog or provider access."""
    from services.routine_feedback_turn import process_catalog_feedback_turn

    def forbidden(*args, **kwargs):
        pytest.fail("Untrusted feedback must not access storage or inference")

    result = process_catalog_feedback_turn("do it", store=RoutineFeedbackStore(forbidden),
        selector=forbidden, now=stamp(7), clock=lambda: stamp(7), trusted=False,
        user_rowid=1, conversation_db_path="unused")
    assert result.status == "none"


@pytest.mark.parametrize("newer_channel", ["web", "telegram", "matrix"])
def test_real_shared_history_change_during_inference_prevents_ledger_write(store, tmp_path, newer_channel):
    """A newer owner message invalidates actual persistence, not just selection."""
    from memory.conversation_history import append_message
    from services.routine_completion_helper import DatedRoutineSelection
    from services.routine_feedback_turn import make_feedback_freshness, process_feedback_turn

    path = str(tmp_path / "conversation.db")
    now = stamp(7)
    first = append_message(role="user", content="I completed it", channel="web", db_path=path)
    fresh = make_feedback_freshness(user_rowid=first["rowid"], db_path=path,
        now=now, clock=lambda: now, correlation_is_current=lambda: True)
    original = store.revision(11)

    def selector(*args, **kwargs):
        append_message(role="user", content="Correction, not yet", channel=newer_channel, db_path=path)
        return DatedRoutineSelection("complete", 11, now.date())

    result = process_feedback_turn("I completed it", {11: "routine"},
        {11: frozenset({now.date()})}, store=store, selector=selector,
        now=now, trusted=True, is_current=fresh)
    assert result.status == "stale"
    assert store.occurrences(11) == []
    assert store.revision(11) == original


def test_real_shared_history_guard_allows_current_owner_feedback(store, tmp_path):
    """Positive control persists engagement with real conversation/ledger storage."""
    from memory.conversation_history import append_message
    from services.routine_completion_helper import DatedRoutineSelection
    from services.routine_feedback_turn import make_feedback_freshness, process_feedback_turn

    path = str(tmp_path / "conversation.db")
    now = stamp(7)
    first = append_message(role="user", content="thanks for reminding me", channel="matrix", db_path=path)
    fresh = make_feedback_freshness(user_rowid=first["rowid"], db_path=path,
        now=now, clock=lambda: now, correlation_is_current=lambda: True)
    result = process_feedback_turn("thanks for reminding me", {11: "routine"},
        {11: frozenset({now.date()})}, store=store,
        selector=lambda *args, **kwargs: DatedRoutineSelection("acknowledge", 11, now.date()),
        now=now, trusted=True, is_current=fresh)
    assert result.status == "applied"
    assert store.occurrences(11)[0].feedback == "acknowledge"


def test_pending_question_survives_reopen_and_matches_exact_channel_receipt(store):
    from services.routine_completion_helper import RoutineFeedbackQuestion
    day = date(2026, 10, 7)
    store.record_delivery(11, day, at=stamp(7), receipt_id="event-11",
                          question="Did you clean the rabbit?", channel="matrix")
    reopened = RoutineFeedbackStore(store.connection_factory)
    assert reopened.pending_question(now=stamp(7), reply_channel="matrix", reply_event_id="event-11") == (
        RoutineFeedbackQuestion(11, day, "event-11", "Did you clean the rabbit?"))
    assert reopened.pending_question(now=stamp(7), reply_channel="telegram", reply_event_id="event-11") is None
    assert reopened.pending_question(now=stamp(7), reply_channel="matrix", reply_event_id="other") is None


def test_stored_turn_reloads_question_after_inference(store, tmp_path):
    from memory.conversation_history import append_message
    from services.routine_completion_helper import DatedRoutineSelection
    from services.routine_feedback_turn import process_stored_feedback_turn
    now = stamp(7, 10)
    day = now.date()
    store.record_delivery(11, day, at=stamp(7), receipt_id="event", question="Cleaned it?", channel="matrix")
    path = str(tmp_path / "history.db")
    user = append_message(role="user", content="yes", channel="matrix", db_path=path)

    def selector(*args, **kwargs):
        assert kwargs["pending_question"].event_id == "event"
        store.record_feedback(11, day, "skip_today", at=now)
        return DatedRoutineSelection("complete", 11, day)

    result = process_stored_feedback_turn("yes", {11: "routine"}, {11: frozenset({day})},
        store=store, selector=selector, now=now, clock=lambda: now, trusted=True,
        user_rowid=user["rowid"], conversation_db_path=path,
        reply_channel="matrix", reply_event_id="event")
    assert result.status == "stale"
    assert store.occurrences(11)[0].feedback == "skip_today"


def test_stored_turn_can_complete_exact_yesterday_reply_without_completing_today(store, tmp_path):
    from memory.conversation_history import append_message
    from services.routine_completion_helper import DatedRoutineSelection
    from services.routine_feedback_turn import process_stored_feedback_turn
    now = stamp(7)
    yesterday = date(2026, 10, 6)
    store.record_delivery(11, yesterday, at=stamp(6), receipt_id="yesterday", question="Cleaned it?", channel="matrix")
    store.record_delivery(11, now.date(), at=now, receipt_id="today", question="Cleaned it?", channel="matrix")
    path = str(tmp_path / "history.db")
    user = append_message(role="user", content="did it yesterday", channel="matrix", db_path=path)

    def selector(*args, **kwargs):
        assert kwargs["pending_question"].occurrence_date == yesterday
        return DatedRoutineSelection("complete", 11, yesterday)

    result = process_stored_feedback_turn("did it yesterday", {11: "routine"},
        {11: frozenset({yesterday, now.date()})}, store=store, selector=selector,
        now=now, clock=lambda: now, trusted=True, user_rowid=user["rowid"],
        conversation_db_path=path, reply_channel="matrix", reply_event_id="yesterday")
    assert result.status == "applied"
    assert [row.feedback for row in store.occurrences(11)] == ["complete", None]


def test_explicit_reply_cannot_apply_feedback_to_another_routine(store, tmp_path):
    from memory.conversation_history import append_message
    from services.routine_completion_helper import DatedRoutineSelection
    from services.routine_feedback_turn import process_stored_feedback_turn
    with store.connection_factory() as connection:
        connection.execute("INSERT INTO routines (id) VALUES (12)")
    now = stamp(7)
    store.record_delivery(11, now.date(), at=now, receipt_id="event", question="question", channel="matrix")
    path = str(tmp_path / "history.db")
    user = append_message(role="user", content="yes", channel="matrix", db_path=path)
    result = process_stored_feedback_turn("yes", {11: "first", 12: "second"},
        {rid: frozenset({now.date()}) for rid in (11, 12)}, store=store,
        selector=lambda *args, **kwargs: DatedRoutineSelection("complete", 12, now.date()),
        now=now, clock=lambda: now, trusted=True, user_rowid=user["rowid"],
        conversation_db_path=path, reply_channel="matrix", reply_event_id="event")
    assert result.status == "none"
    assert store.occurrences(12) == []
    assert store.occurrences(11)[0].feedback is None


def test_unknown_reply_never_falls_back_to_another_pending_question(store, tmp_path):
    from memory.conversation_history import append_message
    from services.routine_feedback_turn import process_stored_feedback_turn
    now = stamp(7)
    store.record_delivery(11, now.date(), at=now, receipt_id="event", question="question", channel="matrix")
    path = str(tmp_path / "history.db")
    user = append_message(role="user", content="yes", channel="matrix", db_path=path)
    def forbidden(*args, **kwargs):
        pytest.fail("unknown reply must not reach classifier")
    result = process_stored_feedback_turn("yes", {11: "routine"}, {11: frozenset({now.date()})},
        store=store, selector=forbidden, now=now, clock=lambda: now, trusted=True,
        user_rowid=user["rowid"], conversation_db_path=path,
        reply_channel="matrix", reply_event_id="tool-approval-not-a-routine")
    assert result.status == "none"
    assert store.occurrences(11)[0].feedback is None


def test_duplicate_delivery_cannot_replace_question_context(store):
    day = date(2026, 10, 7)
    store.record_delivery(11, day, at=stamp(7), receipt_id="first", question="first question", channel="matrix")
    assert not store.record_delivery(11, day, at=stamp(7, 10), receipt_id="second",
                                     question="different question", channel="telegram")
    assert store.pending_question(now=stamp(7)).event_id == "first"
    assert store.pending_question(now=stamp(7)).question == "first question"


def test_resolved_question_is_not_reused_for_short_answer(store):
    day = date(2026, 10, 7)
    store.record_delivery(11, day, at=stamp(7), receipt_id="event", question="question", channel="matrix")
    store.record_feedback(11, day, "acknowledge", at=stamp(7, 10))
    assert store.pending_question(now=stamp(7, 11), reply_channel="matrix", reply_event_id="event") is None


def test_expired_window_removes_implicit_context_not_explicit_reply(store):
    day = date(2026, 10, 7)
    store.record_delivery(11, day, at=stamp(7), receipt_id="event", question="question", channel="matrix")
    assert store.pending_question(now=stamp(7, 10)) is None
    assert store.pending_question(now=stamp(8)) is None
    assert store.pending_question(now=stamp(8), reply_channel="matrix", reply_event_id="event").occurrence_date == day
    assert store.occurrences(11)[0].feedback is None


def test_two_pending_questions_require_explicit_correlation(store):
    with store.connection_factory() as connection:
        connection.execute("INSERT INTO routines (id) VALUES (12)")
    day = date(2026, 10, 7)
    for rid in (11, 12):
        store.record_delivery(rid, day, at=stamp(7), receipt_id=f"event-{rid}",
                              question=f"question {rid}", channel="matrix")
    assert store.pending_question(now=stamp(7)) is None
    assert store.pending_question(now=stamp(7), reply_channel="matrix", reply_event_id="event-12").routine_id == 12


def test_receipt_without_actual_question_does_not_fabricate_context(store):
    store.record_delivery(11, date(2026, 10, 7), at=stamp(7), receipt_id="legacy")
    assert store.pending_question(now=stamp(7)) is None


@pytest.mark.parametrize("question,channel", [("", "matrix"), ("x" * 2001, "matrix"),
    ("question", "unknown"), ("question", None), (None, "matrix")])
def test_invalid_question_metadata_rolls_back_delivery(store, question, channel):
    original = store.revision(11)
    with pytest.raises(ValueError):
        store.record_delivery(11, date(2026, 10, 7), at=stamp(7), receipt_id="event",
                              question=question, channel=channel)
    assert store.revision(11) == original


@pytest.mark.asyncio
@pytest.mark.parametrize("newer_message", [False, True])
async def test_matrix_adapter_with_real_dated_feedback_preserves_yesterday_and_freshness(
    store, tmp_path, monkeypatch, newer_message,
):
    """The real Matrix handler passes its saved row into the real feedback commit."""
    import json
    from langchain_core.messages import AIMessage, SystemMessage
    from memory.conversation_history import append_message, load_messages
    from services.matrix_turn import MatrixTurnService
    from services.routine_completion_helper import DatedRoutineSelection
    from services.routine_feedback_turn import process_stored_feedback_turn
    from services import routine_context_clarification as clarification

    monkeypatch.setattr(clarification, "try_context_question_reply",
                        lambda *args, **kwargs: clarification.QuestionAnswer())
    path = str(tmp_path / "conversation.db")
    now = stamp(7)
    yesterday = date(2026, 10, 6)
    store.record_delivery(11, yesterday, at=stamp(6), receipt_id="yesterday",
                          question="Cleaned it?", channel="matrix")
    store.record_delivery(11, now.date(), at=now, receipt_id="today",
                          question="Cleaned it?", channel="matrix")
    results = []

    def selector(*args, **kwargs):
        if newer_message:
            append_message(role="user", content="not completed yet", channel="web", db_path=path)
        return DatedRoutineSelection("complete", 11, yesterday)

    def handler(text, saved_user):
        result = process_stored_feedback_turn(text, {11: "rabbit care"},
            {11: frozenset({yesterday, now.date()})}, store=store, selector=selector,
            now=now, clock=lambda: now, trusted=True, user_rowid=saved_user["rowid"],
            conversation_db_path=path, reply_channel="matrix", reply_event_id="yesterday")
        results.append(result)
        return SystemMessage(content=json.dumps({"feedback_status": result.status}))

    class OfflineGraph:
        """No model or outbound transport: only observe the trusted result context."""
        def stream(self, state, config):
            assert any(isinstance(msg, SystemMessage) and "feedback_status" in msg.content
                       for msg in state["messages"])
            yield {"Chat_Agent": {"messages": [AIMessage(content="offline reply")]}}

    service = MatrixTurnService(graph=OfflineGraph(), conversation_db_path=path,
        select_tool_channel=lambda channel: None, persisted_routine_confirmation_handler=handler)
    assert await service("I did it yesterday", "$dated-owner") == "offline reply"
    assert results[0].status == ("stale" if newer_message else "applied")
    assert [row.feedback for row in store.occurrences(11)] == (
        [None, None] if newer_message else ["complete", None])
    matrix_users = [row for row in load_messages(db_path=path)
                    if row["role"] == "user" and row["channel"] == "matrix"]
    assert len(matrix_users) == 1


def test_delivery_is_unique_per_day_and_survives_store_recreation(store):
    assert store.record_delivery(11, date(2026, 10, 5), at=stamp(5), receipt_id="event-1")
    assert not store.record_delivery(11, date(2026, 10, 5), at=stamp(5, 10), receipt_id="event-2")
    reopened = RoutineFeedbackStore(store.connection_factory)
    assert reopened.occurrences(11)[0].delivered_at == stamp(5)


def test_historical_complete_preserves_receipt_and_recomputes_pressure(store):
    for day in (1, 2, 3):
        store.record_delivery(11, date(2026, 10, day), at=stamp(day), receipt_id=f"event-{day}")
    assert evaluate_feedback(store.occurrences(11), now=stamp(4)).cooldown_hours == 20
    assert store.record_feedback(11, date(2026, 10, 2), "complete", at=stamp(4))
    rows = store.occurrences(11)
    assert rows[1].delivered_at == stamp(2)
    assert evaluate_feedback(rows, now=stamp(4)).cooldown_hours == 0
    assert len(rows) == 3


def test_stale_feedback_cannot_overwrite_newer_completion(store):
    day = date(2026, 10, 5)
    store.record_feedback(11, day, "complete", at=stamp(5, 12))
    assert not store.record_feedback(11, day, "skip_today", at=stamp(5, 11))
    assert not store.record_feedback(11, day, "acknowledge", at=stamp(5, 13))
    assert store.occurrences(11)[0].feedback == "complete"


def test_preemptive_feedback_creates_no_fabricated_delivery(store):
    store.record_feedback(11, date(2026, 10, 5), "complete", at=stamp(5))
    assert store.occurrences(11)[0].delivered_at is None


def test_concurrent_delivery_has_exactly_one_winner(store):
    def send(index):
        return store.record_delivery(11, date(2026, 10, 5), at=stamp(5), receipt_id=f"event-{index}")
    with ThreadPoolExecutor(max_workers=4) as executor:
        outcomes = list(executor.map(send, range(8)))
    assert sum(outcomes) == 1
    assert len(store.occurrences(11)) == 1


@pytest.mark.parametrize("routine_id,receipt", [(99, "event"), (True, "event"), (11, "")])
def test_invalid_evidence_never_leaves_a_row(store, routine_id, receipt):
    with pytest.raises((ValueError, sqlite3.IntegrityError)):
        store.record_delivery(routine_id, date(2026, 10, 5), at=stamp(5), receipt_id=receipt)
    assert store.occurrences(11) == []


def write_process_receipt(path, index):
    """Use a fresh process/SQLite connection, never production application imports."""
    ledger = RoutineFeedbackStore(lambda: sqlite3.connect(path, timeout=5))
    return ledger.record_delivery(11, date(2026, 10, 5), at=stamp(5), receipt_id=str(index))


def test_independent_processes_preserve_one_receipt_and_atomic_pressure(store):
    connection = store.connection_factory()
    try:
        path = connection.execute("PRAGMA database_list").fetchone()[2]
    finally:
        connection.close()
    with get_context("spawn").Pool(2) as pool:
        outcomes = pool.starmap(write_process_receipt, [(path, index) for index in range(4)])
    assert sum(outcomes) == 1
    assert len(store.occurrences(11)) == 1
    assert routine_fields(store)[1:4] == (0, 0, 0)


def test_initialize_upgrades_inactive_ledger_without_erasing_evidence(store):
    connection = store.connection_factory()
    connection.execute("ALTER TABLE routine_occurrences DROP COLUMN baseline_at")
    connection.commit()
    connection.close()
    store.initialize()
    store.record_feedback(11, date(2026, 10, 5), "complete", at=stamp(5))
    store.record_baseline(11, at=stamp(5, 12))
    assert store.occurrences(11)[0].feedback == "complete"


def test_future_occurrence_feedback_is_rejected(store):
    with pytest.raises(ValueError):
        store.record_feedback(11, date(2026, 10, 6), "complete", at=stamp(5))
    assert store.occurrences(11) == []


def test_failed_write_rolls_back_placeholder_occurrence(store):
    connection = store.connection_factory()
    connection.execute("""CREATE TRIGGER fail_receipt BEFORE UPDATE OF delivered_at
        ON routine_occurrences BEGIN SELECT RAISE(ABORT, 'simulated failure'); END""")
    connection.commit()
    connection.close()
    with pytest.raises(sqlite3.IntegrityError, match="simulated failure"):
        store.record_delivery(11, date(2026, 10, 5), at=stamp(5), receipt_id="event")
    assert store.occurrences(11) == []


def test_additive_initialization_does_not_rewrite_existing_routines(store):
    store.initialize()
    connection = store.connection_factory()
    try:
        assert connection.execute("""SELECT id, notify_cooldown_hours, explicit_skip_streak,
            unanswered_reminder_streak, confidence, last_triggered, last_notified_ts,
            state FROM routines""").fetchall() == [
            (11, 72, 0, 0, 0.6, '2026-09-30', 123, 'paused')]
    finally:
        connection.close()


def test_same_timestamp_conflicting_feedback_is_not_applied_twice(store):
    day = date(2026, 10, 5)
    assert store.record_feedback(11, day, "skip_today", at=stamp(5))
    assert not store.record_feedback(11, day, "acknowledge", at=stamp(5))
    assert store.occurrences(11)[0].feedback == "skip_today"


def test_guard_rejects_result_after_another_channel_updates_the_occurrence(store):
    day = date(2026, 10, 5)
    revision = store.revision(11)
    store.record_feedback(11, day, "skip_today", at=stamp(5, 10))
    assert not store.record_feedback(11, day, "complete", at=stamp(5, 11),
                                     expected_revision=revision, is_current=lambda: True)
    assert store.occurrences(11)[0].feedback == "skip_today"


def test_guard_rejects_result_after_routine_configuration_changes(store):
    revision = store.revision(11)
    connection = store.connection_factory()
    connection.execute("UPDATE routines SET state='active' WHERE id=11")
    connection.commit()
    connection.close()
    assert not store.record_feedback(11, date(2026, 10, 5), "complete", at=stamp(5),
                                     expected_revision=revision, is_current=lambda: True)
    assert store.occurrences(11) == []


def test_history_freshness_is_checked_inside_transaction_before_any_mutation(store):
    revision = store.revision(11)
    checked = []

    def no_longer_current():
        """Represent a newer trusted owner turn arriving during model inference."""
        checked.append(True)
        return False

    assert not store.record_feedback(11, date(2026, 10, 5), "complete", at=stamp(5),
                                     expected_revision=revision, is_current=no_longer_current)
    assert checked == [True]
    assert store.occurrences(11) == []
    assert routine_fields(store)[1] == 72


def test_matching_guard_applies_feedback_and_pressure_together(store):
    revision = store.revision(11)
    assert store.record_feedback(11, date(2026, 10, 5), "acknowledge", at=stamp(5),
                                 expected_revision=revision, is_current=lambda: True)
    assert store.occurrences(11)[0].feedback == "acknowledge"
    assert routine_fields(store)[1] == 0


def test_turn_rejects_state_changed_while_classifier_is_running(store):
    from services.routine_feedback_turn import process_feedback_turn
    from services.routine_completion_helper import DatedRoutineSelection
    day = date(2026, 10, 5)

    def classifier(*args, **kwargs):
        """Simulate another channel's answer arriving during model inference."""
        store.record_feedback(11, day, "skip_today", at=stamp(5, 10))
        return DatedRoutineSelection("complete", 11, day)

    result = process_feedback_turn("Το έκανα", {11: "routine"}, {11: frozenset((day,))},
        store=store, selector=classifier, now=stamp(5, 11), trusted=True, is_current=lambda: True)
    assert result.status == "stale"
    assert store.occurrences(11)[0].feedback == "skip_today"


def test_turn_rechecks_new_user_message_after_classification(store):
    from services.routine_feedback_turn import process_feedback_turn
    from services.routine_completion_helper import DatedRoutineSelection
    current = [True]
    day = date(2026, 10, 5)

    def classifier(*args, **kwargs):
        """Change the shared history version while returning a valid selection."""
        current[0] = False
        return DatedRoutineSelection("complete", 11, day)

    result = process_feedback_turn("Το έκανα", {11: "routine"}, {11: frozenset((day,))},
        store=store, selector=classifier, now=stamp(5), trusted=True, is_current=lambda: current[0])
    assert result.status == "stale"
    assert store.occurrences(11) == []


def test_turn_applies_dated_acknowledgement_without_inventing_completion(store):
    from services.routine_feedback_turn import process_feedback_turn
    from services.routine_completion_helper import DatedRoutineSelection
    day = date(2026, 10, 5)
    result = process_feedback_turn("Σε λίγο φίλε", {11: "routine"}, {11: frozenset((day,))},
        store=store, selector=lambda *args, **kwargs: DatedRoutineSelection("acknowledge", 11, day),
        now=stamp(5), trusted=True, is_current=lambda: True)
    assert result.status == "applied"
    assert store.occurrences(11)[0].feedback == "acknowledge"
    assert routine_fields(store)[4] == 0.6


@pytest.mark.parametrize("action,status,persisted", [
    ("clarify", "clarify", False), ("pause", "applied", True),
    ("defer", "clarify", True),
])
def test_turn_distinguishes_clarification_pause_and_deferral(store, action, status, persisted):
    from services.routine_feedback_turn import process_feedback_turn
    from services.routine_completion_helper import DatedRoutineSelection
    day = date(2026, 10, 5)
    selected = DatedRoutineSelection(action, 11, None if action == "clarify" else day)
    result = process_feedback_turn("natural reply", {11: "routine"}, {11: frozenset((day,))},
        store=store, selector=lambda *args, **kwargs: selected,
        now=stamp(5), trusted=True, is_current=lambda: True)
    assert result.status == status
    rows = store.occurrences(11)
    assert bool(rows) == persisted
    if persisted:
        assert rows[0].feedback == action
        assert rows[0].delivered_at is None


def test_untrusted_turn_cannot_call_selector_or_write_feedback(store):
    from services.routine_feedback_turn import process_feedback_turn
    day = date(2026, 10, 5)

    def forbidden(*args, **kwargs):
        """Make accidental provider-boundary access fail loudly."""
        raise AssertionError("untrusted input reached classification")

    result = process_feedback_turn("external content", {11: "routine"}, {11: frozenset((day,))},
        store=store, selector=forbidden, now=stamp(5), trusted=False, is_current=lambda: True)
    assert result.status == "none"
    assert store.occurrences(11) == []


def routine_fields(store):
    """Read the persisted temporary routine projection, including protected state."""
    connection = store.connection_factory()
    try:
        return connection.execute("""SELECT id, notify_cooldown_hours, explicit_skip_streak,
            unanswered_reminder_streak, confidence, last_triggered, last_notified_ts,
            state FROM routines WHERE id=11""").fetchone()
    finally:
        connection.close()


def test_day_close_projection_is_idempotent_and_preserves_confidence(store):
    for day in (1, 2, 3):
        store.record_delivery(11, date(2026, 10, day), at=stamp(day), receipt_id=str(day))
    assert store.reconcile(11, now=stamp(3, 23)).cooldown_hours == 0
    assert store.reconcile(11, now=stamp(4)).cooldown_hours == 20
    assert store.reconcile(11, now=stamp(4)).cooldown_hours == 20
    assert routine_fields(store)[1:] == (20, 0, 0, 0.6, '2026-09-30', 123, 'paused')
    store.record_feedback(11, date(2026, 10, 2), "complete", at=stamp(4, 10))
    assert routine_fields(store)[1:4] == (0, 0, 1)


def test_projection_failure_rolls_back_feedback_together_with_counters(store):
    connection = store.connection_factory()
    connection.execute("""CREATE TRIGGER fail_pressure BEFORE UPDATE OF notify_cooldown_hours
        ON routines BEGIN SELECT RAISE(ABORT, 'projection failed'); END""")
    connection.commit()
    connection.close()
    with pytest.raises(sqlite3.IntegrityError, match="projection failed"):
        store.record_feedback(11, date(2026, 10, 5), "complete", at=stamp(5))
    assert store.occurrences(11) == []
    assert routine_fields(store)[1] == 72


def test_durable_baseline_discards_old_pressure_without_deleting_receipts(store):
    for day in (1, 2, 3):
        store.record_delivery(11, date(2026, 10, day), at=stamp(day), receipt_id=str(day))
    store.record_baseline(11, at=stamp(3, 12))
    reopened = RoutineFeedbackStore(store.connection_factory)
    assert reopened.reconcile(11, now=stamp(4)).cooldown_hours == 0
    assert not reopened.record_delivery(11, date(2026, 10, 3), at=stamp(4), receipt_id="again")
    assert reopened.occurrences(11)[2].delivered_at == stamp(3)
    assert routine_fields(store)[4:] == (0.6, '2026-09-30', 123, 'paused')
    for day in (4, 5, 6):
        reopened.record_delivery(11, date(2026, 10, day), at=stamp(day), receipt_id=str(day))
    assert reopened.reconcile(11, now=stamp(7)).cooldown_hours == 20


def test_baseline_cannot_move_backwards(store):
    store.record_baseline(11, at=stamp(5))
    with pytest.raises(ValueError, match="backwards"):
        store.record_baseline(11, at=stamp(4))
    assert [row.occurrence_date for row in store.occurrences(11)] == [date(2026, 10, 5)]


def test_baseline_and_projection_rollback_together(store):
    connection = store.connection_factory()
    connection.execute("""CREATE TRIGGER fail_reset BEFORE UPDATE OF notify_cooldown_hours
        ON routines BEGIN SELECT RAISE(ABORT, 'reset failed'); END""")
    connection.commit()
    connection.close()
    with pytest.raises(sqlite3.IntegrityError, match="reset failed"):
        store.record_baseline(11, at=stamp(5))
    assert store.occurrences(11) == []


def pause_fields(store):
    """Inspect canonical pause metadata in this test's private database."""
    connection = store.connection_factory()
    try:
        return connection.execute("""SELECT paused_indefinitely, paused_until, pause_reason,
            state, is_active, confidence, last_triggered, last_notified_ts FROM routines WHERE id=11""").fetchone()
    finally:
        connection.close()


def test_permanent_pause_is_atomic_and_preserves_completed_occurrence(store):
    day = date(2026, 10, 5)
    store.record_feedback(11, day, "complete", at=stamp(5, 10))
    revision = store.revision(11)
    assert store.record_feedback(11, day, "pause", at=stamp(5, 11),
                                 expected_revision=revision, is_current=lambda: True)
    assert store.occurrences(11)[0].feedback == "complete"
    assert pause_fields(store) == (1, None, 'user_requested', 'active', 1, 0.6, '2026-09-30', 123)


def test_pause_failure_rolls_back_feedback_and_pressure(store):
    revision = store.revision(11)
    connection = store.connection_factory()
    connection.execute("""CREATE TRIGGER fail_pause BEFORE UPDATE OF paused_indefinitely
        ON routines BEGIN SELECT RAISE(ABORT, 'pause failed'); END""")
    connection.commit()
    connection.close()
    with pytest.raises(sqlite3.IntegrityError, match="pause failed"):
        store.record_feedback(11, date(2026, 10, 5), "pause", at=stamp(5),
                              expected_revision=revision, is_current=lambda: True)
    assert store.occurrences(11) == []
    assert routine_fields(store)[1] == 72
    assert pause_fields(store)[0] == 0


def test_stale_pause_does_not_disable_newer_routine_state(store):
    revision = store.revision(11)
    store.record_feedback(11, date(2026, 10, 5), "acknowledge", at=stamp(5, 10))
    assert not store.record_feedback(11, date(2026, 10, 5), "pause", at=stamp(5, 11),
                                     expected_revision=revision, is_current=lambda: True)
    assert pause_fields(store)[0] == 0
    assert store.occurrences(11)[0].feedback == "acknowledge"
