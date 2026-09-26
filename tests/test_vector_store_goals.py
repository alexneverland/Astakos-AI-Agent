import json
import pytest
from unittest.mock import patch, MagicMock
from memory.vector_store import (
    get_active_goals,
    save_goal,
    update_goal_milestones,
    update_goal_progress,
    update_goal_status,
)

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


def test_save_goal_retains_external_provenance() -> None:
    """Approved goals keep their external source marker in Chroma metadata."""
    with patch("memory.vector_store.vector_store._collection.get") as mock_get, \
         patch("memory.vector_store.vector_store.add_texts") as mock_add_texts:
        mock_get.return_value = {"ids": [], "documents": [], "metadatas": []}

        assert save_goal(
            "Research",
            "Follow the external deadline",
            external_content_sources=["browse_url"],
        ) is True

        metadata = mock_add_texts.call_args.kwargs["metadatas"][0]
        assert metadata["untrusted_external_tool_names"] == '["browse_url"]'


def test_save_goal_update_retains_existing_external_provenance() -> None:
    """An ordinary goal update cannot clear an existing source marker."""
    with patch("memory.vector_store.vector_store._collection.get") as mock_get, \
         patch("memory.vector_store.vector_store._collection.delete"), \
         patch("memory.vector_store.vector_store.add_texts") as mock_add_texts:
        mock_get.return_value = {
            "ids": ["goal-1"],
            "documents": ["[GOAL] Research: External deadline"],
            "metadatas": [{
                "project": "Research",
                "untrusted_external_tool_names": '["browse_url"]',
            }],
        }

        assert save_goal("Research", "External deadline", progress=50) is True

        metadata = mock_add_texts.call_args.kwargs["metadatas"][0]
        assert metadata["untrusted_external_tool_names"] == '["browse_url"]'


def test_update_goal_milestones_merges_external_provenance() -> None:
    """Milestone writes merge the existing and approved external source markers."""
    from memory.vector_store import update_goal_milestones

    with patch("memory.vector_store.vector_store._collection.get") as mock_get, \
         patch("memory.vector_store.vector_store._collection.delete"), \
         patch("memory.vector_store.vector_store.add_texts") as mock_add_texts:
        mock_get.return_value = {
            "ids": ["goal-1"],
            "documents": ["[GOAL] Research: External deadline"],
            "metadatas": [{
                "project": "Research",
                "untrusted_external_tool_names": '["browse_url"]',
            }],
        }

        assert update_goal_milestones(
            "Research",
            "1) Complete external task",
            external_content_sources=["get_news"],
        ) is True

        metadata = mock_add_texts.call_args.kwargs["metadatas"][0]
        assert metadata["untrusted_external_tool_names"] == '["browse_url", "get_news"]'

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


def test_new_goal_records_creation_and_activity_times():
    with patch("memory.vector_store.vector_store._collection.get") as mock_get, \
         patch("memory.vector_store.vector_store.add_texts") as mock_add:
        mock_get.return_value = {"ids": [], "documents": [], "metadatas": []}

        assert save_goal("Kaggle", "Reach a baseline score") is True

        meta = mock_add.call_args.kwargs["metadatas"][0]
        assert meta["created_at"] == meta["updated_at"] == meta["last_activity_at"]
        assert json.loads(meta["goal_events_json"])[0]["kind"] == "created"


def test_goal_update_preserves_creation_and_records_what_changed():
    prior = {
        "project": "Kaggle", "status": "active", "progress": 0,
        "milestones": "", "created_at": 1_700_000_000.0,
        "updated_at": 1_700_000_000.0, "last_activity_at": 1_700_000_000.0,
        "goal_events_json": json.dumps([
            {"at": 1_700_000_000.0, "kind": "created", "detail": "Goal created"}
        ]),
    }
    with patch("memory.vector_store.vector_store._collection.get") as mock_get, \
         patch("memory.vector_store.vector_store._collection.delete"), \
         patch("memory.vector_store.vector_store.add_texts") as mock_add:
        mock_get.return_value = {
            "ids": ["goal-1"],
            "documents": ["[GOAL] Kaggle: Reach a baseline score"],
            "metadatas": [prior],
        }

        assert save_goal("Kaggle", "Submission scored 0.06", progress=25) is True

        meta = mock_add.call_args.kwargs["metadatas"][0]
        assert meta["created_at"] == 1_700_000_000.0
        assert meta["updated_at"] > 1_700_000_000.0
        assert meta["last_activity_at"] == meta["updated_at"]
        events = json.loads(meta["goal_events_json"])
        assert [event["kind"] for event in events] == ["created", "updated"]
        assert "0.06" in events[-1]["detail"]


def test_progress_update_preserves_creation_and_timeline():
    prior = {
        "project": "Kaggle", "status": "active", "progress": 0,
        "created_at": 1_700_000_000.0,
        "goal_events_json": "[]",
    }
    with patch("memory.vector_store.vector_store._collection.get") as mock_get, \
         patch("memory.vector_store.vector_store._collection.delete"), \
         patch("memory.vector_store.vector_store.add_texts") as mock_add:
        mock_get.return_value = {
            "ids": ["goal-1"],
            "documents": ["[GOAL] Kaggle: Reach a baseline score"],
            "metadatas": [prior],
        }

        assert update_goal_progress("Kaggle", 75) is True

        meta = mock_add.call_args.kwargs["metadatas"][0]
        assert meta["created_at"] == 1_700_000_000.0
        assert meta["last_activity_at"] == meta["updated_at"]
        assert json.loads(meta["goal_events_json"])[-1]["detail"] == "progress: 0% → 75%"


def test_repeat_goal_save_counts_as_activity_without_inventing_a_change():
    prior = {
        "project": "Kaggle", "status": "active", "progress": 0,
        "milestones": "", "created_at": 1_700_000_000.0,
        "updated_at": 1_700_000_000.0, "last_activity_at": 1_700_000_000.0,
        "goal_events_json": "[]",
    }
    with patch("memory.vector_store.vector_store._collection.get") as mock_get, \
         patch("memory.vector_store.vector_store._collection.delete"), \
         patch("memory.vector_store.vector_store.add_texts") as mock_add:
        mock_get.return_value = {
            "ids": ["goal-1"],
            "documents": ["[GOAL] Kaggle: Same goal"],
            "metadatas": [prior],
        }

        assert save_goal("Kaggle", "Same goal") is True

        meta = mock_add.call_args.kwargs["metadatas"][0]
        assert meta["created_at"] == meta["updated_at"] == 1_700_000_000.0
        assert meta["last_activity_at"] > meta["updated_at"]
        assert json.loads(meta["goal_events_json"]) == []


def test_status_change_records_what_happened_without_resetting_creation():
    with patch("memory.vector_store.vector_store._collection.get") as mock_get, \
         patch("memory.vector_store.vector_store._collection.delete"), \
         patch("memory.vector_store.vector_store.add_texts") as mock_add:
        mock_get.return_value = {
            "ids": ["goal-1"],
            "documents": ["[GOAL] Kaggle: Reach a baseline score"],
            "metadatas": [{
                "project": "Kaggle", "status": "active",
                "created_at": 1_700_000_000.0,
            }],
        }

        assert update_goal_status("Kaggle", "paused") is True

        meta = mock_add.call_args.kwargs["metadatas"][0]
        assert meta["created_at"] == 1_700_000_000.0
        assert json.loads(meta["goal_events_json"])[-1]["detail"] == "status: active → paused"
