"""A newer same-value GPS observation must not discard a grounded reunion."""

import json
from datetime import datetime, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

NOW = datetime(2026, 10, 9, 20, 29, tzinfo=ZoneInfo("Europe/Athens"))
REPORT_AT = NOW - timedelta(minutes=4)
REPORT = ("Σε πάρκο είμαι στο πάρκο του Γεωργίου Ιβάνοφ πιο πάνω από εκεί που λες "
          "αποθήκευσε αυτές τις συντεταγμένες με αυτό το μέρος εκεί που έχεις "
          "αποθηκευμένες και για την δουλειά και για το σπίτι ήρθα στο πάρκο και τους βρήκα")


@pytest.mark.parametrize("refresh_during_model", [False, True])
def test_reunion_survives_newer_agreeing_gps(tmp_path, monkeypatch, refresh_during_model):
    from memory import conversation_history as history, routine_db as db
    from services import context_extractor as extractor

    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "routines.db"))
    db.setup_db()
    path = str(tmp_path / "history.db")
    history.append_message(role="user", channel="web", timestamp=REPORT_AT-timedelta(minutes=20),
        content="Η Σοφία και ο Αλέξανδρος είναι στο πάρκο, πάω να τους βρω", db_path=path)
    source = history.append_message(role="user", channel="matrix", timestamp=REPORT_AT,
        content=REPORT, db_path=path)
    old = REPORT_AT-timedelta(minutes=10)
    initial = {key: ("false", NOW.date().isoformat())
               for key in ("partner_with_user", "kid1_with_user")}
    initial["user_out_of_home"] = ("true", NOW.date().isoformat())
    db.set_context_states_if_unchanged(initial, {key: None for key in initial}, recorded_at=old)

    def refresh():
        previous = db.get_context_state("user_out_of_home")
        db.set_context_states_if_unchanged({"user_out_of_home": ("true", NOW.date().isoformat())},
            {"user_out_of_home": previous}, recorded_at=NOW-timedelta(minutes=1))

    if not refresh_during_model:
        refresh()

    def model(prompt):
        assert "Η Σοφία και ο Αλέξανδρος" in prompt
        if refresh_during_model:
            refresh()
        return SimpleNamespace(text=json.dumps({"flags": {"user_out_of_home": True,
            "partner_with_user": True, "kid1_with_user": True, "user_at_work": False},
            "event_rowid": source["rowid"], "support_rowids": [source["rowid"]]}))

    monkeypatch.setattr(extractor, "safe_gemini_call", model)
    monkeypatch.setattr(extractor, "reconcile_context_message", lambda _: None)
    extractor.extract_and_update_context_flags(REPORT, channel="matrix", now=NOW,
        conversation_db_path=path)
    for key in ("partner_with_user", "kid1_with_user", "kid1_with_partner"):
        assert db.get_context_state(key)["value"] == "true"
        assert db.get_context_state(key)["updated_at"] == REPORT_AT.isoformat()
    assert db.get_context_state("kid1_away_from_home")["value"] == "false"
    assert db.get_context_state("user_out_of_home")["updated_at"] == (NOW-timedelta(minutes=1)).isoformat()


@pytest.mark.parametrize("during_model", [False, True])
def test_newer_contrary_evidence_blocks_old_reunion(tmp_path, monkeypatch, during_model):
    from memory import conversation_history as history, routine_db as db
    from services import context_extractor as extractor

    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "routines.db"))
    db.setup_db()
    path = str(tmp_path / "history.db")
    source = history.append_message(role="user", channel="matrix", content=REPORT,
        timestamp=REPORT_AT, db_path=path)
    db.set_context_states_if_unchanged({"user_out_of_home": ("true" if during_model else "false", "2026-10-09")},
        {"user_out_of_home": None}, recorded_at=REPORT_AT-timedelta(minutes=1) if during_model else NOW-timedelta(minutes=1))
    def model(_):
        if during_model:
            db.set_context_states_if_unchanged({"user_out_of_home": ("false", "2026-10-09")},
                {"user_out_of_home": db.get_context_state("user_out_of_home")},
                recorded_at=NOW-timedelta(minutes=1))
        return SimpleNamespace(text=json.dumps({
            "flags": {"user_out_of_home": True, "partner_with_user": True},
            "event_rowid": source["rowid"], "support_rowids": [source["rowid"]]}))
    monkeypatch.setattr(extractor, "safe_gemini_call", model)
    monkeypatch.setattr(extractor, "reconcile_context_message", lambda _: None)
    extractor.extract_and_update_context_flags(REPORT, now=NOW, conversation_db_path=path)
    assert db.get_context_state("partner_with_user") is None
    assert db.get_context_state("user_out_of_home")["value"] == "false"
