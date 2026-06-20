import json

from memory.vector_store import (
    _safe_load_metadata_json,
    _profile_row_to_memory_doc,
    filter_profile_docs_by_entity,
    filter_profile_docs_by_topic,
    filter_profile_docs_by_relation_type,
    search_profile_facts,
    get_latest_state_for_query,
)


def test_safe_load_metadata_json_handles_none():
    assert _safe_load_metadata_json(None) == {}


def test_safe_load_metadata_json_handles_invalid():
    assert _safe_load_metadata_json("not-json") == {}


def test_safe_load_metadata_json_handles_valid_dict():
    raw = json.dumps({
        "tags": ["alexandros", "camp"],
        "entities": ["Αλέξανδρος"],
        "topic": "trip",
        "relation_type": "temporary_state",
    }, ensure_ascii=False)
    data = _safe_load_metadata_json(raw)
    assert data["topic"] == "trip"
    assert data["relation_type"] == "temporary_state"


def test_profile_row_to_memory_doc_extracts_metadata():
    row = {
        "id": 1,
        "category": "family",
        "fact": "[USER_FACT]: Ο Αλέξανδρος είναι στην κατασκήνωση",
        "photo_path": None,
        "date": "2026-06-17",
        "created_at": "2026-06-17 12:00:00",
        "metadata_json": json.dumps({
            "tags": ["alexandros", "camp", "away"],
            "entities": ["Αλέξανδρος"],
            "topic": "trip",
            "topic_detail": "camp",
            "state_markers": ["away"],
            "time_scope": "2026-06-17_to_2026-06-25",
            "relation_type": "temporary_state",
            "confidence": 0.9,
            "source": "telegram",
            "reason": "user_stated",
            "agent_name": "Chat_Agent",
        }, ensure_ascii=False),
    }

    doc = _profile_row_to_memory_doc(row)
    assert doc["topic"] == "trip"
    assert doc["topic_detail"] == "camp"
    assert doc["relation_type"] == "temporary_state"
    assert "Αλέξανδρος" in doc["entities"]
    assert "away" in doc["state_markers"]


def test_filter_profile_docs_by_entity():
    docs = [
        {"entities": ["Αλέξανδρος"], "topic": "trip", "relation_type": "temporary_state"},
        {"entities": ["Σοφία"], "topic": "gift", "relation_type": "confirmed"},
    ]
    out = filter_profile_docs_by_entity(docs, "Αλέξανδρος")
    assert len(out) == 1
    assert out[0]["topic"] == "trip"


def test_filter_profile_docs_by_topic():
    docs = [
        {"entities": ["Αλέξανδρος"], "topic": "trip", "relation_type": "temporary_state"},
        {"entities": ["Σοφία"], "topic": "gift", "relation_type": "confirmed"},
    ]
    out = filter_profile_docs_by_topic(docs, "gift")
    assert len(out) == 1
    assert out[0]["relation_type"] == "confirmed"


def test_filter_profile_docs_by_relation_type():
    docs = [
        {"entities": ["Αλέξανδρος"], "topic": "trip", "relation_type": "temporary_state"},
        {"entities": ["Σοφία"], "topic": "gift", "relation_type": "confirmed"},
    ]
    out = filter_profile_docs_by_relation_type(docs, "confirmed")
    assert len(out) == 1
    assert out[0]["topic"] == "gift"


def test_get_profile_facts_returns_normalized_docs(monkeypatch, tmp_path):
    import sqlite3
    from memory import vector_store as vs
    import config

    db_path = tmp_path / "profile.db"

    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE profile_facts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            category TEXT,
            fact TEXT,
            photo_path TEXT,
            date TEXT,
            metadata_json TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.execute(
        "INSERT INTO profile_facts (category, fact, photo_path, date, metadata_json) VALUES (?, ?, ?, ?, ?)",
        (
            "family",
            "[USER_FACT]: Ο Αλέξανδρος είναι στην κατασκήνωση",
            "",
            "2026-06-17",
            json.dumps({
                "entities": ["Αλέξανδρος"],
                "topic": "trip",
                "topic_detail": "camp",
                "state_markers": ["away"],
                "relation_type": "temporary_state",
            }, ensure_ascii=False),
        ),
    )
    conn.commit()
    conn.close()

    monkeypatch.setattr(config, "PROFILE_DB", str(db_path), raising=False)
    monkeypatch.setattr(vs, "PROFILE_DB", str(db_path), raising=False)

    docs = vs.get_profile_facts(limit=10)
    assert len(docs) == 1
    assert docs[0]["fact"].startswith("[USER_FACT]")
    assert docs[0]["topic"] == "trip"
    assert docs[0]["relation_type"] == "temporary_state"


def test_get_latest_entity_state_prefers_newer_state(monkeypatch):
    from memory import vector_store as vs

    docs = [
        {
            "id": 1,
            "category": "family",
            "fact": "[USER_FACT]: Ο Αλέξανδρος είναι στην κατασκήνωση",
            "entities": ["Αλέξανδρος"],
            "topic": "trip",
            "topic_detail": "camp",
            "state_markers": ["away"],
            "relation_type": "temporary_state",
            "date": "2026-06-17",
            "created_at": "2026-06-17 10:00:00",
        },
        {
            "id": 2,
            "category": "family",
            "fact": "[USER_FACT]: Ο Αλέξανδρος γύρισε σπίτι",
            "entities": ["Αλέξανδρος"],
            "topic": "trip",
            "topic_detail": "camp",
            "state_markers": ["returned"],
            "relation_type": "state_update",
            "date": "2026-06-18",
            "created_at": "2026-06-18 20:00:00",
        },
    ]

    monkeypatch.setattr(vs, "get_profile_facts", lambda category=None, limit=300: docs)

    latest = vs.get_latest_entity_state("Αλέξανδρος", "trip", category="family")
    assert latest is not None
    assert "γύρισε σπίτι" in latest["fact"]
    assert "returned" in latest["state_markers"]


def test_search_profile_facts_scores_generic_query(monkeypatch):
    from memory import vector_store as vs

    docs = [
        {
            "id": 1,
            "category": "family",
            "fact": "[USER_FACT]: ? ?????????? ????? ???? ???????????",
            "entities": ["??????????"],
            "tags": ["alexandros", "camp", "away"],
            "topic": "trip",
            "topic_detail": "camp",
            "state_markers": ["away"],
            "relation_type": "temporary_state",
            "date": "2026-06-17",
            "created_at": "2026-06-17 10:00:00",
        },
        {
            "id": 2,
            "category": "family",
            "fact": "[USER_FACT]: ? ????? ???? ????",
            "entities": ["?????"],
            "tags": ["sofia", "work"],
            "topic": "work",
            "topic_detail": "",
            "state_markers": ["confirmed"],
            "relation_type": "confirmed",
            "date": "2026-06-18",
            "created_at": "2026-06-18 10:00:00",
        },
    ]

    monkeypatch.setattr(vs, "get_profile_facts", lambda category=None, limit=300: docs)

    results = search_profile_facts("?????????? ???????????", category="family", limit=5)
    assert len(results) == 1
    assert "??????????" in results[0]["fact"]



def test_get_latest_state_for_query_uses_query_not_hardcoded(monkeypatch):
    from memory import vector_store as vs

    docs = [
        {
            "id": 1,
            "category": "family",
            "fact": "[USER_FACT]: ? ?????????? ????? ???? ???????????",
            "entities": ["??????????"],
            "tags": ["alexandros", "camp", "away"],
            "topic": "trip",
            "topic_detail": "camp",
            "state_markers": ["away"],
            "relation_type": "temporary_state",
            "date": "2026-06-17",
            "created_at": "2026-06-17 10:00:00",
        },
        {
            "id": 2,
            "category": "family",
            "fact": "[USER_FACT]: ? ????? ???? ????",
            "entities": ["?????"],
            "tags": ["sofia", "work"],
            "topic": "work",
            "topic_detail": "",
            "state_markers": ["confirmed"],
            "relation_type": "confirmed",
            "date": "2026-06-18",
            "created_at": "2026-06-18 10:00:00",
        },
    ]

    monkeypatch.setattr(vs, "get_profile_facts", lambda category=None, limit=300: docs)

    latest = get_latest_state_for_query("????? ????", category="family")
    assert latest is not None
    assert "?????" in latest["fact"]
