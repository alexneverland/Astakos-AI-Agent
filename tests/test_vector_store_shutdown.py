import pytest
from unittest.mock import MagicMock, patch
from memory.vector_store import close_vector_store
import memory.vector_store

def test_close_vector_store_calls_client_close(monkeypatch):
    """Ensure close_vector_store calls _client.close() if client exists."""
    # Create a mock vector_store object with a mock _client
    mock_client = MagicMock()
    mock_vector_store = MagicMock()
    mock_vector_store._client = mock_client
    
    # Patch the global vector_store
    monkeypatch.setattr(memory.vector_store, "vector_store", mock_vector_store)
    
    # Call the function
    close_vector_store()
    
    # Assert _client.close() was called exactly once
    mock_client.close.assert_called_once()

def test_close_vector_store_handles_missing_client(monkeypatch, capsys):
    """Ensure close_vector_store doesn't crash if _client is missing."""
    mock_vector_store = MagicMock(spec=[]) # No _client attribute
    
    monkeypatch.setattr(memory.vector_store, "vector_store", mock_vector_store)
    
    close_vector_store()
    
    # Should not raise exception
    out, err = capsys.readouterr()
    assert "Error closing ChromaDB" not in out

def test_close_vector_store_handles_none_store(monkeypatch):
    """Ensure close_vector_store doesn't crash if vector_store is None."""
    monkeypatch.setattr(memory.vector_store, "vector_store", None)
    
    # Should not raise exception
    close_vector_store()

def test_close_vector_store_handles_exceptions(monkeypatch, capsys):
    """Ensure exceptions during close are caught and logged."""
    mock_client = MagicMock()
    mock_client.close.side_effect = Exception("Simulated DB Crash")
    
    mock_vector_store = MagicMock()
    mock_vector_store._client = mock_client
    
    monkeypatch.setattr(memory.vector_store, "vector_store", mock_vector_store)
    
    close_vector_store()
    
    out, err = capsys.readouterr()
    assert "[VectorStore]: Error closing ChromaDB: Simulated DB Crash" in out
