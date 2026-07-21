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
    fact = "[USER_FACT]: Ο Kid1 λείπει σε κατασκήνωση από τις 16/06/2026 και επιστρέφει στις 25/06/2026."
    directives = infer_routine_reconciliation_directives(
        fact,
        category="family",
        reason="user_stated",
        now=datetime(2026, 6, 17, 12, 0, 0),
    )

    assert any(d["kind"] == "context_state_set" and d["key"] == "kid1_away_from_home" and d["value"] == "true" and d["until_date"] == "2026-06-25" for d in directives)
    assert any(d["kind"] == "context_state_set" and d["key"] == "kid1_away_reason" and d["value"] == "camp" and d["until_date"] == "2026-06-25" for d in directives)
    assert any(d["kind"] == "condition_add" for d in directives)

def test_infer_return_home_unmute_directive():
    fact = "[USER_FACT]: Ο Kid1 γύρισε από την κατασκήνωση και είναι πάλι σπίτι."
    directives = infer_routine_reconciliation_directives(
        fact,
        category="family",
        reason="user_stated",
        now=datetime(2026, 6, 25, 18, 0, 0),
    )

    assert any(d["kind"] == "context_state_set" and d["key"] == "kid1_away_from_home" and d["value"] == "false" for d in directives)
    assert any(d["kind"] == "context_state_set" and d["key"] == "kid1_away_reason" and d["value"] == "" for d in directives)


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
    fact = "[USER_FACT]: Ο Kid1 τελείωσε το σχολείο και από αύριο έχει διακοπές μέχρι τον Σεπτέμβριο."
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


def test_apply_notifications_mute_hits_kid1_routines_only(tmp_path):
    import memory.routine_db as rdb

    db_path = tmp_path / "routines.db"
    _make_routines_db(
        db_path,
        [
            _routine(2, "Ύπνος Αλέξανδρου", time_str="22:20"),
            _routine(3, "Πάρκο με Αλέξανδρο", time_str="18:30"),
            _routine(4, "Σύνταξη μηνύματος στη Partner στο Messenger", time_str="11:00"),
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
            _routine(23, "Μήνυμα στη Partner στο Messenger", time_str="11:00"),
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


def test_sofia_work_does_not_suppress_messenger_routine():
    fact = "[USER_FACT]: Η Partner δουλεύει σήμερα από το σπίτι."

    directives = infer_routine_reconciliation_directives(
        fact,
        category="family",
        reason="user_stated",
        now=datetime(2026, 6, 24, 10, 0, 0),
    )

    assert not any(
        d.get("condition_payload", {}).get("flag") == "partner_with_user"
        for d in directives
    )


def test_sofia_together_suppresses_messenger_routine():
    fact = "[USER_FACT]: Είμαι μαζί με τη Partner τώρα."

    directives = infer_routine_reconciliation_candidates(
        fact,
        category="family",
        reason="user_stated",
        now=datetime(2026, 6, 24, 10, 0, 0),
    )

    assert any(
        d["kind"] == "context_state_set"
        and d["key"] == "partner_with_user"
        and d["value"] == "true"
        for d in directives
    )
    assert any(
        d["kind"] == "condition_add"
        and d["condition_payload"]["flag"] == "partner_with_user"
        and d["condition_mode"] == "suppress_when_true"
        for d in directives
    )


def test_sofia_left_clears_together_flag():
    fact = "[USER_FACT]: Η Partner έφυγε και δεν είναι εδώ τώρα."

    directives = infer_routine_reconciliation_candidates(
        fact,
        category="family",
        reason="user_stated",
        now=datetime(2026, 6, 24, 12, 0, 0),
    )

    assert any(
        d["kind"] == "context_state_set"
        and d["key"] == "partner_with_user"
        and d["value"] == "false"
        for d in directives
    )


def test_not_together_phrase_clears_only_when_sofia_context_is_active():
    fact = "[USER_FACT]: Δεν είμαστε μαζί τώρα."

    with patch("memory.routine_db.get_context_state", return_value={"value": "true", "expires_at": "2026-06-24"}):
        directives = infer_routine_reconciliation_candidates(
            fact,
            category="family",
            reason="user_stated",
            now=datetime(2026, 6, 24, 12, 0, 0),
        )

    assert any(
        d["kind"] == "context_state_set"
        and d["key"] == "partner_with_user"
        and d["value"] == "false"
        for d in directives
    )


def test_not_together_phrase_without_active_sofia_context_does_nothing():
    fact = "[USER_FACT]: Δεν είμαστε μαζί τώρα."

    with patch("memory.routine_db.get_context_state", return_value=None):
        directives = infer_routine_reconciliation_candidates(
            fact,
            category="family",
            reason="user_stated",
            now=datetime(2026, 6, 24, 12, 0, 0),
        )

    assert not any(d.get("key") == "partner_with_user" for d in directives)


def test_shift_logic_weekly_state_auto_applies():
    """A direct weekly shift declaration safely updates temporary context."""
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
        and c["until_date"] == "2026-06-19"
        and c["rule_name"] == "shift_logic"
        for c in candidates
    ), "Expected shift_logic candidate with shift_afternoon_week reason and Friday until_date"
    # Score it and verify it auto applies now
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
        and d["auto_apply"] is True
        and d["key"] == "current_shift"
        for d in scored
    )

    directives = infer_routine_reconciliation_directives(
        fact,
        category="lazaros",
        reason="user_stated",
        now=datetime(2026, 6, 17, 12, 0, 0),
    )
    assert any(
        d.get("kind") == "context_state_set"
        and d.get("key") == "current_shift"
        and d.get("value") == "afternoon"
        and d.get("reason") == "shift_afternoon_week"
        for d in directives
    )


def test_shift_logic_negated_weekly_statement_does_not_set_current_shift():
    """A negated weekly shift statement must not infer the opposite shift."""
    fact = "[USER_FACT]: Δεν δουλεύω απογευματινή βάρδια αυτή την εβδομάδα."

    candidates = infer_routine_reconciliation_candidates(
        fact,
        category="lazaros",
        reason="user_stated",
        now=datetime(2026, 6, 17, 12, 0, 0),
    )

    assert not any(
        c.get("kind") == "context_state_set"
        and c.get("key") == "current_shift"
        for c in candidates
    )


def test_shift_logic_correction_sets_current_workweek():
    fact = "[USER_FACT]: Απογευματινή βάρδια είμαι στη δουλειά, διόρθωσέ το."

    candidates = infer_routine_reconciliation_candidates(
        fact,
        category="lazaros",
        reason="user_stated",
        now=datetime(2026, 7, 21, 9, 0, 0),
    )

    shift = next(
        candidate
        for candidate in candidates
        if candidate.get("kind") == "context_state_set"
        and candidate.get("key") == "current_shift"
    )

    assert shift["value"] == "afternoon"
    assert shift["until_date"] == "2026-07-24"
    assert shift["reason"] == "shift_afternoon_week"

    scored = score_candidate_directive(
        shift,
        normalized_fact=_normalize(fact),
        matched_rule_name=shift["rule_name"],
    )

    assert scored["decision"] == "auto_apply"
    assert scored["auto_apply"] is True


def test_shift_logic_deletion_request_does_not_set_current_workweek():
    fact = "[USER_FACT]: Σβήσε ότι είμαι απογευματινή βάρδια στη δουλειά."

    candidates = infer_routine_reconciliation_candidates(
        fact,
        category="lazaros",
        reason="user_stated",
        now=datetime(2026, 7, 21, 9, 0, 0),
    )

    assert not any(
        candidate.get("kind") == "context_state_set"
        and candidate.get("key") == "current_shift"
        for candidate in candidates
    )


def test_shift_logic_explicit_weekday_auto_applies():
    fact = "[USER_FACT]: Δευτέρα είμαι απογευματινός βάρδια στην δουλειά."

    candidates = infer_routine_reconciliation_candidates(
        fact,
        category="lazaros",
        reason="user_stated",
        now=datetime(2026, 6, 28, 15, 0, 0),
    )

    assert any(
        c["kind"] == "context_state_set"
        and c["reason"] == "shift_afternoon_week"
        and c["key"] == "current_shift"
        and c["until_date"] == "2026-07-03"
        and c["rule_name"] == "shift_logic"
        for c in candidates
    )

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
        and d["auto_apply"] is True
        and d["key"] == "current_shift"
        for d in scored
    )


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


def test_save_fact_triggers_reconciler_even_when_save_is_aborted(tmp_path):
    profile_path = str(tmp_path / "astakos_profile.db")
    manager = AstakosMemoryManager()
    old_content = "[USER_FACT]: Στις 2026-05-20 ο Kid1 πήγε στο πάρκο με τη Partner"
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
            fact="[USER_FACT]: Ο Kid1 πάει συχνά βόλτα",
            category="family",
            agent_name="Chat_Agent",
            source="telegram",
            reason="user_stated",
        )

    assert result is False
    mock_reconcile.assert_called_once()


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

def test_infer_workweek_until_from_wednesday():
    from services.routine_reconciler import _infer_workweek_until
    now = datetime(2026, 6, 17)  # Wednesday
    assert _infer_workweek_until(now) == "2026-06-19"

def test_infer_workweek_until_from_friday():
    from services.routine_reconciler import _infer_workweek_until
    now = datetime(2026, 6, 19)  # Friday
    assert _infer_workweek_until(now) == "2026-06-19"


def test_dynamic_shift_routine():
    from services.routine_reconciler import reconcile_fact_to_routines

    fact = "[USER_FACT]: Το τρέξιμο δεν ισχύει όταν έχω απόγευμα."
    now = datetime(2026, 6, 18, 10, 0)
    res = reconcile_fact_to_routines(fact, category="user", reason="agent_inferred", now=now)
    
    # It should have extracted "τρεξιμο" and matched it
    assert res["candidates"] > 0
    
    # Look for the shift_generic_rule candidate
    gen_cond = next((c for c in res["scored_directives"] if c.get("reason") == "shift_generic_rule"), None)
    assert gen_cond is not None
    assert "τρεξιμο" in gen_cond["include_tokens"]
    assert gen_cond["condition_mode"] == "suppress_when_true"
    assert gen_cond["condition_payload"]["equals"] == "afternoon"

def test_llm_candidates_merge_with_rule_candidates_without_duplicates(monkeypatch):
    import services.routine_reconciler as rr

    fake_llm = [{
        "kind": "context_state_set",
        "key": "football_season",
        "value": "false",
        "until_date": "2026-09-01",
        "reason": "summer_break",
        "subject_tokens": ["αλεξανδρ"],
        "include_tokens": ["ποδοσφαιρο"],
        "exclude_tokens": ["messenger", "μηνυμα"],
    }]

    monkeypatch.setattr(rr, "_infer_llm_reconciliation_candidates", lambda *a, **k: fake_llm)

    directives = rr.infer_routine_reconciliation_candidates(
        "[USER_FACT] Είναι καλοκαίρι ο Kid1 δεν έχει ποδόσφαιρο μέχρι Σεπτέμβριο",
        category="family",
        reason="user_stated",
        now=datetime(2026, 6, 20, 12, 0, 0),
    )

    fps = [rr._candidate_fingerprint(d) for d in directives]
    assert len(fps) == len(set(fps))


def test_return_home_from_outing_requires_active_out_of_home_context():
    from services.routine_reconciler import _rule_return_home_from_outing

    now = datetime(2026, 6, 21, 14, 0)

    with patch("memory.routine_db.get_context_state", return_value=None):
        directives = _rule_return_home_from_outing(
            normalized="γυρισαμε σπιτι",
            dates=[],
            now=now,
        )

    assert directives == []


def test_return_home_from_outing_clears_out_of_home_and_marks_outing_done():
    from services.routine_reconciler import _rule_return_home_from_outing

    now = datetime(2026, 6, 21, 14, 0)

    def fake_get_context_state(key):
        if key == "user_out_of_home":
            return {"value": "true", "expires_at": "2026-06-21"}
        if key == "state:kid1:outing":
            return {"value": "in_progress", "expires_at": "2026-06-21"}
        return None

    with patch("memory.routine_db.get_context_state", side_effect=fake_get_context_state):
        directives = _rule_return_home_from_outing(
            normalized="γυρισαμε σπιτι",
            dates=[],
            now=now,
        )

    assert len(directives) == 2

    user_out = next(d for d in directives if d["key"] == "user_out_of_home")
    alex_outing = next(d for d in directives if d["key"] == "state:kid1:outing")

    assert user_out["value"] == "false"
    assert user_out["until_date"] is None
    assert user_out["reason"] == "returned_home_from_outing"

    assert alex_outing["value"] == "done"
    assert alex_outing["until_date"] == "2026-06-21"
    assert alex_outing["reason"] == "returned_home_from_outing"


def test_family_outing_in_progress_adds_outing_and_home_conditions():
    from services.routine_reconciler import _rule_family_outing_in_progress

    now = datetime(2026, 6, 21, 12, 0)

    directives = _rule_family_outing_in_progress(
        normalized="ειμαστε ολοι μαζι στην πισινα με τον αλεξανδρο",
        dates=[],
        now=now,
    )

    condition_directives = [d for d in directives if d.get("kind") == "condition_add"]

    assert any(
        d.get("condition_payload") == {"flag": "state:kid1:outing", "equals": "in_progress"}
        for d in condition_directives
    )

    assert any(
        d.get("condition_payload") == {"flag": "user_out_of_home", "equals": True}
        and any(tok in d.get("include_tokens", []) for tok in ["παρκο", "βολτα", "παιχνιδ"])
        for d in condition_directives
    )

    assert any(
        d.get("condition_payload") == {"flag": "user_out_of_home", "equals": True}
        and any(tok in d.get("include_tokens", []) for tok in ["μαγειρ", "φαγητ", "γευμα"])
        for d in condition_directives
    )
def test_llm_impact_to_directives_supports_canonical_context_key():
    from services.routine_reconciler import _llm_impact_to_directives

    impact = {
        "context_key": "user_out_of_home",
        "context_value": True,
        "impact": "live_context",
        "until_date": "2026-06-24",
        "reason": "user_out_evening",
    }

    directives = _llm_impact_to_directives(impact)
    assert len(directives) == 1
    assert directives[0]["kind"] == "context_state_set"
    assert directives[0]["key"] == "user_out_of_home"
    assert directives[0]["value"] is True

def test_llm_impact_to_directives_normalizes_string_boolean_context_value():
    from services.routine_reconciler import _llm_impact_to_directives

    impact = {
        "context_key": "user_out_of_home",
        "context_value": "true",
        "impact": "live_context",
        "until_date": "2026-06-24",
        "reason": "family_out_evening",
    }

    directives = _llm_impact_to_directives(impact)
    assert len(directives) == 1
    assert directives[0]["value"] is True

def test_llm_context_key_does_not_require_entity_and_activity():
    from services.routine_reconciler import _llm_impact_to_directives

    impact = {
        "context_key": "kid1_present",
        "context_value": False,
        "impact": "live_context",
        "reason": "child_with_caregiver",
    }

    directives = _llm_impact_to_directives(impact)
    assert len(directives) == 1
    assert directives[0]["key"] == "kid1_away_from_home"
    assert directives[0]["value"] is True

def test_llm_context_key_rejects_non_canonical_keys():
    from services.routine_reconciler import _llm_impact_to_directives

    impact = {
        "context_key": "concert_mode",
        "context_value": True,
        "impact": "live_context",
        "reason": "bad_key",
    }

    directives = _llm_impact_to_directives(impact)
    assert directives == []

def test_partner_with_user_group_outing_reinforces_existing_state(monkeypatch):
    from services import routine_reconciler as rr

    monkeypatch.setattr(rr, "_partner_state_is_active", lambda now: True)

    out = rr._rule_partner_with_user("ηρθαμε θαλασσα ολοι μαζι", [], datetime(2026, 6, 28))

    assert out
    assert any(d.get("kind") == "context_state_set" and d.get("key") == "partner_with_user" for d in out)


def test_family_outing_without_child_still_sets_user_out_of_home():
    from services.routine_reconciler import _rule_family_outing_in_progress

    now = datetime(2026, 6, 28, 14, 0)

    directives = _rule_family_outing_in_progress(
        normalized="πηγαμε θαλασσα και ειμαστε εξω",
        dates=[],
        now=now,
    )

    assert any(
        d.get("kind") == "context_state_set"
        and d.get("key") == "user_out_of_home"
        and d.get("value") == "true"
        for d in directives
    )

    assert not any(
        d.get("kind") == "context_state_set"
        and d.get("key") == "state:kid1:outing"
        for d in directives
    )


def test_family_outing_future_plan_does_not_set_user_out_of_home():
    from services.routine_reconciler import _rule_family_outing_in_progress

    now = datetime(2026, 7, 4, 9, 37)

    directives = _rule_family_outing_in_progress(
        normalized="θα παμε καμια βολτα θα δω θα τον ρωτησω παρκο βολτα κατω κεντρο",
        dates=[],
        now=now,
    )

    assert directives == []


def test_family_outing_future_plan_with_unrelated_live_clause_does_not_set_outing():
    from services.routine_reconciler import _rule_family_outing_in_progress

    now = datetime(2026, 7, 4, 9, 37)

    directives = _rule_family_outing_in_progress(
        normalized="ο αλεξανδρος ειναι σπιτι ακομα αλλα θα παμε μετα παρκο",
        dates=[],
        now=now,
    )

    assert directives == []

def test_shift_logic_tomorrow_morning_work_auto_applies():
    from datetime import datetime
    from services.routine_reconciler import infer_routine_reconciliation_candidates, score_candidate_directive, _normalize

    fact = "[USER_FACT]: Αύριο είμαι πρωινός στη δουλειά, 5:30 ξύπνημα."

    candidates = infer_routine_reconciliation_candidates(
        fact,
        category="lazaros",
        reason="user_stated",
        now=datetime(2026, 7, 5, 22, 45, 0),  # Sunday night
    )

    assert any(
        c["kind"] == "context_state_set"
        and c["reason"] == "shift_morning_week"
        and c["key"] == "current_shift"
        and c["value"] == "morning"
        and c["rule_name"] == "shift_logic"
        for c in candidates
    )

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
        and d["auto_apply"] is True
        and d["key"] == "current_shift"
        and d["value"] == "morning"
        for d in scored
    )

def test_shift_logic_tomorrow_afternoon_work_auto_applies():
    from datetime import datetime
    from services.routine_reconciler import infer_routine_reconciliation_candidates

    fact = "[USER_FACT]: Αύριο είμαι απογευματινός στη δουλειά."

    candidates = infer_routine_reconciliation_candidates(
        fact,
        category="lazaros",
        reason="user_stated",
        now=datetime(2026, 7, 6, 21, 0, 0),
    )

    assert any(
        c["kind"] == "context_state_set"
        and c["reason"] == "shift_afternoon_week"
        and c["key"] == "current_shift"
        and c["value"] == "afternoon"
        and c["rule_name"] == "shift_logic"
        for c in candidates
    )

def test_shift_logic_relative_day_schedule_is_not_conservative():
    from services.routine_reconciler import infer_routine_reconciliation_candidates, score_candidate_directive, _normalize
    from datetime import datetime

    text = "αύριο είμαι πρωινός στη δουλειά 5:30 ξύπνημα"
    now = datetime(2026, 7, 5, 22, 0)

    candidates = infer_routine_reconciliation_candidates(text, category="work", reason="user_stated", now=now)
    shift = next(c for c in candidates if c.get("key") == "current_shift")
    scored = score_candidate_directive(
        shift,
        normalized_fact=_normalize(text),
        matched_rule_name="shift_logic",
    )

    assert "shift_logic_conservative" not in scored.get("ambiguity_flags", [])
    assert scored.get("score", 0) >= 0.75

def test_sofia_with_kid1_at_home_while_user_at_work_does_not_set_partner_with_user():
    from services.routine_reconciler import infer_routine_reconciliation_candidates
    from datetime import datetime

    text = "Εγώ είμαι πρωινή βάρδια αυτή την εβδομάδα και η Partner σήμερα είναι με τον Αλέξανδρο στο σπίτι"
    now = datetime(2026, 7, 6, 8, 30)

    candidates = infer_routine_reconciliation_candidates(
        text,
        category="family",
        reason="live_message_context",
        now=now,
    )

    sofia_true = [
        c for c in candidates
        if c.get("key") == "partner_with_user" and str(c.get("value")).lower() == "true"
    ]

    assert sofia_true == []
