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
