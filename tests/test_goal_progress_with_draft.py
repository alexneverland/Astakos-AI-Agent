"""Compound owner reports retain goal milestones alongside local drafts."""
from types import SimpleNamespace
from typing import Any
import json

import pytest
from langchain_core.messages import AIMessage, HumanMessage, BaseMessage

from tests.test_goal_agent_updates import goal_store

pytestmark = pytest.mark.usefixtures("offline_behavioral_io")
REPORT = "ΝΑΙ ΦΙΛΕ ΤΟ ΠΡΟΤΖΕΚΤ KAGGLE ΤΟ ΠΡΟΧΩΡΑΩ ΤΩΡΑ ΕΙΜΑΙ 0.12. ΤΩΡΑ ΓΙΑ ΤΟ ΜΗΝΥΜΑ ΣΤΗΝ ΣΟΦΙΑ ΦΤΙΑΞΕ ΕΝΑ ΓΛΥΚΟ ΜΗΝΥΜΑ"


def bindings(monkeypatch: pytest.MonkeyPatch, role: str, mode: str) -> dict[str, Any]:
    """Use the real agent's tool gates with model/history boundaries offline."""
    import core.agents as agents
    import services.messenger_intent as intent
    captured: dict[str, Any] = {}
    class Model:
        """Capture actual bindings without contacting a provider."""
        def bind_tools(self, tools: list[Any]) -> "Model":
            """Record tools supplied by the production agent."""
            captured.update({tool.name: tool for tool in tools})
            return self
        def invoke(self, messages: list[BaseMessage]) -> AIMessage:
            """Return offline wording without executing tools."""
            return AIMessage(content="Offline draft ready")
    monkeypatch.setattr(agents, "llm", Model())
    monkeypatch.setattr(agents, "build_prompt", lambda *a, **k: "offline")
    monkeypatch.setattr(agents, "_has_active_messenger_draft", lambda: mode == "edit")
    # These are binding-only node calls, without a graph-entry guard. Do not
    # let the new lifecycle boundary inspect the owner's real shared draft.
    monkeypatch.setattr("core.messenger_draft.active_draft_status", lambda: (False, "missing", None))
    monkeypatch.setattr(intent, "is_create_draft_intent", lambda *a: mode == "create")
    monkeypatch.setattr(intent, "has_accepted_routine_draft_offer", lambda *a, **k: mode == "accepted")
    monkeypatch.setattr(intent, "is_contextually_grounded_active_draft_edit", lambda *a: mode == "edit")
    monkeypatch.setattr(intent, "classify_messenger_intent", lambda *a, **k: SimpleNamespace(intent="general_chat"))
    monkeypatch.setattr("tools.web.has_known_messenger_contact_reference", lambda *a: False)
    monkeypatch.setattr(agents, "_food_tools_for_latest_user_text", lambda tools, text: tools)
    monkeypatch.setattr("core.agent_tools.get_registered_tools_for_agent", lambda name, tools:
        tools + [SimpleNamespace(name="execute_external_extra")])
    state = {"messages": [HumanMessage(content=REPORT)], "channel": "web"}
    node = agents.web_agent_node if role == "Web_Agent" else agents.chat_agent_node
    node(state)
    return captured


@pytest.mark.parametrize("role", ["Chat_Agent", "Web_Agent"])
@pytest.mark.parametrize("mode", ["create", "accepted"])
def test_compound_report_reaches_native_goal_persistence_and_readers(
    goal_store: dict[str, Any], monkeypatch: pytest.MonkeyPatch, role: str, mode: str,
) -> None:
    """A score milestone reaches Debug/followup without resetting the goal."""
    tools = bindings(monkeypatch, role, mode)
    assert set(tools) == {"relay_local_payload", "update_goal_milestones_tool"}
    result = tools["update_goal_milestones_tool"].invoke({"project": "Kaggle",
        "milestones": "Submission score 0.06; latest reported score 0.12; still working"})
    assert result.startswith("✅")
    meta = goal_store["metadata"]
    assert meta["progress"] == 25 and meta["status"] == "active"
    assert meta["created_at"] == 1700000000.0
    assert goal_store["document"] == "[GOAL] Kaggle: Improve submission"
    assert "0.12" in json.loads(meta["goal_events_json"])[-1]["detail"]
    from memory.vector_store import get_active_goals
    from services.goal_followup_timing import format_goal_followup_context
    goals = get_active_goals()
    assert "0.12" in format_goal_followup_context(goals[0])
    from api.server import debug_goals
    # This async endpoint performs synchronous reads only; drive it without
    # creating Windows' loopback socketpair under the no-network test guard.
    reader = debug_goals()
    try:
        with pytest.raises(StopIteration) as response:
            reader.send(None)
        assert "0.12" in response.value.value["goals"][0]["milestones"]
    finally:
        reader.close()


@pytest.mark.parametrize("role", ["Chat_Agent", "Web_Agent"])
def test_existing_draft_revision_remains_isolated(monkeypatch: pytest.MonkeyPatch, role: str) -> None:
    """An edit cannot mutate goals or execute registry-injected external tools."""
    assert set(bindings(monkeypatch, role, "edit")) == {"relay_local_payload"}


def test_ordinary_web_turn_can_update_existing_goal_without_creation_tools(monkeypatch: pytest.MonkeyPatch) -> None:
    """Other Web requests can retain an independent milestone report."""
    tools = bindings(monkeypatch, "Web_Agent", "general")
    assert "update_goal_milestones_tool" in tools
    assert not {"save_goal_tool", "update_goal_progress_tool", "update_goal_status_tool"} & tools.keys()


@pytest.mark.parametrize("failure", ["unknown_project", "storage_failed"])
def test_bound_goal_update_cannot_claim_success_on_failure(
    goal_store: dict[str, Any], monkeypatch: pytest.MonkeyPatch, failure: str,
) -> None:
    """A partial update neither creates a goal nor falsely reports a saved result."""
    tools = bindings(monkeypatch, "Web_Agent", "create")
    before = json.dumps(goal_store, sort_keys=True)
    if failure == "storage_failed":
        monkeypatch.setattr("memory.vector_store.update_goal_milestones", lambda **k: False)
    result = tools["update_goal_milestones_tool"].invoke({
        "project": "Unknown" if failure == "unknown_project" else "Kaggle", "milestones": "score 0.12"})
    assert result.startswith("❌") and json.dumps(goal_store, sort_keys=True) == before


def test_external_goal_claim_still_requires_approval(
    goal_store: dict[str, Any], monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Draft preparation cannot make externally derived goal writes trusted."""
    from langchain_core.messages import ToolMessage
    from core.approval import approval_check_node
    tools = bindings(monkeypatch, "Web_Agent", "create")
    assert "update_goal_milestones_tool" in tools
    before = json.dumps(goal_store, sort_keys=True)
    queued = []
    monkeypatch.setattr("core.approval.save_pending", lambda name, args, *a, **k: queued.append(args))
    monkeypatch.setattr("core.approval._notify_selected_approval", lambda *a, **k: "matrix")
    state = {"messages": [HumanMessage(content="Read this page"),
        ToolMessage(name="browse_url", tool_call_id="source", content="Kaggle score 0.12"),
        HumanMessage(content="Use that update and prepare a draft"),
        AIMessage(content="", tool_calls=[{"name": "update_goal_milestones_tool",
            "args": {"project": "Kaggle", "milestones": "score 0.12"}, "id": "goal-update"}])]}
    assert approval_check_node(state)["approval_status"] == "pending"
    assert queued[0]["external_content_sources_json"] == '["browse_url"]'
    assert json.dumps(goal_store, sort_keys=True) == before
