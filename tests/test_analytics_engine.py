def test_analytics_loader_uses_shared_history(monkeypatch):
    from services import analytics_engine

    shared = [{"role": "user", "content": "shared", "date": "2026-06-04", "time": "10:00"}]

    calls = []
    monkeypatch.setattr(
        analytics_engine,
        "_load_shared_user_messages",
        lambda cutoff: (calls.append(cutoff) or shared),
    )

    messages, source = analytics_engine._load_user_messages_for_analytics("2026-06-01")

    assert messages == shared
    assert source == "shared_sqlite"
    assert calls == ["2026-06-01"]


def test_analytics_loader_has_no_legacy_json_fallback(monkeypatch):
    from services import analytics_engine

    monkeypatch.setattr(analytics_engine, "_load_shared_user_messages", lambda cutoff: [])

    messages, source = analytics_engine._load_user_messages_for_analytics("2026-06-01")

    assert messages == []
    assert source == "shared_sqlite"
    assert not hasattr(analytics_engine, "_load_legacy_history")
    assert not hasattr(analytics_engine, "_filter_recent_user_messages")


def test_record_incremental_activities_writes_state_candidates(tmp_path):
    from services import analytics_engine
    from memory import analytics_state

    db_path = str(tmp_path / "analytics_state.db")
    messages = [
        {
            "rowid": 10,
            "id": "m10",
            "role": "user",
            "date": "2026-06-01",
            "time": "12:10",
            "channel": "telegram",
            "content": "πήγα στη λαϊκή για ψάρια",
        },
        {
            "rowid": 11,
            "id": "m11",
            "role": "user",
            "date": "2026-06-08",
            "time": "12:14",
            "channel": "telegram",
            "content": "πήρα πάλι φρέσκα ψάρια",
        },
    ]
    activities = [("αγορά ψαριών", "family"), ("αγορά ψαριών", "family")]

    stats = analytics_engine._record_incremental_activities(
        messages,
        activities,
        state_db_path=db_path,
    )

    assert stats["recorded"] == 2
    candidates = analytics_state.list_candidates(db_path=db_path)
    assert len(candidates) == 1
    assert candidates[0]["occurrence_count"] == 2
    assert candidates[0]["week_count"] == 2


def test_promote_incremental_candidates_uses_upsert_and_marks_promoted(tmp_path, monkeypatch):
    from services import analytics_engine
    from memory import analytics_state

    db_path = str(tmp_path / "analytics_state.db")
    for rowid, date, week in [
        (10, "2026-06-01", "2026-W23"),
        (11, "2026-06-08", "2026-W24"),
        (12, "2026-06-15", "2026-W25"),
    ]:
        analytics_state.add_occurrence(
            day_of_week="Saturday",
            time_bucket="12:00",
            event_name="αγορά ψαριών",
            event_type="family",
            message={
                "rowid": rowid,
                "id": f"m{rowid}",
                "date": date,
                "time": "12:10",
                "channel": "telegram",
                "content": "ψάρια",
            },
            week_id=week,
            db_path=db_path,
        )

    calls = []

    def fake_upsert_routine(**kwargs):
        calls.append(kwargs)
        return "merged"

    import memory.routine_db as routine_db

    monkeypatch.setattr(routine_db, "upsert_routine", fake_upsert_routine)

    stats, promoted = analytics_engine._promote_incremental_candidates(
        dry_run=False,
        state_db_path=db_path,
    )

    assert stats["merged"] == 1
    assert len(promoted) == 1
    assert calls[0]["event"] == "αγορά ψαριών"
    assert analytics_state.eligible_candidates(
        min_occurrences=3,
        min_weeks=2,
        everyday_days=5,
        db_path=db_path,
    ) == []


def test_incremental_dry_run_does_not_create_state_db(tmp_path, monkeypatch):
    from services import analytics_engine

    db_path = str(tmp_path / "analytics_state.db")
    monkeypatch.setattr(
        analytics_engine,
        "_load_incremental_messages",
        lambda after_rowid, limit: ([], 123, 0),
    )

    stats = analytics_engine.run_analytics_incremental(
        dry_run=True,
        state_db_path=db_path,
    )

    assert stats["last_rowid_after"] == 123
    assert not (tmp_path / "analytics_state.db").exists()
