import pytest
import sqlite3
from unittest.mock import patch, MagicMock
from services.reflection_engine import _apply_action

def test_apply_action_save_to_memory_without_routine_id():
    # action == save_to_memory and no routine_id => should save and return True
    reflection = {
        "action": "save_to_memory",
        "lesson": "Test lesson 1"
    }
    
    with patch("memory.vector_store.vector_store.add_texts") as mock_add_texts:
        res = _apply_action(reflection)
        assert res is True
        mock_add_texts.assert_called_once()
        
def test_apply_action_save_to_memory_with_routine_id():
    # action == save_to_memory with routine_id => should save and return True, not update DB
    reflection = {
        "action": "save_to_memory",
        "routine_id": 999,
        "lesson": "Test lesson 2"
    }
    
    with patch("memory.vector_store.vector_store.add_texts") as mock_add_texts:
        res = _apply_action(reflection)
        assert res is True
        mock_add_texts.assert_called_once()

def test_apply_action_missing_routine_id_for_db_action():
    # action != save_to_memory but missing routine_id => should return False
    reflection = {
        "action": "increase_cooldown",
        "action_value": 48
    }
    res = _apply_action(reflection)
    assert res is False
