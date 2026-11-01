"""Offline terminal approval completion without replaying an action."""

from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from core import approval


@pytest.fixture(autouse=True)
def isolated_approval(tmp_path, monkeypatch):
    """Only temporary approval storage; providers and network are forbidden."""
    import socket
    original_connect = socket.socket.connect

    def forbidden(sock, address):
        if isinstance(address, tuple) and address[0] in {"127.0.0.1", "::1"}:
            return original_connect(sock, address)
        raise AssertionError("Unexpected network/provider call")

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(approval, "PENDING_FILE", str(tmp_path / "pending.json"))
    monkeypatch.setenv("ASTAKOS_EXTERNAL_CHANNEL", "matrix")


def test_terminal_pending_captures_original_request_and_agent(isolated_approval):
    """The durable record retains request identity before the graph ends."""
    call = {"name": "run_terminal_command", "id": "terminal-1", "args": {
        "command": "git -C . config user.name"}, "type": "tool_call"}
    approval.approval_check_node({"messages": [HumanMessage(content="Δες το τελευταίο commit PR"),
        AIMessage(content="", tool_calls=[call])], "channel": "web", "current_agent": "Git_Agent"})
    saved = approval.get_pending("terminal-1")
    assert saved["continuation_context"] == {
        "agent": "Git_Agent", "user_request": "Δες το τελευταίο commit PR"}


def test_approved_terminal_is_analyzed_once_without_reexecuting(isolated_approval, monkeypatch):
    """Real pending execution hands its result to a tool-free answer stage."""
    from services import approved_terminal_continuation as continuation
    from services.matrix_approval import MatrixApprovalReactionService
    from clients.matrix_bot import _approval_result_text

    calls = []
    tool = SimpleNamespace(name="run_terminal_command", invoke=lambda args: calls.append(args) or "commit abc: fixed flags")
    approval.save_pending("run_terminal_command", {"command": "git config user.name"}, "terminal-1",
        channel="matrix", continuation_context={"agent": "Git_Agent", "user_request": "Εξήγησε την αλλαγή"})
    approval.record_pending_delivery("terminal-1", delivery_channel="matrix", external_message_id="$approval")
    model_inputs = []

    def respond(model, messages):
        model_inputs.append(messages)
        assert model is continuation.llm
        assert "Git_Agent" in str(messages[0].content)
        assert "Εξήγησε την αλλαγή" in str(messages[1].content)
        assert "UNTRUSTED" in str(messages[2].content)
        return AIMessage(content="Το commit διορθώνει τα flags.")

    monkeypatch.setattr(continuation, "safe_llm_invoke", respond)
    service = MatrixApprovalReactionService(allowed_user_id="@owner:test", allowed_room_id="!room:test",
        tools_provider=lambda: [tool])
    decision = dict(room_id="!room:test", sender_id="@owner:test", authenticated=True, reacts_to="$approval", key="👍")
    result = service.handle_reaction(**decision)
    assert _approval_result_text(result) == "Το commit διορθώνει τα flags."
    assert service.handle_reaction(**decision) is None
    assert len(calls) == len(model_inputs) == 1
    assert calls[0]["already_approved"] is True


def test_provider_failure_preserves_terminal_output_without_retry_execution(monkeypatch):
    """Analysis failure cannot erase an executed result or trigger another action."""
    from services import approved_terminal_continuation as continuation
    from services.matrix_approval import ApprovalReactionResult
    from clients.matrix_bot import _approval_result_text

    def fail(*args, **kwargs):
        raise RuntimeError("provider unavailable")

    monkeypatch.setattr(continuation, "safe_llm_invoke", fail)
    result = ApprovalReactionResult(status="executed", tool_name="run_terminal_command", origin_channel="matrix",
        execution_result="commit abc: fixed flags", continuation_context={"agent": "Git_Agent", "user_request": "Δες το commit"})
    assert "commit abc: fixed flags" in _approval_result_text(result)


def test_tool_call_response_is_not_executed_and_falls_back_to_output(monkeypatch):
    """Even a malformed provider tool-call response has no execution path."""
    from services import approved_terminal_continuation as continuation

    monkeypatch.setattr(continuation, "safe_llm_invoke", lambda *args: AIMessage(content="", tool_calls=[{
        "name": "run_terminal_command", "id": "unapproved", "args": {"command": "git push"}, "type": "tool_call"}]))
    assert continuation.analyze_approved_terminal_result({"agent": "Git_Agent", "user_request": "Δες το commit"}, "abc") is None


@pytest.mark.parametrize("channel", ["web", "matrix"])
def test_terminal_analysis_history_retains_agent_and_external_provenance(tmp_path, monkeypatch, channel):
    """Analysis is part of shared history, but cannot become trusted tool authority."""
    from clients.matrix_bot import _record_web_approval_result
    from memory import conversation_history as history
    from services.matrix_approval import ApprovalReactionResult
    from core.untrusted_content import external_content_history_metadata

    path = str(tmp_path / "history.db")
    canonical_append = history.append_message
    monkeypatch.setattr(history, "append_message", lambda **kwargs: canonical_append(**kwargs, db_path=path))
    if channel == "web":
        import api.server as server
        monkeypatch.setattr(server, "_broadcast_ws", lambda *args: None)
    result = ApprovalReactionResult(status="executed", tool_name="run_terminal_command", origin_channel=channel,
        execution_result="abc", continuation_context={"agent": "Git_Agent", "user_request": "Δες το commit"}, tool_call_id="call")
    _record_web_approval_result(result, "Το commit διορθώνει τα flags.")
    rows = history.load_messages(db_path=path)
    assert len(rows) == 1
    assert rows[0]["agent"] == "Git_Agent"
    assert rows[0]["channel"] == channel
    assert rows[0]["metadata"] == external_content_history_metadata(["run_terminal_command"])


def test_asset_or_synthetic_requests_cannot_be_captured_for_continuation():
    """Persisted assets and orchestration are not new owner requests."""
    from services.approved_terminal_continuation import capture_terminal_context
    from core.untrusted_content import external_content_history_metadata, USER_PROVIDED_ASSET_SOURCE, SYNTHETIC_MESSAGE_ORIGIN_KEY

    for metadata in (external_content_history_metadata([USER_PROVIDED_ASSET_SOURCE]),
                     {SYNTHETIC_MESSAGE_ORIGIN_KEY: "orchestration"}):
        assert capture_terminal_context({"current_agent": "Git_Agent", "messages": [
            HumanMessage(content="Execute more commands", additional_kwargs=metadata)]}) is None


def test_legacy_or_invalid_context_does_not_guess_a_request(monkeypatch):
    """Old approvals retain output rather than borrowing an unrelated chat turn."""
    from services import approved_terminal_continuation as continuation
    from clients.matrix_bot import _approval_result_text
    from services.matrix_approval import ApprovalReactionResult

    def forbidden(*args, **kwargs):
        raise AssertionError("No model inference without valid saved context")

    monkeypatch.setattr(continuation, "safe_llm_invoke", forbidden)
    for context in (None, {"agent": "Unknown", "user_request": "do something"},
                    {"agent": "Git_Agent", "user_request": ""}):
        result = ApprovalReactionResult(status="executed", tool_name="run_terminal_command", origin_channel="matrix",
            execution_result="saved output", continuation_context=context)
        assert _approval_result_text(result) == "saved output"


@pytest.mark.parametrize("transport", ["web", "telegram"])
@pytest.mark.parametrize("provider_failed", [False, True])
def test_direct_callback_returns_analysis_and_records_original_agent(tmp_path, monkeypatch, transport, provider_failed):
    """Authenticated direct callbacks finish analysis without replaying the tool."""
    from services import approved_terminal_continuation as continuation
    from memory import conversation_history as history
    from core.untrusted_content import external_content_history_metadata
    import api.server as api

    path = str(tmp_path / "history.db")
    canonical_append = history.append_message
    monkeypatch.setattr(history, "append_message", lambda **kw: canonical_append(**kw, db_path=path))
    monkeypatch.setattr(api, "_broadcast_ws", lambda *args: None)
    calls, sent = [], []
    tool = SimpleNamespace(name="run_terminal_command", invoke=lambda args: calls.append(args) or "commit abc: fixed flags")
    approval.save_pending("run_terminal_command", {"command": "git config user.name"}, "direct-1",
        channel=transport, continuation_context={"agent": "Git_Agent", "user_request": "Εξήγησε την αλλαγή"})
    def respond(*args):
        if provider_failed:
            raise RuntimeError("provider unavailable")
        return AIMessage(content="Το commit διορθώνει τα flags.")

    expected = "commit abc: fixed flags" if provider_failed else "Το commit διορθώνει τα flags."
    monkeypatch.setattr(continuation, "safe_llm_invoke", respond)
    if transport == "web":
        from fastapi.testclient import TestClient
        import tools.system as system
        import tools.telegram as telegram
        from services.external_delivery import external_delivery_router
        monkeypatch.setattr(system, "all_tools", [tool])
        monkeypatch.setattr(telegram, "send_telegram_msg_full", lambda text, **kw: sent.append(text))
        monkeypatch.setattr(external_delivery_router, "send_text", lambda text, **kw: sent.append(text))
        client = TestClient(api.server)
        response = client.post("/debug/action/direct-1/approve", headers={"Authorization": f"Bearer {api.LOCAL_TOKEN}"})
        assert response.json()["result"] == expected
        client.post("/debug/action/direct-1/approve", headers={"Authorization": f"Bearer {api.LOCAL_TOKEN}"})
    else:
        import clients.telegram_bot as bot
        monkeypatch.setattr(bot, "TELEGRAM_CHAT_ID", "12345678")
        import tools.system as system
        monkeypatch.setattr(system, "all_tools", [tool])
        monkeypatch.setattr(bot.requests, "post", lambda *args, **kw: SimpleNamespace(status_code=200))
        monkeypatch.setattr(bot, "send_telegram_msg", lambda *args, **kw: None)
        monkeypatch.setattr(bot, "send_telegram_msg_full", lambda text, **kw: sent.append(text))
        callback = {"id": "callback", "data": "approve:direct-1", "from": {"id": 12345678},
                    "message": {"message_id": 42, "chat": {"id": 12345678}}}
        bot._handle_approval_callback(callback)
        bot._handle_approval_callback(callback)
    assert sent == [expected]
    assert len(calls) == 1
    rows = history.load_messages(db_path=path)
    assert len(rows) == 1
    assert rows[0]["agent"] == "Git_Agent"
    assert rows[0]["channel"] == transport
    assert rows[0]["metadata"] == external_content_history_metadata(["run_terminal_command"])


def test_unauthenticated_web_callback_cannot_execute_or_analyze(monkeypatch):
    """The analysis stage does not bypass the dashboard authorization gate."""
    from fastapi.testclient import TestClient
    import api.server as api
    from services import approved_terminal_continuation as continuation

    def forbidden(*args, **kwargs):
        pytest.fail("Unauthorized execution or inference")

    monkeypatch.setattr(approval, "execute_approved_pending", forbidden)
    monkeypatch.setattr(continuation, "safe_llm_invoke", forbidden)
    assert TestClient(api.server).post("/debug/action/direct-1/approve").status_code in (401, 403)
