class _Doc:
    def __init__(self, content, metadata=None):
        self.page_content = content
        self.metadata = metadata or {}


class _VectorStore:
    def __init__(self, results):
        self.results = results
        self._collection = self
        self.calls = []

    def similarity_search(self, query, k=6, filter=None):
        self.calls.append({"query": query, "k": k, "filter": filter})
        return self.results

    def query(self, **kwargs):
        return {"ids": [[]]}


class _Lock:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def test_search_memory_returns_sqlite_and_chroma_sections(monkeypatch):
    import memory.context_builder as context_builder
    import tools.system as system

    monkeypatch.setattr(
        context_builder,
        "temporal_history_for_query",
        lambda query, channel="telegram", limit=8: [
            "- [telegram 11:17] Λάζαρος: Είμαστε στο τελικό ποδόσφαιρο με τον Αλέξανδρο."
        ],
    )
    monkeypatch.setattr(system, "vector_lock", _Lock())
    monkeypatch.setattr(
        system,
        "vector_store",
        _VectorStore([
            _Doc("[USER_FACT]: Ο Αλέξανδρος έχει ποδόσφαιρο.", {"category": "family"})
        ]),
    )

    result = system.search_memory.func("Αλέξανδρος ποδόσφαιρο")

    assert "[ΣΧΕΤΙΚΟ ΙΣΤΟΡΙΚΟ SQLITE]" in result
    assert "[ΣΧΕΤΙΚΕΣ ΜΝΗΜΕΣ CHROMA]" in result
    assert "τελικό ποδόσφαιρο" in result
    assert "Ο Αλέξανδρος έχει ποδόσφαιρο" in result


def test_search_memory_can_return_sqlite_when_chroma_empty(monkeypatch):
    import memory.context_builder as context_builder
    import tools.system as system

    monkeypatch.setattr(
        context_builder,
        "temporal_history_for_query",
        lambda query, channel="telegram", limit=8: [
            "- [web 12:30] Λάζαρος: Ετοιμαζόμαστε για πάρκο με τη Σοφία."
        ],
    )
    monkeypatch.setattr(system, "vector_lock", _Lock())
    monkeypatch.setattr(system, "vector_store", _VectorStore([]))

    result = system.search_memory.func("πάρκο Σοφία")

    assert "[ΣΧΕΤΙΚΟ ΙΣΤΟΡΙΚΟ SQLITE]" in result
    assert "Ετοιμαζόμαστε για πάρκο" in result
    assert "Δεν βρέθηκαν Chroma facts" in result
