"""
Tests for the UNIFIED overwrite in AstakosMemoryManager._save_fact:
A SINGLE decision (decide_memory_overwrite) must guide BOTH Chroma
AND the JSON Profile — not two independent (and potentially conflicting) passes.

Covers:
  (a) keep_old=True  -> return False, NO write to Chroma or JSON (no dup write)
  (b) keep_old=False -> the exact same record is replaced in both stores
  (c) general facts (not [LESSON]/[USER_FACT], no nearby old record)
      -> added normally to both stores, without divergence
"""
import json
import os
import sys
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from memory.vector_store import AstakosMemoryManager


def _make_same_cat_result(old_id, old_content, distance, old_meta=None):
    """Mimics the returned shape of vector_store._collection.query()."""
    return {
        "ids": [[old_id]],
        "documents": [[old_content]],
        "metadatas": [[old_meta or {"category": "family", "timestamp": 0, "confidence": 0.7}]],
        "distances": [[distance]],
    }


def _empty_query_result():
    return {"ids": [[]], "documents": [[]], "metadatas": [[]], "distances": [[]]}


def _patched_save_fact(profile_path, decision, same_cat_result):
    """
    Context manager: patches everything needed by _save_fact so that it runs
    without real Chroma/Gemini, with a controlled decide_memory_overwrite.
    Returns the mocks so that the test can run assertions on them.
    """
    return patch.multiple(
        "memory.vector_store",
        decide_memory_overwrite=MagicMock(return_value=decision),
    ), patch("config.PROFILE_DB", new=profile_path)


def _run_save_fact(tmp_path, fact, category, decision, same_cat_result,
                   profile_seed=None, dup_results=None):
    """
    Runs _save_fact with fully mocked Chroma collection / embeddings / similarity
    search, controlled decide_memory_overwrite, and a real (temporary) JSON
    profile file. Returns (result, mocks-dict, profile-db-after).
    """
    profile_path = str(tmp_path / "astakos_profile.db")
    if profile_seed is not None:
        import sqlite3
        conn = sqlite3.connect(profile_path)
        try:
            c = conn.cursor()
            c.execute('''
                CREATE TABLE IF NOT EXISTS profile_facts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    category TEXT NOT NULL,
                    fact TEXT NOT NULL,
                    photo_path TEXT,
                    date TEXT,
                    metadata_json TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            for cat, facts in profile_seed.items():
                for f in facts:
                    fact_str = f.get("fact", f) if isinstance(f, dict) else str(f)
                    c.execute("INSERT INTO profile_facts (category, fact) VALUES (?, ?)", (cat, fact_str))
            conn.commit()
        finally:
            conn.close()

    m = AstakosMemoryManager()

    mock_collection = MagicMock()
    mock_collection.query.return_value = same_cat_result
    mock_collection.delete = MagicMock()

    with patch("memory.vector_store.decide_memory_overwrite", return_value=decision), \
         patch("memory.vector_store.embeddings") as mock_embeddings, \
         patch.object(type(__import__("memory.vector_store", fromlist=["vector_store"]).vector_store),
                      "_collection", new_callable=lambda: mock_collection), \
         patch("memory.vector_store.vector_store") as mock_vs, \
         patch("config.PROFILE_DB", profile_path):

        mock_embeddings.embed_query.return_value = [0.1, 0.2, 0.3]
        mock_vs._collection = mock_collection
        mock_vs.similarity_search_with_score.return_value = dup_results or []
        mock_vs.add_texts = MagicMock()

        result = m._save_fact(fact=fact, category=category, agent_name="Chat_Agent",
                              source="user_stated", reason="user_stated")

    db_out = {}
    if os.path.exists(profile_path):
        import sqlite3
        conn = sqlite3.connect(profile_path)
        try:
            c = conn.cursor()
            # Verify table exists before querying
            c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='profile_facts'")
            if c.fetchone():
                c.execute("SELECT category, fact FROM profile_facts")
                for cat, fact_str in c.fetchall():
                    if cat not in db_out:
                        db_out[cat] = []
                    db_out[cat].append(fact_str)
        finally:
            conn.close()
        
    return result, mock_collection, mock_vs, db_out


# ──────────────────────────────────────────────────────────────────
# (a) keep_old=True -> no duplicate entries anywhere
# ──────────────────────────────────────────────────────────────────

def test_keep_old_returns_false_and_writes_nothing(tmp_path):
    old_content = "[USER_FACT]: Στις 2026-05-20 ο Kid1 πήγε στο πάρκο με τη Partner"
    new_fact = "[USER_FACT]: Ο Kid1 πάει συχνά βόλτα"

    decision = {
        "keep_old": True, "looks_like_correction": False, "stale": False,
        "old_age_days": 1, "new_richness": 1.0, "old_richness": 3.0, "much_longer": False,
    }
    same_cat = _make_same_cat_result("old-id-1", old_content, 0.10)
    profile_seed = {"family": [old_content]}

    result, mock_collection, mock_vs, db_after = _run_save_fact(
        tmp_path, new_fact, "family", decision, same_cat, profile_seed=profile_seed,
    )

    # The function must stop immediately — nothing is written anywhere.
    assert result is False
    mock_collection.delete.assert_not_called()
    mock_vs.add_texts.assert_not_called()

    # The JSON Profile remains EXACTLY as it was — no append, no replace.
    assert db_after == profile_seed


# ──────────────────────────────────────────────────────────────────
# (b) keep_old=False -> SAME record is replaced in both stores
# ──────────────────────────────────────────────────────────────────

def test_overwrite_replaces_same_entry_in_both_stores(tmp_path):
    old_content = "[USER_FACT]: Λάθος παλιά διεύθυνση Πεστών 7"
    new_fact = "[USER_FACT]: Λάθος, η σωστή διεύθυνση είναι Πίστων 7"

    decision = {
        "keep_old": False, "looks_like_correction": True, "stale": False,
        "old_age_days": 1, "new_richness": 2.0, "old_richness": 1.0, "much_longer": False,
    }
    same_cat = _make_same_cat_result("old-id-2", old_content, 0.05)
    # An irrelevant fact + the one to be replaced — ONLY the correct index must change.
    profile_seed = {"family": ["[USER_FACT]: κάτι άσχετο", old_content]}

    result, mock_collection, mock_vs, db_after = _run_save_fact(
        tmp_path, new_fact, "family", decision, same_cat, profile_seed=profile_seed,
    )

    # Chroma: the old entry is deleted, the new one is added — ONCE.
    mock_collection.delete.assert_called_once_with(ids=["old-id-2"])
    mock_vs.add_texts.assert_called_once()
    assert mock_vs.add_texts.call_args.args[0] == [new_fact]

    # JSON Profile: EXACTLY the same record is replaced (exact-text match) —
    # the irrelevant fact remains intact, there is NO addition/duplicate.
    assert len(db_after["family"]) == 2
    assert db_after["family"][0] == "[USER_FACT]: κάτι άσχετο"
    assert db_after["family"][1] == new_fact


def test_overwrite_appends_when_no_matching_json_entry_found(tmp_path):
    """Pre-existing divergence: Chroma had something that JSON never had —
    the new fact is added (no silent loss), it does not crash."""
    old_content = "[USER_FACT]: Παλιό fact που υπήρχε ΜΟΝΟ στη Chroma"
    new_fact = "[USER_FACT]: Νέο, σωστότερο fact"

    decision = {
        "keep_old": False, "looks_like_correction": True, "stale": False,
        "old_age_days": 1, "new_richness": 2.0, "old_richness": 1.0, "much_longer": False,
    }
    same_cat = _make_same_cat_result("old-id-3", old_content, 0.05)
    profile_seed = {"family": ["[USER_FACT]: κάτι εντελώς διαφορετικό"]}

    result, mock_collection, mock_vs, db_after = _run_save_fact(
        tmp_path, new_fact, "family", decision, same_cat, profile_seed=profile_seed,
    )

    mock_collection.delete.assert_called_once_with(ids=["old-id-3"])
    assert len(db_after["family"]) == 2
    assert new_fact in db_after["family"]
    assert "[USER_FACT]: κάτι εντελώς διαφορετικό" in db_after["family"]


# ──────────────────────────────────────────────────────────────────
# (c) General facts (no nearby old record) -> normal append everywhere
# ──────────────────────────────────────────────────────────────────

def test_general_fact_with_no_close_match_appends_to_both_stores(tmp_path):
    new_fact = "Ο User δοκίμασε νέα συνταγή με φακές το Σαββατοκύριακο"

    decision = {
        "keep_old": False, "looks_like_correction": False, "stale": False,
        "old_age_days": 0, "new_richness": 0.0, "old_richness": 0.0, "much_longer": False,
    }
    # No close record -> old_id remains None -> decide_memory_overwrite
    # NOT even called (the decision here is not used, it just shouldn't
    # blocks the happy-path append).
    same_cat = _empty_query_result()
    profile_seed = {"general": ["Κάτι παλιό άσχετο"]}

    result, mock_collection, mock_vs, db_after = _run_save_fact(
        tmp_path, new_fact, "general", decision, same_cat, profile_seed=profile_seed,
    )

    # No deletion — simple addition to both stores.
    mock_collection.delete.assert_not_called()
    mock_vs.add_texts.assert_called_once()
    assert mock_vs.add_texts.call_args.args[0] == [new_fact]

    assert len(db_after["general"]) == 2
    assert db_after["general"][0] == "Κάτι παλιό άσχετο"
    assert db_after["general"][1] == new_fact


def test_close_unrelated_family_fact_adds_alongside_instead_of_overwrite(tmp_path):
    old_content = "[USER_FACT]: On 2026-06-13, Lazaros and Alexandros went to the park after lunch."
    new_fact = "[USER_FACT]: On 2026-06-13, the family ate fish for lunch at home."

    decision = {
        "keep_old": False, "looks_like_correction": False, "stale": False,
        "old_age_days": 0, "new_richness": 3.7, "old_richness": 3.7, "much_longer": False,
    }
    same_cat = _make_same_cat_result("old-id-family", old_content, 0.05)
    profile_seed = {"family": [old_content]}

    dup_doc = MagicMock()
    dup_doc.metadata = {"category": "family"}
    dup_doc.page_content = old_content

    result, mock_collection, mock_vs, db_after = _run_save_fact(
        tmp_path,
        new_fact,
        "family",
        decision,
        same_cat,
        profile_seed=profile_seed,
        dup_results=[(dup_doc, 0.05)],
    )

    assert result is True
    mock_collection.delete.assert_not_called()
    mock_vs.add_texts.assert_called_once()
    assert db_after["family"] == [old_content, new_fact]


# ──────────────────────────────────────────────────────────────────
# (d) [MASTRO-FIX] High overlap (>=0.55) BUT "episodic" — different
#     explicit date within the text itself -> add_alongside, NO
#     silent loss. Before the fix, overlap>=0.55 ALWAYS led to
#     keep_old, regardless of episodic-ness — this was the bug.
# ──────────────────────────────────────────────────────────────────

def test_high_overlap_with_differing_literal_dates_adds_alongside(tmp_path):
    old_content = "[USER_FACT]: Στις 2026-05-20 ο Kid1 πήγε βόλτα στο πάρκο."
    new_fact = "[USER_FACT]: Στις 2026-06-17 ο Kid1 πήγε βόλτα στο πάρκο."

    decision = {
        "keep_old": True, "looks_like_correction": False, "stale": False,
        "old_age_days": 28, "new_richness": 2.0, "old_richness": 2.0, "much_longer": False,
    }
    same_cat = _make_same_cat_result("old-id-park", old_content, 0.05)
    profile_seed = {"family": [old_content]}

    dup_doc = MagicMock()
    dup_doc.metadata = {"category": "family"}
    dup_doc.page_content = old_content

    result, mock_collection, mock_vs, db_after = _run_save_fact(
        tmp_path, new_fact, "family", decision, same_cat, profile_seed=profile_seed,
        dup_results=[(dup_doc, 0.05)],
    )

    # Same vocabulary (overlap=1.0), BUT different explicit date inside the
    # text -> different day/incident, not just a repetition of a fixed pattern
    # fact. BOTH must be kept.
    assert result is True
    mock_collection.delete.assert_not_called()
    mock_vs.add_texts.assert_called_once()
    assert db_after["family"] == [old_content, new_fact]


# ──────────────────────────────────────────────────────────────────
# (e) High overlap, WITHOUT any indication of episodic (no date,
#     no state_marker/relation_type difference) -> keep_old remains —
#     the grouping of fixed/timeless facts (e.g. preferences) DOES NOT break.
# ──────────────────────────────────────────────────────────────────

def test_high_overlap_static_preference_still_keeps_old(tmp_path):
    old_content = "[USER_FACT]: Ο Kid1 αγαπάει τις φακές για φαγητό."
    new_fact = "[USER_FACT]: Ο Kid1 αγαπάει πολύ τις φακές."

    decision = {
        "keep_old": True, "looks_like_correction": False, "stale": False,
        "old_age_days": 5, "new_richness": 1.0, "old_richness": 1.0, "much_longer": False,
    }
    same_cat = _make_same_cat_result("old-id-fakes", old_content, 0.05)
    profile_seed = {"family": [old_content]}

    result, mock_collection, mock_vs, db_after = _run_save_fact(
        tmp_path, new_fact, "family", decision, same_cat, profile_seed=profile_seed,
    )

    # Same fixed preference rephrased, no indication of a new incident -> n
    # new is NOT saved anywhere, it is grouped with the existing one (as before).
    assert result is False
    mock_collection.delete.assert_not_called()
    mock_vs.add_texts.assert_not_called()
    assert db_after == profile_seed
