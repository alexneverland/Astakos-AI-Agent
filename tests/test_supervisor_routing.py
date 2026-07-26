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
