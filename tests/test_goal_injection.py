import pytest
from core.utils import build_prompt

class MockMessage:
    def __init__(self, content):
        self.content = content

def test_goal_injection_routine_command():
    # Routine commands should NOT inject goals
    msg = MockMessage("Ναι προχώρα")
    prompt = build_prompt([msg], agent_role="Chat_Agent", channel="telegram")
    assert "ΣΤΟΧΟΙ ΣΕ ΕΞΕΛΙΞΗ" not in prompt

def test_goal_injection_keyword_match():
    # Short text with a goal keyword should inject goals
    msg = MockMessage("τι κάνουμε με τους στόχους;")
    prompt = build_prompt([msg], agent_role="Chat_Agent", channel="telegram")
    assert "ΣΤΟΧΟΙ ΣΕ ΕΞΕΛΙΞΗ" in prompt

def test_goal_injection_long_text():
    # Long text (>15 chars) that is not a routine command should inject goals
    msg = MockMessage("Πες μου μια συνταγή για μακαρόνια με κιμά που να είναι πολύ νόστιμη")
    prompt = build_prompt([msg], agent_role="Chat_Agent", channel="telegram")
    assert "ΣΤΟΧΟΙ ΣΕ ΕΞΕΛΙΞΗ" in prompt

def test_goal_injection_short_unrelated_text():
    # Short unrelated text without keywords should NOT inject goals
    msg = MockMessage("Καλημέρα Αστακέ")
    prompt = build_prompt([msg], agent_role="Chat_Agent", channel="telegram")
    assert "ΣΤΟΧΟΙ ΣΕ ΕΞΕΛΙΞΗ" not in prompt

def test_goal_injection_planner_role():
    # Any text with Planner role should inject goals
    msg = MockMessage("ΟΚ")
    prompt = build_prompt([msg], agent_role="Planner", channel="telegram")
    assert "ΣΤΟΧΟΙ ΣΕ ΕΞΕΛΙΞΗ" in prompt
