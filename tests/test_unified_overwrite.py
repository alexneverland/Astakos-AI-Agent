"""
Tests για το ΕΝΟΠΟΙΗΜΕΝΟ overwrite στο AstakosMemoryManager._save_fact:
ΜΙΑ απόφαση (decide_memory_overwrite) πρέπει να καθοδηγεί ΚΑΙ τη Chroma
ΚΑΙ το JSON Profile — όχι δύο ανεξάρτητα (και πιθανώς αντικρουόμενα) περάσματα.

Καλύπτει:
  (a) keep_old=True  -> return False, ΚΑΜΙΑ εγγραφή σε Chroma ή JSON (no dup write)
  (b) keep_old=False -> ίδια ακριβώς εγγραφή αντικαθίσταται και στα δύο stores
  (c) γενικά facts (όχι [LESSON]/[USER_FACT], καμία κοντινή παλιά εγγραφή)
      -> προστίθενται κανονικά και στα δύο stores, χωρίς απόκλιση
"""
import json
import os
import sys
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from memory.vector_store import AstakosMemoryManager


def _make_same_cat_result(old_id, old_content, distance, old_meta=None):
    """Μιμείται το επιστρεφόμενο σχήμα του vector_store._collection.query()."""
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
    Context manager-άκι: patch-άρει ό,τι χρειάζεται το _save_fact ώστε να τρέξει
    χωρίς πραγματική Chroma/Gemini, με ελεγχόμενη decide_memory_overwrite.
    Επιστρέφει τα mocks ώστε το test να κάνει assertions πάνω τους.
    """
    return patch.multiple(
        "memory.vector_store",
        decide_memory_overwrite=MagicMock(return_value=decision),
    ), patch("config.PROFILE_DB", new=profile_path)


def _run_save_fact(tmp_path, fact, category, decision, same_cat_result,
                   profile_seed=None, dup_results=None):
    """
    Τρέχει _save_fact με πλήρως mocked Chroma collection / embeddings / similarity
    search, ελεγχόμενη decide_memory_overwrite και πραγματικό (προσωρινό) JSON
    profile αρχείο. Επιστρέφει (result, mocks-dict, profile-db-μετά).
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
# (a) keep_old=True -> καμία διπλοεγγραφή πουθενά
# ──────────────────────────────────────────────────────────────────

def test_keep_old_returns_false_and_writes_nothing(tmp_path):
    old_content = "[USER_FACT]: Στις 2026-05-20 ο Αλέξανδρος πήγε στο πάρκο με τη Σοφία"
    new_fact = "[USER_FACT]: Ο Αλέξανδρος πάει συχνά βόλτα"

    decision = {
        "keep_old": True, "looks_like_correction": False, "stale": False,
        "old_age_days": 1, "new_richness": 1.0, "old_richness": 3.0, "much_longer": False,
    }
    same_cat = _make_same_cat_result("old-id-1", old_content, 0.10)
    profile_seed = {"family": [old_content]}

    result, mock_collection, mock_vs, db_after = _run_save_fact(
        tmp_path, new_fact, "family", decision, same_cat, profile_seed=profile_seed,
    )

    # Η συνάρτηση πρέπει να σταματήσει αμέσως — τίποτα δεν γράφεται πουθενά.
    assert result is False
    mock_collection.delete.assert_not_called()
    mock_vs.add_texts.assert_not_called()

    # Το JSON Profile μένει ΑΚΡΙΒΩΣ όπως ήταν — όχι append, όχι replace.
    assert db_after == profile_seed


# ──────────────────────────────────────────────────────────────────
# (b) keep_old=False -> ΙΔΙΑ εγγραφή αντικαθίσταται και στα δύο stores
# ──────────────────────────────────────────────────────────────────

def test_overwrite_replaces_same_entry_in_both_stores(tmp_path):
    old_content = "[USER_FACT]: Λάθος παλιά διεύθυνση Πεστών 7"
    new_fact = "[USER_FACT]: Λάθος, η σωστή διεύθυνση είναι Πίστων 7"

    decision = {
        "keep_old": False, "looks_like_correction": True, "stale": False,
        "old_age_days": 1, "new_richness": 2.0, "old_richness": 1.0, "much_longer": False,
    }
    same_cat = _make_same_cat_result("old-id-2", old_content, 0.05)
    # Ένα άσχετο fact + το προς αντικατάσταση — πρέπει να αλλάξει ΜΟΝΟ το σωστό index.
    profile_seed = {"family": ["[USER_FACT]: κάτι άσχετο", old_content]}

    result, mock_collection, mock_vs, db_after = _run_save_fact(
        tmp_path, new_fact, "family", decision, same_cat, profile_seed=profile_seed,
    )

    # Chroma: η παλιά εγγραφή σβήνεται, η νέα προστίθεται — ΜΙΑ φορά.
    mock_collection.delete.assert_called_once_with(ids=["old-id-2"])
    mock_vs.add_texts.assert_called_once()
    assert mock_vs.add_texts.call_args.args[0] == [new_fact]

    # JSON Profile: ΑΚΡΙΒΩΣ η ίδια εγγραφή αντικαθίσταται (exact-text match) —
    # το άσχετο fact μένει ανέπαφο, ΔΕΝ υπάρχει προσθήκη/duplicate.
    assert len(db_after["family"]) == 2
    assert db_after["family"][0] == "[USER_FACT]: κάτι άσχετο"
    assert db_after["family"][1] == new_fact


def test_overwrite_appends_when_no_matching_json_entry_found(tmp_path):
    """Προϋπάρχουσα απόκλιση: η Chroma είχε κάτι που το JSON δεν είχε ποτέ —
    το νέο fact προστίθεται (όχι σιωπηλή απώλεια), δεν κάνει crash."""
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
# (c) Γενικά facts (καμία κοντινή παλιά εγγραφή) -> κανονικό append παντού
# ──────────────────────────────────────────────────────────────────

def test_general_fact_with_no_close_match_appends_to_both_stores(tmp_path):
    new_fact = "Ο Λάζαρος δοκίμασε νέα συνταγή με φακές το Σαββατοκύριακο"

    decision = {
        "keep_old": False, "looks_like_correction": False, "stale": False,
        "old_age_days": 0, "new_richness": 0.0, "old_richness": 0.0, "much_longer": False,
    }
    # Καμία κοντινή εγγραφή -> old_id παραμένει None -> decide_memory_overwrite
    # ΔΕΝ καλείται καν (η απόφαση εδώ δεν χρησιμοποιείται, απλώς δεν πρέπει να
    # μπλοκάρει το happy-path append).
    same_cat = _empty_query_result()
    profile_seed = {"general": ["Κάτι παλιό άσχετο"]}

    result, mock_collection, mock_vs, db_after = _run_save_fact(
        tmp_path, new_fact, "general", decision, same_cat, profile_seed=profile_seed,
    )

    # Καμία διαγραφή — απλή προσθήκη και στα δύο stores.
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
