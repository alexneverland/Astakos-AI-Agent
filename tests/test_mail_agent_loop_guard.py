from types import SimpleNamespace

from langchain_core.messages import HumanMessage, ToolMessage, AIMessage, SystemMessage


def test_mail_agent_synthesizes_after_mail_tool_results(monkeypatch):
    """Loop guard: uses clean 2-msg prompt with embedded results, NOT sanitize_history."""
    import core.agents as agents

    class NoToolsLLM:
        def bind_tools(self, tools):
            raise AssertionError("Mail_Agent should not bind tools after mail results exist")

    calls = []

    def fake_safe_llm(llm, messages):
        calls.append(messages)
        return SimpleNamespace(content="Diagnostika to Kaggle mail kai sou ekana perilipsi.")

    monkeypatch.setattr(agents, "llm", NoToolsLLM())
    monkeypatch.setattr(agents, "safe_llm_invoke", fake_safe_llm)

    result = agents.mail_agent_node(
        {
            "messages": [
                HumanMessage(content="irthe neo mail diabase"),
                ToolMessage(
                    content="ID: 123 | Apo: Kaggle <no-reply@kaggle.com> | Thema: Day 1",
                    tool_call_id="mail-search",
                ),
            ],
            "channel": "web",
        }
    )

    assert result["current_agent"] == "Mail_Agent"
    # 2-msg prompt: [System, Human]
    assert len(calls[0]) == 2
    assert isinstance(calls[0][0], SystemMessage)
    assert isinstance(calls[0][1], HumanMessage)
    # Mail results embedded in system prompt
    assert "ID: 123" in calls[0][0].content


def test_mail_agent_falls_back_to_raw_when_llm_returns_tool_call_string(monkeypatch):
    """If LLM still outputs '[...Ergaleiou...' as text, raw results are used."""
    import core.agents as agents

    class NoToolsLLM:
        def bind_tools(self, tools):
            raise AssertionError("should not bind tools")

    def fake_safe_llm(llm, messages):
        return SimpleNamespace(content="[Klisi Ergaleiou: mail_manager]")

    monkeypatch.setattr(agents, "llm", NoToolsLLM())
    monkeypatch.setattr(agents, "safe_llm_invoke", fake_safe_llm)

    result = agents.mail_agent_node(
        {
            "messages": [
                HumanMessage(content="des an irthe kati"),
                ToolMessage(
                    content="ID: 456 | Apo: test@example.com | Thema: Test",
                    tool_call_id="mail-search",
                ),
            ],
            "channel": "web",
        }
    )

    assert result["current_agent"] == "Mail_Agent"
    final = result["messages"][0].content
    assert final.startswith("\U0001f4e9"), f"Expected emoji prefix fallback, got: {final!r}"
    assert "ID: 456" in final


def test_mail_agent_allows_read_when_only_prev_turn_has_search(monkeypatch):
    """
    Cross-turn guard: ToolMessage from prev turn should NOT block a new action.
    If the current human message has no tool results after it, agent should call tools.
    """
    import core.agents as agents

    bind_calls = []
    invoke_calls = []

    class MockLLM:
        def bind_tools(self, tools):
            bind_calls.append(tools)
            return self

        def invoke(self, messages):
            invoke_calls.append(messages)
            # Return a tool call response (agent wants to read the email)
            return SimpleNamespace(
                content="",
                tool_calls=[{"name": "mail_manager", "id": "tc1", "args": {"action": "read", "email_id": "123"}}],
            )

    def fake_safe_llm(llm, messages):
        invoke_calls.append(messages)
        return SimpleNamespace(
            content="",
            tool_calls=[{"name": "mail_manager", "id": "tc1", "args": {"action": "read", "email_id": "123"}}],
        )

    monkeypatch.setattr(agents, "llm", MockLLM())
    monkeypatch.setattr(agents, "safe_llm_invoke", fake_safe_llm)

    # History: prev turn's HumanMessage + ToolMessage + AIMessage, then NEW HumanMessage
    result = agents.mail_agent_node(
        {
            "messages": [
                # Turn 1 (old)
                HumanMessage(content="irthe neo mail"),
                AIMessage(content="Vrika to: ID 123 Kaggle. Thes na to diavaso?",
                          tool_calls=[]),
                ToolMessage(content="ID: 123 | Kaggle | Day 1", tool_call_id="old-search"),
                AIMessage(content="Vrika to: ID 123 Kaggle. Thes na to diavaso?"),
                # Turn 2 (current) — NO tool results yet after this human msg
                HumanMessage(content="nai diabase to oloklirotiko"),
            ],
            "channel": "web",
        }
    )

    # Agent should have BOUND tools (not synthesized from old results)
    assert bind_calls, "Agent should have called bind_tools for the new read action"
