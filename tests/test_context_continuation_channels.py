"""Offline full-handler continuation contracts for Web and Telegram."""

from __future__ import annotations

import json
import socket
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from memory.conversation_history import append_message, load_messages


TEXT = "Ναι φίλε, η Σοφία έφυγε στη δουλειά. Θυμήσου το αυριανό ρεπό και βάλε υπενθύμιση στις έξι."
REPLY = "Κατάλαβα φίλε, πάμε να οργανώσουμε αυτά που ζήτησες."


@pytest.fixture
def continuation_boundaries(monkeypatch: pytest.MonkeyPatch):
    """Replace only external/storage boundaries; run the real channel handlers."""
    import memory.execution_trace as execution_trace
    import memory.pending_assets as assets
    from core import messenger_draft, planner
    from services import messenger_intent, routine_context_clarification as clarification

    original_connect = socket.socket.connect

    def forbidden_connect(sock: socket.socket, address: Any) -> Any:
        """Allow asyncio's self-pipe, reject every accidental remote connection."""
        if isinstance(address, tuple) and address[0] in {"127.0.0.1", "::1"}:
            return original_connect(sock, address)
        raise AssertionError("Unexpected external connection")

    monkeypatch.setattr(socket.socket, "connect", forbidden_connect)
    monkeypatch.setattr(execution_trace, "ExecutionTrace", MagicMock())
    monkeypatch.setattr(assets, "clear_expired_pending_assets", lambda: None)
    for name in ("get_latest_pending_asset", "get_latest_pending_asset_any", "get_latest_recent_asset"):
        monkeypatch.setattr(assets, name, lambda *a, **k: None)
    monkeypatch.setattr(messenger_draft, "active_draft_status", lambda: (False, "missing", None))
    monkeypatch.setattr(messenger_intent, "classify_messenger_intent",
                        lambda *a, **k: SimpleNamespace(intent="unrelated"))
    monkeypatch.setattr(planner, "get_fresh_pending_plan_confirmation", lambda *a, **k: None)
    monkeypatch.setattr(clarification, "try_context_question_reply",
                        lambda *a, **k: clarification.QuestionAnswer(True, "resolved", True))
    tasks: list[tuple[Any, ...]] = []
    return tasks


def assert_background_continues_once(tasks: list[tuple[Any, ...]]) -> None:
    """Memory/followup work survives while canonical flag extraction is not repeated."""
    names = [task[0].__name__ for task in tasks]
    assert names.count("log_exchange") == 1
    assert names.count("update_working_memory") == 1
    assert names.count("_enqueue_slow_memory_sifter") == 1
    assert names.count("_enqueue_followup_pipeline") == 1
    assert "extract_and_update_context_flags" not in names


def assert_context_and_original(messages: list[Any]) -> None:
    """The full trusted request remains, with a bounded non-authorizing context note."""
    assert sum(TEXT in str(message.content) for message in messages if isinstance(message, HumanMessage)) == 1
    notes = [message for message in messages if isinstance(message, SystemMessage)
             and "canonical answer outcome" in str(message.content)]
    assert len(notes) == 1
    assert "not reinterpret" in notes[0].content
    assert "normal conversation and tool approval paths" in notes[0].content


@pytest.mark.asyncio
async def test_web_mixed_answer_preserves_normal_graph_history_and_memory(
    tmp_path, monkeypatch: pytest.MonkeyPatch, continuation_boundaries,
) -> None:
    """Web handles one mixed owner turn, not an acknowledgement-only early return."""
    from api import server as api

    tasks = continuation_boundaries
    path = str(tmp_path / "web-history.db")
    graph_inputs: list[list[Any]] = []

    def save(role: str, content: str, **kwargs: Any) -> dict[str, Any]:
        """Persist the handler's exact output through the real disposable history store."""
        return append_message(role=role, content=content, channel="web",
                              agent=kwargs.get("agent"), db_path=path)

    def graph(messages: list[Any], *args: Any, **kwargs: Any) -> dict[str, Any]:
        """Provide a deterministic provider-boundary result without running tools."""
        graph_inputs.append(messages)
        return {"final_ai_response": REPLY, "handling_agent": "Chat_Agent",
                "tool_result_fallbacks": [], "external_tool_names": [],
                "graph_elapsed_ms": 1, "saved_local_draft": False}

    monkeypatch.setattr(api.server.state, "persisted_routine_feedback_handler", lambda *a, **k: None, raising=False)
    monkeypatch.setattr(api, "append_to_chat_history", save)
    monkeypatch.setattr(api, "_load_shared_context_messages", lambda *a, **k: [])
    monkeypatch.setattr(api, "_run_web_graph_stream_sync", graph)
    monkeypatch.setattr(api, "enqueue_fast_task", lambda *a, **k: tasks.append(a))
    monkeypatch.setattr(api, "enqueue_slow_task", lambda *a, **k: tasks.append(a))

    async def body() -> dict[str, str]:
        """Supply an ordinary Web text request without live client state."""
        return {"message": TEXT}

    response = await api.chat_endpoint(SimpleNamespace(json=body, headers={}, client=None))

    assert response.status_code == 200, response.body
    assert json.loads(response.body)["response"] == REPLY
    assert len(graph_inputs) == 1
    assert_context_and_original(graph_inputs[0])
    assert [row["content"] for row in load_messages(db_path=path)] == [TEXT, REPLY]
    assert_background_continues_once(tasks)


def test_telegram_mixed_answer_preserves_normal_graph_history_and_memory(
    tmp_path, monkeypatch: pytest.MonkeyPatch, continuation_boundaries,
) -> None:
    """Telegram retains the original mixed turn and queues normal background work once."""
    from clients import telegram_bot as bot
    import tools.telegram as transport

    tasks = continuation_boundaries
    path = str(tmp_path / "telegram-history.db")
    graph_inputs: list[list[Any]] = []
    sent: list[str] = []

    def save(role: str, content: str, **kwargs: Any) -> int:
        """Use disposable real history, returning the row identity Telegram expects."""
        row = append_message(role="assistant" if role == "ai" else role,
                             content=content, channel="telegram", db_path=path)
        return row["rowid"]

    def graph(state: dict[str, Any], *args: Any, **kwargs: Any) -> list[dict[str, Any]]:
        """Return one model answer while exercising the full handler's extraction."""
        graph_inputs.append(state["messages"])
        assert not state.get("routine_draft_offer_authorized", False)
        return [{"Chat_Agent": {"messages": [AIMessage(content=REPLY)]}}]

    for name in ("pending_routine_confirmations", "pending_reflection_confirmations"):
        monkeypatch.setattr(bot, name, {})
    monkeypatch.setattr(bot, "pending_exec_command", None)
    monkeypatch.setattr(bot, "pending_photo", None)
    monkeypatch.setattr(bot.config, "TELEGRAM_CHAT_ID", "owner")
    monkeypatch.setattr(bot, "_persisted_routine_feedback_handler", lambda *a, **k: None)
    monkeypatch.setattr(bot, "_safe_active_draft_status", lambda: (False, "missing", None))
    monkeypatch.setattr(bot, "_safe_classify_messenger_intent", lambda *a, **k: None)
    monkeypatch.setattr(bot, "_append_to_analytics_log", save)
    monkeypatch.setattr(bot, "_build_fast_chat_context", lambda text, **k: ([], HumanMessage(content=text)))
    monkeypatch.setattr(bot, "_cache_bot_message", lambda *a, **k: None)
    monkeypatch.setattr(bot, "_schedule_capability_gap_if_valid", lambda *a, **k: None)
    monkeypatch.setattr(bot, "enqueue_fast_task", lambda *a, **k: tasks.append(a))
    monkeypatch.setattr(bot, "enqueue_slow_task", lambda *a, **k: tasks.append(a))
    monkeypatch.setattr(bot.threading, "Thread", lambda *a, **k: SimpleNamespace(start=lambda: None))
    monkeypatch.setattr(bot.graph, "stream", graph)
    monkeypatch.setattr(transport, "send_telegram_msg", lambda text: sent.append(text) or 1)

    bot.handle_message(TEXT, "owner")

    assert sent == [REPLY]
    assert len(graph_inputs) == 1
    assert_context_and_original(graph_inputs[0])
    assert [row["content"] for row in load_messages(db_path=path)] == [TEXT, REPLY]
    assert_background_continues_once(tasks)
