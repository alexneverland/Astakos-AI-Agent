"""Exercise Web extraction with a real finite graph, no provider or tool I/O."""

from unittest.mock import MagicMock

import pytest
from langchain_core.messages import AIMessage, ToolMessage
from langgraph.graph import StateGraph, START, END


@pytest.mark.parametrize("status", ["blocked", "pending", "ok"])
def test_web_preserves_terminal_approval_at_budget(monkeypatch: pytest.MonkeyPatch, status: str) -> None:
    """The final emitted approval must survive an exact-budget exception."""
    from api import server
    from core.utils import AgentState

    builder = StateGraph(AgentState)
    previous = START
    for index in range(11):
        name = f"step_{index}"
        builder.add_node(name, lambda state: {})
        builder.add_edge(previous, name)
        previous = name
    builder.add_node("approval_check", lambda state: {
        "approval_status": status,
        "messages": [AIMessage(content="terminal approval result")],
    })
    builder.add_edge(previous, "approval_check")
    builder.add_edge("approval_check", END)
    monkeypatch.setattr(server, "graph", builder.compile())
    trace = MagicMock()
    trace.phase_timings = {}
    result = server._run_web_graph_stream_sync([], 12, trace)
    if status in ("blocked", "pending"):
        assert result["final_ai_response"] == "terminal approval result"
    else:
        assert result["final_ai_response"] == server.t("api.server.graph_budget_exhausted")
        assert result["graph_budget_exhausted"] is True


def test_web_does_not_hide_unrelated_graph_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """Only budget exhaustion is handled; other failures keep their semantics."""
    from api import server

    fake = MagicMock()
    fake.stream.side_effect = ValueError("other failure")
    monkeypatch.setattr(server, "graph", fake)
    with pytest.raises(ValueError, match="other failure"):
        server._run_web_graph_stream_sync([], 12, MagicMock())


def test_incomplete_web_turn_keeps_provenance_and_never_replays(monkeypatch: pytest.MonkeyPatch) -> None:
    """Executed steps stay single and tainted even when the next step is cut off."""
    from api import server
    from core.utils import AgentState

    executed = []
    builder = StateGraph(AgentState)

    def tool_step(state: dict) -> dict:
        """Record a single fake read result with external provenance."""
        executed.append("one")
        return {"messages": [ToolMessage(
            content="external page", name="browse_url", tool_call_id="page",
        )]}

    builder.add_node("tools", tool_step)
    builder.add_node("unfinished", lambda state: {"messages": [AIMessage(content="unreachable")]})
    builder.add_edge(START, "tools")
    builder.add_edge("tools", "unfinished")
    builder.add_edge("unfinished", END)
    monkeypatch.setattr(server, "graph", builder.compile())
    trace = MagicMock()
    trace.phase_timings = {}
    result = server._run_web_graph_stream_sync([], 1, trace)
    assert executed == ["one"]
    assert result["external_tool_names"] == ["browse_url"]
    assert result["graph_budget_exhausted"] is True
    assert result["final_ai_response"] == server.t("api.server.graph_budget_exhausted")


def test_web_gps_provenance_matches_shared_collector(monkeypatch: pytest.MonkeyPatch) -> None:
    """Web result collection and Matrix's shared collector agree on typed GPS."""
    from api import server
    from core.location_result import location_payload
    from core.untrusted_content import external_tool_names_from_events

    events = [{"tools": {"messages": [ToolMessage(
        content=location_payload("current", 40, 23, 123, True),
        name="get_current_location", tool_call_id="gps",
    )]}}, {"Home_Agent": {"messages": [AIMessage(content="done")]}}]
    fake = MagicMock()
    fake.stream.return_value = events
    monkeypatch.setattr(server, "graph", fake)
    trace = MagicMock()
    trace.phase_timings = {}
    result = server._run_web_graph_stream_sync([], 12, trace)
    assert result["external_tool_names"] == []
    assert external_tool_names_from_events(events) == set()
