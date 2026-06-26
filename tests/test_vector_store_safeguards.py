import pytest
from unittest.mock import patch, MagicMock

import memory.vector_store as vs
from memory.vector_store import AstakosMemoryManager

@pytest.fixture
def memory_mgr():
    return AstakosMemoryManager()

def test_same_cat_query_failure_is_graceful(memory_mgr, monkeypatch):
    def mock_query(*args, **kwargs):
        return {
            "ids": [[]],
            "documents": [[]],
            "metadatas": [[]],
            "distances": [[]],
            "_error": "Mocked query error"
        }
    
    monkeypatch.setattr(vs, "_safe_chroma_query", mock_query)
    
    mock_add = MagicMock()
    monkeypatch.setattr(vs.vector_store, "add_texts", mock_add)
    
    mock_audit = MagicMock()
    monkeypatch.setattr(vs, "_audit_log", mock_audit)

    memory_mgr.save("fact", fact="[USER_FACT] I like apples", category="preferences", agent_name="test_agent")
    
    call_args_list = [call.args[0] for call in mock_audit.call_args_list]
    assert "overwrite" not in call_args_list
    assert "delete_skip" not in call_args_list

def test_cross_query_failure_is_graceful(memory_mgr, monkeypatch):
    def mock_query(*args, **kwargs):
        if kwargs.get("where") and kwargs["where"].get("category"):
            return {"ids": [[]], "documents": [[]], "metadatas": [[]], "distances": [[]]}
        else:
            return {
                "ids": [[]],
                "documents": [[]],
                "metadatas": [[]],
                "distances": [[]],
                "_error": "Mocked cross error"
            }

    monkeypatch.setattr(vs, "_safe_chroma_query", mock_query)
    
    mock_add = MagicMock()
    monkeypatch.setattr(vs.vector_store, "add_texts", mock_add)

    memory_mgr.save("fact", fact="[USER_FACT] I like oranges", category="preferences", agent_name="test_agent")
    # Should not crash and should not do cross logic

def test_delete_failure_is_audited_but_save_continues(memory_mgr, monkeypatch):
    def mock_query(*args, **kwargs):
        if kwargs.get("where") and kwargs["where"].get("category") == "preferences":
            return {
                "ids": [["old_id_123"]],
                "documents": [["[USER_FACT] I like apples"]],
                "metadatas": [[{"category": "preferences"}]],
                "distances": [[0.05]]
            }
        return {"ids": [[]], "documents": [[]], "metadatas": [[]], "distances": [[]]}

    monkeypatch.setattr(vs, "_safe_chroma_query", mock_query)
    
    def mock_delete(*args, **kwargs):
        return False
    
    monkeypatch.setattr(vs, "_safe_chroma_delete", mock_delete)
    
    mock_add = MagicMock()
    monkeypatch.setattr(vs.vector_store, "add_texts", mock_add)
    
    mock_audit = MagicMock()
    monkeypatch.setattr(vs, "_audit_log", mock_audit)

    # Force decision to overwrite
    def mock_decide_action(*args, **kwargs):
        return {"action": "overwrite", "overlap": 1.0}

    monkeypatch.setattr(vs, "decide_memory_storage_action", mock_decide_action)
    monkeypatch.setattr(vs, "decide_memory_overwrite", MagicMock(return_value={"looks_like_correction": False, "stale": False, "old_richness": 1.0, "new_richness": 1.0, "old_age_days": 1}))

    memory_mgr.save("fact", fact="[USER_FACT] I like apples", category="preferences", agent_name="test_agent")
    
    call_events = [call.args[0] for call in mock_audit.call_args_list]
    assert "delete_skip" in call_events
