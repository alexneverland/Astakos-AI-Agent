import json
import sqlite3

import pytest
from unittest.mock import patch, MagicMock

import memory.vector_store as vs
from core.ai_provider import EmbeddingsProviderSetupRequired, ProviderAuthError
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


def test_safe_chroma_query_retries_after_error_finding_id(monkeypatch):
    class _Collection:
        def __init__(self):
            self.calls = 0

        def query(self, **kwargs):
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("Error executing plan: Internal error: Error finding id")
            return {"ids": [["ok"]], "documents": [["doc"]], "metadatas": [[{}]], "distances": [[0.1]]}

    class _VectorStore:
        def __init__(self):
            self._collection = _Collection()

    mock_store = _VectorStore()
    monkeypatch.setattr(vs, "vector_store", mock_store)
    monkeypatch.setattr(vs, "_refresh_vector_store", lambda reason="": True)

    result = vs._safe_chroma_query(query_embeddings=[[0.1, 0.2]], n_results=1)

    assert result["ids"] == [["ok"]]
    assert mock_store._collection.calls == 2


def test_similarity_search_uses_reopened_store_after_error_finding_id(monkeypatch):
    """A refresh must replace a stale imported Chroma handle for later searches."""
    stale_store = MagicMock()
    stale_store.similarity_search.side_effect = RuntimeError(
        "Error executing plan: Internal error: Error finding id",
    )
    refreshed_store = MagicMock()
    refreshed_store.similarity_search.return_value = ["fresh result"]

    monkeypatch.setattr(vs, "vector_store", stale_store)

    def replace_store(reason=""):
        monkeypatch.setattr(vs, "vector_store", refreshed_store)
        return True

    monkeypatch.setattr(vs, "_refresh_vector_store", replace_store)

    assert vs.safe_similarity_search("test", k=3) == ["fresh result"]
    refreshed_store.similarity_search.assert_called_once_with("test", k=3)


def test_similarity_search_propagates_embeddings_setup_errors(monkeypatch):
    """A missing semantic-memory backend must not masquerade as no memories."""
    store = MagicMock()
    store.similarity_search.side_effect = EmbeddingsProviderSetupRequired(
        "Configure an embeddings provider.",
        provider="anthropic",
    )
    monkeypatch.setattr(vs, "vector_store", store)

    with pytest.raises(EmbeddingsProviderSetupRequired, match="Configure an embeddings provider"):
        vs.safe_similarity_search("test", k=3)


def test_similarity_search_propagates_embeddings_auth_errors(monkeypatch):
    """An invalid embeddings key must not look like an empty memory result."""
    store = MagicMock()
    store.similarity_search.side_effect = ProviderAuthError(
        "openai",
        "OPENAI_API_KEY is not configured.",
    )
    monkeypatch.setattr(vs, "vector_store", store)

    with pytest.raises(ProviderAuthError, match="OPENAI_API_KEY"):
        vs.safe_similarity_search("test", k=3)


def test_chroma_query_propagates_embeddings_auth_errors(monkeypatch):
    """Authentication failures must also escape the low-level query helper."""
    collection = MagicMock()
    collection.query.side_effect = ProviderAuthError(
        "openai",
        "OPENAI_API_KEY is not configured.",
    )
    store = MagicMock()
    store._collection = collection
    monkeypatch.setattr(vs, "vector_store", store)

    with pytest.raises(ProviderAuthError, match="OPENAI_API_KEY"):
        vs._safe_chroma_query(query_embeddings=[[0.1]], n_results=1)


def test_fact_save_preserves_structured_profile_without_embeddings(monkeypatch, tmp_path):
    """Facts remain available to structured retrieval if semantic setup is incomplete."""
    profile_db = tmp_path / "profile.db"
    monkeypatch.setattr("config.PROFILE_DB", str(profile_db))
    monkeypatch.setattr(
        vs.embeddings,
        "embed_query",
        MagicMock(
            side_effect=EmbeddingsProviderSetupRequired(
                "Configure an embeddings provider.",
                provider="anthropic",
            ),
        ),
    )
    monkeypatch.setattr(vs.AstakosMemoryManager, "_trigger_routine_reconciler", lambda *args, **kwargs: None)

    saved = AstakosMemoryManager().save(
        "fact",
        fact="[USER_FACT]: Ο Αλέξανδρος αγαπά τις φακές",
        category="family",
        agent_name="test_agent",
        reason="user_stated",
    )

    assert saved is True
    with sqlite3.connect(profile_db) as connection:
        rows = connection.execute("SELECT category, fact FROM profile_facts").fetchall()
    assert rows == [("family", "[USER_FACT]: Ο Αλέξανδρος αγαπά τις φακές")]


@pytest.mark.parametrize(
    ("memory_type", "entry_key"),
    [
        ("photo", "analysis"),
        ("document", "summary"),
    ],
)
def test_confirmed_asset_save_preserves_nonsemantic_archive_without_embeddings(
    monkeypatch,
    tmp_path,
    memory_type,
    entry_key,
):
    """Confirmed files remain archived if their optional semantic index is unavailable."""
    index_path = tmp_path / f"{memory_type}_index.json"
    if memory_type == "photo":
        monkeypatch.setattr(vs, "PHOTOS_INDEX_FILE", str(index_path))
    else:
        monkeypatch.setattr("config.DOCS_INDEX_FILE", str(index_path))
    monkeypatch.setattr(
        vs.vector_store,
        "add_texts",
        MagicMock(
            side_effect=EmbeddingsProviderSetupRequired(
                "Configure an embeddings provider.",
                provider="anthropic",
            ),
        ),
    )

    saved = AstakosMemoryManager().save(
        memory_type,
        file_path="C:/example/file.pdf",
        analysis="Confirmed archive content",
        caption="Example file",
    )

    assert saved is True
    entries = json.loads(index_path.read_text(encoding="utf-8"))
    assert entries[0]["file_path"] == "C:/example/file.pdf"
    assert entries[0][entry_key] == "Confirmed archive content"
