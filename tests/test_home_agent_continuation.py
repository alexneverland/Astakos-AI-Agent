"""Behavioral regression coverage for Home-Agent brief continuations."""

from __future__ import annotations

from types import SimpleNamespace

from langchain_core.messages import AIMessage, HumanMessage


class _BoundLLM:
    """Capture bound tools and return the configured Home-Agent response."""

    def __init__(self, tools: list, response: AIMessage) -> None:
        self.tools = tools
        self._response = response

    def invoke(self, _messages: list) -> AIMessage:
        """Return the deterministic response without contacting a provider."""
        return self._response


class _HomeLLM:
    """Offline Home-Agent LLM double for continuation and tool-binding tests."""

    def __init__(self, decision: object, response: AIMessage) -> None:
        self._decision = decision
        self._response = response
        self.bound_tools: list[list] = []

    def with_structured_output(self, _schema: object) -> object:
        """Return a structured-output double for the continuation resolver."""
        return SimpleNamespace(invoke=lambda _prompt: self._decision)

    def bind_tools(self, tools: list) -> _BoundLLM:
        """Record available tools before returning a deterministic bound LLM."""
        self.bound_tools.append(tools)
        return _BoundLLM(tools, self._response)


def _prepare_home_agent(monkeypatch, decision: object, response: AIMessage) -> _HomeLLM:
    """Patch Home-Agent dependencies for deterministic continuation behavior tests."""
    import core.agents as agents

    fake_llm = _HomeLLM(decision, response)
    monkeypatch.setattr(agents, "llm", fake_llm)
    monkeypatch.setattr(agents, "build_prompt", lambda _history, base, **_kwargs: base)
    monkeypatch.setattr(agents, "sanitize_history_for_gemini", lambda history: history)
    monkeypatch.setattr(agents, "_ensure_text_response", lambda response, *_args: response)
    monkeypatch.setattr(agents, "_food_tools_for_latest_user_text", lambda tools, *_args: tools)
    monkeypatch.setattr(
        "core.agent_tools.get_registered_tools_for_agent",
        lambda _agent, tools: tools,
    )
    return fake_llm


def test_ambiguous_brief_followup_cannot_reopen_completed_routine(monkeypatch) -> None:
    """Several or no unresolved actions force clarification with no bound mutation tools."""
    import core.agents as agents

    decision = agents.HomeContinuationDecision(outcome="clarify")
    fake_llm = _prepare_home_agent(
        monkeypatch,
        decision,
        AIMessage(content="Ποια ενέργεια εννοείς να συνεχίσω;"),
    )
    state = {
        "channel": "telegram",
        "messages": [
            HumanMessage(content="Άλλαξε τις routines ποδοσφαίρου."),
            AIMessage(content="Έγινε, οι routines ενεργοποιήθηκαν."),
            HumanMessage(content="Βάλε"),
        ],
    }

    result = agents.home_agent_node(state)

    assert result["messages"][0].content == "Ποια ενέργεια εννοείς να συνεχίσω;"
    assert fake_llm.bound_tools == [[]]


def test_single_unresolved_brief_followup_keeps_reminder_tool_available(monkeypatch) -> None:
    """One semantically resolved pending action may continue without reviving routines."""
    import core.agents as agents

    decision = agents.HomeContinuationDecision(
        outcome="single_unresolved",
        action_summary="create the requested local package reminder at 18:05",
    )
    fake_llm = _prepare_home_agent(
        monkeypatch,
        decision,
        AIMessage(content="", tool_calls=[{
            "name": "set_local_reminder",
            "args": {"action": "add", "task": "Package pickup", "exact_time": "18:05"},
            "id": "reminder-add",
        }]),
    )
    state = {
        "channel": "telegram",
        "messages": [
            HumanMessage(content="Θύμισέ μου στις 18:05 να πάρω το δέμα."),
            AIMessage(content="Δεν ολοκληρώθηκε ακόμη η υπενθύμιση."),
            HumanMessage(content="Βάλε"),
        ],
    }

    result = agents.home_agent_node(state)

    assert result["messages"][0].tool_calls[0]["name"] == "set_local_reminder"
    assert {tool.name for tool in fake_llm.bound_tools[0]} >= {"set_local_reminder"}
