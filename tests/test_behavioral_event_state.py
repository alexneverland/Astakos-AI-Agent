from memory import behavioral_event_state


def _event(**overrides):
    event = {
        "event_type": "substance_use",
        "category": "health",
        "subject": "user",
        "item": "alcohol",
        "item_detail": "tsipouro",
        "status": "consumed",
        "event_date": "2026-08-13",
        "confidence": 0.93,
        "negated": False,
        "hypothetical": False,
        "reported_by_user": True,
        "source_message_id": "telegram:123",
        "source_rowid": 123,
        "source_channel": "telegram",
        "record_state": "confirmed",
    }
    event.update(overrides)
    return event


def test_store_records_confirmed_event_and_rejects_source_replay(tmp_path):
    db_path = str(tmp_path / "behavioral_events.db")

    first = behavioral_event_state.record_event(_event(), db_path=db_path)
    replay = behavioral_event_state.record_event(_event(), db_path=db_path)

    assert first["action"] == "recorded"
    assert replay == {"action": "duplicate_source", "event_id": first["event_id"]}
    events = behavioral_event_state.list_events(db_path=db_path)
    assert len(events) == 1
    assert events[0]["record_state"] == "confirmed"
    assert events[0]["item_detail"] == "tsipouro"


def test_store_keeps_candidate_separate_from_confirmed_events(tmp_path):
    db_path = str(tmp_path / "behavioral_events.db")

    behavioral_event_state.record_event(_event(record_state="candidate"), db_path=db_path)

    assert behavioral_event_state.list_events(record_state="confirmed", db_path=db_path) == []
    candidates = behavioral_event_state.list_events(record_state="candidate", db_path=db_path)
    assert len(candidates) == 1
    assert candidates[0]["record_state"] == "candidate"


def test_read_only_list_does_not_create_a_missing_event_database(tmp_path):
    db_path = str(tmp_path / "behavioral_events.db")

    assert behavioral_event_state.list_events(db_path=db_path, initialize=False) == []
    assert not (tmp_path / "behavioral_events.db").exists()


def test_progress_starts_empty_and_updates_independently(tmp_path):
    db_path = str(tmp_path / "behavioral_events.db")

    assert behavioral_event_state.get_progress(db_path=db_path)["last_rowid"] == 0

    behavioral_event_state.set_progress(last_rowid=77, db_path=db_path)

    assert behavioral_event_state.get_progress(db_path=db_path)["last_rowid"] == 77


def test_progress_never_moves_backwards_after_a_concurrent_worker_finishes_late(tmp_path):
    db_path = str(tmp_path / "behavioral_events.db")

    behavioral_event_state.set_progress(last_rowid=77, db_path=db_path)
    behavioral_event_state.set_progress(last_rowid=42, db_path=db_path)

    assert behavioral_event_state.get_progress(db_path=db_path)["last_rowid"] == 77


def test_store_rejects_non_boolean_safety_flags(tmp_path):
    db_path = str(tmp_path / "behavioral_events.db")

    try:
        behavioral_event_state.record_event(_event(negated="false"), db_path=db_path)
    except ValueError as exc:
        assert "boolean" in str(exc)
    else:
        raise AssertionError("non-boolean safety flag was accepted")
