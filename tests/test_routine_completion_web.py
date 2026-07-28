"""
Integration tests for routine completion via the actual Web API endpoint.
Uses FastAPI TestClient to hit the real api.server.chat_endpoint path.

Asserts:
- a) Pre-emptive selected routine ⇒ only mark_routine_triggered_today(selected_id)
- b) Multiple pending + bare no ⇒ localized clarification, no decay
- c) One pending + yes ⇒ only selected ID confirm/remove
- d) Handled completion returns the actual endpoint response without graph invocation.
"""

import sys
import pytest
from unittest.mock import patch, MagicMock

# Remove top-level sys.modules stub since it causes state leakage with telegram tests.
# Instead, we will patch it dynamically inside _run_chat.

from fastapi.testclient import TestClient
from api.server import server, LOCAL_TOKEN

@pytest.fixture
def client():
    return TestClient(server)

def _run_chat(client, text, pending=None, today_routines=None, selector_return=None):
    pending_dict = dict(pending or {})

    def _graph_trap(*args, **kwargs):
        raise AssertionError("Graph was invoked — handled completion must return early")

    with (
        patch("memory.routine_db.get_routines_for_day", return_value=today_routines or []),
        patch("memory.routine_db.mark_routine_triggered_today") as m_triggered,
        patch("memory.routine_db.confirm_routine") as m_confirm,
        patch("memory.routine_db.mark_routine_responded") as m_responded,
        patch("memory.routine_db.remove_pending_confirmation") as m_remove,
        patch("memory.routine_db.decay_routine") as m_decay,
        patch("services.routine_completion_selector.select_routine", return_value=selector_return),
        patch("memory.event_log.log_event") as m_log,
        patch("api.server.enqueue_fast_task"),
        patch("api.server.enqueue_slow_task"),
        patch("api.server.append_to_chat_history"),
        patch("api.server.graph.stream", side_effect=_graph_trap),
        patch("clients.telegram_bot.pending_routine_confirmations", pending_dict),
    ):
        headers = {"Authorization": f"Bearer {LOCAL_TOKEN}"}
        payload = {"message": text}

        try:
            response = client.post("/chat", json=payload, headers=headers)
        except AssertionError as e:
            if "Graph was invoked" in str(e):
                raise
            raise e

        return response, {
            "triggered": m_triggered,
            "confirm": m_confirm,
            "responded": m_responded,
            "remove": m_remove,
            "decay": m_decay,
            "log": m_log,
            "pending_dict": pending_dict,
        }

def test_web_preemptive_completion_calls_mark_triggered(client):
    """(a) Pre-emptive selected routine => only mark_routine_triggered_today(selected_id)"""
    resp, mocks = _run_chat(
        client,
        text="πήγαμε στο σούπερ μάρκετ",
        today_routines=[{"id": 5, "event": "Σούπερ μάρκετ"}]
    )

    assert resp.status_code == 200
    json_resp = resp.json()
    assert "Σημειώθηκε ως ολοκληρωμένη" in json_resp["response"]
    assert "Σούπερ μάρκετ" in json_resp["response"]

    mocks["triggered"].assert_called_once_with(5)
    mocks["confirm"].assert_not_called()
    mocks["decay"].assert_not_called()

def test_web_multi_pending_bare_no_returns_clarification(client):
    """(b) Multiple pending + bare no => localized clarification, no decay"""
    resp, mocks = _run_chat(
        client,
        text="όχι",
        pending={
            5: {"event": "Πάρκο"},
            8: {"event": "Σούπερ μάρκετ"},
        }
    )

    assert resp.status_code == 200
    json_resp = resp.json()
    assert "Ποια ρουτίνα εννοείς;" in json_resp["response"]
    assert "Πάρκο" in json_resp["response"] or "Σούπερ" in json_resp["response"]

    mocks["decay"].assert_not_called()
    mocks["confirm"].assert_not_called()

def test_web_single_pending_bare_yes_confirms(client):
    """(c) One pending + yes => only selected ID confirm/remove"""
    resp, mocks = _run_chat(
        client,
        text="ναι",
        pending={5: {"event": "Πάρκο"}}
    )

    assert resp.status_code == 200
    json_resp = resp.json()
    assert "Ολοκληρώθηκε" in json_resp["response"]
    assert "Πάρκο" in json_resp["response"]

    mocks["confirm"].assert_called_once_with(5)
    mocks["remove"].assert_called_once_with(5)
    mocks["decay"].assert_not_called()
    assert 5 not in mocks["pending_dict"]

def test_web_handled_completion_returns_actual_response(client):
    """(d) Handled completion returns the actual endpoint response without graph invocation."""
    # Tested by _graph_trap asserting it's not called, and returning 200 JSONResponse.
    resp, mocks = _run_chat(
        client,
        text="ναι",
        pending={5: {"event": "Πάρκο"}}
    )

    assert resp.status_code == 200
    json_resp = resp.json()
    assert json_resp.get("agent") == "Chat_Agent"
