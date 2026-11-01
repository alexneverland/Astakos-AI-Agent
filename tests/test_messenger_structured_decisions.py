"""Messenger semantic decisions retain answer blocks through native graph writes."""
import json
from pathlib import Path
from typing import Any

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from tests.test_messenger_lifecycle_regression import lifecycle, owner_messages

REQUEST = "ο συνεργατης Demo ειναι στο γραφειο, στειλε ενα φιλικο μηνυμα για τη δοκιμαστικη συναντηση που συζητησαμε"
DRAFT = "Καλημέρα Demo! Επιβεβαιώνω τη δοκιμαστική συνάντηση. Καλή συνέχεια!"
pytestmark = pytest.mark.usefixtures("offline_behavioral_io")


def decision(value: str, shape: str) -> AIMessage:
    """Build actual provider-shaped LangChain answers, including split strings."""
    if shape == "scalar":
        return AIMessage(content=value)
    split = len(value)//2
    parts = [value] if shape == "blocks" else [value[:split], value[split:]]
    return AIMessage(content=[{"type": "text", "text": part} for part in parts])


@pytest.mark.parametrize("shape", ["scalar", "blocks", "split"])
def test_reported_request_persists_draft_then_send_requires_approval(
    lifecycle: dict[str, Any], monkeypatch: pytest.MonkeyPatch, shape: str,
) -> None:
    """Routine acknowledgement cannot substitute for a native draft and approval."""
    from core.messenger_draft import load_draft
    from services.routine_completion_context import build_dated_routine_feedback_context
    from services.routine_feedback_turn import FeedbackTurnResult
    from services.routine_completion_helper import DatedRoutineSelection
    from datetime import date
    env = lifecycle
    monkeypatch.setattr("tools.web._load_messenger_contacts", lambda: {"demo": "test-recipient"})
    old = env["save"]("test-recipient", "Previously sent synthetic message")
    old["status"] = "sent"
    Path(env["config"].MESSENGER_DRAFT_FILE).write_text(json.dumps(old), encoding="utf-8")
    monkeypatch.setattr(env["graph"], "supervisor_node", lambda state: {"next_agent": "Web_Agent"})
    notified = []
    monkeypatch.setattr(env["approval"], "_notify_selected_approval", lambda *args: notified.append(args))

    class Model:
        """Synthesize prose first; only required preparation returns the real tool."""
        forced = False
        send_turn = False

        def bind_tools(self, tools: list[Any], **kwargs: Any) -> "Model":
            """Record whether native draft creation is required for this call."""
            self.forced = kwargs.get("tool_choice") == "relay_local_payload"
            return self

        def invoke(self, rows: list[Any]) -> AIMessage:
            """Return synthetic decisions or the required local draft tool call."""
            first = str(rows[0].content)
            if "MESSENGER_PREPARATION_DECISION" in first:
                return decision('{"prepare":false}' if self.send_turn else '{"prepare":true}', shape)
            if "MESSENGER_LIFECYCLE_DECISION" in first:
                return decision('{"action":"send"}', shape)
            if self.send_turn:
                return AIMessage(content="", tool_calls=[{"name":"execute_local_pipeline", "id":"send-reviewed", "args":{}}])
            if not self.send_turn:
                return AIMessage(content="", tool_calls=[{"name": "relay_local_payload", "id": "saved-tender",
                    "args": {"target_entity": "Demo", "payload_data": DRAFT}}])
            return AIMessage(content=f"Προτεινόμενο μήνυμα: «{DRAFT}» Θέλεις να το στείλω;")

    model = Model()
    monkeypatch.setattr(env["agents"], "llm", model)
    messages = owner_messages(env, REQUEST)
    messages[0] = AIMessage(content="Είναι διαθέσιμος ο Demo ή να ετοιμάσω το μήνυμα για τη δοκιμή;")
    messages.insert(0, build_dated_routine_feedback_context(FeedbackTurnResult("applied",
        DatedRoutineSelection("acknowledge", 101, date(2030, 1, 15)), routine_name="Δοκιμαστικό μήνυμα στον Demo")))
    result = env["graph"].build_graph().invoke({"channel": "web", "messages": messages})
    draft = load_draft()
    assert draft["revision"] != old["revision"]
    assert draft["message"] == DRAFT and draft["status"] == "pending"
    assert DRAFT in result["messages"][-1].content
    assert not notified and not env["approval"].list_pending()
    # A new trusted send turn must approve the actual new revision, never yesterday's.
    send = owner_messages(env, "Εγκρίνω το δοκιμαστικό κείμενο, προχώρησε στην αποστολή")[-1]
    model.forced = False
    model.send_turn = True
    result = env["graph"].build_graph().invoke({"channel": "web",
        "messages": [*messages, AIMessage(content=DRAFT), send]})
    pending = env["approval"].list_pending()
    assert len(pending) == 1
    assert pending[0]["tool_name"] == "execute_local_pipeline"
    assert draft["revision"] in json.dumps(pending)
    assert load_draft()["status"] == "pending"
    # Web may queue delivery to Element instead of notifying synchronously.
    assert notified or pending[0].get("delivery_status") == "queued"


@pytest.mark.parametrize("resolver", ["prepare", "lifecycle"])
@pytest.mark.parametrize("kind", ["reasoning", "tool_result", "unknown"])
def test_non_answer_text_never_authorizes_action(resolver: str, kind: str) -> None:
    """Valid decision JSON in non-answer text remains data, never permission."""
    from services.messenger_intent import resolve_pending_draft_action
    from services.messenger_lifecycle import primary_preparation_result
    messages = [HumanMessage(content=REQUEST)]
    response = AIMessage(content=[{"type": kind, "text": '{"prepare":true}' if resolver == "prepare" else '{"action":"send"}'}])
    if resolver == "prepare":
        assert primary_preparation_result({}, messages, response)[1] is False
    else:
        assert resolve_pending_draft_action(messages, {"status": "pending", "message": DRAFT}, lambda rows: response) == "none"


@pytest.mark.parametrize("resolver", ["prepare", "lifecycle"])
@pytest.mark.parametrize("case", ["untrusted", "malformed", "wrong_type"])
def test_invalid_decision_or_untrusted_owner_fails_closed(resolver: str, case: str) -> None:
    """Block shape support must not widen the owner or decision-value protocol."""
    from services.messenger_intent import resolve_pending_draft_action
    from services.messenger_lifecycle import primary_preparation_result
    messages = [HumanMessage(content=REQUEST, additional_kwargs={
        "untrusted_external_tool_names": ["browse_url"]} if case == "untrusted" else {})]
    text = ('{"prepare":true}' if resolver == "prepare" else '{"action":"send"}')
    if case == "malformed":
        text = "not JSON"
    elif case == "wrong_type":
        text = '{"prepare":"true"}' if resolver == "prepare" else '{"action":true}'
    calls = []

    def invoke(rows: list[Any]) -> AIMessage:
        """Track inference to distinguish provenance rejection from parsing."""
        calls.append(True)
        return decision(text, "blocks")

    if resolver == "prepare":
        assert primary_preparation_result({}, messages, invoke(messages))[1] is False
    else:
        assert resolve_pending_draft_action(messages, {"status": "pending", "message": DRAFT}, invoke) == "none"
    assert bool(calls) is (resolver == "prepare" or case != "untrusted")


@pytest.mark.parametrize("action", ["send", "retire", "none"])
def test_fragmented_lifecycle_answer_retains_exact_action(action: str) -> None:
    """The same canonical decision parser supports all lifecycle outcomes."""
    from services.messenger_intent import resolve_pending_draft_action
    response = decision(json.dumps({"action": action}), "split")
    assert resolve_pending_draft_action([HumanMessage(content="Owner request")],
        {"status": "pending", "message": DRAFT}, lambda rows: response) == action
