import os
import pytest
from astakos_skills.read_agent_skill import list_agent_skills, read_agent_skill

def test_list_agent_skills_contains_known_skill():
    """
    Δοκιμή ότι το εργαλείο επιστρέφει λίστα που περιέχει τα γνωστά skills
    (π.χ. 'test-driven-development', 'using-agent-skills').
    """
    result = list_agent_skills.invoke({})
    assert "Διαθέσιμα Agent Skills:" in result
    assert "test-driven-development" in result
    assert "using-agent-skills" in result

def test_read_agent_skill_valid():
    """
    Δοκιμή ότι η ανάγνωση ενός υπαρκτού skill επιστρέφει το περιεχόμενό του.
    """
    result = read_agent_skill.invoke({"skill_name": "using-agent-skills"})
    assert "=== KANONEΣ / WORKFLOW ΓΙΑ ΤΟ SKILL: using-agent-skills ===" in result
    assert "Discovers and invokes agent skills." in result

def test_read_agent_skill_invalid():
    """
    Δοκιμή ότι η ανάγνωση ενός ανύπαρκτου skill επιστρέφει κατάλληλο μήνυμα λάθους.
    """
    result = read_agent_skill.invoke({"skill_name": "non-existent-skill-123"})
    assert "Σφάλμα:" in result
    assert "δεν βρέθηκε" in result
