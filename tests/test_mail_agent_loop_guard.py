from types import SimpleNamespace

from langchain_core.messages import HumanMessage, ToolMessage


def test_mail_agent_synthesizes_after_mail_tool_results(monkeypatch):
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
                ToolMessage(
                    content="📩 Περιεχόμενο: Kaggle Hi Lazaros, Today's Assignments...",
                    tool_call_id="mail-read",
                ),
            ],
            "channel": "web",
        }
    )

    assert result["current_agent"] == "Mail_Agent"
    assert result["messages"][0].content == "Διάβασα το Kaggle mail και σου έκανα περίληψη."
    assert "ΑΠΑΓΟΡΕΥΕΤΑΙ να καλέσεις άλλο εργαλείο" in calls[0][0].content
