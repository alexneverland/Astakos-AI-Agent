import os
import sqlite3
import sys
from datetime import datetime
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from memory.vector_store import AstakosMemoryManager
from services.routine_reconciler import (
    infer_routine_reconciliation_directives,
    infer_routine_reconciliation_candidates,
    score_candidate_directive,
    apply_routine_reconciliation_directives,
    _normalize,
    _AUTO_APPLY_THRESHOLD,
    _DEBUG_ONLY_THRESHOLD,
)


def _make_routines_db(path, rows):
    conn = sqlite3.connect(path)
    conn.execute(
        """
        CREATE TABLE routines ( priority INTEGER DEFAULT 0, conflict_group TEXT, condition_type TEXT, condition_payload TEXT, condition_mode TEXT, conditions_json TEXT, source_memory_ref TEXT,
            id INTEGER PRIMARY KEY,
            day_of_week TEXT,
            time_str TEXT,
            event_name TEXT,
            event_type TEXT,
            confidence REAL,
            state TEXT,
            muted_until TEXT,
            muted_from TEXT,
            sentimental_last_sent TEXT,
            sentimental_silenced INTEGER DEFAULT 0,
            active_from TEXT,
            active_until TEXT,
            paused_until TEXT,
            resume_rule TEXT,
            pause_reason TEXT
        )
        """
    )
    for row in rows:
        if "source_memory_ref" not in row:
            row["source_memory_ref"] = None
        if "priority" not in row:
            row["priority"] = 0
        if "condition_type" not in row:
            row["condition_type"] = None
        if "condition_payload" not in row:
            row["condition_payload"] = None
        if "condition_mode" not in row:
            row["condition_mode"] = None

        conn.execute(
            """
            INSERT INTO routines (
                id, day_of_week, time_str, event_name, event_type, confidence, state,
                muted_until, muted_from, sentimental_last_sent, sentimental_silenced,
                active_from, active_until, paused_until, resume_rule, pause_reason,
                condition_type, condition_payload, condition_mode, conditions_json, priority, source_memory_ref
            ) VALUES (
                :id, :day_of_week, :time_str, :event_name, :event_type, :confidence, :state,
                :muted_until, :muted_from, :sentimental_last_sent, :sentimental_silenced,
                :active_from, :active_until, :paused_until, :resume_rule, :pause_reason,
                :condition_type, :condition_payload, :condition_mode, null, :priority, :source_memory_ref
            )
            """,
            row,
        )
    conn.commit()
    conn.close()


def _routine(
    rid: int,
    event_name: str,
    *,
    day_of_week: str = "Everyday",
    time_str: str = "12:00",
):
    return {
        "id": rid,
        "day_of_week": day_of_week,
        "time_str": time_str,
        "event_name": event_name,
        "event_type": "general",
        "confidence": 0.8,
        "state": "active",
        "muted_until": None,
        "muted_from": None,
        "sentimental_last_sent": None,
        "sentimental_silenced": 0,
        "active_from": None,
        "active_until": None,
        "paused_until": None,
        "resume_rule": None,
        "pause_reason": None,
    }


def test_infer_summer_break_pause_directive():
    fact = "[USER_FACT]: Οι προπονήσεις ποδοσφαίρου του Αλέξανδρου σταμάτησαν για όλο το καλοκαίρι και ξαναρχίζουν τον Σεπτέμβριο."
    directives = infer_routine_reconciliation_directives(
        fact,
        category="family",
        reason="user_stated",
        now=datetime(2026, 6, 17, 12, 0, 0),
    )

    assert len([d for d in directives if d.get("rule_name") == "seasonal_football"]) == 2
    assert directives[0]["kind"] == "context_state_set"
    assert directives[0]["key"] == "football_season"
    assert directives[0]["value"] == "false"
    assert directives[1]["kind"] == "condition_add"


def test_infer_camp_absence_mute_directive():
    fact = "[USER_FACT]: Ο Αλέξανδρος λείπει σε κατασκήνωση από τις 16/06/2026 και επιστρέφει στις 25/06/2026."
    directives = infer_routine_reconciliation_directives(
        fact,
        category="family",
        reason="user_stated",
        now=datetime(2026, 6, 17, 12, 0, 0),
    )

    assert any(d["kind"] == "context_state_set" and d["key"] == "alexandros_away_from_home" and d["value"] == "true" and d["until_date"] == "2026-06-25" for d in directives)
    assert any(d["kind"] == "context_state_set" and d["key"] == "alexandros_away_reason" and d["value"] == "camp" and d["until_date"] == "2026-06-25" for d in directives)
    assert any(d["kind"] == "condition_add" for d in directives)

def test_infer_return_home_unmute_directive():
    fact = "[USER_FACT]: Ο Αλέξανδρος γύρισε από την κατασκήνωση και είναι πάλι σπίτι."
    directives = infer_routine_reconciliation_directives(
        fact,
        category="family",
        reason="user_stated",
        now=datetime(2026, 6, 25, 18, 0, 0),
    )

    assert any(d["kind"] == "context_state_set" and d["key"] == "alexandros_away_from_home" and d["value"] == "false" for d in directives)
    assert any(d["kind"] == "context_state_set" and d["key"] == "alexandros_away_reason" and d["value"] == "" for d in directives)


def test_infer_school_break_requires_child_subject():
    fact = "[USER_FACT]: Τελείωσε το σχολείο και από αύριο διακοπές μέχρι τον Σεπτέμβριο."
    directives = infer_routine_reconciliation_directives(
        fact,
        category="family",
        reason="user_stated",
        now=datetime(2026, 6, 17, 12, 0, 0),
    )

    assert not any(d.get("reason") == "school_break" for d in directives)


def test_infer_school_break_with_child_subject_creates_pause():
    fact = "[USER_FACT]: Ο Αλέξανδρος τελείωσε το σχολείο και από αύριο έχει διακοπές μέχρι τον Σεπτέμβριο."
    directives = infer_routine_reconciliation_directives(
        fact,
        category="family",
        reason="user_stated",
        now=datetime(2026, 6, 17, 12, 0, 0),
    )

    assert any(
        d["kind"] == "context_state_set"
        and d["key"] == "school_open"
        and d["value"] == "false"
        and d["until_date"] == "2026-09-01"
        for d in directives
    )
    assert any(d["kind"] == "condition_add" for d in directives)


def test_apply_schedule_pause_hits_all_football_routines(tmp_path):
    import memory.routine_db as rdb

    db_path = tmp_path / "routines.db"
    _make_routines_db(
        db_path,
        [
            _routine(13, "ποδόσφαιρο Αλέξανδρου", day_of_week="Monday", time_str="17:00"),
            _routine(14, "ποδόσφαιρο Αλέξανδρου", day_of_week="Thursday", time_str="17:00"),
            _routine(15, "Ύπνος Αλέξανδρου", time_str="22:20"),
        ],
    )

    directives = [{
        "kind": "schedule_pause",
        "subject_tokens": ["αλεξανδρ"],
        "include_tokens": ["ποδοσφαιρ"],
        "exclude_tokens": [],
        "until_date": "2026-09-01",
        "reason": "summer_break",
        "resume_rule": "every_september",
    }]

    with (
        patch.object(rdb, "get_connection", side_effect=lambda write=False: sqlite3.connect(db_path)),
        patch("memory.event_log.log_event"),
    ):
        stats = apply_routine_reconciliation_directives(directives)

    conn = sqlite3.connect(db_path)
    rows = conn.execute(
        "SELECT id, paused_until, resume_rule, pause_reason FROM routines ORDER BY id"
    ).fetchall()
    conn.close()

    assert stats["schedule_paused"] == 2
    assert rows[0][1:] == ("2026-09-01", "every_september", "summer_break")
    assert rows[1][1:] == ("2026-09-01", "every_september", "summer_break")
    assert rows[2][1:] == (None, None, None)


def test_apply_notifications_mute_hits_alexandros_routines_only(tmp_path):
    import memory.routine_db as rdb

    db_path = tmp_path / "routines.db"
    _make_routines_db(
        db_path,
        [
            _routine(2, "Ύπνος Αλέξανδρου", time_str="22:20"),
            _routine(3, "Πάρκο με Αλέξανδρο", time_str="18:30"),
            _routine(4, "Σύνταξη μηνύματος στη Σοφία στο Messenger", time_str="11:00"),
        ],
    )

    directives = [{
        "kind": "notifications_mute",
        "subject_tokens": ["αλεξανδρ"],
        "include_tokens": [],
        "exclude_tokens": ["σοφια", "messenger", "μηνυμα"],
        "until_date": "2026-06-25",
        "reason": "camp_absence",
    }]

    with (
        patch.object(rdb, "get_connection", side_effect=lambda write=False: sqlite3.connect(db_path)),
        patch("memory.event_log.log_event"),
    ):
        stats = apply_routine_reconciliation_directives(directives)

    conn = sqlite3.connect(db_path)
    rows = conn.execute("SELECT id, muted_until FROM routines ORDER BY id").fetchall()
    conn.close()

    assert stats["notifications_muted"] == 2
    assert rows == [
        (2, "2026-06-25"),
        (3, "2026-06-25"),
        (4, None),
    ]


def test_apply_shift_week_mute_matches_include_only_routines(tmp_path):
    import memory.routine_db as rdb

    db_path = tmp_path / "routines.db"
    _make_routines_db(
        db_path,
        [
            _routine(20, "Αναχώρηση για δουλειά", time_str="10:00"),
            _routine(21, "Μεσημεριανό φαγητό", time_str="15:00"),
            _routine(22, "Ύπνος Αλέξανδρου", time_str="22:20"),
            _routine(23, "Μήνυμα στη Σοφία στο Messenger", time_str="11:00"),
        ],
    )

    directives = [{
        "kind": "notifications_mute",
        "subject_tokens": [],
        "include_tokens": ["αναχωρησ", "φευγ", "δουλεια", "δουλειαν", "μεσημερ", "φαγητ", "γευμ"],
        "exclude_tokens": ["αλεξανδρ", "σοφια"],
        "until_date": "2026-06-21",
        "reason": "shift_afternoon_week",
    }]

    with (
        patch.object(rdb, "get_connection", side_effect=lambda write=False: sqlite3.connect(db_path)),
        patch("memory.event_log.log_event"),
    ):
        stats = apply_routine_reconciliation_directives(directives)

    conn = sqlite3.connect(db_path)
    rows = conn.execute("SELECT id, muted_until FROM routines ORDER BY id").fetchall()
    conn.close()

    assert stats["notifications_muted"] == 2
    assert rows == [
        (20, "2026-06-21"),
        (21, "2026-06-21"),
        (22, None),
        (23, None),
    ]


def test_shift_logic_candidate_scores_auto_apply():
    """shift_logic produces a candidate directive and auto applies it."""
    fact = "[USER_FACT]: Αυτή την εβδομάδα δουλεύω απόγευμα στη βάρδια."

    candidates = infer_routine_reconciliation_candidates(
        fact,
        category="lazaros",
        reason="user_stated",
        now=datetime(2026, 6, 17, 12, 0, 0),
    )

    # Candidate must exist with correct metadata
    assert any(
        c["kind"] == "context_state_set"
        and c["reason"] == "shift_afternoon_week"
        and c["until_date"] == "2026-06-21"
        and c["rule_name"] == "shift_logic"
        for c in candidates
    ), "Expected shift_logic candidate with shift_afternoon_week reason and Sunday until_date"
    # Score it and verify it becomes auto_apply
    normalized_fact = _normalize(fact)
    scored = [
        score_candidate_directive(
            c,
            normalized_fact=normalized_fact,
            matched_rule_name=c["rule_name"],
        )
        for c in candidates
    ]

    assert any(
        d["rule_name"] == "shift_logic"
        and d["decision"] == "auto_apply"
        and d["score"] >= _AUTO_APPLY_THRESHOLD
        for d in scored
    ), "shift_logic should be auto_apply: score >= 0.80"

    # The backward-compat wrapper MUST include shift_logic in its output
    directives = infer_routine_reconciliation_directives(
        fact,
        category="lazaros",
        reason="user_stated",
        now=datetime(2026, 6, 17, 12, 0, 0),
    )
    assert any(
        d.get("reason") == "shift_afternoon_week" for d in directives
    ), "infer_routine_reconciliation_directives must return auto_apply directives"


def _make_same_cat_result(old_id, old_content, distance, old_meta=None):
    return {
        "ids": [[old_id]],
        "documents": [[old_content]],
        "metadatas": [[old_meta or {"category": "family", "timestamp": 0, "confidence": 0.7}]],
        "distances": [[distance]],
    }


def _empty_query_result():
    return {"ids": [[]], "documents": [[]], "metadatas": [[]], "distances": [[]]}


def test_save_fact_triggers_reconciler_after_successful_save(tmp_path):
    profile_path = str(tmp_path / "astakos_profile.db")
    manager = AstakosMemoryManager()
    same_cat = _empty_query_result()

    mock_collection = MagicMock()
    mock_collection.query.return_value = same_cat
    mock_collection.delete = MagicMock()

    with (
        patch("memory.vector_store.embeddings") as mock_embeddings,
        patch.object(type(__import__("memory.vector_store", fromlist=["vector_store"]).vector_store), "_collection", new_callable=lambda: mock_collection),
        patch("memory.vector_store.vector_store") as mock_vs,
        patch("config.PROFILE_DB", profile_path),
        patch("services.routine_reconciler.reconcile_fact_to_routines", return_value={"applied": True, "directives": 1, "matched_routines": 2, "schedule_paused": 2, "notifications_muted": 0, "notifications_unmuted": 0}) as mock_reconcile,
    ):
        mock_embeddings.embed_query.return_value = [0.1, 0.2, 0.3]
        mock_vs._collection = mock_collection
        mock_vs.similarity_search_with_score.return_value = []
        mock_vs.add_texts = MagicMock()

        result = manager._save_fact(
            fact="[USER_FACT]: Οι προπονήσεις ποδοσφαίρου του Αλέξανδρου σταμάτησαν για το καλοκαίρι.",
            category="family",
            agent_name="Chat_Agent",
            source="telegram",
            reason="user_stated",
        )

    assert result is True
    mock_reconcile.assert_called_once()


def test_save_fact_does_not_trigger_reconciler_when_save_is_aborted(tmp_path):
    profile_path = str(tmp_path / "astakos_profile.db")
    manager = AstakosMemoryManager()
    old_content = "[USER_FACT]: Στις 2026-05-20 ο Αλέξανδρος πήγε στο πάρκο με τη Σοφία"
    same_cat = _make_same_cat_result("old-id-1", old_content, 0.10)

    mock_collection = MagicMock()
    mock_collection.query.return_value = same_cat
    mock_collection.delete = MagicMock()

    decision = {
        "keep_old": True,
        "looks_like_correction": False,
        "stale": False,
        "old_age_days": 1,
        "new_richness": 1.0,
        "old_richness": 3.0,
        "much_longer": False,
    }

    with (
        patch("memory.vector_store.decide_memory_overwrite", return_value=decision),
        patch("memory.vector_store.embeddings") as mock_embeddings,
        patch.object(type(__import__("memory.vector_store", fromlist=["vector_store"]).vector_store), "_collection", new_callable=lambda: mock_collection),
        patch("memory.vector_store.vector_store") as mock_vs,
        patch("config.PROFILE_DB", profile_path),
        patch("services.routine_reconciler.reconcile_fact_to_routines") as mock_reconcile,
    ):
        mock_embeddings.embed_query.return_value = [0.1, 0.2, 0.3]
        mock_vs._collection = mock_collection
        mock_vs.similarity_search_with_score.return_value = []
        mock_vs.add_texts = MagicMock()

        result = manager._save_fact(
            fact="[USER_FACT]: Ο Αλέξανδρος πάει συχνά βόλτα",
            category="family",
            agent_name="Chat_Agent",
            source="telegram",
            reason="user_stated",
        )

    assert result is False
    mock_reconcile.assert_not_called()


def test_apply_condition_add_hits_correct_routines_without_error(tmp_path):
    import memory.routine_db as rdb

    db_path = tmp_path / "routines.db"
    _make_routines_db(
        db_path,
        [
            _routine(1, "alexandros football", time_str="17:00"),
            _routine(2, "alexandros english", time_str="16:00"),
        ],
    )

    directives = [
        {
            "kind": "condition_add",
            "subject_tokens": ["alexandros"],
            "include_tokens": ["football"],
            "exclude_tokens": [],
            "condition_type": "context_flag",
            "condition_payload": {"flag": "football_season", "equals": True},
            "condition_mode": "allow_when_true",
            "rule_name": "seasonal_football",
            "decision": "auto_apply"
        }
    ]

    with (
        patch.object(rdb, "get_connection", side_effect=lambda write=False: sqlite3.connect(db_path)),
        patch("memory.event_log.log_event"),
    ):
        from services.routine_reconciler import apply_routine_reconciliation_directives
        
        stats = apply_routine_reconciliation_directives(directives)

    assert stats["conditions_added"] == 1

    conn = sqlite3.connect(db_path)
    rows = conn.execute("SELECT id, conditions_json FROM routines ORDER BY id").fetchall()
    conn.close()

    import json
    row1_id, row1_json = rows[0]
    assert row1_id == 1
    assert row1_json is not None
    conds = json.loads(row1_json)
    assert len(conds) == 1
    assert conds[0]["condition_type"] == "context_flag"
    assert conds[0]["condition_mode"] == "allow_when_true"
    
    row2_id, row2_json = rows[1]
    assert row2_id == 2
    assert row2_json is None

def test_apply_condition_add_skips_identical_existing_condition(tmp_path):
    import memory.routine_db as rdb
    import json

    db_path = tmp_path / "routines.db"
    _make_routines_db(
        db_path,
        [
            _routine(1, "alexandros football", time_str="17:00"),
        ],
    )

    with patch.object(rdb, "get_connection", side_effect=lambda write=False: sqlite3.connect(db_path)):
        rdb.set_routine_condition(
            1, 
            condition_type="context_flag", 
            condition_payload=json.dumps({"flag": "football_season", "equals": True}), 
            condition_mode="allow_when_true", 
            source_memory_ref="reconciler"
        )

    directives = [
        {
            "kind": "condition_add",
            "subject_tokens": ["alexandros"],
            "include_tokens": ["football"],
            "exclude_tokens": [],
            "condition_type": "context_flag",
            "condition_payload": {"flag": "football_season", "equals": True},
            "condition_mode": "allow_when_true",
            "rule_name": "seasonal_football",
            "decision": "auto_apply"
        }
    ]

    with (
        patch.object(rdb, "get_connection", side_effect=lambda write=False: sqlite3.connect(db_path)),
        patch("memory.event_log.log_event"),
    ):
        from services.routine_reconciler import apply_routine_reconciliation_directives
        stats = apply_routine_reconciliation_directives(directives)

    assert stats["conditions_added"] == 0
    assert stats["skipped"] == 1
