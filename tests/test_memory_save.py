"""
Tests for AstakosMemoryManager.save() with mocked dependencies.
No live ChromaDB is required.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from unittest.mock import patch, MagicMock


# -- Routing tests (correct function per memory_type) ---------------

def test_save_fact_calls_save_fact():
    from memory.vector_store import AstakosMemoryManager
    m = AstakosMemoryManager()
    with patch.object(m, '_save_fact', return_value=True) as mock:
        m.save(memory_type="fact", fact="test", category="general", agent_name="Chat_Agent")
        mock.assert_called_once_with(fact="test", category="general", agent_name="Chat_Agent")

def test_save_reflection_calls_save_reflection():
    from memory.vector_store import AstakosMemoryManager
    m = AstakosMemoryManager()
    with patch.object(m, '_save_reflection', return_value=True) as mock:
        m.save(memory_type="reflection", source="planner", observation="test obs",
               action="save_to_memory", confidence=0.8)
        mock.assert_called_once()

def test_save_event_calls_save_event():
    from memory.vector_store import AstakosMemoryManager
    m = AstakosMemoryManager()
    with patch.object(m, '_save_event', return_value=True) as mock:
        m.save(memory_type="event", job="routines", action="triggered")
        mock.assert_called_once_with(job="routines", action="triggered")

def test_save_session_calls_save_session():
    from memory.vector_store import AstakosMemoryManager
    m = AstakosMemoryManager()
    with patch.object(m, '_save_session', return_value=True) as mock:
        m.save(memory_type="session", summary={}, session_text="test")
        mock.assert_called_once()

def test_save_unknown_type_returns_none():
    from memory.vector_store import AstakosMemoryManager
    m = AstakosMemoryManager()
    result = m.save(memory_type="unknown_xyz")
    assert result is None

def test_save_exception_returns_false():
    from memory.vector_store import AstakosMemoryManager
    m = AstakosMemoryManager()
    with patch.object(m, '_save_fact', side_effect=Exception("DB error")):
        result = m.save(memory_type="fact", fact="test", category="x", agent_name="y")
        assert result is False
