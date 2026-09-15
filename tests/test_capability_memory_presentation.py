"""Regression coverage for historical capability-memory presentation."""

from collections.abc import Iterator
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

import core.i18n
import core.utils as utils
from core.ai_provider import EmbeddingsProviderSetupRequired, ProviderAuthError
from core.i18n import load_locale, t
from memory.context_builder import MemoryContext
from core.utils import build_prompt, load_agent_prompt


class MockMessage:
    """Minimal message object accepted by the prompt builder."""

    def __init__(self, content: str) -> None:
        self.content = content


@pytest.fixture(autouse=True)
def restore_locale() -> Iterator[None]:
    """Restore the active locale after each prompt assertion."""
    original_locale = core.i18n.LANG
    yield
    load_locale(original_locale)


def test_prompt_includes_draft_verification_rule_for_historical_memory() -> None:
    """Require a current verification before agents claim a draft exists."""
    load_locale("en")
    with patch("memory.context_builder.build_memory_context") as build_memory_context:
        context = MagicMock()
        context.render.return_value = "[CAPABILITY] Historical world-time draft"
        build_memory_context.return_value = context

        prompt = build_prompt(state_messages=[MockMessage("hello")], agent_role="Chat_Agent")

    assert "[CAPABILITY]" in prompt
    assert t("core.approval.draft_verification_rule") in prompt


def test_prompt_skips_persisted_memory_for_orphan_tool_output(monkeypatch) -> None:
    """A tool result without a user query must not trigger semantic memory."""
    build_memory_context = MagicMock()
    monkeypatch.setattr(
        "memory.context_builder.build_memory_context",
        build_memory_context,
    )

    build_prompt(
        state_messages=[
            SimpleNamespace(
                type="tool",
                content=(
                    "Found 1 matching routines: - ID: 2 | Event: "
                    "Ύπνος Αλέξανδρου | Day: Everyday | Time: 23:00"
                ),
            )
        ],
        agent_role="Home_Agent",
        channel="web",
    )

    build_memory_context.assert_not_called()


def test_prompt_uses_latest_human_query_after_structured_tool_output(
    monkeypatch,
) -> None:
    """Post-tool synthesis rebuilds memory from the user query, not tool prose."""
    context = MemoryContext([], [], ["[USER_FACT] prefers quiet routines"])
    build_memory_context = MagicMock(return_value=context)
    monkeypatch.setattr(
        "memory.context_builder.build_memory_context",
        build_memory_context,
    )
    user_query = "Compare my saved preference with the current routine"

    prompt = build_prompt(
        state_messages=[
            HumanMessage(content=user_query),
            AIMessage(
                content="",
                tool_calls=[{
                    "name": "search_routines",
                    "args": {"event_name": "sleep"},
                    "id": "routine-1",
                }],
            ),
            ToolMessage(
                content="Found 1 matching routine: Sleep at 23:00",
                name="search_routines",
                tool_call_id="routine-1",
            ),
        ],
        agent_role="Home_Agent",
        channel="web",
    )

    assert "prefers quiet routines" in prompt
    build_memory_context.assert_called_once_with(
        user_query,
        channel="web",
        recent_limit=6,
        semantic_k=8,
        write_debug=True,
    )


def test_home_agent_final_post_tool_response_preserves_user_memory(
    monkeypatch,
) -> None:
    """The final agent pass can combine a remembered fact with a tool result."""
    import core.agents as agents

    class BoundLLM:
        def invoke(self, messages: list) -> AIMessage:
            """Return a result that exposes whether memory reached synthesis."""
            system_prompt = messages[0].content
            reply = (
                "Memory and current routine preserved"
                if "prefers quiet routines" in system_prompt
                else "Memory missing"
            )
            return AIMessage(content=reply)

    class FakeLLM:
        def bind_tools(self, _tools: list) -> BoundLLM:
            """Return the offline bound model used by the final agent pass."""
            return BoundLLM()

    monkeypatch.setattr(agents, "llm", FakeLLM())
    monkeypatch.setattr(
        "memory.context_builder.build_memory_context",
        MagicMock(
            return_value=MemoryContext(
                [],
                [],
                ["[USER_FACT] prefers quiet routines"],
            )
        ),
    )
    monkeypatch.setattr(
        "core.agent_tools.get_registered_tools_for_agent",
        lambda _agent, tools: tools,
    )
    state = {
        "channel": "web",
        "messages": [
            HumanMessage(content="Compare my saved preference with the current routine"),
            AIMessage(
                content="",
                tool_calls=[{
                    "name": "search_routines",
                    "args": {"event_name": "sleep"},
                    "id": "routine-1",
                }],
            ),
            ToolMessage(
                content="Found 1 matching routine: Sleep at 23:00",
                name="search_routines",
                tool_call_id="routine-1",
            ),
        ],
    }

    result = agents.home_agent_node(state)

    assert result["messages"][0].content == "Memory and current routine preserved"


def test_prompt_keeps_persisted_memory_for_human_text_that_resembles_tool_output(
    monkeypatch,
) -> None:
    """Tool provenance, not matching prose, controls the memory skip."""
    context = MagicMock()
    context.render.return_value = ""
    build_memory_context = MagicMock(return_value=context)
    monkeypatch.setattr(
        "memory.context_builder.build_memory_context",
        build_memory_context,
    )

    build_prompt(
        state_messages=[
            SimpleNamespace(
                type="human",
                content="Found 1 matching routines in the notes I pasted here",
            )
        ],
        agent_role="Home_Agent",
        channel="web",
    )

    build_memory_context.assert_called_once()


def test_dev_prompt_requires_prefix_and_no_tools_during_proposal() -> None:
    """Keep the capability proposal turn deterministic and non-executing."""
    load_locale("en")
    prompt = build_prompt(state_messages=[MockMessage("hello")], agent_role="Dev_Agent")

    dev_prompt = load_agent_prompt("Dev_Agent")
    assert "You MUST start your response EXACTLY with the localized proposal prefix" in dev_prompt
    assert "CRITICAL: You must NOT call ANY tools during this proposal turn." in prompt


def test_prompt_surfaces_embeddings_setup_once_without_blocking_chat(monkeypatch) -> None:
    """Provider setup failures become one clear user-facing prompt status."""
    utils._embedding_setup_notifications.clear()
    setup_error = EmbeddingsProviderSetupRequired(
        "Configure an embeddings provider.",
        provider="anthropic",
    )
    monkeypatch.setattr(
        "memory.context_builder.build_memory_context",
        MagicMock(side_effect=setup_error),
    )

    first_prompt = build_prompt(
        state_messages=[MockMessage("Πες μου κάτι χρήσιμο")],
        agent_role="Chat_Agent",
        channel="telegram",
    )
    second_prompt = build_prompt(
        state_messages=[MockMessage("Πες μου κάτι χρήσιμο")],
        agent_role="Chat_Agent",
        channel="telegram",
    )

    assert "SEMANTIC MEMORY SETUP REQUIRED" in first_prompt
    assert "Configure an embeddings provider." in first_prompt
    assert "SEMANTIC MEMORY SETUP REQUIRED" not in second_prompt


def test_prompt_surfaces_embeddings_authentication_once_without_blocking_chat(monkeypatch) -> None:
    """Invalid embeddings credentials get one clear status instead of a silent empty search."""
    utils._embedding_setup_notifications.clear()
    auth_error = ProviderAuthError("openai", "OPENAI_API_KEY is not configured.")
    monkeypatch.setattr(
        "memory.context_builder.build_memory_context",
        MagicMock(side_effect=auth_error),
    )

    first_prompt = build_prompt(
        state_messages=[MockMessage("Πες μου κάτι χρήσιμο")],
        agent_role="Chat_Agent",
        channel="telegram",
    )
    second_prompt = build_prompt(
        state_messages=[MockMessage("Πες μου κάτι χρήσιμο")],
        agent_role="Chat_Agent",
        channel="telegram",
    )

    assert "SEMANTIC MEMORY AUTHENTICATION REQUIRED" in first_prompt
    assert "OPENAI_API_KEY is not configured." in first_prompt
    assert "SEMANTIC MEMORY AUTHENTICATION REQUIRED" not in second_prompt
