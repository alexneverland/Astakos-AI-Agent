import os
import pytest
from astakos_skills.read_agent_skill import list_agent_skills, read_agent_skill

def test_list_agent_skills_contains_known_skill():
    """
    Test that the tool returns a list containing the known skills
    (e.g., 'test-driven-development', 'using-agent-skills').
    """
    result = list_agent_skills.invoke({})
    assert "Διαθέσιμα Agent Skills:" in result
    assert "test-driven-development" in result
    assert "using-agent-skills" in result

def test_read_agent_skill_valid():
    """
    Test that reading an existing skill returns its content.
    """
    result = read_agent_skill.invoke({"skill_name": "using-agent-skills"})
    assert "=== KANONEΣ / WORKFLOW ΓΙΑ ΤΟ SKILL: using-agent-skills ===" in result
    assert "Discovers and invokes agent skills." in result

def test_read_agent_skill_invalid():
    """
    Test that reading a non-existent skill returns an appropriate error message.
    """
    result = read_agent_skill.invoke({"skill_name": "non-existent-skill-123"})
    assert "Σφάλμα:" in result
    assert "δεν βρέθηκε" in result
