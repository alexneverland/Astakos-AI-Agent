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

    def get(self, **kwargs):
        docs = []
        metas = []
        where = kwargs.get("where") or {}
        for doc in self.results:
            if where and doc.metadata.get("category") != where.get("category"):
                continue
            docs.append(doc.page_content)
            metas.append(doc.metadata)
        return {"documents": docs, "metadatas": metas, "ids": [str(i) for i in range(len(docs))]}


class _Lock:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def test_search_memory_expands_gift_queries_without_hardcoded_product(monkeypatch):
    import memory.context_builder as context_builder
    import tools.system as system

    seen_sql_queries = []

    def fake_history(query, channel="telegram", limit=8):
        seen_sql_queries.append(query)
        return [
            "- [telegram 19:30] Αστακός: Αποθηκεύτηκε στη μνήμη στα μελλοντικά δώρα για τη Σοφία (Rosefield Bangle S - White Gold)."
        ]

    store = _VectorStore([
        _Doc(
            "Ιδέα για δώρο στη Σοφία: Ρολόι Rosefield Bangle S (White Gold) από το link: https://eu.rosefieldwatches.com/products/bangle-s-white-gold",
            {"category": "family"},
        )
    ])

    monkeypatch.setattr(context_builder, "temporal_history_for_query", fake_history)
    monkeypatch.setattr(system, "vector_lock", _Lock())
    monkeypatch.setattr(system, "vector_store", store)

    result = system.search_memory.func("Θυμάσαι δώρο για τα γενέθλια της Σοφίας;")

    assert "Rosefield Bangle S" in result
    assert "eu.rosefieldwatches.com" in result
    assert "μελλοντικό δώρο" in seen_sql_queries[0]
    assert "Rosefield" not in seen_sql_queries[0]
    assert all("Rosefield" not in call["query"] for call in store.calls)
    assert any(call["filter"] == {"category": "family"} for call in store.calls)
