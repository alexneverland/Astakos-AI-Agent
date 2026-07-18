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
        system,
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
