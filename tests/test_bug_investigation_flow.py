"""Offline regression checks for the two-consent existing-bug workflow."""

from unittest.mock import MagicMock, patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

import core.i18n as i18n
from core.agents import Router, dev_agent_node, supervisor_node
from core.approval import approval_check_node
from core.capability_draft import has_pending_bug_followup, has_pending_bug_proposal
from core.graph import _route_supervisor


@pytest.fixture(autouse=True)
def english_locale():
    """Use one stable localized proposal prefix and restore the prior locale."""
    previous = i18n.LANG
    i18n.load_locale("en")
    yield
    i18n.load_locale(previous)


def _bug_offer_state(reply: str) -> dict:
    """Build a current offer and one owner response from either channel."""
    return {
        "channel": "matrix",
        "messages": [
            AIMessage(content="[2026-09-26 10:00 / web] Possible problem in existing behavior: the timing is wrong."),
            HumanMessage(content=f"[2026-09-26 10:01 / matrix] {reply}"),
        ],
    }


def test_current_bug_offer_routes_accepted_investigation_read_only():
    """A semantic acceptance of the current offer starts diagnosis, not a fix."""
    state = _bug_offer_state("Yes, check what caused that timing mistake.")
    with patch("core.capability_lookup.lookup_agent", return_value="Chat_Agent"), patch(
        "core.agents.safe_llm_invoke",
        return_value=Router(next_agent="Chat_Agent", bug_offer_intent="investigate"),
    ):
        result = supervisor_node(state)
    assert result["next_agent"] == "Dev_Agent"
    assert result["bug_diagnosis_read_only"] is True


def test_diagnosis_route_cannot_be_promoted_to_auto_plan():
    """The auto-plan judge cannot replace the protected diagnosis turn."""
    state = _bug_offer_state("Investigate the issue and propose a fix")
    state.update(next_agent="Dev_Agent", bug_diagnosis_read_only=True, bug_followup_routed=True)
    with patch("core.plan_judge.should_auto_plan", return_value=True) as judge:
        assert _route_supervisor(state) == "Dev_Agent"
    judge.assert_not_called()


def test_short_ack_after_current_bug_offer_is_not_a_transport_only_ack():
    """Both Web and Telegram must submit a brief yes to the shared graph."""
    from core.utils import is_ultra_light_ack

    state = _bug_offer_state("ναι")
    assert is_ultra_light_ack("ναι") is True
    assert has_pending_bug_followup(state) is True


def test_trusted_transport_system_hint_does_not_hide_current_bug_offer():
    """Matrix can append a trusted routine hint after the current owner turn."""
    state = _bug_offer_state("Please investigate")
    state["messages"].append(SystemMessage(content="routine context"))
    assert has_pending_bug_followup(state) is True
    with patch("core.agents.safe_llm_invoke", return_value=Router(
        next_agent="Chat_Agent", bug_offer_intent="investigate"
    )):
        result = supervisor_node(state)
    assert result["next_agent"] == "Dev_Agent"
    assert result["bug_diagnosis_read_only"] is True


@pytest.mark.parametrize("reply", ["No thanks.", "What do you mean?", "Show me the weather instead."])
def test_bug_offer_decline_question_or_unrelated_does_not_authorize_diagnosis(reply):
    """Neither a refusal nor a new topic can silently start project inspection."""
    state = _bug_offer_state(reply)
    with patch("core.capability_lookup.lookup_agent", return_value="Web_Agent"), patch(
        "core.agents.safe_llm_invoke",
        return_value=Router(next_agent="Web_Agent", bug_offer_intent="other"),
    ):
        result = supervisor_node(state)
    assert result["next_agent"] != "Dev_Agent"
    assert result.get("bug_diagnosis_read_only") is not True


def test_stale_bug_offer_has_no_authority():
    """Only the offer immediately before the latest owner turn has provenance."""
    state = _bug_offer_state("Check it")
    state["messages"].insert(-1, HumanMessage(content="Tell me the time first"))
    state["messages"].insert(-1, AIMessage(content="It is noon."))
    assert has_pending_bug_proposal(state) is False


def test_failed_semantic_decision_does_not_authorize_investigation():
    """An LLM outage fails closed instead of guessing owner consent."""
    state = _bug_offer_state("Check it")
    with patch("core.agents.safe_llm_invoke", side_effect=RuntimeError("offline")):
        result = supervisor_node(state)
    assert result["next_agent"] == "Chat_Agent"
    assert result.get("bug_diagnosis_read_only") is not True


@pytest.mark.parametrize("tool_name", ["write_code", "edit_project_file", "run_terminal_command"])
def test_diagnosis_tool_boundary_rejects_non_allowlisted_calls(tool_name):
    """The backend rejects writes and terminal execution, even for read commands."""
    state = _bug_offer_state("Please investigate")
    state["bug_diagnosis_read_only"] = True
    state["messages"].append(AIMessage(content="", tool_calls=[{
        "name": tool_name,
        "args": {"command": "git status --short"} if tool_name == "run_terminal_command" else {},
        "id": "attempt-write",
    }]))
    result = approval_check_node(state)
    assert result["approval_status"] == "blocked"


def test_diagnosis_tool_boundary_allows_project_read():
    """Bounded project reading remains possible in diagnosis mode."""
    state = _bug_offer_state("Please investigate")
    state["bug_diagnosis_read_only"] = True
    state["messages"].append(AIMessage(content="", tool_calls=[{
        "name": "read_project_file", "args": {"path": "core/agents.py"}, "id": "read-one",
    }]))
    result = approval_check_node(state)
    assert result["approval_status"] == "ok"


def test_diagnosis_agent_binds_only_reads_and_marks_final_report():
    """The model sees only project readers and its final answer carries provenance."""
    state = _bug_offer_state("Please investigate")
    state["bug_diagnosis_read_only"] = True
    fake_model = MagicMock()
    fake_model.bind_tools.return_value.invoke.return_value = AIMessage(
        content="Observed: the timer reads a stale timestamp. Uncertain: restart behavior."
    )
    with patch("core.agents.llm_heavy", fake_model):
        result = dev_agent_node(state)
    tool_names = {tool.name for tool in fake_model.bind_tools.call_args.args[0]}
    assert "read_project_file" in tool_names
    assert "repo_mapper" not in tool_names
    assert "write_code" not in tool_names
    assert "run_terminal_command" not in tool_names
    assert result["messages"][0].content.startswith("Bug diagnosis:")
    assert "ask for that explicitly in a new message" in result["messages"][0].content


def test_vague_assent_after_diagnosis_is_not_fix_authority():
    """The second decision cannot be inferred from a bare assent."""
    state = {
        "messages": [
            AIMessage(content="Bug diagnosis: the timer uses the wrong timestamp. Ask me explicitly to fix it."),
            HumanMessage(content="Yes"),
        ]
    }
    with patch("core.capability_lookup.lookup_agent", return_value="Dev_Agent"), patch(
        "core.agents.safe_llm_invoke",
        return_value=Router(next_agent="Dev_Agent", bug_fix_intent="ambiguous"),
    ):
        result = supervisor_node(state)
    assert result["next_agent"] == "Chat_Agent"


def test_explicit_second_fix_instruction_uses_normal_dev_gates():
    """A later explicit fix request leaves diagnosis mode and uses ordinary gates."""
    state = {
        "messages": [
            AIMessage(content="Bug diagnosis: the timer uses the wrong timestamp. Ask me explicitly to fix it."),
            HumanMessage(content="Fix that timestamp bug now."),
        ]
    }
    with patch("core.capability_lookup.lookup_agent", return_value="Chat_Agent"), patch(
        "core.agents.safe_llm_invoke",
        return_value=Router(next_agent="Chat_Agent", bug_fix_intent="fix"),
    ):
        result = supervisor_node(state)
    assert result["next_agent"] == "Dev_Agent"
    assert result.get("bug_diagnosis_read_only") is not True
