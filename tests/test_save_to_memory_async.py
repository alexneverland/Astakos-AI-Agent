"""
Tests for the save_to_memory fire-and-forget async behaviour.
Run: venv/Scripts/python.exe tests/test_save_to_memory_async.py
"""
import sys, os, time, threading
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8")

from unittest.mock import patch, MagicMock
from tools.system import save_to_memory

errors = []

def check(desc, cond, detail=""):
    if cond:
        print(f"✅ {desc}")
    else:
        msg = f"{desc}" + (f" — {detail}" if detail else "")
        errors.append(msg)
        print(f"❌ {msg}")


def test_save_to_memory_async():
    # ── 1. Returns IMMEDIATELY (< 1s) ─────────────────────────────────
    # Mocking embeddings + vector_store to avoid making a real Vertex AI call_
    mock_vs  = MagicMock()
    mock_emb = MagicMock()
    mock_emb.embed_query.return_value = [0.0] * 768
    mock_vs.similarity_search_with_score.return_value = []
    mock_vs._collection.query.return_value = {
        "ids": [[]],
        "documents": [[]],
        "metadatas": [[]],
        "distances": [[]],
    }
    first_write = threading.Event()
    mock_vs._collection.upsert.side_effect = lambda **kwargs: first_write.set()

    with patch("memory.vector_store.embeddings", mock_emb), \
         patch("memory.vector_store.vector_store", mock_vs):

        t0 = time.time()
        result = save_to_memory.invoke({
            "fact": "Ο Kid1 αγαπάει τα LEGO",
            "entities": "Kid1, LEGO",
            "category": "family",
        })
        elapsed = time.time() - t0
        first_write_in_time = first_write.wait(timeout=5)

    check("Επιστρέφει σε < 1s (fire-and-forget)", elapsed < 1.0,
          f"elapsed={elapsed:.2f}s")

    # ── 2. Returns string ───────────────────────────────────────────────
    check("Επιστρέφει string", isinstance(result, str))

    # ── 3. Does not block — does not contain 'Error' ──────────────────
    check("Δεν επιστρέφει Error", "Error" not in result, result[:80])
    check("Το πρώτο background save ολοκληρώνεται μέσα σε 5s", first_write_in_time)

    # ── 4. Background thread finally writes to vector_store ──────────
    # We wait for a max of 3s for the background thread`of`
    mock_vs2  = MagicMock()
    mock_emb2 = MagicMock()
    mock_emb2.embed_query.return_value = [0.0] * 768
    mock_vs2.similarity_search_with_score.return_value = []
    mock_vs2._collection.query.return_value = {
        "ids": [[]],
        "documents": [[]],
        "metadatas": [[]],
        "distances": [[]],
    }

    written = threading.Event()
    def _capture_upsert(*args, **kwargs):
        written.set()
    mock_vs2._collection.upsert.side_effect = _capture_upsert

    with patch("memory.vector_store.embeddings", mock_emb2), \
         patch("memory.vector_store.vector_store", mock_vs2):
        save_to_memory.invoke({
            "fact": "Η Partner γεννήθηκε στις 17/07/1989",
            "entities": "Partner",
            "category": "family",
        })
        written_in_time = written.wait(timeout=5)

    check("Background thread καλεί Chroma upsert μέσα σε 5s", written_in_time)

    # ── 5. Duplicate skip — add_texts IS NOT called ───────────────────
    mock_vs3  = MagicMock()
    mock_emb3 = MagicMock()
    mock_emb3.embed_query.return_value = [0.0] * 768
    # distance < 0.10 → duplicate
    mock_doc = MagicMock()
    mock_doc.page_content = "Ο Kid1 αγαπάει τα LEGO"
    mock_doc.metadata = {"category": "family"}
    mock_vs3.similarity_search_with_score.return_value = [(mock_doc, 0.05)]
    mock_vs3._collection.query.return_value = {
        "ids": [["existing-id"]],
        "documents": [["Ο Kid1 αγαπάει τα LEGO"]],
        "metadatas": [[{"category": "family"}]],
        "distances": [[0.05]],
    }
    not_written = threading.Event()

    with patch("memory.vector_store.embeddings", mock_emb3), \
         patch("memory.vector_store.vector_store", mock_vs3):
        save_to_memory.invoke({
            "fact": "Ο Kid1 αγαπάει τα LEGO",
            "entities": "Kid1, LEGO",
            "category": "family",
        })
        time.sleep(3)  # we give time to the background

    check("Duplicate: Chroma upsert ΔΕΝ κλήθηκε", not mock_vs3._collection.upsert.called,
          f"upsert called {mock_vs3._collection.upsert.call_count} times")

    # ── Results ─────────────────────────────────────────────────────────
    assert not errors, f"{len(errors)} αποτυχίες: {errors}"

if __name__ == "__main__":
    test_save_to_memory_async()
    print("\n✅ All tests passed!")
