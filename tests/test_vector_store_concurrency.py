"""
Deterministic offline concurrency regression tests for semantic memory and vector store.

Verifies that slow remote embedding generation for background fact saves does NOT hold
vector_lock or block foreground semantic retrieval, while ensuring data persistence,
duplicate checks, and retrieval correctness remain intact.
"""

import threading
import time
from unittest.mock import MagicMock

import pytest
from langchain_core.documents import Document

import memory.vector_store as vs
from memory.context_builder import semantic_facts_for_query
from memory.vector_store import AstakosMemoryManager


class _MockDoc:
    def __init__(self, page_content, metadata=None):
        self.page_content = page_content
        self.metadata = metadata or {}


def test_background_fact_save_does_not_block_foreground_retrieval(tmp_path, monkeypatch):
    """
    Prove that while a background thread is waiting for a slow embedding API call during save(),
    a foreground semantic retrieval query acquires vector_lock and completes immediately without
    blocking on the background task.
    """
    memory_mgr = AstakosMemoryManager()
    profile_db_path = str(tmp_path / "test_profile.db")
    monkeypatch.setattr("config.PROFILE_DB", profile_db_path)

    fact_text = "[USER_FACT] Background task is indexing important notes."
    query_text = "important notes"

    bg_embed_started = threading.Event()
    release_bg_embed = threading.Event()
    fg_finished = threading.Event()

    from services.embeddings import embeddings as s_embeddings

    saved_texts = []
    vector_mock = MagicMock()
    vector_mock.similarity_search_with_score.return_value = []
    vector_mock.similarity_search.return_value = [_MockDoc(fact_text, {"category": "general"})]
    vector_mock.similarity_search_by_vector.return_value = [_MockDoc(fact_text, {"category": "general"})]

    monkeypatch.setattr(vs, "vector_store", vector_mock)
    monkeypatch.setattr(vs, "_safe_chroma_add_texts", lambda texts, **kw: saved_texts.extend(texts) or ["id-1"])

    # Mock embeddings to introduce an artificial delay on the background fact embedding call
    def mock_embed_query(text: str) -> list[float]:
        if text == fact_text:
            bg_embed_started.set()
            # Wait until foreground retrieval has completed before proceeding
            released = release_bg_embed.wait(timeout=3.0)
            assert released, "Background embedding wait timed out"
            return [0.1, 0.2, 0.3]
        return [0.1, 0.2, 0.3]

    def mock_embed_documents(texts: list[str]) -> list[list[float]]:
        return [[0.1, 0.2, 0.3] for _ in texts]

    monkeypatch.setattr(s_embeddings, "embed_query", mock_embed_query)
    monkeypatch.setattr(s_embeddings, "embed_documents", mock_embed_documents)
    monkeypatch.setattr(
        vs,
        "_safe_chroma_query",
        lambda *args, **kwargs: {"ids": [[]], "documents": [[]], "metadatas": [[]], "distances": [[]]},
    )
    monkeypatch.setattr(memory_mgr, "_trigger_routine_reconciler", lambda *args, **kwargs: None)

    bg_result = {"success": None}

    def run_bg_save():
        try:
            bg_result["success"] = memory_mgr.save(
                "fact",
                fact=fact_text,
                category="general",
                agent_name="Test_Agent",
            )
        except Exception as e:
            bg_result["error"] = e

    bg_thread = threading.Thread(target=run_bg_save)
    bg_thread.start()

    # Wait until background embedding call has definitely started
    assert bg_embed_started.wait(timeout=2.0), "Background embedding did not start in time"

    # Now execute foreground semantic retrieval while background embedding is still pending
    t0 = time.perf_counter()
    retrieved_facts = semantic_facts_for_query(query_text, k=3)
    fg_duration = time.perf_counter() - t0
    fg_finished.set()

    # The foreground retrieval must have completed quickly (< 500ms) while background was still blocked
    assert fg_duration < 0.5, f"Foreground query blocked unexpectedly: took {fg_duration:.3f}s"
    assert len(retrieved_facts) == 1
    assert fact_text in retrieved_facts[0]

    # Now release the background thread to finish its save
    release_bg_embed.set()
    bg_thread.join(timeout=5.0)
    assert not bg_thread.is_alive(), "Background thread hung"
    assert bg_result["success"] is True, f"Background save failed: {bg_result}"
    assert fact_text in saved_texts


def test_fact_save_never_invokes_embeddings_under_locks(tmp_path, monkeypatch):
    """
    Prove that embed_query and embed_documents are NEVER called while vector_lock,
    memory_lock, or cross_process_lock are held during fact save.
    """
    memory_mgr = AstakosMemoryManager()
    profile_db_path = str(tmp_path / "test_profile_locks.db")
    monkeypatch.setattr("config.PROFILE_DB", profile_db_path)

    fact_text = "[USER_FACT] Lock invariant test fact."
    expected_query_vector = [0.11, 0.22, 0.33]
    expected_doc_vector = [0.44, 0.55, 0.66]

    from services.embeddings import embeddings as s_embeddings

    query_calls = []
    doc_calls = []

    def tracking_embed_query(text: str) -> list[float]:
        # Must NOT hold locks when embedding is computed
        assert not vs.vector_lock.locked(), "vector_lock was held during embed_query!"
        assert not vs.memory_lock.locked(), "memory_lock was held during embed_query!"
        query_calls.append(text)
        return expected_query_vector

    def tracking_embed_documents(texts: list[str]) -> list[list[float]]:
        # Must NOT hold locks when embedding is computed
        assert not vs.vector_lock.locked(), "vector_lock was held during embed_documents!"
        assert not vs.memory_lock.locked(), "memory_lock was held during embed_documents!"
        doc_calls.append(texts)
        return [expected_doc_vector]

    monkeypatch.setattr(s_embeddings, "embed_query", tracking_embed_query)
    monkeypatch.setattr(s_embeddings, "embed_documents", tracking_embed_documents)

    captured_query_embeddings = []
    captured_add_embeddings = []

    def mock_query(*args, **kwargs):
        captured_query_embeddings.append(kwargs.get("query_embeddings"))
        return {"ids": [[]], "documents": [[]], "metadatas": [[]], "distances": [[]]}

    def mock_add(texts, metadatas=None, embeddings=None, ids=None):
        captured_add_embeddings.append(embeddings)
        return ["id-lock-1"]

    monkeypatch.setattr(vs, "_safe_chroma_query", mock_query)
    monkeypatch.setattr(vs, "_safe_chroma_add_texts", mock_add)
    monkeypatch.setattr(memory_mgr, "_trigger_routine_reconciler", lambda *args, **kwargs: None)

    saved = memory_mgr.save("fact", fact=fact_text, category="general", agent_name="Chat_Agent")
    assert saved is True
    assert query_calls == [fact_text]
    assert doc_calls == [[fact_text]]

    # Verify precomputed vectors reached the Chroma query and add paths
    assert any(expected_query_vector in q_emb for q_emb in captured_query_embeddings if q_emb)
    assert captured_add_embeddings == [[expected_doc_vector]]


def test_foreground_retrieval_never_invokes_embeddings_under_vector_lock(monkeypatch):
    """
    Prove that foreground semantic retrieval computes embeddings outside vector_lock
    and passes that exact vector to safe_similarity_search without any embedding work under lock.
    """
    from services.embeddings import embeddings as s_embeddings

    query_text = "Who is Sofia?"
    expected_vector = [0.77, 0.88, 0.99]
    query_calls = []

    def tracking_embed_query(text: str) -> list[float]:
        assert not vs.vector_lock.locked(), "vector_lock was held during embed_query in foreground retrieval!"
        query_calls.append(text)
        return expected_vector

    monkeypatch.setattr(s_embeddings, "embed_query", tracking_embed_query)

    captured_search_call = {}

    def mock_safe_similarity_search(query: str, *, k: int, filter: dict | None = None, query_embedding=None):
        # When called inside vector_lock, verify vector was passed
        assert vs.vector_lock.locked(), "safe_similarity_search expected vector_lock to be held"
        captured_search_call["query"] = query
        captured_search_call["k"] = k
        captured_search_call["query_embedding"] = query_embedding
        return [_MockDoc("[USER_FACT] Sofia is a friend", {"category": "family"})]

    monkeypatch.setattr(vs, "safe_similarity_search", mock_safe_similarity_search)

    results = semantic_facts_for_query(query_text, k=2)
    assert len(results) == 1
    assert query_calls == [query_text]
    assert captured_search_call["query_embedding"] == expected_vector
    assert captured_search_call["k"] == 2


def test_safe_chroma_add_texts_and_similarity_refresh_retries(monkeypatch):
    """
    Prove that _safe_chroma_add_texts and safe_similarity_search both preserve
    stale-handle refresh retry semantics on transient Chroma errors.
    """
    refresh_calls = []
    monkeypatch.setattr(vs, "_refresh_vector_store", lambda reason: refresh_calls.append(reason) or True)

    mock_collection = MagicMock()
    # Attempt 0 fails with a retryable Chroma error; Attempt 1 succeeds
    mock_collection.upsert.side_effect = [RuntimeError("stale collection handle"), None]
    mock_collection.query.return_value = {"ids": [[]], "documents": [[]], "metadatas": [[]], "distances": [[]]}

    vector_mock = MagicMock()
    vector_mock._collection = mock_collection
    vector_mock.similarity_search_by_vector.side_effect = [RuntimeError("stale collection handle"), [_MockDoc("doc1")]]
    monkeypatch.setattr(vs, "vector_store", vector_mock)

    # 1. _safe_chroma_add_texts retries and passes precomputed embeddings
    ids = vs._safe_chroma_add_texts(["test text"], metadatas=[{"k": "v"}], embeddings=[[0.1, 0.2]])
    assert len(ids) == 1
    assert "upsert retry" in refresh_calls
    assert mock_collection.upsert.call_count == 2
    assert mock_collection.upsert.call_args.kwargs["embeddings"] == [[0.1, 0.2]]

    # 2. safe_similarity_search retries with query_embedding
    search_res = vs.safe_similarity_search("dummy", k=1, query_embedding=[0.3, 0.4])
    assert len(search_res) == 1
    assert "similarity retry" in refresh_calls
    assert vector_mock.similarity_search_by_vector.call_count == 2


def test_failed_duplicate_query_aborts_fact_save_fail_closed(tmp_path, monkeypatch):
    """
    Prove that if the duplicate check query in _save_fact fails with an _error,
    the save aborts fail-closed (returns False) without writing to Chroma, profile facts, or routines.
    """
    memory_mgr = AstakosMemoryManager()
    profile_db_path = str(tmp_path / "test_profile_fail_closed.db")
    monkeypatch.setattr("config.PROFILE_DB", profile_db_path)

    fact_text = "[USER_FACT] Fail closed duplicate check fact."

    from services.embeddings import embeddings as s_embeddings
    monkeypatch.setattr(s_embeddings, "embed_query", lambda text: [0.1, 0.2, 0.3])
    monkeypatch.setattr(s_embeddings, "embed_documents", lambda texts: [[0.1, 0.2, 0.3]])

    # Query returns an _error payload after failing
    mock_query = MagicMock(return_value={
        "ids": [[]],
        "documents": [[]],
        "metadatas": [[]],
        "distances": [[]],
        "_error": "Chroma query timeout / SQLite operational error",
    })
    monkeypatch.setattr(vs, "_safe_chroma_query", mock_query)

    mock_add = MagicMock()
    monkeypatch.setattr(vs, "_safe_chroma_add_texts", mock_add)

    mock_profile_save = MagicMock()
    monkeypatch.setattr(memory_mgr, "_save_fact_profile_only", mock_profile_save)
    monkeypatch.setattr(memory_mgr, "_trigger_routine_reconciler", lambda *args, **kwargs: None)

    saved = memory_mgr.save("fact", fact=fact_text, category="general", agent_name="Chat_Agent")

    # Must fail closed
    assert saved is False
    # Chroma must NOT have been written to
    mock_add.assert_not_called()
    # Profile facts DB must NOT have been written to
    mock_profile_save.assert_not_called()
