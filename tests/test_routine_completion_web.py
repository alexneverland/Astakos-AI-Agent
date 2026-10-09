"""Web integration coverage for natural routine completion and graph continuity."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Callable, Iterator
from unittest.mock import ANY, MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import HumanMessage, SystemMessage

from api.server import LOCAL_TOKEN, server
from services.routine_completion_helper import RoutineSelection


def test_telegram_history_notification_preserves_provider_identity(tmp_path, monkeypatch):
    """Actual Web bridge stores equal Telegram messages with distinct event IDs."""
    import api.server as api
    from memory import conversation_history as history
    path = str(tmp_path / "telegram-history.db")
    append = history.append_message
    maximum = history.get_max_rowid
    monkeypatch.setattr(history, "append_message", lambda **kwargs: append(db_path=path, **kwargs))
    monkeypatch.setattr(history, "get_max_rowid", lambda: maximum(db_path=path))
    monkeypatch.setattr(api, "_broadcast_ws", lambda event: None)
    results = [api.notify_telegram_message("user", "ναι", return_saved=True,
        message_id=f"telegram-user-123456-{event_id}") for event_id in (81, 82, 81)]
    assert results[0]["rowid"] != results[1]["rowid"]
    assert results[2]["rowid"] is None  # Replay cannot authorize a second turn.
    assert len(history.load_messages(db_path=path)) == 2


@pytest.fixture(autouse=True)
def isolated_context_question_boundary() -> Iterator[None]:
    """Do not consult the owner's pending context-question file in API tests."""
    from services.routine_context_clarification import QuestionAnswer

    with patch("services.routine_context_clarification.try_context_question_reply", return_value=QuestionAnswer()):
        yield


@pytest.fixture
def client() -> TestClient:
    """Provide the actual Web API app with its normal authentication token."""
    return TestClient(server)


def test_web_consumed_context_answer_never_reaches_routine_or_graph(client, tmp_path):
    """One context-owned turn records once and cannot mutate another routine."""
    from memory.conversation_history import append_message, load_messages
    from services.routine_context_clarification import QuestionAnswer
    path = str(tmp_path / "context-history.db")
    answer = QuestionAnswer(True, "resolved")
    handler = MagicMock()
    def save(role, content, **kwargs):
        return append_message(role=role, content=content, channel="web", db_path=path)
    with (
        patch("services.routine_context_clarification.try_context_question_reply", return_value=answer),
        patch.object(server.state, "persisted_routine_feedback_handler", handler, create=True),
    ):
        response, mocks = _post_chat(client, message="Ναι είμαστε σπίτι", history_writer=save)
    assert response.status_code == 200
    assert response.json()["agent"] == "Routine_Context"
    assert response.json()["response"] == answer.reply
    handler.assert_not_called()
    mocks["load_pending"].assert_not_called()
    mocks["graph"].assert_not_called()
    assert [row["role"] for row in load_messages(db_path=path)] == ["user", "assistant"]


@pytest.mark.parametrize("outcome", [None, SystemMessage(content="dated feedback applied for yesterday")])
def test_web_persisted_feedback_hook_replaces_legacy_mutation(client, outcome):
    """An opt-in callback receives the actual saved row and never falls through."""
    handler = MagicMock(return_value=outcome)
    with patch.object(server.state, "persisted_routine_feedback_handler", handler, create=True):
        response, mocks = _post_chat(client, message="Χθες το πρωί καθάρισα το κουνέλι")
    assert response.status_code == 200
    handler.assert_called_once_with("Χθες το πρωί καθάρισα το κουνέλι", {"id": "test-message", "rowid": 1})
    mocks["load_pending"].assert_not_called()
    mocks["selector"].assert_not_called()
    mocks["triggered"].assert_not_called()
    mocks["confirmed"].assert_not_called()
    if outcome is not None:
        assert outcome in mocks["graph"].call_args.args[0]


def test_web_feedback_hook_failure_does_not_use_legacy_completion(client):
    """No stale fallback mutation or false completion claim after an error."""
    handler = MagicMock(side_effect=OSError("isolated storage failure"))
    with patch.object(server.state, "persisted_routine_feedback_handler", handler, create=True):
        response, mocks = _post_chat(client, message="Το έκανα χθες")
    assert response.status_code == 200
    mocks["load_pending"].assert_not_called()
    mocks["triggered"].assert_not_called()
    contexts = [msg for msg in mocks["graph"].call_args.args[0] if isinstance(msg, SystemMessage)]
    assert any('"status": "error"' in str(msg.content) for msg in contexts)


@pytest.mark.parametrize("broadcast_failure", [False, True])
def test_real_web_history_writer_supplies_saved_identity_to_dated_handler(client, tmp_path, broadcast_failure):
    """An ID-only writer result silently disables actual dated feedback."""
    import sqlite3
    from zoneinfo import ZoneInfo
    from api.server import append_to_chat_history
    from memory.conversation_history import append_message, load_messages
    from memory.routine_feedback import RoutineFeedbackStore
    from services.routine_completion_helper import DatedRoutineSelection
    from services.routine_feedback_turn import PersistedRoutineFeedbackHandler

    db = tmp_path / "routines.db"
    def connect():
        return sqlite3.connect(db)
    with connect() as connection:
        connection.execute("""CREATE TABLE routines (id INTEGER PRIMARY KEY,
            event_name TEXT, notify_cooldown_hours REAL, explicit_skip_streak INTEGER,
            unanswered_reminder_streak INTEGER, confidence REAL)""")
        connection.execute("INSERT INTO routines VALUES (5, 'Καθάρισμα κουνελιού', 0, 0, 0, 1)")
    ledger = RoutineFeedbackStore(connect)
    ledger.initialize()
    now = datetime(2026, 10, 7, 9, tzinfo=ZoneInfo("Europe/Athens"))
    ledger.record_delivery(5, now.date(), at=now, receipt_id="$routine",
        question="Το έκανες;", channel="web")
    history = str(tmp_path / "history.db")
    def persist(**kwargs):
        return append_message(db_path=history, **kwargs)
    handler = PersistedRoutineFeedbackHandler(store=ledger,
        selector=lambda *a, **kw: DatedRoutineSelection("complete", 5, now.date()),
        clock=lambda: now, channel="web", conversation_db_path=history, trusted_owner=True)
    with (
        patch("memory.conversation_history.append_message", side_effect=persist),
        patch("api.server._broadcast_ws", side_effect=OSError("offline display failure") if broadcast_failure else None),
        patch("services.behavioral_event_scheduler.schedule_persisted_user_intake"),
        patch.object(server.state, "persisted_routine_feedback_handler", handler, create=True),
        patch("memory.pending_assets.get_latest_recent_asset", return_value=None),
        patch("memory.pending_assets.get_latest_pending_asset_any", return_value=None),
    ):
        response, mocks = _post_chat(client, message="Ναι το έκανα", history_writer=append_to_chat_history)
    assert response.status_code == 200
    assert ledger.occurrences(5)[0].feedback == "complete"
    rows = load_messages(db_path=history)
    assert [row["role"] for row in rows] == ["user", "assistant"]
    assert response.json()["user_rowid"] == rows[0]["rowid"]
    assert response.json()["assistant_rowid"] == rows[1]["rowid"]
    mocks["load_pending"].assert_not_called()
    mocks["triggered"].assert_not_called()


@pytest.mark.parametrize("saved_local_draft", [False, True])
def test_web_dated_hook_draft_consumed_only_after_local_creation(client, saved_local_draft):
    """Draft metadata stays in the existing success-only consumption path."""
    from services.matrix_routine_completion import MatrixRoutineDraftOffer
    context = SystemMessage(content="trusted local draft offer")
    offered_at = datetime(2026, 10, 7, 9)
    offer = MatrixRoutineDraftOffer(5, offered_at, "Message Sofia", context)
    with patch.object(server.state, "persisted_routine_feedback_handler", lambda *a: offer, create=True):
        response, mocks = _post_chat(client, message="Ετοίμασέ το", saved_local_draft=saved_local_draft)
    assert response.status_code == 200
    assert context in mocks["graph"].call_args.args[0]
    assert mocks["consume_offer"].call_count == int(saved_local_draft)
    if saved_local_draft:
        mocks["consume_offer"].assert_called_once_with(5, offered_at)
    mocks["confirmed"].assert_not_called()
    mocks["triggered"].assert_not_called()


def _saved_message(*_args: object, **kwargs: object) -> object:
    """Return a stable history payload only where the endpoint requests it."""
    return {"id": "test-message", "rowid": 1} if kwargs.get("return_saved") else None


def _graph_result(*_args: object, **_kwargs: object) -> dict[str, object]:
    """Return one normal graph response without invoking external model services."""
    return {
        "final_ai_response": "Natural graph reply.",
        "handling_agent": "Chat_Agent",
        "tool_result_fallbacks": [],
        "external_tool_names": [],
        "graph_elapsed_ms": 1,
        "saved_local_draft": False,
    }


def _post_chat(
    client: TestClient,
    pending: dict[int, dict[str, str]] | None = None,
    selector_returns: list[RoutineSelection] | None = None,
    *,
    message: str = "natural message",
    catalog_routines: list[dict[str, object]] | None = None,
    accepted_draft_offer: object | None = None,
    active_draft_status: tuple[bool, str, dict | None] = (False, "missing", None),
    saved_local_draft: bool = False,
    voice_mode: bool = False,
    photo_path: str = "",
    graph_budget_exhausted: bool = False,
    graph_runner: MagicMock | None = None,
    history_writer: Callable[..., object] | None = None,
    selection_callback: Callable[..., RoutineSelection] | None = None,
) -> tuple[object, dict[str, MagicMock]]:
    """Run one Web message under isolated completion and graph dependencies."""
    graph_runner = graph_runner if graph_runner is not None else MagicMock(side_effect=lambda *args, **kwargs: {
        **_graph_result(*args, **kwargs),
        "saved_local_draft": saved_local_draft,
        "graph_budget_exhausted": graph_budget_exhausted,
    })
    selector = MagicMock(
        side_effect=(selection_callback if selection_callback is not None else
                     selector_returns if selector_returns is not None else
                     [RoutineSelection(action="complete", routine_id=5)])
    )
    with (
        patch("memory.routine_db.get_eligible_preemptive_routines_for_day", return_value=[{"id": 5, "event": "dynamic routine"}]) as eligible,
        patch("memory.routine_db.get_active_routine_catalog", return_value=catalog_routines or []),
        patch("memory.routine_db.mark_routine_triggered_today") as triggered,
        patch("memory.routine_db.confirm_routine") as confirmed,
        patch("memory.routine_db.mark_routine_responded"),
        patch("memory.routine_db.remove_pending_confirmation"),
        patch("memory.routine_db.mark_routine_acknowledged") as acknowledged,
        patch("memory.routine_db.acknowledge_pending_draft_offer", return_value=True) as consume_offer,
        patch("memory.routine_db.record_routine_skip_today", return_value={"skip_streak": 1, "cooldown_applied": False}) as skipped,
        patch("memory.routine_db.pause_routine_indefinitely") as paused,
        patch(
            "memory.routine_db.load_pending_confirmations",
            return_value=pending or {},
        ) as load_pending,
        patch("memory.event_log.log_event") as logged,
        patch("services.routine_completion_selector.select_routine", selector),
        patch(
            "services.routine_completion_context.accept_pending_messenger_draft_offer",
            return_value=accepted_draft_offer,
        ) as accepted_offer,
        patch(
            "services.routine_completion_context.build_routine_completion_context",
            return_value=SystemMessage(content="Routine lifecycle updated."),
        ),
        patch("api.server.append_to_chat_history", side_effect=history_writer or _saved_message),
        patch("api.server._load_shared_context_messages", return_value=[]),
        patch("core.messenger_draft.active_draft_status", return_value=active_draft_status),
        patch("api.server._run_web_graph_stream_sync", graph_runner),
        patch("api.server.enqueue_fast_task"),
        patch("api.server.enqueue_slow_task"),
    ):
        response = client.post(
            "/chat",
            json={"message": message, "voice_mode": voice_mode, "photo_path": photo_path},
            headers={"Authorization": f"Bearer {LOCAL_TOKEN}"},
        )
        return response, {
            "eligible": eligible,
            "triggered": triggered,
            "confirmed": confirmed,
            "acknowledged": acknowledged,
            "consume_offer": consume_offer,
            "skipped": skipped,
            "paused": paused,
            "load_pending": load_pending,
            "logged": logged,
            "selector": selector,
            "accepted_offer": accepted_offer,
            "graph": graph_runner,
        }


def test_web_selector_sees_exact_persisted_user_once(client: TestClient, tmp_path: Path) -> None:
    """Routine inference sees its actual shared-history row without duplicate writes."""
    from memory.conversation_history import append_message, load_messages

    db_path = str(tmp_path / "conversation.db")
    saved_users = []

    def save(role: str, content: str, agent: str | None = None, **kwargs: object) -> object:
        """Use the real conversation abstraction with an isolated database."""
        saved = append_message(role=role, content=content, agent=agent, channel="web", db_path=db_path)
        if role == "user":
            saved_users.append(saved)
        return saved if kwargs.get("return_saved") else saved["id"]

    def select(*args: object, **kwargs: object) -> RoutineSelection:
        """Check the persisted input at the inference boundary."""
        rows = load_messages(db_path=db_path)
        assert len(saved_users) == 1
        assert rows[-1]["rowid"] == saved_users[0]["rowid"]
        assert rows[-1]["content"] == "I completed it today"
        return RoutineSelection(action="complete", routine_id=5)

    response, mocks = _post_chat(client, message="I completed it today", history_writer=save, selection_callback=select)
    assert response.status_code == 200
    mocks["triggered"].assert_called_once_with(5)
    assert len(saved_users) == 1
    assert response.json()["user_rowid"] == saved_users[0]["rowid"]


def test_web_failed_user_persistence_cannot_mutate_routine(client: TestClient) -> None:
    """Missing history identity must stop before inference or routine mutations."""
    response, mocks = _post_chat(client, history_writer=lambda *args, **kwargs: {"id": None, "rowid": None})
    assert response.status_code == 503
    for key in ("selector", "triggered", "confirmed", "skipped", "paused", "graph"):
        mocks[key].assert_not_called()


@pytest.mark.parametrize("outcome", ["error", "empty", "success"])
def test_web_trace_is_finalized_and_saved_on_graph_exit(client, capsys, outcome):
    """Real endpoint exits preserve a single completed trace with pending evidence."""
    import json
    from langchain_core.messages import AIMessage
    from memory.execution_trace import load_traces
    def run(messages, limit, trace):
        trace.process_event({"Home_Agent": {"messages": [AIMessage(content="", tool_calls=[{
            "name": "get_current_location", "id": "pending-web", "args": {}}])]}})
        if outcome == "error":
            raise RuntimeError("offline graph failure")
        return {**_graph_result(), "final_ai_response": "" if outcome == "empty" else "ready"}
    with patch("api.server._tool_results_fallback_response", return_value=""):
        response, _ = _post_chat(client, graph_runner=MagicMock(side_effect=run))
    assert response.status_code == (500 if outcome == "error" else 200)
    rows = load_traces()
    assert len(rows) == 1
    assert rows[0]["error"] == {"error": "RuntimeError", "empty": "NoResponse", "success": None}[outcome]
    assert rows[0]["tool_calls"][0]["status"] == "unresolved"
    logs = [json.loads(line.removeprefix("[WebTrace]: "))
        for line in capsys.readouterr().out.splitlines() if line.startswith("[WebTrace]: ")]
    assert sum(row["event"] == "turn_finished" for row in logs) == 1


@pytest.mark.parametrize("dated", [False, True])
def test_web_photo_chat_cannot_complete_routine_before_asset_analysis(client, tmp_path, dated):
    """An attachment caption must not consume a routine before graph provenance exists."""
    import sqlite3
    from contextlib import nullcontext
    from memory.conversation_history import append_message, load_messages
    from memory.routine_feedback import RoutineFeedbackStore
    from services.routine_completion_helper import DatedRoutineSelection
    from services.routine_feedback_turn import PersistedRoutineFeedbackHandler
    from core.untrusted_content import external_content_source_names
    from zoneinfo import ZoneInfo

    path = tmp_path / "routines.db"
    def connect():
        return sqlite3.connect(path)
    with connect() as connection:
        connection.execute("""CREATE TABLE routines (id INTEGER PRIMARY KEY,
            event_name TEXT, notify_cooldown_hours REAL, explicit_skip_streak INTEGER,
            unanswered_reminder_streak INTEGER, confidence REAL)""")
        connection.execute("INSERT INTO routines VALUES (5, 'Καθάρισμα κουνελιού', 0, 0, 0, 1)")
    ledger = RoutineFeedbackStore(connect)
    ledger.initialize()
    now = datetime(2026, 10, 7, 9, tzinfo=ZoneInfo("Europe/Athens"))
    ledger.record_delivery(5, now.date(), at=now, receipt_id="$routine", question="Το έκανες;", channel="web")
    history = str(tmp_path / "history.db")
    def save(role, content, **kwargs):
        return append_message(role=role, content=content, channel="web",
            metadata=kwargs.get("metadata"), db_path=history)
    handler = PersistedRoutineFeedbackHandler(store=ledger,
        selector=lambda *a, **kw: DatedRoutineSelection("complete", 5, now.date()),
        clock=lambda: now, channel="web", conversation_db_path=history, trusted_owner=True)
    photos = tmp_path / "photos"
    photos.mkdir()
    photo = photos / "photo.png"
    photo.write_bytes(b"offline vision fixture")
    with (
        patch("api.server.PHOTOS_DIR", str(photos)),
        patch("core.brain.get_active_provider_adapter", return_value=MagicMock()),
        patch("core.brain.safe_adapter_call", return_value="Ναι το έκανα"),
        patch.object(server.state, "persisted_routine_feedback_handler", handler, create=True) if dated else nullcontext(),
    ):
        response, mocks = _post_chat(client, message="Ναι το έκανα", photo_path=str(photo),
            history_writer=save, pending={5: {"event": "Καθάρισμα κουνελιού"}})
    assert response.status_code == 200
    assert ledger.occurrences(5)[0].feedback is None
    for key in ("load_pending", "selector", "triggered", "confirmed"):
        mocks[key].assert_not_called()
    rows = load_messages(db_path=history)
    assert external_content_source_names(rows[0]["metadata"]) == {"user_provided_asset"}
    assert len(mocks["graph"].call_args.args[0]) > 0


@pytest.mark.parametrize("intent", ["clarify_draft", "clear_draft"])
def test_web_draft_intercept_reuses_persisted_user(client: TestClient, tmp_path: Path, intent: str) -> None:
    """Short draft responses reuse the same user row and avoid the graph."""
    from memory.conversation_history import append_message, load_messages

    db_path = str(tmp_path / "conversation.db")

    def save(role: str, content: str, agent: str | None = None, **kwargs: object) -> object:
        """Store both intercepted messages through the real history API."""
        saved = append_message(role=role, content=content, agent=agent, channel="web", db_path=db_path)
        return saved if kwargs.get("return_saved") else saved["id"]

    with (
        patch("services.messenger_intent.classify_messenger_intent", return_value=SimpleNamespace(intent=intent)),
        patch("core.messenger_draft.clear_draft", return_value=True),
        patch("memory.execution_trace.ExecutionTrace"),
    ):
        response, mocks = _post_chat(
            client, message="Show or discard the local draft",
            selector_returns=[RoutineSelection(action="none", routine_id=None)],
            history_writer=save,
        )
    assert response.status_code == 200
    users = [row for row in load_messages(db_path=db_path) if row["role"] == "user"]
    assert len(users) == 1
    assert response.json()["user_rowid"] == users[0]["rowid"]
    mocks["graph"].assert_not_called()
    mocks["triggered"].assert_not_called()


@pytest.mark.parametrize("authenticated", [False, True])
def test_web_rejected_input_never_persists_or_classifies(client: TestClient, authenticated: bool) -> None:
    """Authentication and firewall rejection still precede user persistence."""
    with (
        patch("api.server.detect_prompt_injection", return_value=True),
        patch("api.server.append_to_chat_history") as save,
        patch("services.routine_completion_selector.select_routine") as select,
    ):
        response = client.post(
            "/chat", json={"message": "Rejected input"},
            headers={"Authorization": f"Bearer {LOCAL_TOKEN}"} if authenticated else {},
        )
    if authenticated:
        assert response.status_code == 200
        assert response.json()["agent"] == "Security_Firewall"
    else:
        assert response.status_code in {401, 403}
    save.assert_not_called()
    select.assert_not_called()


def test_web_preemptive_completion_continues_to_graph(client: TestClient) -> None:
    """A verified today completion mutates once and still receives a normal graph reply."""
    response, mocks = _post_chat(client)
    assert response.status_code == 200
    assert response.json()["response"] == "Natural graph reply."
    mocks["triggered"].assert_called_once_with(5)
    mocks["confirmed"].assert_not_called()
    graph_messages = mocks["graph"].call_args.args[0]
    system_messages = [message for message in graph_messages if isinstance(message, SystemMessage)]
    assert len(system_messages) == 1
    assert "dynamic routine" not in str(system_messages[0].content)


@pytest.mark.parametrize("status", ["blocked", "pending"])
def test_draft_then_exact_budget_approval_preserves_visible_result(client: TestClient, status: str) -> None:
    """Real graph extraction and endpoint formatting preserve the terminal approval."""
    from langchain_core.messages import AIMessage, ToolMessage
    from langgraph.graph import StateGraph, START, END
    from core.utils import AgentState
    from api import server as api_server

    builder = StateGraph(AgentState)
    builder.add_node("tools", lambda state: {"messages": [ToolMessage(
        name="relay_local_payload", tool_call_id="draft",
        content=api_server.t("prompts.ext_draft_2") + "\nMessage: fixture draft",
    )]})
    builder.add_edge(START, "tools")
    previous = "tools"
    for index in range(10):
        name = f"step_{index}"
        builder.add_node(name, lambda state: {})
        builder.add_edge(previous, name)
        previous = name
    visible = f"{status}: terminal approval result"
    builder.add_node("approval_check", lambda state: {
        "approval_status": status, "messages": [AIMessage(content=visible)],
    })
    builder.add_edge(previous, "approval_check")
    builder.add_edge("approval_check", END)
    real_runner = api_server._run_web_graph_stream_sync
    results = []

    def run(messages: list, limit: int, trace: object) -> dict:
        """Capture real extraction at exactly twelve steps without tool I/O."""
        result = real_runner(messages, 12, trace)
        results.append(result)
        return result

    runner = MagicMock(side_effect=run)
    with (
        patch.object(api_server, "graph", builder.compile()),
        patch("core.utils.build_messenger_draft_ready_reply", return_value="wrong draft success"),
        patch("core.utils.should_attach_linkedin_draft_reply", return_value=True),
        patch("core.utils.build_linkedin_draft_ready_reply", return_value="wrong LinkedIn draft success"),
    ):
        response, _ = _post_chat(client, graph_runner=runner)
    assert response.status_code == 200
    assert results[0]["tool_result_fallbacks"]
    assert results[0]["final_ai_response"] == visible
    assert results[0]["saved_local_draft"] is True
    assert response.json()["response"] == visible


def test_web_empty_eligible_pool_does_not_call_selector(client: TestClient) -> None:
    """Already-completed or absent today routines do not enter the LLM selector."""
    graph_runner = MagicMock(side_effect=_graph_result)
    with (
        patch("memory.routine_db.get_eligible_preemptive_routines_for_day", return_value=[]),
        patch("memory.routine_db.get_active_routine_catalog", return_value=[]),
        patch("services.routine_completion_selector.select_routine") as selector,
        patch("api.server.append_to_chat_history", side_effect=_saved_message),
        patch("api.server._load_shared_context_messages", return_value=[]),
        patch("api.server._run_web_graph_stream_sync", graph_runner),
        patch("api.server.enqueue_fast_task"),
        patch("api.server.enqueue_slow_task"),
        patch("memory.routine_db.load_pending_confirmations", return_value={}),
    ):
        response = client.post("/chat", json={"message": "natural message"}, headers={"Authorization": f"Bearer {LOCAL_TOKEN}"})
    assert response.status_code == 200
    selector.assert_not_called()
    assert not any(isinstance(message, SystemMessage) for message in graph_runner.call_args.args[0])


def test_web_voice_turn_keeps_transcript_clean_and_adds_delivery_context(
    client: TestClient,
) -> None:
    """A live weather turn reaches the graph as user text plus server context."""
    transcript = "Ας δούμε, ο καιρός πώς θα είναι σήμερα;"

    response, mocks = _post_chat(
        client,
        message=transcript,
        voice_mode=True,
    )

    assert response.status_code == 200
    graph_messages = mocks["graph"].call_args.args[0]
    human_messages = [
        message for message in graph_messages if isinstance(message, HumanMessage)
    ]
    system_messages = [
        message for message in graph_messages if isinstance(message, SystemMessage)
    ]
    assert human_messages[-1].content.endswith(transcript)
    assert "HIDDEN INSTRUCTION" not in human_messages[-1].content
    assert any(
        "live spoken conversation" in str(message.content).lower()
        for message in system_messages
    )


def test_web_pending_confirmation_marks_routine_triggered_today(client: TestClient) -> None:
    """A confirmed pending routine is excluded from today's later candidate pool."""
    response, mocks = _post_chat(client, pending={5: {"event": "dynamic routine"}})
    assert response.status_code == 200
    mocks["confirmed"].assert_called_once_with(5)
    mocks["triggered"].assert_called_once_with(5)


def test_web_acknowledgement_does_not_complete_routine(client: TestClient) -> None:
    """A future commitment is acknowledged without marking the routine done."""
    response, mocks = _post_chat(
        client,
        selector_returns=[RoutineSelection(action="acknowledge", routine_id=5)],
    )
    assert response.status_code == 200
    mocks["acknowledged"].assert_called_once_with(5)
    mocks["consume_offer"].assert_not_called()
    mocks["triggered"].assert_not_called()
    mocks["confirmed"].assert_not_called()


def test_web_bare_draft_offer_acceptance_loads_persisted_offer(client: TestClient) -> None:
    """Web bare consent consumes the persisted Telegram offer and injects draft context."""
    draft_context = SystemMessage(content="[MESSENGER_ROUTINE_DRAFT_OFFER_ACCEPTED]")
    accepted_offer = SimpleNamespace(routine_id=5, context=draft_context)

    response, mocks = _post_chat(
        client,
        pending={
            5: {
                "event": "Message routine",
                "draft_offer": True,
                "sent_at": datetime.now(),
            }
        },
        message="yes",
        accepted_draft_offer=accepted_offer,
        saved_local_draft=True,
    )

    assert response.status_code == 200
    mocks["load_pending"].assert_called_once()
    mocks["accepted_offer"].assert_called_once()
    mocks["selector"].assert_not_called()
    mocks["consume_offer"].assert_called_once_with(5, ANY)
    mocks["acknowledged"].assert_not_called()
    graph_messages = mocks["graph"].call_args.args[0]
    assert draft_context in graph_messages


def test_web_bare_draft_offer_survives_a_failed_draft_write(client: TestClient) -> None:
    """Bare consent leaves the offer retryable until a local draft is saved."""
    draft_context = SystemMessage(content="[MESSENGER_ROUTINE_DRAFT_OFFER_ACCEPTED]")
    accepted_offer = SimpleNamespace(routine_id=5, context=draft_context)

    response, mocks = _post_chat(
        client,
        pending={
            5: {
                "event": "Message routine",
                "draft_offer": True,
                "sent_at": datetime.now(),
            }
        },
        message="yes",
        accepted_draft_offer=accepted_offer,
        saved_local_draft=False,
    )

    assert response.status_code == 200
    mocks["consume_offer"].assert_not_called()
    mocks["logged"].assert_not_called()


def test_web_semantic_draft_offer_acceptance_saves_a_draft_before_any_send(client: TestClient) -> None:
    """A natural response to one persisted offer grants only the local-draft path."""
    response, mocks = _post_chat(
        client,
        pending={
            5: {
                "event": "Morning message",
                "draft_offer": True,
                "sent_at": datetime.now(),
            }
        },
        message="Ναι φίλε κάνε το πιο γλυκό",
        selector_returns=[RoutineSelection(action="draft", routine_id=5)],
        saved_local_draft=True,
    )

    assert response.status_code == 200
    assert mocks["selector"].call_args_list[0].args[1] == {
        5: "Morning message\n[MESSENGER_DRAFT_OFFER]",
    }
    mocks["consume_offer"].assert_called_once_with(5, ANY)
    mocks["acknowledged"].assert_not_called()
    mocks["logged"].assert_any_call(
        "routines",
        "routine_acknowledged",
        routine_id=5,
        event="Morning message",
    )
    graph_messages = mocks["graph"].call_args.args[0]
    assert any(
        "[MESSENGER_ROUTINE_DRAFT_OFFER_ACCEPTED]" in str(message.content)
        for message in graph_messages
        if isinstance(message, SystemMessage)
    )


def test_web_semantic_draft_offer_survives_a_failed_draft_write(client: TestClient) -> None:
    """A failed graph run leaves the persisted offer available for a retry."""
    response, mocks = _post_chat(
        client,
        pending={
            5: {
                "event": "Morning message",
                "draft_offer": True,
                "sent_at": datetime.now(),
            }
        },
        message="Ναι φίλε κάνε το πιο γλυκό",
        selector_returns=[RoutineSelection(action="draft", routine_id=5)],
        saved_local_draft=False,
    )

    assert response.status_code == 200
    mocks["consume_offer"].assert_not_called()
    mocks["logged"].assert_not_called()


def test_web_active_draft_keeps_bare_yes_out_of_pending_offer_path(client: TestClient) -> None:
    """An active draft takes precedence over a pending routine draft offer."""
    draft_context = SystemMessage(content="[MESSENGER_ROUTINE_DRAFT_OFFER_ACCEPTED]")
    accepted_offer = SimpleNamespace(routine_id=5, context=draft_context)

    response, mocks = _post_chat(
        client,
        pending={5: {"event": "Message routine", "draft_offer": True}},
        message="yes",
        accepted_draft_offer=accepted_offer,
        active_draft_status=(True, "active", {"message": "draft"}),
        selector_returns=[
            RoutineSelection(action="none", routine_id=None),
            RoutineSelection(action="none", routine_id=None),
        ],
    )

    assert response.status_code == 200
    mocks["accepted_offer"].assert_not_called()
    mocks["consume_offer"].assert_not_called()


def test_web_active_draft_blocks_semantic_offer_replacement(client: TestClient) -> None:
    """A pending offer cannot replace an already saved draft through semantic selection."""
    response, mocks = _post_chat(
        client,
        pending={
            5: {
                "event": "Morning message",
                "draft_offer": True,
                "sent_at": datetime.now(),
            }
        },
        message="Ναι φίλε κάνε το πιο γλυκό",
        active_draft_status=(True, "active", {"message": "Existing draft"}),
        selector_returns=[
            RoutineSelection(action="draft", routine_id=5),
            RoutineSelection(action="none", routine_id=None),
        ],
    )

    assert response.status_code == 200
    assert mocks["selector"].call_args_list[0].args[1] == {5: "Morning message"}
    mocks["consume_offer"].assert_not_called()


def test_web_pending_pass_through_allows_today_completion(client: TestClient) -> None:
    """An unrelated pending routine does not block a same-day completion."""
    response, mocks = _post_chat(
        client,
        pending={7: {"event": "unrelated pending routine"}},
        selector_returns=[
            RoutineSelection(action="none", routine_id=None),
            RoutineSelection(action="complete", routine_id=5),
        ],
    )
    assert response.status_code == 200
    mocks["selector"].assert_called()
    assert mocks["selector"].call_count == 2
    mocks["triggered"].assert_called_once_with(5)


def test_web_skip_today_does_not_complete_routine(client: TestClient) -> None:
    """An explicit one-day refusal records a skip without completion."""
    response, mocks = _post_chat(
        client,
        selector_returns=[RoutineSelection(action="skip_today", routine_id=5)],
    )
    assert response.status_code == 200
    mocks["skipped"].assert_called_once_with(5)
    mocks["triggered"].assert_not_called()


def test_web_pause_keeps_routine_reversible(client: TestClient) -> None:
    """A permanent refusal pauses the routine instead of deleting or completing it."""
    response, mocks = _post_chat(
        client,
        selector_returns=[RoutineSelection(action="pause", routine_id=5)],
    )
    assert response.status_code == 200
    mocks["paused"].assert_called_once_with(5)
    mocks["triggered"].assert_not_called()


def test_web_catalog_pause_handles_explicit_named_routine_outside_today(client: TestClient) -> None:
    """A named routine may be permanently paused even when it is not due today."""
    response, mocks = _post_chat(
        client,
        catalog_routines=[{"id": 9, "event": "dynamic routine"}],
        message="natural permanent cancellation of dynamic routine",
        selector_returns=[
            RoutineSelection(action="none", routine_id=None),
            RoutineSelection(action="pause", routine_id=9),
        ],
    )
    assert response.status_code == 200
    mocks["paused"].assert_called_once_with(9)


def test_web_routine_action_does_not_confirm_pending_asset(client: TestClient) -> None:
    """A consumed routine action cannot also approve a pending asset in the same turn."""
    pending_asset = {"id": "asset-1", "asset_type": "document", "file_path": "safe.txt"}
    with (
        patch("memory.pending_assets.clear_expired_pending_assets"),
        patch("memory.pending_assets.get_latest_pending_asset", return_value=pending_asset),
        patch("memory.pending_assets.classify_pending_asset_reply", return_value="yes"),
        patch("memory.pending_assets.is_reply_to_recent_asset_prompt", return_value=True),
        patch("memory.pending_assets.mark_pending_asset_confirmed") as asset_confirmed,
    ):
        response, _ = _post_chat(client, pending={5: {"event": "dynamic routine"}})
    assert response.status_code == 200
    assert response.json()["response"] == "Natural graph reply."
    asset_confirmed.assert_not_called()


def test_exhausted_web_turn_does_not_replace_result_with_draft_success(client: TestClient) -> None:
    """A pending draft cannot overwrite the incomplete-turn response."""
    with (
        patch("core.utils.should_attach_linkedin_draft_reply", return_value=True),
        patch("core.utils.build_linkedin_draft_ready_reply", side_effect=AssertionError("must not claim success")),
        patch("core.utils.looks_like_terminal_messenger_draft_result", return_value=True),
        patch("core.utils.build_messenger_draft_ready_reply", side_effect=AssertionError("must not claim success")),
    ):
        response, _ = _post_chat(client, graph_budget_exhausted=True)
    assert response.status_code == 200
    assert response.json()["response"] == "Natural graph reply."
