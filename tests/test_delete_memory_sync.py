import threading


def test_delete_from_memory_removes_matching_profile_fact(monkeypatch):
    from tools import system

    class FakeCollection:
        def __init__(self):
            self.deleted_ids = []

        def get(self, include):
            return {
                "ids": ["camp-question"],
                "documents": [
                    "[USER_FACT]: Στις 2026-07-18, θυμασαι που ο λαεξανδροσ ειχε παει κατασκινωση?"
                ],
                "metadatas": [{}],
            }

        def delete(self, ids):
            self.deleted_ids.extend(ids)

    collection = FakeCollection()
    monkeypatch.setattr(
        system.vector_memory,
        "vector_store",
        type("FakeStore", (), {"_collection": collection})(),
    )
    monkeypatch.setattr(system, "vector_lock", threading.Lock())

    deleted_profile_facts = []
    monkeypatch.setattr(
        system,
        "delete_profile_facts_by_exact_fact",
        lambda fact: deleted_profile_facts.append(fact) or 1,
    )

    result = system.delete_from_memory.func("λαεξανδροσ ειχε παει κατασκινωση")

    assert collection.deleted_ids == ["camp-question"]
    assert deleted_profile_facts == [
        "[USER_FACT]: Στις 2026-07-18, θυμασαι που ο λαεξανδροσ ειχε παει κατασκινωση?"
    ]
    assert "Chroma + 1 structured profile record" in result


def test_delete_from_memory_aborts_when_exact_scan_fails(monkeypatch):
    """A failed exact-match scan must not fall through to semantic deletion."""
    from tools import system

    monkeypatch.setattr(system, "vector_lock", threading.Lock())
    monkeypatch.setattr(
        system.vector_memory,
        "_safe_chroma_get",
        lambda **kwargs: {"ids": [], "documents": [], "metadatas": [], "_error": "query failed"},
    )
    monkeypatch.setattr(
        system.vector_memory,
        "_safe_chroma_query",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("semantic fallback must not run")),
    )

    result = system.delete_from_memory.func("παλιά λάθος διεύθυνση")

    assert result == "Deletion error: Chroma scan could not complete safely."


def test_delete_from_memory_surfaces_semantic_query_failure(monkeypatch):
    """A failed semantic fallback must not be reported as an empty search result."""
    from tools import system

    monkeypatch.setattr(system, "vector_lock", threading.Lock())
    monkeypatch.setattr(
        system.vector_memory,
        "_safe_chroma_get",
        lambda **kwargs: {"ids": [], "documents": [], "metadatas": []},
    )
    monkeypatch.setattr(
        system.vector_memory,
        "_safe_chroma_query",
        lambda **kwargs: {"ids": [[]], "documents": [[]], "metadatas": [[]], "_error": "query failed"},
    )
    monkeypatch.setattr(
        system.embeddings,
        "embed_query",
        lambda query: [0.1, 0.2],
    )

    result = system.delete_from_memory.func("παλιά λάθος διεύθυνση")

    assert result == "Deletion error: Chroma search could not complete safely."


def test_delete_from_memory_removes_profile_only_fact_without_embeddings(monkeypatch):
    """Structured-only fallback facts remain erasable while semantic search is offline."""
    from tools import system

    monkeypatch.setattr(system, "vector_lock", threading.Lock())
    monkeypatch.setattr(
        system.vector_memory,
        "_safe_chroma_get",
        lambda **kwargs: {"ids": [], "documents": [], "metadatas": []},
    )
    monkeypatch.setattr(
        system,
        "get_profile_facts",
        lambda limit=300: [{"fact": "[USER_FACT]: Η Σοφία δουλεύει εκτός σπιτιού"}],
    )
    deleted = []
    monkeypatch.setattr(
        system,
        "delete_profile_facts_by_exact_fact",
        lambda fact: deleted.append(fact) or 1,
    )
    monkeypatch.setattr(
        system.embeddings,
        "embed_query",
        lambda _query: (_ for _ in ()).throw(AssertionError("semantic fallback must not run")),
    )

    result = system.delete_from_memory.func("Σοφία δουλεύει εκτός")

    assert deleted == ["[USER_FACT]: Η Σοφία δουλεύει εκτός σπιτιού"]
    assert "structured profile only" in result
