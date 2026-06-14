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
        return SimpleNamespace(content="Διάβασα το Kaggle mail και σου έκανα περίληψη.")

    monkeypatch.setattr(agents, "llm", NoToolsLLM())
    monkeypatch.setattr(agents, "safe_llm_invoke", fake_safe_llm)

    result = agents.mail_agent_node(
        {
            "messages": [
                HumanMessage(content="ηρθε νεο μαιλ διαβασε"),
                ToolMessage(
                    content="ID: 123 | Από: Kaggle <no-reply@kaggle.com> | Θέμα: Day 1",
                    tool_call_id="mail-search",
                ),
            ],
            "channel": "web",
        }
    )

    assert result["current_agent"] == "Mail_Agent"
    assert result["messages"][0].content == "Διάβασα το Kaggle mail και σου έκανα περίληψη."

    # New: 2-msg prompt [System, Human] — no sanitized history
    assert len(calls[0]) == 2, f"Expected 2 messages, got {len(calls[0])}"
    assert isinstance(calls[0][0], SystemMessage)
    assert isinstance(calls[0][1], HumanMessage)
    # Mail results must be embedded directly in the system prompt
    assert "ID: 123" in calls[0][0].content, "Mail results must be in system prompt"


def test_mail_agent_falls_back_to_raw_when_llm_returns_tool_call_string(monkeypatch):
    """If LLM still outputs '[Κλήση Εργαλείου:' as text, raw results are used."""
    import core.agents as agents

    class NoToolsLLM:
        def bind_tools(self, tools):
            raise AssertionError("should not bind tools")

    def fake_safe_llm(llm, messages):
        return SimpleNamespace(content="[Κλήση Εργαλείου: mail_manager]")

    monkeypatch.setattr(agents, "llm", NoToolsLLM())
    monkeypatch.setattr(agents, "safe_llm_invoke", fake_safe_llm)

    result = agents.mail_agent_node(
        {
            "messages": [
                HumanMessage(content="δες αν ηρθε κατι"),
                ToolMessage(
                    content="ID: 456 | Από: test@example.com | Θέμα: Test",
                    tool_call_id="mail-search",
                ),
            ],
            "channel": "web",
        }
    )

    assert result["current_agent"] == "Mail_Agent"
    final = result["messages"][0].content
    # Should fall back to raw mail result, not the tool-call string
    assert final.startswith("\U0001f4e9"), f"Expected emoji prefix fallback, got: {final!r}"
    assert "ID: 456" in final
