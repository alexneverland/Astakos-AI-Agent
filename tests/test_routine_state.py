"""
Tests για το Routine State Machine.
Τρεξε: python -m pytest tests/ -v
"""
import pytest
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.routine_state import RoutineState, validate_transition, is_notifiable, state_from_str
from core.exceptions import RoutineConflictError


# -- Valid transitions --------------------------------------------

def test_learned_to_active():
    validate_transition(RoutineState.LEARNED, RoutineState.ACTIVE)

def test_active_to_trigger_pending():
    validate_transition(RoutineState.ACTIVE, RoutineState.TRIGGER_PENDING)

def test_trigger_pending_to_confirmed():
    validate_transition(RoutineState.TRIGGER_PENDING, RoutineState.CONFIRMED)

def test_trigger_pending_to_ignored():
    validate_transition(RoutineState.TRIGGER_PENDING, RoutineState.IGNORED)

def test_trigger_pending_to_dismissed():
    validate_transition(RoutineState.TRIGGER_PENDING, RoutineState.DISMISSED)

def test_confirmed_to_active():
    validate_transition(RoutineState.CONFIRMED, RoutineState.ACTIVE)

def test_ignored_to_active():
    validate_transition(RoutineState.IGNORED, RoutineState.ACTIVE)

def test_dismissed_to_decayed():
    validate_transition(RoutineState.DISMISSED, RoutineState.DECAYED)

def test_decayed_to_archived():
    validate_transition(RoutineState.DECAYED, RoutineState.ARCHIVED)

def test_archived_to_learned():
    validate_transition(RoutineState.ARCHIVED, RoutineState.LEARNED)


# -- Invalid transitions ------------------------------------------

def test_active_to_confirmed_invalid():
    with pytest.raises(RoutineConflictError):
        validate_transition(RoutineState.ACTIVE, RoutineState.CONFIRMED)

def test_learned_to_trigger_pending_invalid():
    with pytest.raises(RoutineConflictError):
        validate_transition(RoutineState.LEARNED, RoutineState.TRIGGER_PENDING)

def test_archived_to_active_invalid():
    with pytest.raises(RoutineConflictError):
        validate_transition(RoutineState.ARCHIVED, RoutineState.ACTIVE)

def test_confirmed_to_decayed_invalid():
    with pytest.raises(RoutineConflictError):
        validate_transition(RoutineState.CONFIRMED, RoutineState.DECAYED)


# -- Helpers ------------------------------------------------------

def test_is_notifiable_only_active():
    assert is_notifiable(RoutineState.ACTIVE) is True
    assert is_notifiable(RoutineState.LEARNED) is False
    assert is_notifiable(RoutineState.TRIGGER_PENDING) is False
    assert is_notifiable(RoutineState.ARCHIVED) is False

def test_state_from_str_valid():
    assert state_from_str("active") == RoutineState.ACTIVE
    assert state_from_str("learned") == RoutineState.LEARNED
    assert state_from_str("archived") == RoutineState.ARCHIVED

def test_state_from_str_unknown_falls_back_to_learned():
    assert state_from_str("garbage") == RoutineState.LEARNED
    assert state_from_str("") == RoutineState.LEARNED
