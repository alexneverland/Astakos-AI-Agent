"""Offline regressions for conversational goal updates through bound tools."""

import json
from types import SimpleNamespace
from typing import Any

import pytest
from langchain_core.messages import AIMessage, HumanMessage


@pytest.fixture
def goal_store(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Exercise real goal persistence functions against an in-memory boundary."""
    from memory import vector_store as vs

    record = {
        "document": "[GOAL] Kaggle: Improve submission",
        "metadata": {
            "category": "goal", "project": "Kaggle", "status": "active",
            "progress": 25, "milestones": "Submission score 0.06",
            "created_at": 1700000000.0, "updated_at": 1700000000.0,
            "last_activity_at": 1700000000.0, "goal_events_json": "[]",
        },
    }

    def get(**kwargs: Any) -> dict[str, Any]:
        """Resolve only the existing exact project, as the collection would."""
        conditions = kwargs.get("where", {}).get("$and", [])
        if any("project" in item and item["project"] != "Kaggle" for item in conditions):
            return {"ids": [], "documents": [], "metadatas": []}
        return {"ids": ["goal-1"], "documents": [record["document"]],
                "metadatas": [dict(record["metadata"])]}

    def add_texts(texts: list[str], metadatas: list[dict], **kwargs: Any) -> None:
        """Retain the actual persisted output without embeddings or network."""
        record.update(document=texts[0], metadata=dict(metadatas[0]))

    monkeypatch.setattr(vs, "vector_store", SimpleNamespace(
        _collection=SimpleNamespace(get=get, delete=lambda **kwargs: None),
        add_texts=add_texts,
    ))
    return record


def bound_goal_tools(monkeypatch: pytest.MonkeyPatch, role: str, channel: str,
                     *, diagnosis_only: bool = False) -> dict[str, Any]:
    """Capture real agent bindings with the model and context boundaries offline."""
    import core.agents as agents
    import core.utils as utils

    captured: dict[str, Any] = {}

    class Model:
        """An offline model that exposes no tool execution side effects."""

        def bind_tools(self, tools: list[Any]) -> "Model":
            """Record the tools available to the model."""
            captured.update({tool.name: tool for tool in tools})
            return self

        def invoke(self, messages: list[Any]) -> AIMessage:
            """Do not claim to test provider language inference."""
            return AIMessage(content="Διπλασιασμός στο σκορ, δυνατός.")

    monkeypatch.setattr(agents, "llm", Model())
    monkeypatch.setattr(agents, "llm_heavy", Model())
    monkeypatch.setattr(agents, "build_prompt", lambda *args, **kwargs: "offline")
    monkeypatch.setattr(utils, "build_prompt", lambda *args, **kwargs: "offline")
    monkeypatch.setattr("services.messenger_intent.is_create_draft_intent", lambda *args, **kwargs: False)
    monkeypatch.setattr(agents, "_food_tools_for_latest_user_text", lambda tools, text: tools)
    state = {
        "messages": [
            AIMessage(content="Πώς προχωράει το Kaggle με σκορ 0.06;"),
            HumanMessage(content="Το έχω προχωρήσει φίλε το έφτασα μέχρι 0.12 ακόμα το δουλεύω"),
        ],
        "channel": channel, "bug_diagnosis_read_only": diagnosis_only,
    }
    node = agents.chat_agent_node if role == "Chat_Agent" else agents.dev_agent_node
    node(state)
    return captured


@pytest.mark.parametrize("channel", ["web", "matrix", "telegram"])
@pytest.mark.parametrize("role", ["Chat_Agent", "Dev_Agent"])
def test_score_update_is_persistable_without_resetting_goal(
    monkeypatch: pytest.MonkeyPatch, goal_store: dict[str, Any], role: str, channel: str,
) -> None:
    """A reported score is a milestone, not a percentage or a new goal."""
    tools = bound_goal_tools(monkeypatch, role, channel)
    assert {"save_goal_tool", "update_goal_status_tool", "update_goal_progress_tool",
            "update_goal_milestones_tool"} <= tools.keys()
    result = tools["update_goal_milestones_tool"].invoke({
        "project": "Kaggle", "milestones": "Submission score 0.06; latest score 0.12; still working",
    })
    assert result.startswith("✅")
    meta = goal_store["metadata"]
    assert "0.12" in meta["milestones"]
    assert meta["progress"] == 25
    assert meta["status"] == "active"
    assert meta["created_at"] == 1700000000.0
    assert meta["last_activity_at"] > 1700000000.0
    assert "0.12" in json.loads(meta["goal_events_json"])[-1]["detail"]
    assert goal_store["document"] == "[GOAL] Kaggle: Improve submission"


@pytest.mark.parametrize("role", ["Chat_Agent", "Dev_Agent"])
def test_explicit_completion_percentage_can_be_persisted(
    monkeypatch: pytest.MonkeyPatch, goal_store: dict[str, Any], role: str,
) -> None:
    """The existing percentage updater is usable during both kinds of conversation."""
    tools = bound_goal_tools(monkeypatch, role, "web")
    assert tools["update_goal_progress_tool"].invoke({"project": "Kaggle", "progress": 60}).startswith("✅")
    assert goal_store["metadata"]["progress"] == 60
    assert goal_store["metadata"]["milestones"] == "Submission score 0.06"


def test_goal_update_does_not_create_an_unknown_project(goal_store: dict[str, Any]) -> None:
    """Partial updates must not silently create another goal on identity mistakes."""
    from tools.system import update_goal_milestones_tool

    before = dict(goal_store["metadata"])
    assert update_goal_milestones_tool.invoke({"project": "Unknown", "milestones": "score 0.12"}).startswith("❌")
    assert goal_store["metadata"] == before


def test_read_only_diagnosis_cannot_update_goals(monkeypatch: pytest.MonkeyPatch) -> None:
    """Exposing goal tools to Dev must preserve its read-only investigation boundary."""
    tools = bound_goal_tools(monkeypatch, "Dev_Agent", "matrix", diagnosis_only=True)
    assert not any(name.startswith(("save_goal", "update_goal")) for name in tools)
