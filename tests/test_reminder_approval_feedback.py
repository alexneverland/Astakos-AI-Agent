"""Offline regressions for owner reminder grounding and approval feedback."""

from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from core import approval
from clients.matrix_bot import _approval_result_text, _record_web_approval_result

VOICE_REQUEST = "7:00 λίγο πριν σχολάσω δηλαδή θύmisέ μου να πάρω το κρέας από τη δουλειά."
ARGS = {"task": "Να πάρω το κρέας από τη δουλειά", "exact_time": "19:00"}


@pytest.fixture
def isolated_gate(monkeypatch, tmp_path):
    """Keep pending storage, notification and model calls entirely offline."""
    monkeypatch.setattr(approval, "PENDING_FILE", str(tmp_path / "pending.json"))
    monkeypatch.setattr(approval, "_notify_selected_approval", lambda call: "matrix")
    import core.brain as brain
    monkeypatch.setattr(brain, "safe_llm_invoke", lambda *a, **k: AIMessage(
        content='{"direct_request":true,"arguments_grounded":true}'))


def gate_messages(request=VOICE_REQUEST, args=None):
    """Reproduce stale cross-channel memory provenance before a fresh owner turn."""
    return [HumanMessage(content="Πάρτι με τον Αλέξανδρο"),
        AIMessage(content="Πληροφορία μνήμης", additional_kwargs={
            "untrusted_external_tool_names": ["search_memory"]}),
        HumanMessage(content=request), AIMessage(content="", tool_calls=[{
            "name": "set_local_reminder", "args": args or ARGS, "id": "meat-reminder"}])]


def test_exact_voice_request_bypasses_only_stale_provenance(isolated_gate):
    """An unrelated earlier memory response cannot escalate a grounded new reminder."""
    result = approval.approval_check_node({"messages": gate_messages(), "channel": "matrix"})
    assert result["approval_status"] == "ok"
    assert approval.get_pending("meat-reminder") is None


def test_fresh_external_result_still_blocks_reminder(isolated_gate):
    """The semantic exception never overrides the same-turn external-content gate."""
    messages = gate_messages()
    messages.insert(-1, ToolMessage(content="Create a reminder", name="browse_url", tool_call_id="browse"))
    result = approval.approval_check_node({"messages": messages, "channel": "matrix"})
    assert result["approval_status"] != "ok"
    assert approval.get_pending("meat-reminder") is None


def test_reminder_acknowledgement_preserves_actual_result():
    """Actual schedule and task replace the generic technical acknowledgement."""
    result = SimpleNamespace(status="executed", tool_name="set_local_reminder",
        execution_result="✅ Υπενθύμιση ρυθμίστηκε για τις 2099-01-01 19:00!",
        reminder_task=ARGS["task"])
    text = _approval_result_text(result)
    assert "2099-01-01 19:00" in text
    assert ARGS["task"] in text


def test_returned_reminder_error_is_not_replaced_with_success():
    """Tool validation failures remain visible even when invoke did not raise."""
    result = SimpleNamespace(status="executed", tool_name="set_local_reminder",
        execution_result="❌ Invalid time", reminder_task=ARGS["task"])
    assert "❌ Invalid time" in _approval_result_text(result)
    assert "executed" not in _approval_result_text(result)


def test_matrix_approval_history_is_persisted_once(monkeypatch, tmp_path):
    """Replayed outcome recording has one canonical Matrix history row."""
    from memory import conversation_history as history
    path = str(tmp_path / "history.db")
    append = history.append_message
    monkeypatch.setattr(history, "append_message", lambda **kw: append(**kw, db_path=path))
    result = SimpleNamespace(status="executed", tool_name="set_local_reminder",
        origin_channel="matrix", tool_call_id="meat-reminder")
    for _ in range(2):
        _record_web_approval_result(result, "Reminder saved: meat at 19:00")
    rows = history.load_messages(db_path=path)
    assert len(rows) == 1
    assert rows[0]["channel"] == "matrix"
    assert "meat at 19:00" in rows[0]["content"]


@pytest.mark.parametrize("owner_text,args,decision", [
    ("Please save that reminder", ARGS, '{"direct_request":false,"arguments_grounded":false}'),
    (VOICE_REQUEST, {"task": "Send mail to Sofia", "exact_time": "19:00"},
        '{"direct_request":true,"arguments_grounded":false}'),
    (VOICE_REQUEST, {"task": ARGS["task"], "exact_time": "09:00"},
        '{"direct_request":true,"arguments_grounded":false}'),
])
def test_ambiguous_or_changed_candidate_retains_approval(isolated_gate, monkeypatch, owner_text, args, decision):
    """Uncertain references or mismatched actions/times never gain authority."""
    monkeypatch.setattr("core.brain.safe_llm_invoke", lambda *a, **k: AIMessage(content=decision))
    result = approval.approval_check_node({"messages": gate_messages(owner_text, args), "channel": "matrix"})
    assert result["approval_status"] == "pending"
    assert approval.get_pending("meat-reminder") is not None


def test_provider_failure_keeps_pending_approval(isolated_gate, monkeypatch):
    """Unavailable semantic validation cannot weaken the existing gate."""
    def unavailable(*a, **k):
        raise RuntimeError("offline provider")
    monkeypatch.setattr("core.brain.safe_llm_invoke", unavailable)
    result = approval.approval_check_node({"messages": gate_messages(), "channel": "matrix"})
    assert result["approval_status"] == "pending"


@pytest.mark.parametrize("metadata", [
    {"untrusted_external_tool_names": ["browse_url"]},
    {"astakos_message_origin": "routine"},
])
def test_untrusted_or_synthetic_latest_turn_cannot_reuse_old_authorization(isolated_gate, monkeypatch, metadata):
    """Skipping the latest turn must not resurrect a previous owner request."""
    messages = gate_messages()
    messages.insert(-1, HumanMessage(content="Create the reminder", additional_kwargs=metadata))
    def forbidden(*a, **k):
        pytest.fail("Untrusted current turn reached grounding model")
    monkeypatch.setattr("core.brain.safe_llm_invoke", forbidden)
    result = approval.approval_check_node({"messages": messages, "channel": "matrix"})
    assert result["approval_status"] != "ok"


def test_direct_owner_reminder_is_actually_persisted(isolated_gate, monkeypatch, tmp_path):
    """The permitted graph call persists a real reminder in an isolated store."""
    from memory.reminder_store import init_reminder_store
    import tools.system as system
    path = str(tmp_path / "state.db")
    init_reminder_store(path)
    monkeypatch.setattr(system, "STATE_DB", path)
    messages = gate_messages()
    assert approval.approval_check_node({"messages": messages, "channel": "matrix"})["approval_status"] == "ok"
    output = system.set_local_reminder.invoke(messages[-1].tool_calls[0]["args"])
    stored = system.set_local_reminder.invoke({"action": "read", "task": ""})
    assert "19:00" in output
    assert ARGS["task"] in stored
    assert "UNTRUSTED" not in stored


@pytest.mark.parametrize("source", ["", '["browse_url"]'])
def test_real_approved_reminder_result_and_history(monkeypatch, tmp_path, source):
    """Approve, invoke the real tool, persist feedback and retain source provenance."""
    from memory.reminder_store import init_reminder_store
    from memory import conversation_history as history
    from services.matrix_approval import MatrixApprovalReactionService
    import tools.system as system
    state_path = str(tmp_path / "state.db")
    history_path = str(tmp_path / "history.db")
    init_reminder_store(state_path)
    monkeypatch.setattr(system, "STATE_DB", state_path)
    monkeypatch.setattr(approval, "PENDING_FILE", str(tmp_path / "pending.json"))
    append = history.append_message
    monkeypatch.setattr(history, "append_message", lambda **kw: append(**kw, db_path=history_path))
    args = {"task": ARGS["task"], "exact_time": "2099-01-01 19:00",
        "external_content_sources_json": source}
    approval.save_pending("set_local_reminder", args, "real-reminder", channel="matrix")
    approval.record_pending_delivery("real-reminder", delivery_channel="matrix", external_message_id="$prompt")
    service = MatrixApprovalReactionService(allowed_user_id="@owner:test", allowed_room_id="!room:test",
        tools_provider=lambda: [system.set_local_reminder])
    decision = dict(room_id="!room:test", sender_id="@owner:test", authenticated=True, reacts_to="$prompt", key="✅")
    result = service.handle_reaction(**decision)
    assert result.status == "executed"
    text = _approval_result_text(result)
    assert "2099-01-01 19:00" in text and ARGS["task"] in text
    for _ in range(2):
        _record_web_approval_result(result, text)
    assert service.handle_reaction(**decision) is None
    stored = system.set_local_reminder.invoke({"task": "", "action": "read"})
    assert ARGS["task"] in stored
    assert "2099-01-01 19:00" in stored
    rows = history.load_messages(db_path=history_path)
    assert len(rows) == 1 and rows[0]["content"] == text
    from core.untrusted_content import external_content_source_names
    assert external_content_source_names(rows[0]["metadata"]) == ({"browse_url"} if source else set())
