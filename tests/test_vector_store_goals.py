import pytest
from unittest.mock import patch, MagicMock
from memory.vector_store import save_goal, update_goal_progress, update_goal_milestones, get_active_goals

def test_save_goal_with_progress_and_milestones():
    with patch("memory.vector_store.vector_store._collection.get") as mock_get, \
         patch("memory.vector_store.vector_store._collection.delete") as mock_delete, \
         patch("memory.vector_store.vector_store.add_texts") as mock_add_texts:
         
        # Mock no existing goal
        mock_get.return_value = {"ids": [], "documents": [], "metadatas": []}
        
        ok = save_goal("TestApp", "A test goal", status="active", progress=25, milestones="1) Start")
        assert ok is True
        
        # Verify metadata
        mock_add_texts.assert_called_once()
        args, kwargs = mock_add_texts.call_args
        metadata = kwargs["metadatas"][0]
        assert metadata["project"] == "TestApp"
        assert metadata["progress"] == 25
        assert metadata["milestones"] == "1) Start"

def test_update_goal_progress():
    with patch("memory.vector_store.vector_store._collection.get") as mock_get, \
         patch("memory.vector_store.vector_store._collection.delete") as mock_delete, \
         patch("memory.vector_store.vector_store.add_texts") as mock_add_texts:
         
        mock_get.return_value = {
            "ids": ["id1"], 
            "documents": ["[GOAL] TestApp: desc"], 
            "metadatas": [{"project": "TestApp", "status": "active", "progress": 0}]
        }
        
        ok = update_goal_progress("TestApp", 75)
        assert ok is True
        
        mock_delete.assert_called_once_with(ids=["id1"])
        mock_add_texts.assert_called_once()
        args, kwargs = mock_add_texts.call_args
        metadata = kwargs["metadatas"][0]
        assert metadata["progress"] == 75

def test_update_goal_milestones():
    with patch("memory.vector_store.vector_store._collection.get") as mock_get, \
         patch("memory.vector_store.vector_store._collection.delete") as mock_delete, \
         patch("memory.vector_store.vector_store.add_texts") as mock_add_texts:
         
        mock_get.return_value = {
            "ids": ["id1"], 
            "documents": ["[GOAL] TestApp: desc"], 
            "metadatas": [{"project": "TestApp", "status": "active", "milestones": ""}]
        }
        
        ok = update_goal_milestones("TestApp", "1) Finish backend")
        assert ok is True
        
        args, kwargs = mock_add_texts.call_args
        metadata = kwargs["metadatas"][0]
        assert metadata["milestones"] == "1) Finish backend"

def test_get_active_goals_extraction():
    with patch("memory.vector_store.vector_store._collection.get") as mock_get:
        mock_get.return_value = {
            "ids": ["id1"], 
            "documents": ["[GOAL] TestApp: A test goal"], 
            "metadatas": [{
                "project": "TestApp", 
                "status": "active", 
                "progress": 50, 
                "milestones": "Halfway there"
            }]
        }
        
        goals = get_active_goals()
        assert len(goals) == 1
        assert goals[0]["project"] == "TestApp"
        assert goals[0]["progress"] == 50
        assert goals[0]["milestones"] == "Halfway there"
