def test_search_memory_includes_structured_profile_block(monkeypatch):
    from tools import system

    monkeypatch.setattr(system, "_expand_memory_query", lambda q: ([q], "family"))
    monkeypatch.setattr(system, "_lexical_memory_matches", lambda *a, **k: [])

    class DummyCollection:
        def query(self, **kwargs):
            return {"ids": [[]]}

    class DummyStore:
        _collection = DummyCollection()
        def similarity_search(self, *args, **kwargs):
            return []

    monkeypatch.setattr(system.vector_memory, "vector_store", DummyStore())
    monkeypatch.setattr(system, "embeddings", type("E", (), {"embed_query": lambda self, x: [0.0]})())
    import threading
    monkeypatch.setattr(system, "vector_lock", threading.Lock())

    import memory.vector_store as vs
    monkeypatch.setattr(vs, "get_latest_state_for_query", lambda query, category=None: {
        "fact": "[USER_FACT]: Ο Kid1 γύρισε σπίτι"
    })
    monkeypatch.setattr(vs, "build_profile_memory_summary", lambda query, category=None, limit=5: [
        "  • [USER_FACT]: Ο Kid1 γύρισε σπίτι [entities=Kid1 | topic=trip | rel=state_update | states=returned]"
    ])

    import memory.context_builder as cb
    monkeypatch.setattr(cb, "temporal_history_for_query", lambda *a, **k: [])

    result = system.search_memory.func("Kid1 γύρισε σπίτι", "family")

    assert "[LATEST MATCHING STATE]" in result
    assert "[STRUCTURED PROFILE MEMORY]" in result
    assert "Kid1 γύρισε σπίτι" in result
