import os
import sys
import pytest
from langchain_core.messages import AIMessage, HumanMessage

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.approval import approval_check_node
from core.capability_draft import has_capability_draft_authorization
import core.i18n as i18n

@pytest.fixture(autouse=True)
def restore_locale():
    # Save the current language and restore it after each test
    current_lang = i18n.LANG
    yield
    i18n.load_locale(current_lang)

def test_draft_authorization_exact():
    i18n.load_locale("en")
    ai_proposal = AIMessage(content="New tool proposal: I can make this.")
    human_msg = HumanMessage(content="create draft")
    ai_msg = AIMessage(content="", tool_calls=[{"name": "write_custom_tool", "args": {}, "id": "tc-1"}])
    state = {"messages": [ai_proposal, human_msg, ai_msg]}
    result = approval_check_node(state)
    assert result["approval_status"] == "ok"
    assert "messages" not in result

def test_draft_authorization_with_suffix():
    i18n.load_locale("en")
    ai_proposal = AIMessage(content="New tool proposal: let's build it.")
    human_msg = HumanMessage(content="create draft for a weather tool")
    ai_msg = AIMessage(content="", tool_calls=[{"name": "write_custom_tool", "args": {}, "id": "tc-1"}])
    state = {"messages": [ai_proposal, human_msg, ai_msg]}
    result = approval_check_node(state)
    assert result["approval_status"] == "ok"

def test_draft_authorization_with_exclamation():
    i18n.load_locale("en")
    ai_proposal = AIMessage(content="New tool proposal: doing it")
    human_msg = HumanMessage(content="create draft!")
    ai_msg = AIMessage(content="", tool_calls=[{"name": "write_custom_tool", "args": {}, "id": "tc-1"}])
    state = {"messages": [ai_proposal, human_msg, ai_msg]}
    result = approval_check_node(state)
    assert result["approval_status"] == "ok"

def test_draft_authorization_with_question_mark_blocks():
    i18n.load_locale("en")
    ai_proposal = AIMessage(content="New tool proposal: waiting.")
    human_msg = HumanMessage(content="create draft?")
    ai_msg = AIMessage(content="", tool_calls=[{"name": "write_custom_tool", "args": {}, "id": "tc-1"}])
    state = {"messages": [ai_proposal, human_msg, ai_msg]}
    result = approval_check_node(state)
    assert result["approval_status"] == "blocked"

def test_draft_revocation_blocks_english():
    i18n.load_locale("en")
    ai_proposal = AIMessage(content="New tool proposal: ...")
    human_msg = HumanMessage(content="create draft, but do not create it")
    ai_msg = AIMessage(content="", tool_calls=[{"name": "write_custom_tool", "args": {}, "id": "tc-1"}])
    result = approval_check_node({"messages": [ai_proposal, human_msg, ai_msg]})
    assert result["approval_status"] == "blocked"

def test_draft_revocation_blocks_greek():
    i18n.load_locale("el")
    ai_proposal = AIMessage(content="Πρόταση νέου εργαλείου: φτιάχνω;")
    human_msg = HumanMessage(content="φτιάξε draft, αλλά μην το δημιουργήσεις")
    ai_msg = AIMessage(content="", tool_calls=[{"name": "write_custom_tool", "args": {}, "id": "tc-1"}])
    result = approval_check_node({"messages": [ai_proposal, human_msg, ai_msg]})
    assert result["approval_status"] == "blocked"

def test_draft_negation_blocks():
    i18n.load_locale("en")
    ai_proposal = AIMessage(content="New tool proposal: sure.")
    human_msg = HumanMessage(content="don't create draft")
    ai_msg = AIMessage(content="", tool_calls=[{"name": "write_custom_tool", "args": {}, "id": "tc-1"}])
    state = {"messages": [ai_proposal, human_msg, ai_msg]}
    result = approval_check_node(state)
    assert result["approval_status"] == "blocked"

def test_draft_stale_authorization_blocks():
    i18n.load_locale("en")
    ai_proposal = AIMessage(content="New tool proposal: sure.")
    human_msg_stale = HumanMessage(content="create draft")
    ai_msg_intermediate = AIMessage(content="I'll do that.")
    human_msg_new = HumanMessage(content="Actually just tell me the weather.")
    ai_msg = AIMessage(content="", tool_calls=[{"name": "write_custom_tool", "args": {}, "id": "tc-1"}])
    state = {"messages": [ai_proposal, human_msg_stale, ai_msg_intermediate, human_msg_new, ai_msg]}
    result = approval_check_node(state)
    assert result["approval_status"] == "blocked"

def test_draft_authorization_greek_exact():
    i18n.load_locale("el")
    ai_proposal = AIMessage(content="Πρόταση νέου εργαλείου: να το κάνουμε;")
    human_msg = HumanMessage(content="φτιάξε draft για ένα weather tool")
    ai_msg = AIMessage(content="", tool_calls=[{"name": "write_custom_tool", "args": {}, "id": "tc-1"}])
    state = {"messages": [ai_proposal, human_msg, ai_msg]}
    result = approval_check_node(state)
    assert result["approval_status"] == "ok"

def test_draft_command_without_prefix_blocks():
    i18n.load_locale("en")
    ai_proposal = AIMessage(content="I can build a tool but I didn't use the prefix.")
    human_msg = HumanMessage(content="create draft")
    ai_msg = AIMessage(content="", tool_calls=[{"name": "write_custom_tool", "args": {}, "id": "tc-1"}])
    state = {"messages": [ai_proposal, human_msg, ai_msg]}
    result = approval_check_node(state)
    assert result["approval_status"] == "blocked"

def test_draft_prefix_later_in_text_blocks():
    i18n.load_locale("en")
    ai_proposal = AIMessage(content="I see you want something. New tool proposal: I can build it.")
    human_msg = HumanMessage(content="create draft")
    ai_msg = AIMessage(content="", tool_calls=[{"name": "write_custom_tool", "args": {}, "id": "tc-1"}])
    state = {"messages": [ai_proposal, human_msg, ai_msg]}
    result = approval_check_node(state)
    assert result["approval_status"] == "blocked"

def test_draft_unrelated_intervening_user_message_blocks():
    i18n.load_locale("en")
    ai_proposal = AIMessage(content="New tool proposal: let's build it.")
    human_msg1 = HumanMessage(content="Wait what time is it?")
    ai_msg2 = AIMessage(content="It is noon.")
    human_msg2 = HumanMessage(content="create draft")
    ai_msg = AIMessage(content="", tool_calls=[{"name": "write_custom_tool", "args": {}, "id": "tc-1"}])
    state = {"messages": [ai_proposal, human_msg1, ai_msg2, human_msg2, ai_msg]}
    result = approval_check_node(state)
    assert result["approval_status"] == "blocked"

def test_draft_llm_args_bypassed():
    i18n.load_locale("en")
    human_msg = HumanMessage(content="do some work")
    ai_msg = AIMessage(content="", tool_calls=[{"name": "write_custom_tool", "args": {"authorized": True, "create_draft": "yes"}, "id": "tc-1"}])
    state = {"messages": [human_msg, ai_msg]}
    result = approval_check_node(state)
    assert result["approval_status"] == "blocked"

def test_draft_mixed_batch():
    i18n.load_locale("en")
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

def test_prompt_injection_requires_canonical_dev_proposal():
    from core.utils import build_prompt

    i18n.load_locale("en")
    prompt = build_prompt([])
    assert "If you are Dev_Agent: Use this prefix" in prompt
    assert "New tool proposal:" in prompt

    i18n.load_locale("el")
    prompt_el = build_prompt([])
    assert "Εάν είστε ο Dev_Agent" in prompt_el
    assert "Πρόταση νέου εργαλείου:" in prompt_el

def test_draft_authorization_with_transport_metadata():
    i18n.load_locale("en")
    ai_proposal = AIMessage(content="[12:34] New tool proposal: I can make this.")
    human_msg = HumanMessage(content="[12:35] create draft")
    ai_msg = AIMessage(content="", tool_calls=[{"name": "write_custom_tool", "args": {}, "id": "tc-1"}])
    state = {"messages": [ai_proposal, human_msg, ai_msg]}
    result = approval_check_node(state)
    assert result["approval_status"] == "ok"

def test_draft_authorization_with_history_metadata_consecutive():
    i18n.load_locale("en")
    ai_proposal = AIMessage(content="[2024-05-12 12:34 / telegram] [12:34] New tool proposal: sure.")
    human_msg = HumanMessage(content="[2024-05-12 12:35 / telegram] [12:35] create draft")
    ai_msg = AIMessage(content="", tool_calls=[{"name": "write_custom_tool", "args": {}, "id": "tc-1"}])
    state = {"messages": [ai_proposal, human_msg, ai_msg]}
    result = approval_check_node(state)
    assert result["approval_status"] == "ok"

def test_draft_authorization_rejects_arbitrary_brackets():
    i18n.load_locale("en")
    ai_proposal = AIMessage(content="New tool proposal: sure.")
    human_msg = HumanMessage(content="[USER_UPLOADED_FILE] create draft")
    ai_msg = AIMessage(content="", tool_calls=[{"name": "write_custom_tool", "args": {}, "id": "tc-1"}])
    state = {"messages": [ai_proposal, human_msg, ai_msg]}
    result = approval_check_node(state)
    assert result["approval_status"] == "blocked"
