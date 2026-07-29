"""Web integration coverage for natural routine completion and graph continuity."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import SystemMessage

from api.server import LOCAL_TOKEN, server
from services.routine_completion_helper import RoutineSelection


@pytest.fixture
def client() -> TestClient:
    """Provide the actual Web API app with its normal authentication token."""
    return TestClient(server)


def _saved_message(*_args: object, **kwargs: object) -> object:
    """Return a stable history payload only where the endpoint requests it."""
    return {"id": "test-message", "rowid": 1} if kwargs.get("return_saved") else None


def _graph_result(*_args: object, **_kwargs: object) -> dict[str, object]:
    """Return one normal graph response without invoking external model services."""
    return {
        "final_ai_response": "Natural graph reply.",
        "handling_agent": "Chat_Agent",
        "tool_result_fallbacks": [],
        "graph_elapsed_ms": 1,
    }


def _post_chat(
    client: TestClient,
    pending: dict[int, dict[str, str]] | None = None,
) -> tuple[object, dict[str, MagicMock]]:
    """Run one Web message under isolated completion and graph dependencies."""
    graph_runner = MagicMock(side_effect=_graph_result)
    with (
        patch("memory.routine_db.get_eligible_preemptive_routines_for_day", return_value=[{"id": 5, "event": "dynamic routine"}]) as eligible,
        patch("memory.routine_db.mark_routine_triggered_today") as triggered,
        patch("memory.routine_db.confirm_routine") as confirmed,
        patch("memory.routine_db.mark_routine_responded"),
        patch("memory.routine_db.remove_pending_confirmation"),
        patch("memory.routine_db.decay_routine"),
        patch("memory.event_log.log_event"),
        patch("services.routine_completion_selector.select_routine", return_value=RoutineSelection(action="complete", routine_id=5)) as selector,
        patch("api.server.append_to_chat_history", side_effect=_saved_message),
        patch("api.server._load_shared_context_messages", return_value=[]),
        patch("api.server._run_web_graph_stream_sync", graph_runner),
        patch("api.server.enqueue_fast_task"),
        patch("api.server.enqueue_slow_task"),
        patch("clients.telegram_bot.pending_routine_confirmations", pending or {}),
    ):
        response = client.post("/chat", json={"message": "natural message"}, headers={"Authorization": f"Bearer {LOCAL_TOKEN}"})
        return response, {"eligible": eligible, "triggered": triggered, "confirmed": confirmed, "selector": selector, "graph": graph_runner}


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


def test_web_empty_eligible_pool_does_not_call_selector(client: TestClient) -> None:
    """Already-completed or absent today routines do not enter the LLM selector."""
    graph_runner = MagicMock(side_effect=_graph_result)
    with (
        patch("memory.routine_db.get_eligible_preemptive_routines_for_day", return_value=[]),
        patch("services.routine_completion_selector.select_routine") as selector,
        patch("api.server.append_to_chat_history", side_effect=_saved_message),
        patch("api.server._load_shared_context_messages", return_value=[]),
        patch("api.server._run_web_graph_stream_sync", graph_runner),
        patch("api.server.enqueue_fast_task"),
        patch("api.server.enqueue_slow_task"),
        patch("clients.telegram_bot.pending_routine_confirmations", {}),
    ):
        response = client.post("/chat", json={"message": "natural message"}, headers={"Authorization": f"Bearer {LOCAL_TOKEN}"})
    assert response.status_code == 200
    selector.assert_not_called()
    assert not any(isinstance(message, SystemMessage) for message in graph_runner.call_args.args[0])


def test_web_pending_confirmation_marks_routine_triggered_today(client: TestClient) -> None:
    """A confirmed pending routine is excluded from today's later candidate pool."""
    response, mocks = _post_chat(client, pending={5: {"event": "dynamic routine"}})
    assert response.status_code == 200
    mocks["confirmed"].assert_called_once_with(5)
    mocks["triggered"].assert_called_once_with(5)


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
