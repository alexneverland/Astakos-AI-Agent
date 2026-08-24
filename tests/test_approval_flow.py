"""
Tests for the approval flow — save/get/resolve/pop pending + is_critical routing.
No live Telegram required.
"""
import sys, os, json, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock
import pytest


# -- Pending store (save/get/pop/list) ----------------------------

def _make_approval_with_tmp():
    """Returns the approval module with a temp file instead of the real pending file."""
    import core.approval as ap
    return ap

def test_save_and_get_pending(tmp_path):
    pending_file = str(tmp_path / "pending.json")
    with patch("core.approval.PENDING_FILE", pending_file):
        from core.approval import save_pending, get_pending
        save_pending("github_manager", {"repo": "astakos"}, "call-123")
        item = get_pending("call-123")
        assert item is not None
        assert item["tool_name"] == "github_manager"
        assert item["status"] == "pending"

def test_resolve_pending_approved(tmp_path):
    pending_file = str(tmp_path / "pending.json")
    with patch("core.approval.PENDING_FILE", pending_file):
        from core.approval import save_pending, resolve_pending, get_pending
        save_pending("mail_manager", {}, "call-456")
        resolve_pending("call-456", approved=True)
        item = get_pending("call-456")
        assert item["status"] == "approved"

def test_resolve_pending_rejected(tmp_path):
    pending_file = str(tmp_path / "pending.json")
    with patch("core.approval.PENDING_FILE", pending_file):
        from core.approval import save_pending, resolve_pending, get_pending
        save_pending("mail_manager", {}, "call-789")
        resolve_pending("call-789", approved=False)
        item = get_pending("call-789")
        assert item["status"] == "rejected"

def test_pop_pending_removes_item(tmp_path):
    pending_file = str(tmp_path / "pending.json")
    with patch("core.approval.PENDING_FILE", pending_file):
        from core.approval import save_pending, pop_pending, get_pending
        save_pending("github_manager", {}, "call-pop")
        item = pop_pending("call-pop")
        assert item is not None
        assert get_pending("call-pop") is None

def test_list_pending_only_returns_pending_status(tmp_path):
    pending_file = str(tmp_path / "pending.json")
    with patch("core.approval.PENDING_FILE", pending_file):
        from core.approval import save_pending, resolve_pending, list_pending
        save_pending("github_manager", {}, "p1")
        save_pending("mail_manager", {}, "p2")
        resolve_pending("p2", approved=True)
        pending = list_pending()
        ids = [p["tool_call_id"] for p in pending]
        assert "p1" in ids
        assert "p2" not in ids  # approved — is not displayed


# -- is_critical routing ------------------------------------------

def test_critical_tool_blocked_in_node():
    """approval_check_node with CRITICAL tool → approval_status=pending."""
    from core.approval import approval_check_node
    from langchain_core.messages import AIMessage

    ai_msg = MagicMock()
    ai_msg.tool_calls = [{"name": "github_manager", "args": {}, "id": "tc-1"}]

    with patch("core.approval.save_pending"), \
         patch("core.approval._notify_telegram"):
        result = approval_check_node({"messages": [ai_msg]})
        assert result["approval_status"] == "pending"

def test_safe_tool_passes_through():
    """approval_check_node with SAFE tool → approval_status=ok."""
    from core.approval import approval_check_node

    ai_msg = MagicMock()
    ai_msg.tool_calls = [{"name": "search_memory", "args": {}, "id": "tc-2"}]

    result = approval_check_node({"messages": [ai_msg]})
    assert result["approval_status"] == "ok"

def test_execute_local_pipeline_without_active_draft_does_not_request_approval(monkeypatch, tmp_path):
    """No active Messenger draft -> no Telegram approval prompt."""
    import config
    from core.approval import approval_check_node

    monkeypatch.setattr(config, "MESSENGER_DRAFT_FILE", str(tmp_path / "missing.json"))

    ai_msg = MagicMock()
    ai_msg.tool_calls = [{"name": "execute_local_pipeline", "args": {}, "id": "tc-send"}]

    with patch("core.approval.save_pending") as save_pending, \
         patch("core.approval._notify_telegram") as notify:
        result = approval_check_node({"messages": [ai_msg]})

    assert result["approval_status"] == "ok"
    save_pending.assert_not_called()
    notify.assert_not_called()


def test_execute_local_pipeline_with_active_draft_requests_approval(monkeypatch, tmp_path):
    """Active Messenger draft -> send remains CRITICAL."""
    import config
    from core.approval import approval_check_node

    draft_file = tmp_path / "messenger_draft.json"
    monkeypatch.setattr(config, "MESSENGER_DRAFT_FILE", str(draft_file))
    draft_file.write_text(
        json.dumps(
            {
                "target_name": "Sofia",
                "message": "hello",
                "status": "pending",
                "created_at": datetime.now().isoformat(timespec="seconds"),
                "expires_at": (datetime.now() + timedelta(minutes=30)).isoformat(timespec="seconds"),
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    ai_msg = MagicMock()
    ai_msg.tool_calls = [{"name": "execute_local_pipeline", "args": {}, "id": "tc-send"}]

    with patch("core.approval.save_pending") as save_pending, \
         patch("core.approval._notify_telegram") as notify:
        result = approval_check_node({"messages": [ai_msg]})

    assert result["approval_status"] == "pending"
    save_pending.assert_called_once()
    notify.assert_called_once()


def test_explicit_messenger_draft_creation_skips_stale_external_approval():
    """A requested draft remains reviewable even with stale external provenance."""
    from langchain_core.messages import AIMessage, HumanMessage
    from core.approval import approval_check_node
    from core.untrusted_content import external_content_history_metadata

    external_reply = AIMessage(
        content="A prior news summary.",
        additional_kwargs=external_content_history_metadata(["get_news"]),
    )
    user_message = HumanMessage(content="Ναι φίλε φτιάξε ένα μήνυμα")
    draft_call = AIMessage(
        content="",
        tool_calls=[{
            "name": "relay_local_payload",
            "args": {"target_entity": "Sofia", "payload_data": "Καλημέρα"},
            "id": "tc-draft",
        }],
    )

    with patch("core.approval.save_pending") as save_pending, \
         patch("core.approval._notify_telegram") as notify:
        result = approval_check_node({
            "messages": [external_reply, user_message, draft_call],
        })

    assert result["approval_status"] == "ok"
    save_pending.assert_not_called()
    notify.assert_not_called()


def test_accepted_routine_offer_draft_creation_skips_stale_external_approval():
    """A trusted accepted routine offer may create its reviewable draft."""
    from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
    from core.approval import approval_check_node
    from core.untrusted_content import external_content_history_metadata
    from services.messenger_intent import MESSENGER_ROUTINE_DRAFT_OFFER_MARKER

    external_reply = AIMessage(
        content="A prior news summary.",
        additional_kwargs=external_content_history_metadata(["get_news"]),
    )
    offer_context = SystemMessage(content=MESSENGER_ROUTINE_DRAFT_OFFER_MARKER)
    user_message = HumanMessage(content="ναι")
    draft_call = AIMessage(
        content="",
        tool_calls=[{
            "name": "relay_local_payload",
            "args": {"target_entity": "Sofia", "payload_data": "Καλημέρα"},
            "id": "tc-routine-draft",
        }],
    )

    with patch("core.approval.save_pending") as save_pending, \
         patch("core.approval._notify_telegram") as notify:
        result = approval_check_node({
            "messages": [external_reply, offer_context, user_message, draft_call],
        })

    assert result["approval_status"] == "ok"
    save_pending.assert_not_called()
    notify.assert_not_called()


def test_explicit_draft_creation_stays_blocked_after_same_turn_external_result():
    """A same-turn external result cannot authorize a requested draft write."""
    from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
    from core.approval import approval_check_node

    user_message = HumanMessage(content="Ναι φίλε φτιάξε ένα μήνυμα")
    external_result = ToolMessage(
        content="Untrusted page content.",
        name="get_news",
        tool_call_id="tc-news",
    )
    draft_call = AIMessage(
        content="",
        tool_calls=[{
            "name": "relay_local_payload",
            "args": {"target_entity": "Sofia", "payload_data": "Καλημέρα"},
            "id": "tc-draft",
        }],
    )

    with patch("core.approval.save_pending") as save_pending, \
         patch("core.approval._notify_telegram") as notify:
        result = approval_check_node({
            "messages": [user_message, external_result, draft_call],
        })

    assert result["approval_status"] == "blocked"
    save_pending.assert_not_called()
    notify.assert_not_called()


def test_negated_draft_request_stays_approval_gated_with_stale_external_history():
    """A negated draft request cannot bypass stale external-content approval."""
    from langchain_core.messages import AIMessage, HumanMessage
    from core.approval import approval_check_node
    from core.untrusted_content import external_content_history_metadata

    external_reply = AIMessage(
        content="A prior news summary.",
        additional_kwargs=external_content_history_metadata(["get_news"]),
    )
    user_message = HumanMessage(content="Μην φτιάξεις ένα μήνυμα")
    draft_call = AIMessage(
        content="",
        tool_calls=[{
            "name": "relay_local_payload",
            "args": {"target_entity": "Sofia", "payload_data": "Καλημέρα"},
            "id": "tc-negated-draft",
        }],
    )

    with patch("core.approval.save_pending") as save_pending, \
         patch("core.approval._notify_telegram") as notify:
        result = approval_check_node({
            "messages": [external_reply, user_message, draft_call],
        })

    assert result["approval_status"] == "pending"
    save_pending.assert_called_once()
    notify.assert_called_once()


def test_descriptive_message_stays_approval_gated_with_stale_external_history():
    """A message mention without a draft request cannot bypass stale-context approval."""
    from langchain_core.messages import AIMessage, HumanMessage
    from core.approval import approval_check_node
    from core.untrusted_content import external_content_history_metadata

    external_reply = AIMessage(
        content="A prior news summary.",
        additional_kwargs=external_content_history_metadata(["get_news"]),
    )
    user_message = HumanMessage(content="I received a message from Alice")
    draft_call = AIMessage(
        content="",
        tool_calls=[{
            "name": "relay_local_payload",
            "args": {"target_entity": "Sofia", "payload_data": "Καλημέρα"},
            "id": "tc-descriptive-message",
        }],
    )

    with patch("core.approval.save_pending") as save_pending, \
         patch("core.approval._notify_telegram") as notify:
        result = approval_check_node({
            "messages": [external_reply, user_message, draft_call],
        })

    assert result["approval_status"] == "pending"
    save_pending.assert_called_once()
    notify.assert_called_once()


def test_provenance_marked_human_message_cannot_bypass_draft_approval():
    """Asset analysis stored in a HumanMessage is not direct draft authorization."""
    from langchain_core.messages import AIMessage, HumanMessage
    from core.approval import approval_check_node
    from core.untrusted_content import external_content_history_metadata

    user_message = HumanMessage(
        content="Write a message",
        additional_kwargs=external_content_history_metadata(["user_provided_asset"]),
    )
    draft_call = AIMessage(
        content="",
        tool_calls=[{
            "name": "relay_local_payload",
            "args": {"target_entity": "Sofia", "payload_data": "Καλημέρα"},
            "id": "tc-provenance-marked-draft",
        }],
    )

    with patch("core.approval.save_pending") as save_pending, \
         patch("core.approval._notify_telegram") as notify:
        result = approval_check_node({"messages": [user_message, draft_call]})

    assert result["approval_status"] == "pending"
    save_pending.assert_called_once()
    notify.assert_called_once()


def test_blocked_terminal_command_is_not_saved_for_approval():
    """BLOCKED terminal command → approval_status=blocked and pending is not saved."""
    from core.approval import approval_check_node

    ai_msg = MagicMock()
    ai_msg.tool_calls = [{
        "name": "run_terminal_command",
        "args": {"command": "rm -rf /"},
        "id": "tc-blocked",
    }]

    with patch("core.approval.save_pending") as save_pending, \
         patch("core.approval._notify_telegram") as notify:
        result = approval_check_node({"messages": [ai_msg]})

    assert result["approval_status"] == "blocked"
    save_pending.assert_not_called()
    notify.assert_not_called()

def test_no_tool_calls_passes_through():
    """approval_check_node without tool calls → approval_status=ok."""
    from core.approval import approval_check_node

    ai_msg = MagicMock()
    ai_msg.tool_calls = []

    result = approval_check_node({"messages": [ai_msg]})
    assert result["approval_status"] == "ok"
def test_accepted_routine_offer_draft_creation_skips_same_turn_memory_read_block():
    """A routine-approved draft survives an incidental untrusted memory read."""
    from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
    from core.approval import approval_check_node
    from services.messenger_intent import MESSENGER_ROUTINE_DRAFT_OFFER_MARKER

    offer_context = SystemMessage(content=MESSENGER_ROUTINE_DRAFT_OFFER_MARKER)
    user_message = HumanMessage(content="yes, prepare the draft")
    memory_result = ToolMessage(
        content="[UNTRUSTED EXTERNAL TOOL RESULT] persisted memory reference",
        name="search_memory",
        tool_call_id="tc-memory-read",
    )
    draft_call = AIMessage(
        content="",
        tool_calls=[{
            "name": "relay_local_payload",
            "args": {"target_entity": "Sofia", "payload_data": "Hello"},
            "id": "tc-routine-draft-after-read",
        }],
    )

    with (
        patch("core.approval.save_pending") as save_pending,
        patch("core.approval._notify_telegram") as notify,
    ):
        result = approval_check_node({
            "messages": [offer_context, user_message, memory_result, draft_call],
        })

    assert result["approval_status"] == "ok"
    save_pending.assert_not_called()
    notify.assert_not_called()


def test_routine_draft_state_authorization_survives_missing_system_marker():
    """Telegram's trusted per-run authorization survives context truncation."""
    from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
    from core.approval import approval_check_node

    user_message = HumanMessage(content="ναι φίλε γράψε")
    memory_result = ToolMessage(
        content="[UNTRUSTED EXTERNAL TOOL RESULT] persisted memory reference",
        name="search_memory",
        tool_call_id="tc-memory-read",
    )
    draft_call = AIMessage(
        content="",
        tool_calls=[{
            "name": "relay_local_payload",
            "args": {"target_entity": "Sofia", "payload_data": "Καλημέρα"},
            "id": "tc-routine-draft-state",
        }],
    )

    with (
        patch("core.approval.save_pending") as save_pending,
        patch("core.approval._notify_telegram") as notify,
    ):
        result = approval_check_node({
            "messages": [user_message, memory_result, draft_call],
            "routine_draft_offer_authorized": True,
        })

    assert result["approval_status"] == "ok"
    assert result.get("routine_draft_offer_authorized") is None
    save_pending.assert_not_called()
    notify.assert_not_called()


def test_routine_draft_authorization_is_consumed_only_after_successful_write():
    """A failed relay leaves the one-shot authorization available for correction."""
    from langchain_core.messages import AIMessage, ToolMessage
    from core.approval import consume_successful_routine_draft_authorization

    tool_call = AIMessage(
        content="",
        tool_calls=[{"name": "relay_local_payload", "args": {}, "id": "tc-draft"}],
    )
    failed_write = ToolMessage(
        content="❌ Δεν αποθήκευσα Messenger draft. Η εικόνα δεν βρέθηκε.",
        name="relay_local_payload",
        tool_call_id="tc-draft",
    )
    successful_write = ToolMessage(
        content="✅ DRAFT ΑΠΟΘΗΚΕΥΤΗΚΕ.\nmessage: Καλημέρα",
        name="relay_local_payload",
        tool_call_id="tc-draft",
    )
    state = {"routine_draft_offer_authorized": True, "messages": [tool_call, failed_write]}

    assert consume_successful_routine_draft_authorization(state) == {}
    state["messages"][-1] = successful_write
    assert consume_successful_routine_draft_authorization(state) == {
        "routine_draft_offer_authorized": False,
    }


def test_routine_draft_authorization_consumes_if_any_relay_in_batch_succeeds():
    """A later failed relay cannot preserve authority after an earlier success."""
    from langchain_core.messages import AIMessage, ToolMessage
    from core.approval import consume_successful_routine_draft_authorization

    tool_call = AIMessage(
        content="",
        tool_calls=[
            {"name": "relay_local_payload", "args": {}, "id": "tc-first"},
            {"name": "relay_local_payload", "args": {}, "id": "tc-second"},
        ],
    )
    success = ToolMessage(
        content="✅ DRAFT ΑΠΟΘΗΚΕΥΤΗΚΕ.\nmessage: Καλημέρα",
        name="relay_local_payload",
        tool_call_id="tc-first",
    )
    failure = ToolMessage(
        content="❌ Δεν αποθήκευσα Messenger draft. Η εικόνα δεν βρέθηκε.",
        name="relay_local_payload",
        tool_call_id="tc-second",
    )

    assert consume_successful_routine_draft_authorization({
        "routine_draft_offer_authorized": True,
        "messages": [tool_call, success, failure],
    }) == {"routine_draft_offer_authorized": False}


def test_active_draft_edit_after_untrusted_read_requires_isolated_context(monkeypatch, tmp_path):
    """A draft revision after a read needs the agent's isolated-context proof."""
    import config
    from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
    from core.approval import approval_check_node

    draft_file = tmp_path / "messenger_draft.json"
    monkeypatch.setattr(config, "MESSENGER_DRAFT_FILE", str(draft_file))
    draft_file.write_text(
        json.dumps(
            {
                "target_name": "Sofia",
                "message": "Παλιό μήνυμα",
                "status": "pending",
                "created_at": datetime.now().isoformat(timespec="seconds"),
                "expires_at": (datetime.now() + timedelta(minutes=30)).isoformat(timespec="seconds"),
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    user_message = HumanMessage(content="Άλλαξε το μήνυμα και κάν' το πιο σύντομο")
    memory_result = ToolMessage(
        content="[UNTRUSTED EXTERNAL TOOL RESULT] persisted memory reference",
        name="search_memory",
        tool_call_id="tc-memory-read",
    )
    draft_call = AIMessage(
        content="",
        tool_calls=[{
            "name": "relay_local_payload",
            "args": {"target_entity": "Sofia", "payload_data": "Νέο σύντομο μήνυμα"},
            "id": "tc-active-draft-edit",
        }],
    )

    with (
        patch("core.approval.save_pending") as save_pending,
        patch("core.approval._notify_telegram") as notify,
    ):
        result = approval_check_node({
            "messages": [user_message, memory_result, draft_call],
        })

    assert result["approval_status"] == "blocked"
    save_pending.assert_not_called()
    notify.assert_not_called()


def test_active_draft_edit_after_untrusted_read_allows_isolated_context(monkeypatch, tmp_path):
    """An isolated direct revision remains approval-free after a memory read."""
    import config
    from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
    from core.approval import approval_check_node

    draft_file = tmp_path / "messenger_draft.json"
    monkeypatch.setattr(config, "MESSENGER_DRAFT_FILE", str(draft_file))
    draft_file.write_text(
        json.dumps(
            {
                "target_name": "Sofia",
                "message": "Παλιό μήνυμα",
                "status": "pending",
                "created_at": datetime.now().isoformat(timespec="seconds"),
                "expires_at": (datetime.now() + timedelta(minutes=30)).isoformat(timespec="seconds"),
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    user_message = HumanMessage(content="Άλλαξε το μήνυμα και κάν' το πιο σύντομο")
    memory_result = ToolMessage(
        content="[UNTRUSTED EXTERNAL TOOL RESULT] persisted memory reference",
        name="search_memory",
        tool_call_id="tc-memory-read",
    )
    draft_call = AIMessage(
        content="",
        tool_calls=[{
            "name": "relay_local_payload",
            "args": {"target_entity": "Sofia", "payload_data": "Νέο σύντομο μήνυμα"},
            "id": "tc-active-draft-edit",
        }],
    )

    with (
        patch("core.approval.save_pending") as save_pending,
        patch("core.approval._notify_telegram") as notify,
    ):
        result = approval_check_node({
            "messages": [user_message, memory_result, draft_call],
            "active_draft_edit_context_isolated": True,
        })

    assert result["approval_status"] == "ok"
    save_pending.assert_not_called()
    notify.assert_not_called()


def test_active_draft_edit_history_excludes_external_messages():
    """Draft revision prompts retain only trusted conversation messages."""
    from langchain_core.messages import HumanMessage, ToolMessage
    from core.agents import _isolate_active_draft_edit_history
    from core.untrusted_content import external_content_history_metadata

    trusted_user_message = HumanMessage(content="Άλλαξε το μήνυμα")
    external_tool_result = ToolMessage(
        content="untrusted reference",
        name="search_memory",
        tool_call_id="tc-memory-read",
    )
    provenance_marked_message = HumanMessage(
        content="external image analysis",
        additional_kwargs=external_content_history_metadata(["user_provided_asset"]),
    )

    assert _isolate_active_draft_edit_history([
        trusted_user_message,
        external_tool_result,
        provenance_marked_message,
    ]) == [trusted_user_message]


def test_active_draft_edit_cannot_change_target_after_memory_read(monkeypatch, tmp_path):
    """Untrusted content cannot redirect a direct revision to another contact."""
    import config
    from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
    from core.approval import approval_check_node

    draft_file = tmp_path / "messenger_draft.json"
    monkeypatch.setattr(config, "MESSENGER_DRAFT_FILE", str(draft_file))
    draft_file.write_text(
        json.dumps(
            {
                "target_name": "Sofia",
                "message": "Παλιό μήνυμα",
                "status": "pending",
                "created_at": datetime.now().isoformat(timespec="seconds"),
                "expires_at": (datetime.now() + timedelta(minutes=30)).isoformat(timespec="seconds"),
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    user_message = HumanMessage(content="Άλλαξε το μήνυμα και κάν' το πιο σύντομο")
    memory_result = ToolMessage(
        content="[UNTRUSTED EXTERNAL TOOL RESULT] persisted memory reference",
        name="search_memory",
        tool_call_id="tc-memory-read",
    )
    draft_call = AIMessage(
        content="",
        tool_calls=[{
            "name": "relay_local_payload",
            "args": {"target_entity": "Alex", "payload_data": "Νέο μήνυμα"},
            "id": "tc-draft-target-change",
        }],
    )

    with (
        patch("core.approval.save_pending") as save_pending,
        patch("core.approval._notify_telegram") as notify,
    ):
        result = approval_check_node({
            "messages": [user_message, memory_result, draft_call],
        })

    assert result["approval_status"] == "blocked"
    save_pending.assert_not_called()
    notify.assert_not_called()


def test_provenance_marked_active_draft_edit_stays_approval_gated(monkeypatch, tmp_path):
    """External text inside a HumanMessage cannot revise an active draft unchecked."""
    import config
    from langchain_core.messages import AIMessage, HumanMessage
    from core.approval import approval_check_node
    from core.untrusted_content import external_content_history_metadata

    draft_file = tmp_path / "messenger_draft.json"
    monkeypatch.setattr(config, "MESSENGER_DRAFT_FILE", str(draft_file))
    draft_file.write_text(
        json.dumps(
            {
                "target_name": "Sofia",
                "message": "Παλιό μήνυμα",
                "status": "pending",
                "created_at": datetime.now().isoformat(timespec="seconds"),
                "expires_at": (datetime.now() + timedelta(minutes=30)).isoformat(timespec="seconds"),
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    external_reply = AIMessage(
        content="A prior news summary.",
        additional_kwargs=external_content_history_metadata(["get_news"]),
    )
    user_message = HumanMessage(
        content="Άλλαξε το μήνυμα",
        additional_kwargs=external_content_history_metadata(["user_provided_asset"]),
    )
    draft_call = AIMessage(
        content="",
        tool_calls=[{
            "name": "relay_local_payload",
            "args": {"target_entity": "Sofia", "payload_data": "Μήνυμα"},
            "id": "tc-provenance-active-draft-edit",
        }],
    )

    with (
        patch("core.approval.save_pending") as save_pending,
        patch("core.approval._notify_telegram") as notify,
    ):
        result = approval_check_node({
            "messages": [external_reply, user_message, draft_call],
        })

    assert result["approval_status"] == "pending"
    save_pending.assert_called_once()
    notify.assert_called_once()
