"""Web integration coverage for natural routine completion and graph continuity."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import ANY, MagicMock, patch

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
        "external_tool_names": [],
        "graph_elapsed_ms": 1,
    }


def _post_chat(
    client: TestClient,
    pending: dict[int, dict[str, str]] | None = None,
    selector_returns: list[RoutineSelection] | None = None,
    *,
    message: str = "natural message",
    accepted_draft_offer: object | None = None,
    active_draft_status: tuple[bool, str, dict | None] = (False, "missing", None),
) -> tuple[object, dict[str, MagicMock]]:
    """Run one Web message under isolated completion and graph dependencies."""
    graph_runner = MagicMock(side_effect=_graph_result)
    selector = MagicMock(
        side_effect=selector_returns
        if selector_returns is not None
        else [RoutineSelection(action="complete", routine_id=5)]
    )
    with (
        patch("memory.routine_db.get_eligible_preemptive_routines_for_day", return_value=[{"id": 5, "event": "dynamic routine"}]) as eligible,
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
        patch("memory.event_log.log_event"),
        patch("services.routine_completion_selector.select_routine", selector),
        patch(
            "services.routine_completion_context.accept_pending_messenger_draft_offer",
            return_value=accepted_draft_offer,
        ) as accepted_offer,
        patch(
            "services.routine_completion_context.build_routine_completion_context",
            return_value=SystemMessage(content="Routine lifecycle updated."),
        ),
        patch("api.server.append_to_chat_history", side_effect=_saved_message),
        patch("api.server._load_shared_context_messages", return_value=[]),
        patch("core.messenger_draft.active_draft_status", return_value=active_draft_status),
        patch("api.server._run_web_graph_stream_sync", graph_runner),
        patch("api.server.enqueue_fast_task"),
        patch("api.server.enqueue_slow_task"),
    ):
        response = client.post("/chat", json={"message": message}, headers={"Authorization": f"Bearer {LOCAL_TOKEN}"})
        return response, {
            "eligible": eligible,
            "triggered": triggered,
            "confirmed": confirmed,
            "acknowledged": acknowledged,
            "consume_offer": consume_offer,
            "skipped": skipped,
            "paused": paused,
            "load_pending": load_pending,
            "selector": selector,
            "accepted_offer": accepted_offer,
            "graph": graph_runner,
        }


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
        patch("memory.routine_db.load_pending_confirmations", return_value={}),
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
        pending={5: {"event": "Message routine", "draft_offer": True}},
        message="yes",
        accepted_draft_offer=accepted_offer,
    )

    assert response.status_code == 200
    mocks["load_pending"].assert_called_once()
    mocks["accepted_offer"].assert_called_once()
    mocks["selector"].assert_not_called()
    mocks["consume_offer"].assert_called_once_with(5, ANY)
    mocks["acknowledged"].assert_not_called()
    graph_messages = mocks["graph"].call_args.args[0]
    assert draft_context in graph_messages


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
