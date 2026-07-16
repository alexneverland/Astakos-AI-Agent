import pytest
from datetime import datetime
import config
import memory.routine_db as routine_db
from services.routine_reconciler import reconcile_fact_to_routines
from memory.routine_db import (
    upsert_routine,
    get_routines_by_ids,
    delete_routine_db,
    get_connection
)

@pytest.fixture
def clean_db(monkeypatch, tmp_path):
    test_db = tmp_path / "test_routines.db"
    monkeypatch.setattr(config, "ROUTINES_DB", str(test_db), raising=False)
    monkeypatch.setattr(routine_db, "DB_PATH", str(test_db), raising=False)
    routine_db.setup_db()
    conn = get_connection()
    c = conn.cursor()
    c.execute("DELETE FROM routines")
    conn.commit()
    conn.close()
    yield

def test_routine_completion_reconciliation(clean_db, monkeypatch):
    # Create routines: one target, one unrelated, one similar but different
    upsert_routine("monday", "15:00", "Πάρκο")
    upsert_routine("monday", "18:00", "Σούπερ μάρκετ")
    upsert_routine("monday", "11:00", "Παιδική χαρά")
    
    from memory.routine_db import find_routines_by_name
    park_found = find_routines_by_name("Πάρκο", 0.1)
    park_id = park_found[0]["id"]
    
    supermarket_found = find_routines_by_name("Σούπερ μάρκετ", 0.1)
    supermarket_id = supermarket_found[0]["id"]

    playground_found = find_routines_by_name("Παιδική χαρά", 0.1)
    playground_id = playground_found[0]["id"]

    # Assert last_triggered is None initially for all
    routines = get_routines_by_ids([park_id, supermarket_id, playground_id])
    r_park = next(r for r in routines if r["id"] == park_id)
    r_supermarket = next(r for r in routines if r["id"] == supermarket_id)
    r_playground = next(r for r in routines if r["id"] == playground_id)
    assert r_park.get("last_triggered") is None
    assert r_supermarket.get("last_triggered") is None
    assert r_playground.get("last_triggered") is None

    class MockLLM:
        def invoke(self, *args, **kwargs):
            class MockResp:
                content = """[
                  {
                    "entity": "user",
                    "activity": "park",
                    "aliases": ["Πάρκο", "βόλτα"],
                    "state_change": "done",
                    "impact": "routine_completed_today",
                    "context_key": null,
                    "context_value": null,
                    "until_date": "2026-07-16",
                    "reason": "user_completed"
                  }
                ]"""
            return MockResp()
            
    import core.brain
    monkeypatch.setattr(core.brain, "llm", MockLLM())

    # Run the reconciler
    stats = reconcile_fact_to_routines(
        "Πήγαμε βόλτα στο πάρκο", 
        category="chat", 
        reason="user_stated",
        now=datetime.now()
    )

    # Check stats
    assert stats["applied"] is True
    assert stats.get("routines_completed", 0) > 0
    
    # Check DB
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT id, last_triggered FROM routines WHERE id IN (?, ?, ?)", (park_id, supermarket_id, playground_id))
    rows = c.fetchall()
    conn.close()
    
    park_last_trig = next(row[1] for row in rows if row[0] == park_id)
    supermarket_last_trig = next(row[1] for row in rows if row[0] == supermarket_id)
    playground_last_trig = next(row[1] for row in rows if row[0] == playground_id)
    
    today_str = datetime.now().strftime("%Y-%m-%d")
    assert park_last_trig == today_str
    assert supermarket_last_trig is None
    assert playground_last_trig is None
    
    # Clean up
    delete_routine_db(park_id)
    delete_routine_db(supermarket_id)
    delete_routine_db(playground_id)
