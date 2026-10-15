"""Owner continuation reaches the real Web draft tool and native persistence."""
from typing import Any
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage, HumanMessage

pytestmark = pytest.mark.usefixtures("offline_behavioral_io")


@pytest.mark.parametrize("owner_text,expected", [
    ("ΕΤΟΙΜΑΣΕ ΕΝΑ ΚΑΛΗΜΕΡΑ ΩΡΑΙΟ ΦΙΛΕ", True),
    ("ΣΤΕΙΛΕ", False),
])
@pytest.mark.parametrize("existing", [False, True])
def test_owner_reply_to_offer_reaches_saved_draft(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, owner_text: str, expected: bool, existing: bool,
) -> None:
    """Mock inference only; execute the actual graph approval/write/receipt path."""
    import config
    import core.agents as agents
    import core.graph as graph
    import core.approval as approval
    import tools.web as web
    from core.messenger_draft import load_draft, save_draft
    monkeypatch.setattr(config, "MESSENGER_DRAFT_FILE", str(tmp_path / "draft.json"))
    if existing:
        save_draft("Other contact", "Existing draft must stay unchanged")
        expected = False
    before = load_draft()
    monkeypatch.setattr(approval, "PENDING_FILE", str(tmp_path / "pending.json"))
    monkeypatch.setattr(web, "_load_messenger_contacts", lambda: {"σοφια": "Sofia"})
    monkeypatch.setattr(agents, "build_prompt", lambda *a, **k: "offline")
    monkeypatch.setattr("core.utils.build_prompt", lambda *a, **k: "offline")
    monkeypatch.setattr(agents, "_food_tools_for_latest_user_text", lambda tools, text: tools)
    monkeypatch.setattr("core.agent_tools.get_registered_tools_for_agent", lambda name, tools: tools)
    monkeypatch.setattr(approval, "_notify_selected_approval", lambda *a: pytest.fail("No extra draft approval"))
    bindings = []

    class Model:
        """Provider decision conditional on actual tool availability."""
        def bind_tools(self, tools: list[Any]) -> "Model":
            """Retain production bindings without changing the gate under test."""
            self.names = {tool.name for tool in tools}
            bindings.append(self.names)
            return self

        def invoke(self, messages: list[Any]) -> AIMessage:
            """Choose the offered local draft, never the outbound send tool."""
            receipts = [str(msg.content) for msg in messages if "Καλημέρα γλυκιά μου" in str(msg.content)]
            if receipts:
                return AIMessage(content=receipts[-1])
            if "relay_local_payload" in getattr(self, "names", set()):
                return AIMessage(content="", tool_calls=[{"name": "relay_local_payload", "id": "draft", "args": {
                    "target_entity": "Σοφία", "payload_data": "Καλημέρα γλυκιά μου! Καλή δύναμη στη δουλειά."}}])
            return AIMessage(content="Ορίστε μια πρόταση, να τη στείλουμε;")

    monkeypatch.setattr(agents, "llm", Model())
    monkeypatch.setattr(graph, "all_tools", [web.relay_local_payload])
    monkeypatch.setattr(graph, "pre_check_node", lambda state: {"next_agent": "supervisor"})
    monkeypatch.setattr(graph, "supervisor_node", lambda state: {"next_agent": "Web_Agent"})
    result = graph.build_graph().invoke({"channel": "web", "messages": [
        HumanMessage(content="Για το πρωινό μήνυμα στη Σοφία"),
        AIMessage(content="Θες να της ετοιμάσω κανένα μήνυμα για καλημέρα ή το αφήνουμε;"),
        HumanMessage(content=owner_text),
    ]})
    draft = load_draft()
    assert (draft is not None) is (existing or expected)
    assert ("relay_local_payload" in bindings[0]) is expected
    if expected:
        assert draft["target_name"] == "Sofia"
        assert "Καλημέρα γλυκιά μου" in draft["message"]
        assert any(getattr(msg, "name", "") == "relay_local_payload" for msg in result["messages"])
        assert "Καλημέρα γλυκιά μου" in result["messages"][-1].content
        assert not approval.list_pending()
    else:
        assert draft == before
