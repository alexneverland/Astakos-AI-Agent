import os
import sys
import pytest
from langchain_core.messages import AIMessage, HumanMessage

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.approval import approval_check_node
import core.i18n as i18n

@pytest.fixture(autouse=True)
def restore_locale():
    # Save the current language and restore it after each test
    current_lang = i18n.LANG
    yield
    i18n.load_locale(current_lang)

def test_draft_authorization_exact():
    i18n.load_locale("en")
    human_msg = HumanMessage(content="create draft")
    ai_msg = AIMessage(content="", tool_calls=[{"name": "write_custom_tool", "args": {}, "id": "tc-1"}])
    state = {"messages": [human_msg, ai_msg]}
    result = approval_check_node(state)
    assert result["approval_status"] == "ok"
    assert "messages" not in result

def test_draft_authorization_with_suffix():
    i18n.load_locale("en")
    human_msg = HumanMessage(content="create draft for a weather tool")
    ai_msg = AIMessage(content="", tool_calls=[{"name": "write_custom_tool", "args": {}, "id": "tc-1"}])
    state = {"messages": [human_msg, ai_msg]}
    result = approval_check_node(state)
    assert result["approval_status"] == "ok"

def test_draft_authorization_with_exclamation():
    i18n.load_locale("en")
    human_msg = HumanMessage(content="create draft!")
    ai_msg = AIMessage(content="", tool_calls=[{"name": "write_custom_tool", "args": {}, "id": "tc-1"}])
    state = {"messages": [human_msg, ai_msg]}
    result = approval_check_node(state)
    assert result["approval_status"] == "ok"

def test_draft_authorization_with_question_mark_blocks():
    i18n.load_locale("en")
    human_msg = HumanMessage(content="create draft?")
    ai_msg = AIMessage(content="", tool_calls=[{"name": "write_custom_tool", "args": {}, "id": "tc-1"}])
    state = {"messages": [human_msg, ai_msg]}
    result = approval_check_node(state)
    assert result["approval_status"] == "blocked"


def test_draft_revocation_blocks_english():
    i18n.load_locale("en")
    human_msg = HumanMessage(content="create draft, but do not create it")
    ai_msg = AIMessage(content="", tool_calls=[{"name": "write_custom_tool", "args": {}, "id": "tc-1"}])
    result = approval_check_node({"messages": [human_msg, ai_msg]})
    assert result["approval_status"] == "blocked"


def test_draft_revocation_blocks_greek():
    i18n.load_locale("el")
    human_msg = HumanMessage(content="φτιάξε draft, αλλά μην το δημιουργήσεις")
    ai_msg = AIMessage(content="", tool_calls=[{"name": "write_custom_tool", "args": {}, "id": "tc-1"}])
    result = approval_check_node({"messages": [human_msg, ai_msg]})
    assert result["approval_status"] == "blocked"


def test_draft_negation_blocks():
    i18n.load_locale("en")
    human_msg = HumanMessage(content="don't create draft")
    ai_msg = AIMessage(content="", tool_calls=[{"name": "write_custom_tool", "args": {}, "id": "tc-1"}])
    state = {"messages": [human_msg, ai_msg]}
    result = approval_check_node(state)
    assert result["approval_status"] == "blocked"

def test_draft_stale_authorization_blocks():
    i18n.load_locale("en")
    human_msg_stale = HumanMessage(content="create draft")
    ai_msg_intermediate = AIMessage(content="I'll do that.")
    human_msg_new = HumanMessage(content="Actually just tell me the weather.")
    ai_msg = AIMessage(content="", tool_calls=[{"name": "write_custom_tool", "args": {}, "id": "tc-1"}])
    state = {"messages": [human_msg_stale, ai_msg_intermediate, human_msg_new, ai_msg]}

    result = approval_check_node(state)
    assert result["approval_status"] == "blocked"

def test_draft_authorization_greek_exact():
    i18n.load_locale("el")
    human_msg = HumanMessage(content="φτιάξε draft για ένα weather tool")
    ai_msg = AIMessage(content="", tool_calls=[{"name": "write_custom_tool", "args": {}, "id": "tc-1"}])
    state = {"messages": [human_msg, ai_msg]}
    result = approval_check_node(state)
    assert result["approval_status"] == "ok"

def test_draft_llm_args_bypassed():
    human_msg = HumanMessage(content="do some work")
    ai_msg = AIMessage(content="", tool_calls=[{"name": "write_custom_tool", "args": {"authorized": True, "create_draft": "yes"}, "id": "tc-1"}])
    state = {"messages": [human_msg, ai_msg]}

    result = approval_check_node(state)
    assert result["approval_status"] == "blocked"

def test_draft_mixed_batch():
    human_msg = HumanMessage(content="check the database")
    ai_msg = AIMessage(content="", tool_calls=[
        {"name": "search_memory", "args": {}, "id": "tc-safe"},
        {"name": "write_custom_tool", "args": {}, "id": "tc-bad"}
    ])
    state = {"messages": [human_msg, ai_msg]}

    result = approval_check_node(state)
    assert result["approval_status"] == "blocked"
    assert len(result["messages"]) == 1
    assert result["messages"][0].tool_call_id == "tc-bad"
