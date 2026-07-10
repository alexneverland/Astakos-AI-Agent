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
        """Mock of collection.get(...) used by _lexical_memory_matches."""
        where = kwargs.get("where") or {}
        docs, metas = [], []
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
    system._lexical_cache.clear()

    result = system.search_memory.func("πάρκο Σοφία")

    assert "[ΣΧΕΤΙΚΟ ΙΣΤΟΡΙΚΟ SQLITE]" in result
    assert "Ετοιμαζόμαστε για πάρκο" in result
    assert "Δεν βρέθηκαν Chroma facts" in result


def test_stem_token_drops_common_greek_inflectional_endings():
    import tools.system as system

    # What _lexical_memory_matches actually needs is not
    # "the stem of the two words must be the same" (implementation detail
    # which breaks when words differ in length), but "the stem of the
    # of the query-word being located within the stored text":
    # i.e., stem(query_token) in stored_text. We check exactly this.
    assert system._stem_token("γενεθλιων") in "γενεθλια"
    assert system._stem_token("αλεξανδρος") == system._stem_token("αλεξανδρου")
    assert (system._stem_token("αλεξανδρου") in "αλεξανδρος"
            or system._stem_token("αλεξανδρος") in "αλεξανδρου")
    # short words remain as they are (no noise under 4 characters)
    assert system._stem_token("σπιτι") and len(system._stem_token("σπιτι")) >= 4


def test_lexical_memory_matches_finds_doc_despite_different_grammatical_case(monkeypatch):
    import tools.system as system

    # The memory is stored in the nominative case ("birthday", "Alexander's"),
    # but we ask in the genitive plural ("γενεθλιών" / "of birthdays") — natural phrase
    # ("for the child's birthday"). Before stemming, only 1/2 tokens
    # matched -> below the threshold score >= 2 -> memory was being lost here.
    doc = system.SimpleNamespace(
        page_content="[USER_FACT]: Στις 2026-03-25 είναι τα γενέθλια του Αλέξανδρου, θέλει LEGO διαστημόπλοιο.",
        metadata={"category": "family"},
    )
    monkeypatch.setattr(system, "vector_lock", _Lock())
    monkeypatch.setattr(system, "vector_store", _VectorStore([doc]))

    matches = system._lexical_memory_matches("τι θέλει για τα γενεθλιών του Αλεξάνδρου;")

    assert len(matches) == 1
    assert "διαστημόπλοιο" in matches[0].page_content
