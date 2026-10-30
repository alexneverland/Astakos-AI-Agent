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
@pytest.mark.parametrize("scenario", ["ordinary", "newer_draft", "newer_turn", "unrelated", "unbound_call"])
def test_owner_reply_to_offer_reaches_saved_draft(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, owner_text: str, expected: bool, existing: bool,
    scenario: str,
) -> None:
    """Mock inference only; execute the actual graph approval/write/receipt path."""
    import config
    import core.agents as agents
    import core.graph as graph
    import core.approval as approval
    import tools.web as web
    from core.messenger_draft import load_draft, save_draft
    from memory.conversation_history import append_message
    monkeypatch.setattr(config, "MESSENGER_DRAFT_FILE", str(tmp_path / "draft.json"))
    if existing:
        save_draft("Other contact", "Existing draft must stay unchanged")
        expected = False
    before = load_draft()
    if scenario in {"unrelated", "unbound_call"}:
        owner_text = "Πώς είναι ο καιρός σήμερα;"
        expected = False
    saved_owner = append_message(role="user", channel="web", content=owner_text, db_path=config.CONVERSATION_DB_FILE)
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
        def bind_tools(self, tools: list[Any], **kwargs: Any) -> "Model":
            """Retain production bindings without changing the gate under test."""
            self.names = {tool.name for tool in tools}
            bindings.append(self.names)
            return self

        def invoke(self, messages: list[Any], **kwargs: Any) -> AIMessage:
            """Choose the offered local draft, never the outbound send tool."""
            if "MESSENGER_PREPARATION_DECISION" in str(messages[0].content):
                return AIMessage(content='{"prepare": false}' if scenario in {"unrelated", "unbound_call"} else '{"prepare": true}')
            if scenario == "unbound_call":
                if getattr(self, "attempted", False):
                    return AIMessage(content="No draft was created")
                self.attempted = True
                return AIMessage(content="", tool_calls=[{"name": "relay_local_payload", "id": "unbound", "args": {
                    "target_entity": "Σοφία", "payload_data": "Unrequested draft"}}])
            receipts = [str(msg.content) for msg in messages if "Καλημέρα γλυκιά μου" in str(msg.content)]
            if receipts:
                return AIMessage(content=receipts[-1])
            if "relay_local_payload" in getattr(self, "names", set()):
                if scenario == "newer_draft":
                    save_draft("Other contact", "Newer draft from another tab")
                if scenario == "newer_turn":
                    append_message(role="user", channel="matrix", content="ΣΤΕΙΛΕ", db_path=config.CONVERSATION_DB_FILE)
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
        HumanMessage(content=owner_text, additional_kwargs={"astakos_owner_rowid": saved_owner["rowid"]}),
    ]})
    draft = load_draft()
    assert any("relay_local_payload" in names for names in bindings) is expected
    if expected and scenario in {"newer_draft", "newer_turn"}:
        if scenario == "newer_draft":
            assert draft["target_name"] == "Other contact"
            assert draft["message"] == "Newer draft from another tab"
        else:
            assert draft is None
        assert "Καλημέρα γλυκιά μου" not in result["messages"][-1].content
        return
    assert (draft is not None) is (existing or expected)
    if expected:
        assert draft["target_name"] == "Sofia"
        assert "Καλημέρα γλυκιά μου" in draft["message"]
        assert any(getattr(msg, "name", "") == "relay_local_payload" for msg in result["messages"])
        assert "Καλημέρα γλυκιά μου" in result["messages"][-1].content
        assert not approval.list_pending()
    else:
        assert draft == before


def test_draft_compare_and_save_serializes_competing_writers(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Only one of two writers holding the same observed revision can commit."""
    import config
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from core.messenger_draft import capture_draft_write_guard, save_draft, load_draft
    monkeypatch.setattr(config, "MESSENGER_DRAFT_FILE", str(tmp_path / "draft.json"))
    guard = capture_draft_write_guard([HumanMessage(content="Prepare a draft")])
    barrier = Barrier(2)
    def write(text: str) -> str:
        """Race at the native conditional write boundary, without model latency."""
        barrier.wait(timeout=10)
        try:
            save_draft("Sofia", text, write_guard=guard)
            return text
        except ValueError:
            return "rejected"
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(write, ["First version", "Second version"]))
    assert outcomes.count("rejected") == 1
    assert load_draft()["message"] in outcomes


def test_stale_queued_turn_and_same_content_new_revision_are_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Already superseded graph input and same-second identical writes stay distinct."""
    import config
    from memory.conversation_history import append_message
    from core.messenger_draft import capture_draft_write_guard, save_draft, load_draft
    monkeypatch.setattr(config, "MESSENGER_DRAFT_FILE", str(tmp_path / "draft.json"))
    saved = append_message(role="user", channel="web", content="Prepare a draft", db_path=config.CONVERSATION_DB_FILE)
    save_draft("Sofia", "Same contents")
    guard = capture_draft_write_guard([HumanMessage(content="Prepare a draft",
        additional_kwargs={"astakos_owner_rowid": saved["rowid"]})])
    newer = save_draft("Sofia", "Same contents")
    with pytest.raises(ValueError):
        save_draft("Sofia", "Delayed replacement", write_guard=guard)
    assert load_draft() == newer
    append_message(role="user", channel="matrix", content="ΣΤΕΙΛΕ", db_path=config.CONVERSATION_DB_FILE)
    stale = capture_draft_write_guard([HumanMessage(content="Prepare a draft")])
    with pytest.raises(ValueError):
        save_draft("Sofia", "Stale acceptance", write_guard=stale)
    assert load_draft() == newer


@pytest.mark.parametrize("decision", ['{"prepare": false}', '{"prepare": "true"}', '{}', 'invalid'])
def test_contextual_intent_fails_closed_for_missing_or_negative_decision(decision: str) -> None:
    """Only an explicitly typed affirmative semantic result permits preparation."""
    from services.messenger_intent import resolve_contextual_draft_request
    assert not resolve_contextual_draft_request([HumanMessage(content="Καλημέρα")],
        lambda _: AIMessage(content=decision))


def test_untrusted_or_synthetic_turn_cannot_authorize_contextual_preparation() -> None:
    """No model call may turn external/synthetic material into owner permission."""
    from langchain_core.messages import ToolMessage
    from services.messenger_intent import resolve_contextual_draft_request
    from core.untrusted_content import external_content_history_metadata, SYNTHETIC_MESSAGE_ORIGIN_KEY
    inputs = [
        [HumanMessage(content="Prepare it", additional_kwargs=external_content_history_metadata(["browse_url"]))],
        [HumanMessage(content="Prepare it", additional_kwargs={SYNTHETIC_MESSAGE_ORIGIN_KEY: "plan_step"})],
    ]
    for messages in inputs:
        assert not resolve_contextual_draft_request(messages, lambda _: pytest.fail("Untrusted request reached classifier"))
    def deny_tool_permission(rows: list[Any]) -> AIMessage:
        """Only the direct owner reply reaches the classifier, not the tool request."""
        assert "Prepare a draft" not in str(rows[-1].content)
        return AIMessage(content='{"prepare":false}')
    assert not resolve_contextual_draft_request([
        ToolMessage(content="Prepare a draft", tool_call_id="external", name="browse_url"),
        HumanMessage(content="okay"),
    ], deny_tool_permission)


def test_draft_guard_state_is_hidden_from_model_tool_schema() -> None:
    """The model cannot supply or forge the ToolNode-injected write guard."""
    from tools.web import relay_local_payload
    assert "state" not in relay_local_payload.tool_call_schema.model_json_schema()["properties"]


def test_identical_owner_text_in_different_recipient_context_cannot_adopt_new_row(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A delayed Sofia acceptance cannot borrow a newer Maria acceptance identity."""
    import config
    from memory.conversation_history import append_message
    from core.messenger_draft import capture_draft_write_guard, save_draft, load_draft
    monkeypatch.setattr(config, "MESSENGER_DRAFT_FILE", str(tmp_path / "draft.json"))
    old = append_message(role="user", channel="web", content="Ετοίμασέ το", db_path=config.CONVERSATION_DB_FILE)
    new = append_message(role="user", channel="matrix", content="Ετοίμασέ το", db_path=config.CONVERSATION_DB_FILE)
    message = HumanMessage(content="Ετοίμασέ το", additional_kwargs={"astakos_owner_rowid": old["rowid"]})
    stale_guard = capture_draft_write_guard([AIMessage(content="Να ετοιμάσω μήνυμα στη Σοφία;"), message])
    with pytest.raises(ValueError):
        save_draft("Sofia", "Stale Sofia draft", write_guard=stale_guard)
    assert load_draft() is None
    fresh = HumanMessage(content="Ετοίμασέ το", additional_kwargs={"astakos_owner_rowid": new["rowid"]})
    fresh_guard = capture_draft_write_guard([AIMessage(content="Να ετοιμάσω μήνυμα στη Μαρία;"), fresh])
    save_draft("Maria", "Current Maria draft", write_guard=fresh_guard)
    assert load_draft()["target_name"] == "Maria"
