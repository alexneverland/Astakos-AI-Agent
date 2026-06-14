from memory import analytics_state


def _msg(rowid, *, date="2026-06-01", time="12:10", content="πήγα για ψάρια"):
    return {
        "rowid": rowid,
        "id": f"msg-{rowid}",
        "date": date,
        "time": time,
        "channel": "telegram",
        "content": content,
    }


def test_progress_defaults_and_updates(tmp_path):
    db_path = str(tmp_path / "analytics_state.db")

    assert analytics_state.get_progress(db_path=db_path)["last_rowid"] == 0

    analytics_state.set_progress(last_rowid=42, bootstrap_completed=True, db_path=db_path)
    progress = analytics_state.get_progress(db_path=db_path)

    assert progress["last_rowid"] == 42
    assert progress["bootstrap_completed"] is True


def test_add_occurrence_creates_candidate_and_dedupes_message(tmp_path):
    db_path = str(tmp_path / "analytics_state.db")

    first = analytics_state.add_occurrence(
        day_of_week="Saturday",
        time_bucket="12:00",
        event_name="αγορά ψαριών",
        event_type="family",
        message=_msg(10),
        week_id="2026-W23",
        db_path=db_path,
    )
    duplicate = analytics_state.add_occurrence(
        day_of_week="Saturday",
        time_bucket="12:00",
        event_name="αγορά ψαριών",
        event_type="family",
        message=_msg(10),
        week_id="2026-W23",
        db_path=db_path,
    )

    assert first["action"] == "created_candidate"
    assert duplicate["action"] == "duplicate_occurrence"
    assert analytics_state.state_stats(db_path=db_path) == {
        "candidates": 1,
        "occurrences": 1,
        "promoted": 0,
    }


def test_similar_occurrences_merge_into_same_candidate(tmp_path):
    db_path = str(tmp_path / "analytics_state.db")

    analytics_state.add_occurrence(
        day_of_week="Saturday",
        time_bucket="12:00",
        event_name="αγορά ψαριών",
        event_type="family",
        message=_msg(10),
        week_id="2026-W23",
        db_path=db_path,
    )
    second = analytics_state.add_occurrence(
        day_of_week="Σάββατο",
        time_bucket="12:00",
        event_name="αγορά φρέσκων ψαριών",
        event_type="family",
        message=_msg(11, date="2026-06-08"),
        week_id="2026-W24",
        db_path=db_path,
        similarity_threshold=0.45,
    )

    candidates = analytics_state.list_candidates(db_path=db_path)

    assert second["action"] == "merged_candidate"
    assert len(candidates) == 1
    assert candidates[0]["occurrence_count"] == 2
    assert candidates[0]["week_count"] == 2


def test_eligible_candidates_and_promoted_status(tmp_path):
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
            message=_msg(rowid, date=date),
            week_id=week,
            db_path=db_path,
        )

    ready = analytics_state.eligible_candidates(
        min_occurrences=3,
        min_weeks=2,
        everyday_days=5,
        db_path=db_path,
    )
    assert len(ready) == 1

    analytics_state.mark_promoted(ready[0]["id"], result="merged", db_path=db_path)

    assert analytics_state.eligible_candidates(
        min_occurrences=3,
        min_weeks=2,
        everyday_days=5,
        db_path=db_path,
    ) == []
    assert analytics_state.state_stats(db_path=db_path)["promoted"] == 1
