import pytest
from unittest.mock import MagicMock
import memory.vector_store as vs
from memory.vector_store import AstakosMemoryManager

@pytest.fixture
def memory_mgr():
    return AstakosMemoryManager()

def test_cross_category_warning_suppressed_for_unrelated(memory_mgr, monkeypatch, capsys):
    # Mock same_cat query to find nothing
    def mock_same_cat_query(*args, **kwargs):
        if kwargs.get('where'):
            return {"ids": [[]], "documents": [[]], "metadatas": [[]], "distances": [[]]}
        # cross query returns something very distant in meaning but somehow close in distance
        return {
            "ids": [["old_parkour_123"]],
            "documents": [["[USER_FACT] O Χρήστος κάνει παρκούρ κάθε μέρα."]],
            "metadatas": [[{"category": "sports"}]],
            "distances": [[0.15]]
        }
        
    monkeypatch.setattr(vs, "_safe_chroma_query", mock_same_cat_query)
    
    mock_add = MagicMock()
    monkeypatch.setattr(vs.vector_store, "add_texts", mock_add)
    monkeypatch.setattr(vs.vector_store, "similarity_search_with_score", MagicMock(return_value=[]))

    memory_mgr.save("fact", fact="[USER_FACT] Ο μετρητής ΔΕΔΔΗΕ είναι στο ισόγειο", category="home", agent_name="test_agent")
    
    # Verify no print
    captured = capsys.readouterr()
    assert "⚠️ Κοντινή μνήμη σε άλλη category" not in captured.out
    
    # Should proceed to add
    mock_add.assert_called_once()

def test_user_fact_not_skipped_when_lexical_poor(memory_mgr, monkeypatch):
    # Mock same_cat to find nothing so we reach duplicate logic
    monkeypatch.setattr(vs, "_safe_chroma_query", MagicMock(return_value={"ids": [[]], "documents": [[]], "metadatas": [[]], "distances": [[]]}))
    
    class MockDoc:
        def __init__(self, content):
            self.page_content = content
            self.metadata = {"category": "home"}

    # Mock similarity_search_with_score to return embedding-near but lexical-poor doc
    # Score is < 0.25 threshold, so without lexical guard it would duplicate skip
    mock_search = MagicMock(return_value=[(MockDoc("[USER_FACT] Η τηλεόραση είναι χαλασμένη"), 0.15)])
    monkeypatch.setattr(vs.vector_store, "similarity_search_with_score", mock_search)
    
    mock_add = MagicMock()
    monkeypatch.setattr(vs.vector_store, "add_texts", mock_add)

    # They have 0 shared meaningful tokens
    memory_mgr.save("fact", fact="[USER_FACT] Ο μετρητής ΔΕΔΔΗΕ είναι στο ισόγειο", category="home", agent_name="test_agent")
    
    # Should NOT duplicate skip, should proceed to add
    mock_add.assert_called_once()

def test_user_fact_skipped_when_lexical_overlap_exists(memory_mgr, monkeypatch):
    monkeypatch.setattr(vs, "_safe_chroma_query", MagicMock(return_value={"ids": [[]], "documents": [[]], "metadatas": [[]], "distances": [[]]}))
    
    class MockDoc:
        def __init__(self, content):
            self.page_content = content
            self.metadata = {"category": "home"}

    # Mock similarity_search_with_score to return embedding-near AND lexical-rich doc
    # Score < 0.25 and shared tokens >= 2 ("μετρητής", "δεδδηε")
    mock_search = MagicMock(return_value=[(MockDoc("[USER_FACT] Ο μετρητής ΔΕΔΔΗΕ βρίσκεται στο ισόγειο"), 0.15)])
    monkeypatch.setattr(vs.vector_store, "similarity_search_with_score", mock_search)
    
    mock_add = MagicMock()
    monkeypatch.setattr(vs.vector_store, "add_texts", mock_add)

    # Should have shared tokens "μετρητής", "δεδδηε", "ισόγειο" -> 3 tokens
    result = memory_mgr.save("fact", fact="[USER_FACT] Ο μετρητής ΔΕΔΔΗΕ είναι στο ισόγειο", category="home", agent_name="test_agent")
    
    # Should duplicate skip and NOT add
    mock_add.assert_not_called()
    assert result is False
