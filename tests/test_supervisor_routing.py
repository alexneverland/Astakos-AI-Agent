import os
import sys
from unittest.mock import patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import core.i18n as i18n
from core.agents import Router, supervisor_node

@pytest.fixture(autouse=True)
def restore_locale():
    current_lang = i18n.LANG
    yield
    i18n.load_locale(current_lang)

@patch("core.capability_lookup.lookup_agent")
@patch("core.agents.safe_llm_invoke")
def test_supervisor_routes_to_dev_agent_with_valid_sequence(mock_safe_llm_invoke, mock_lookup_agent):
    i18n.load_locale("en")
    mock_lookup_agent.return_value = None

    ai_proposal = AIMessage(content="New tool proposal: let's build it.")
    human_msg = HumanMessage(content="create draft")
    state = {"messages": [ai_proposal, human_msg]}

    result = supervisor_node(state)

    assert result["next_agent"] == "Dev_Agent"
    # Router LLM should not be invoked
    mock_safe_llm_invoke.assert_not_called()

@patch("core.capability_lookup.lookup_agent")
@patch("core.agents.safe_llm_invoke")
def test_supervisor_normal_routing_without_proposal(mock_safe_llm_invoke, mock_lookup_agent):
    i18n.load_locale("en")
    mock_lookup_agent.return_value = None

    # Mock LLM to return a different agent
    router_result = Router(next_agent="Web_Agent")
    mock_safe_llm_invoke.return_value = router_result

    human_msg = HumanMessage(content="create draft")
    state = {"messages": [human_msg]}

    result = supervisor_node(state)

    # Should fall back to the LLM Router since no prefix was present
    assert result["next_agent"] == "Web_Agent"
    mock_safe_llm_invoke.assert_called_once()

@patch("core.capability_lookup.lookup_agent")
@patch("core.agents.safe_llm_invoke")
def test_supervisor_routes_to_dev_agent_with_timestamp_prefix(mock_safe_llm_invoke, mock_lookup_agent):
    i18n.load_locale("en")
    mock_lookup_agent.return_value = None

    ai_proposal = AIMessage(content="[2024-05-12 12:34 / telegram] [12:34] New tool proposal: let's build it.")
    human_msg = HumanMessage(content="[2024-05-12 12:35 / telegram] [12:35] create draft")
    state = {"messages": [ai_proposal, human_msg]}

    result = supervisor_node(state)

    assert result["next_agent"] == "Dev_Agent"
    mock_safe_llm_invoke.assert_not_called()


@patch("core.capability_lookup.lookup_agent")
@patch("core.agents.safe_llm_invoke")
def test_supervisor_keeps_ambiguous_reply_out_of_dev_after_capability_proposal(
    mock_safe_llm_invoke, mock_lookup_agent
):
    """Only the canonical draft authorization may continue a capability proposal."""
    i18n.load_locale("el")
    mock_lookup_agent.return_value = None
    mock_safe_llm_invoke.return_value = Router(next_agent="Dev_Agent")
    state = {
        "messages": [
            AIMessage(content=(
                "[23:47] Πρόταση νέου εργαλείου: Μπορούμε να φτιάξουμε "
                "ένα εργαλείο παραγωγής βίντεο."
            )),
            HumanMessage(content="για γραψε να σε δω"),
        ]
    }

    result = supervisor_node(state)

    assert result["next_agent"] == "Chat_Agent"
    mock_safe_llm_invoke.assert_called_once()


@patch("core.capability_lookup.lookup_agent")
@patch("core.agents.safe_llm_invoke")
def test_supervisor_preserves_registry_routing_after_capability_proposal(
    mock_safe_llm_invoke, mock_lookup_agent
):
    """An unrelated reply after a proposal keeps its normal specialized route."""
    i18n.load_locale("el")
    mock_lookup_agent.return_value = "Web_Agent"
    state = {
        "messages": [
            AIMessage(content="Πρόταση νέου εργαλείου: εργαλείο παραγωγής βίντεο."),
            HumanMessage(content="Όχι, δείξε μου τον αυριανό καιρό."),
        ]
    }

    result = supervisor_node(state)

    assert result["next_agent"] == "Web_Agent"
    mock_safe_llm_invoke.assert_not_called()


@patch("core.capability_lookup.lookup_agent")
@patch("core.agents.safe_llm_invoke")
def test_supervisor_preserves_standalone_dev_registry_route_after_proposal(
    mock_safe_llm_invoke, mock_lookup_agent
):
    """A new registered Dev request is not mistaken for proposal authorization."""
    i18n.load_locale("el")
    mock_lookup_agent.return_value = "Dev_Agent"
    state = {
        "messages": [
            AIMessage(content="Πρόταση νέου εργαλείου: εργαλείο παραγωγής βίντεο."),
            HumanMessage(content="Όχι, αντί γι' αυτό διόρθωσε αυτό το Python error."),
        ]
    }

    result = supervisor_node(state)

    assert result["next_agent"] == "Dev_Agent"
    mock_safe_llm_invoke.assert_not_called()


@patch("core.capability_lookup.lookup_agent")
@patch("core.agents.safe_llm_invoke")
def test_supervisor_accepts_explicit_greek_draft_authorization_after_proposal(
    mock_safe_llm_invoke, mock_lookup_agent
):
    i18n.load_locale("el")
    mock_lookup_agent.return_value = None
    state = {
        "messages": [
            AIMessage(content="Πρόταση νέου εργαλείου: εργαλείο παραγωγής βίντεο."),
            HumanMessage(content="φτιάξε draft"),
        ]
    }

    result = supervisor_node(state)

    assert result["next_agent"] == "Dev_Agent"
    mock_safe_llm_invoke.assert_not_called()


@patch("core.capability_lookup.lookup_agent")
@patch("core.agents.safe_llm_invoke")
def test_supervisor_fallback_knows_natural_image_creation_uses_existing_web_tool(
    mock_safe_llm_invoke, mock_lookup_agent
):
    """The user's exact wording must not be mistaken for a new technical capability."""
    mock_lookup_agent.return_value = None
    mock_safe_llm_invoke.return_value = Router(next_agent="Web_Agent")
    state = {
        "messages": [HumanMessage(content=(
            "φτιαξε μου μια φωτογραφια ενα γραφιο με υπολογιστη "
            "και χυμα χαρτια γυρω γυρω"
        ))]
    }

    result = supervisor_node(state)

    routing_prompt = mock_safe_llm_invoke.call_args.args[1]
    assert result["next_agent"] == "Web_Agent"
    assert "generate_image_tool" in routing_prompt
    assert "original image" in routing_prompt.lower()
    assert "not" in routing_prompt.lower() and "Tech_Agent" in routing_prompt


@patch("core.capability_lookup.lookup_agent")
@patch("core.agents.safe_llm_invoke")
def test_supervisor_distinguishes_existing_photo_retrieval_from_image_creation(
    mock_safe_llm_invoke, mock_lookup_agent
):
    """Looking for an existing photo remains a Chat capability."""
    mock_lookup_agent.return_value = None
    mock_safe_llm_invoke.return_value = Router(next_agent="Chat_Agent")
    state = {"messages": [HumanMessage(content="δειξε μου μια παλια φωτογραφια απο το παρκο")]}

    result = supervisor_node(state)

    routing_prompt = mock_safe_llm_invoke.call_args.args[1]
    assert result["next_agent"] == "Chat_Agent"
    assert "existing photo" in routing_prompt.lower()
