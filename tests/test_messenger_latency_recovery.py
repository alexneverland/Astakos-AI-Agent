"""Use native graph/store outcomes for repeated preparation recovery."""
from langchain_core.messages import AIMessage
import pytest

from tests.test_messenger_lifecycle_regression import lifecycle, owner_messages
from tests.test_routine_completion_web import client, _post_chat


@pytest.fixture(autouse=True)
def offline_transport(monkeypatch):
    """Block external sockets, retaining Windows asyncio's loopback wakeup pipe."""
    import socket
    original = socket.socket.connect

    def connect(sock, address):
        if isinstance(address, tuple) and address[0] in {"127.0.0.1", "::1", "localhost"}:
            return original(sock, address)
        raise AssertionError("Outbound transport forbidden")

    monkeypatch.setattr(socket.socket, "connect", connect)


def test_web_owner_copy_is_queued_before_context_inference(client, tmp_path, monkeypatch):
    """Slow clarification must not delay persisting the owner's display copy."""
    from memory.conversation_history import append_message, load_pending_web_mirrors, load_messages
    from services.routine_context_clarification import QuestionAnswer
    path = str(tmp_path / "mirror.db")

    def save(role, content, **kwargs):
        return append_message(role=role, content=content, channel="web", db_path=path,
                              mirror_target=kwargs.get("mirror_target"), metadata=kwargs.get("metadata"))

    def classify(*args, **kwargs):
        queued = load_pending_web_mirrors("matrix", db_path=path)
        assert len(queued) == 1 and queued[0]["role"] == "user"
        assert queued[0]["content"] == "Synthetic context reply"
        return QuestionAnswer(True, "resolved")

    monkeypatch.setattr("core.messaging_channel.resolve_external_channel", lambda: "matrix")
    monkeypatch.setattr("services.routine_context_clarification.try_context_question_reply", classify)
    response, _ = _post_chat(client, message="Synthetic context reply", history_writer=save)
    assert response.status_code == 200
    rows = load_messages(db_path=path)
    assert [r["role"] for r in rows] == ["user", "assistant"]
    assert response.json()["user_rowid"] == rows[0]["rowid"]


@pytest.mark.parametrize("timeout", [False, True])
def test_project_update_does_not_reclassify_after_goal_tool(lifecycle, monkeypatch, timeout):
    """The reported score reply should resolve intent once across tool execution."""
    from core.messenger_draft import load_draft
    env = lifecycle
    import core.brain as brain
    monkeypatch.setattr(brain, "_effective_provider_name", "vertex")
    monkeypatch.setattr(env["agents"], "invoke_messenger_decision", brain.invoke_messenger_decision)
    decisions = []
    saved = []

    class Model:
        """Model emits a harmless local tool before the final project reply."""
        main_passes = 0
        def bind_tools(self, *args, **kwargs):
            return self

        def invoke(self, rows, **kwargs):
            if "MESSENGER_PREPARATION_DECISION" in str(rows[0].content):
                decisions.append(kwargs)
                if timeout:
                    raise TimeoutError("synthetic provider timeout")
                return AIMessage(content='{"prepare":false}')
            assert kwargs == {}  # Main generation does not inherit helper options.
            self.main_passes += 1
            if self.main_passes > 1:
                return AIMessage(content="The score is still pending.")
            return AIMessage(content="", tool_calls=[{"name": "update_goal_milestones_tool",
                "id": "goal-demo", "args": {"project": "Demo", "milestones": "Still running"}}])

    from tools.system import update_goal_milestones_tool
    monkeypatch.setattr(update_goal_milestones_tool, "func", lambda **kwargs: saved.append(kwargs) or "updated")
    monkeypatch.setattr(env["graph"], "all_tools", [update_goal_milestones_tool])
    monkeypatch.setattr(env["agents"], "llm", Model())
    result = env["graph"].build_graph().invoke({"channel": "web",
        "messages": owner_messages(env, "ακομα δεν εχει βγει το σκορ")})
    assert result["messages"][-1].content == "The score is still pending."
    assert len(saved) == 1
    assert len(decisions) == 1
    assert decisions[0]["timeout"] == 15
    assert decisions[0]["max_retries"] == 1
    assert not load_draft() and not env["approval"].list_pending()


@pytest.mark.parametrize("change", ["owner", "draft"])
def test_decision_cache_cannot_cross_owner_or_draft_changes(lifecycle, monkeypatch, change):
    from services.messenger_lifecycle import recover_preparation_reason
    env = lifecycle
    cache = {}
    decisions = []
    rows = owner_messages(env, "The demo project is still running")

    def invoke(messages):
        decisions.append(1)
        return AIMessage(content='{"prepare":false}')

    response = AIMessage(content="Still pending")
    assert recover_preparation_reason(rows, response, None, invoke, decision_cache=cache) is None
    assert recover_preparation_reason(rows, response, None, invoke, decision_cache=cache) is None
    assert len(decisions) == 1
    if change == "draft":
        draft = env["save"]("Demo", "New draft")
        draft["status"] = "sent"
        import json
        from pathlib import Path
        Path(env["config"].MESSENGER_DRAFT_FILE).write_text(json.dumps(draft), encoding="utf-8")
    else:
        rows = owner_messages(env, "The demo project has a new result")
    recover_preparation_reason(rows, response, None, invoke, decision_cache=cache)
    assert len(decisions) == 2


def test_new_candidate_can_recover_a_missed_mixed_request(lifecycle):
    """Caching cannot suppress later recovery from a genuinely new candidate."""
    from services.messenger_lifecycle import recover_preparation_reason
    env = lifecycle
    cache = {}
    rows = owner_messages(env, "Prepare a greeting for the demo contact and update the project")
    calls = []

    def invoke(messages):
        calls.append(1)
        return AIMessage(content='{"prepare":false}' if len(calls) == 1 else '{"prepare":true}')

    assert recover_preparation_reason(rows, AIMessage(content="Updating the project"), None, invoke,
                                     decision_cache=cache) is None
    assert recover_preparation_reason(rows, AIMessage(content="Here is the greeting draft"), None, invoke,
                                     decision_cache=cache) == "response_grounded_preparation"
    assert len(calls) == 2


def test_google_preparation_uses_native_single_attempt_request_budget(monkeypatch):
    """Inspect the installed SDK request, replacing only its network boundary."""
    from langchain_google_genai import ChatGoogleGenerativeAI
    from langchain_core.messages import HumanMessage
    from core.brain import invoke_messenger_decision
    monkeypatch.setattr("core.brain._effective_provider_name", "vertex")
    model = ChatGoogleGenerativeAI(model="gemini-demo", api_key="synthetic-unused")
    captured = []

    def invoke(self, rows, **kwargs):
        request = self._prepare_request(rows, **kwargs)
        captured.append(request["config"].http_options)
        return AIMessage(content='{"prepare":false}')

    monkeypatch.setattr(ChatGoogleGenerativeAI, "invoke", invoke)
    assert invoke_messenger_decision(model, [HumanMessage(content="Synthetic update")]).content
    assert captured[0].timeout == 15000
    assert captured[0].retry_options.attempts == 1


@pytest.mark.parametrize("provider", ["openai", "anthropic"])
def test_non_google_request_budget_does_not_override_sdk_retry_policy(monkeypatch, provider):
    from core.brain import invoke_messenger_decision
    from types import SimpleNamespace
    monkeypatch.setattr("core.brain._effective_provider_name", provider)
    options = []

    def invoke(messages, **kwargs):
        options.append(kwargs)
        return AIMessage(content='{"prepare":false}')

    invoke_messenger_decision(SimpleNamespace(invoke=invoke), [])
    assert options == [{"timeout": 15.0}]


def test_mirror_reports_queue_age_separately_from_transport_duration(tmp_path, monkeypatch, capsys):
    """A slow queue is distinguishable from a slow network send without text logs."""
    import json
    from datetime import datetime
    from memory.conversation_history import append_message
    from services import web_mirror_delivery as delivery
    from services.external_delivery import ExternalDeliveryRouter
    path = str(tmp_path / "mirror.db")
    queued_at = datetime(2030, 1, 15, 10, 0)
    append_message(role="user", content="PRIVATE DISPLAY TEXT", channel="web",
                   mirror_target="matrix", timestamp=queued_at, db_path=path)
    clock = [20.0]
    monkeypatch.setattr(delivery.time, "time", lambda: queued_at.timestamp() + 300)
    monkeypatch.setattr(delivery.time, "monotonic", lambda: clock[0])

    class Transport:
        def send_text(self, text, *, silent=False):
            clock[0] += 2
            return "$offline-copy"

    router = ExternalDeliveryRouter(channel_selector=lambda: "matrix")
    router.register("matrix", Transport())
    assert delivery.drain_web_mirrors("matrix", router=router, db_path=path) == 1
    lines = capsys.readouterr().out
    rows = [json.loads(line.removeprefix("[WebMirror]: ")) for line in lines.splitlines()
            if line.startswith('[WebMirror]: {')]
    assert rows[0]["queue_age_ms"] == 300000
    assert rows[-1]["duration_ms"] == 2000
    assert rows[-1]["event"] == "mirror_delivered"
    assert "PRIVATE DISPLAY TEXT" not in lines
