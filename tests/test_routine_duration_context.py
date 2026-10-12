"""Duration proofs use isolated persistence and offline semantic boundaries."""
from datetime import datetime, timedelta
import json
from types import SimpleNamespace

import pytest

from services.routine_feedback import ATHENS

pytestmark = pytest.mark.usefixtures("offline_behavioral_io")
NOW = datetime(2026, 10, 12, 10, 45, tzinfo=ATHENS)


@pytest.mark.parametrize("ending", ["explicit_time", "day_commitment"])
def test_morning_work_duration_avoids_redundant_partner_question(tmp_path, monkeypatch, ending):
    """A grounded day/work duration survives the momentary two-hour cutoff."""
    from memory import conversation_history as history, routine_db as db
    from memory.routine_context_clarification import ClarificationStore
    from services import context_extractor as extractor
    from services.routine_context import build_routine_context_evidence
    from services.routine_context_clarification import RoutineCandidate
    from services.routine_context_clarification_poll import PollSnapshot, run_clarification_poll
    path = str(tmp_path / "history.db")
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "routines.db"))
    monkeypatch.setattr(extractor.config, "CONVERSATION_DB_FILE", path)
    db.setup_db()
    plan = history.append_message(role="user", channel="matrix", timestamp=NOW.replace(hour=7, minute=0),
        content="Σήμερα είμαστε ο καθένας στη δική του δουλειά μέχρι τις 14:00" if ending == "explicit_time"
            else "Σήμερα θα είμαστε χωριστά όλη μέρα στις δουλειές μας", db_path=path)
    source = history.append_message(role="user", channel="web", timestamp=NOW.replace(hour=7, minute=36),
        content="εφτασα δουλεια φιλε σημερα και η σοφια δουλευει", db_path=path)
    at = datetime.fromisoformat(source["timestamp"]).replace(tzinfo=ATHENS)
    db.set_context_states_if_unchanged({"partner_with_user": ("false", NOW.date().isoformat())},
        {"partner_with_user": None}, recorded_at=at)
    original = db.get_context_state("partner_with_user")
    condition = {"condition_type": "context_flag", "condition_mode": "suppress_when_true",
                 "condition_payload": {"flag": "partner_with_user", "equals": True}}
    routine = RoutineCandidate("4", "Μήνυμα στη Σοφία", NOW + timedelta(minutes=15), (condition,))
    def snapshot(current):
        return PollSnapshot((routine,), {}, build_routine_context_evidence(current,
            gps_loader=lambda: None), str(history.get_max_rowid(db_path=path)))
    def model(prompt):
        assert source["content"] in prompt
        return SimpleNamespace(text=json.dumps({"flags": {"partner_with_user": False},
            "event_rowid": source["rowid"], "support_rowids": [plan["rowid"], source["rowid"]],
            "duration_source_rowids": [plan["rowid"]],
            "valid_until": (NOW.replace(hour=14, minute=0) if ending == "explicit_time"
                else (NOW+timedelta(days=1)).replace(hour=0, minute=0)).isoformat()}))
    monkeypatch.setattr(extractor, "safe_gemini_call", model)
    args = dict(store=ClarificationStore(tmp_path / "questions.json"), clock=lambda: NOW,
        selected_channel=lambda: "matrix", snapshot_loader=snapshot, unavailable=lambda: False,
        classify=lambda _: pytest.fail("No redundant question"), budget=lambda: True,
        sender=lambda *a: pytest.fail("No outbound question"), record=lambda **k: None,
        resolve_context=lambda state, now, fresh: extractor.resolve_daily_context_before_question(
            ("partner_with_user",), now=now, still_current=fresh, channel="matrix", conversation_db_path=path))
    assert run_clarification_poll(**args) == "not_due"
    assert db.get_context_state("partner_with_user") == original
    assert snapshot(NOW).evidence["partner_with_user"].effective_value is False
    assert snapshot(NOW.replace(hour=14, minute=0) if ending == "explicit_time"
        else NOW+timedelta(days=1)).evidence["partner_with_user"].effective_value is None
    # A canonical state/GPS update invalidates duration even without new chat.
    db.set_context_state("user_out_of_home", "false", NOW.date().isoformat())
    assert snapshot(NOW).evidence["partner_with_user"].effective_value is None
    history.append_message(role="user", channel="telegram", timestamp=NOW,
        content="Τελικά ήρθε εδώ η Σοφία", db_path=path)
    assert snapshot(NOW).evidence["partner_with_user"].effective_value is None


@pytest.mark.parametrize("scenario", ["plain_presence", "both_work", "shared_workplace", "remote_work", "contradiction"])
def test_uncertain_duration_keeps_normal_question(tmp_path, monkeypatch, scenario):
    """Semantic refusal preserves the real clarification delivery lifecycle."""
    from memory import conversation_history as history, routine_db as db
    from memory.routine_context_clarification import ClarificationStore
    from services import context_extractor as extractor
    from services.routine_context_clarification import RoutineCandidate
    from services.routine_context_clarification_poll import PollSnapshot, run_clarification_poll
    from services.routine_context import build_routine_context_evidence
    path = str(tmp_path / "history.db")
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "routines.db"))
    monkeypatch.setattr(extractor.config, "CONVERSATION_DB_FILE", path)
    db.setup_db()
    texts = {"plain_presence": "Είμαι στη δουλειά, η Σοφία δεν είναι μαζί μου",
        "both_work": "εφτασα δουλεια φιλε σημερα και η σοφια δουλευει",
        "shared_workplace": "Σήμερα δουλεύουμε μαζί στο ίδιο γραφείο",
        "remote_work": "Δουλεύουμε και οι δύο από το σπίτι",
        "contradiction": "Σήμερα θα είμαστε σε διαφορετικές δουλειές μέχρι τις 14:00"}
    history.append_message(role="user", channel="web", content=texts[scenario],
        timestamp=NOW-timedelta(hours=3), db_path=path)
    if scenario == "contradiction":
        history.append_message(role="user", channel="telegram", content="Ήρθε τελικά εδώ η Σοφία",
            timestamp=NOW-timedelta(minutes=5), db_path=path)
    def model(prompt):
        assert "shared workplace" in prompt and "mere" in prompt
        return SimpleNamespace(text='{"flags": {}, "event_rowid": null, "support_rowids": []}')
    monkeypatch.setattr(extractor, "safe_gemini_call", model)
    condition = {"condition_type": "context_flag", "condition_mode": "suppress_when_true",
        "condition_payload": {"flag": "partner_with_user", "equals": True}}
    routine = RoutineCandidate("4", "Partner message", NOW+timedelta(minutes=15), (condition,))
    def snapshot(current):
        return PollSnapshot((routine,), {}, build_routine_context_evidence(current,
            gps_loader=lambda: None), str(history.get_max_rowid(db_path=path)))
    sent = []
    outcome = run_clarification_poll(store=ClarificationStore(tmp_path / "questions.json"),
        clock=lambda: NOW, selected_channel=lambda: "matrix", snapshot_loader=snapshot,
        unavailable=lambda: False, classify=lambda _: {"routine_ids": ["4"],
            "flags": ["partner_with_user"], "question": "Είστε μαζί τώρα;"},
        budget=lambda: True, sender=lambda *a: sent.append(a) or SimpleNamespace(channel="matrix", external_id="$question"),
        record=lambda **k: None,
        resolve_context=lambda state, now, fresh: extractor.resolve_daily_context_before_question(
            ("partner_with_user",), now=now, still_current=fresh, channel="matrix", conversation_db_path=path))
    assert outcome == "delivered" and len(sent) == 1
    assert db.get_context_state("routine_context_duration_proof") is None


@pytest.mark.parametrize("damage", ["json", "bool_version", "bool_flag", "naive_end", "missing_anchor", "old_marker"])
def test_corrupt_persisted_duration_fails_closed(tmp_path, monkeypatch, damage):
    """A malformed proof never becomes effective presence or renews old flags."""
    from memory import conversation_history as history, routine_db as db
    from services import context_extractor as extractor
    from services.routine_context import build_routine_context_evidence
    from services.routine_duration_context import DURATION_KEY
    path = str(tmp_path / "history.db")
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "routines.db"))
    monkeypatch.setattr(extractor.config, "CONVERSATION_DB_FILE", path)
    db.setup_db()
    source = history.append_message(role="user", channel="matrix", timestamp=NOW-timedelta(hours=3),
        content="Όλη μέρα χωριστά στις δουλειές μας", db_path=path)
    monkeypatch.setattr(extractor, "safe_gemini_call", lambda _: SimpleNamespace(text=json.dumps({
        "flags": {"partner_with_user": False}, "event_rowid": source["rowid"],
        "support_rowids": [source["rowid"]], "duration_source_rowids": [source["rowid"]],
        "valid_until": NOW.replace(hour=14, minute=0).isoformat()})))
    assert extractor.resolve_daily_context_before_question(("partner_with_user",), now=NOW,
        still_current=lambda: True, channel="matrix", conversation_db_path=path)
    proof = json.loads(db.get_context_state(DURATION_KEY)["value"])
    if damage == "bool_version": proof["version"] = True
    if damage == "bool_flag": proof["flags"]["partner_with_user"] = "false"
    if damage == "naive_end": proof["valid_until"] = "2026-10-12T14:00:00"
    if damage == "missing_anchor": del proof["anchors"]["partner_with_user"]
    if damage == "old_marker": proof["history_marker"] -= 1
    db.set_context_state(DURATION_KEY, "invalid json" if damage == "json" else json.dumps(proof), NOW.date().isoformat())
    assert build_routine_context_evidence(NOW, gps_loader=lambda: None)["partner_with_user"].effective_value is None


@pytest.mark.parametrize("invalid", ["no_duration_ids", "bad_source", "naive_end", "expired", "tomorrow",
    "yesterday", "non_boolean", "not_allowed", "state_race", "history_race", "snapshot_race"])
def test_duration_resolution_rejects_invalid_or_racing_evidence(tmp_path, monkeypatch, invalid):
    """Only bounded source proof survives canonical/history/final-snapshot guards."""
    from memory import conversation_history as history, routine_db as db
    from services import context_extractor as extractor
    path = str(tmp_path / "history.db")
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "routines.db"))
    db.setup_db()
    source = history.append_message(role="user", channel="web", content="Είμαστε σε διαφορετικές δουλειές σήμερα",
        timestamp=NOW-timedelta(days=1) if invalid == "yesterday" else NOW-timedelta(hours=3), db_path=path)
    payload = {"flags": {"partner_with_user": False}, "event_rowid": source["rowid"],
        "support_rowids": [source["rowid"]], "duration_source_rowids": [source["rowid"]],
        "valid_until": NOW.replace(hour=14, minute=0).isoformat()}
    if invalid == "no_duration_ids": payload["duration_source_rowids"] = []
    if invalid == "bad_source": payload["duration_source_rowids"] = [999]
    if invalid == "naive_end": payload["valid_until"] = "2026-10-12T14:00:00"
    if invalid == "expired": payload["valid_until"] = NOW.isoformat()
    if invalid == "tomorrow": payload["valid_until"] = (NOW+timedelta(days=1)).isoformat()
    if invalid == "non_boolean": payload["flags"]["partner_with_user"] = "false"
    if invalid == "not_allowed": payload["flags"] = {"kid1_with_user": False}
    def model(_):
        if invalid == "state_race": db.set_context_state("partner_with_user", "true", NOW.date().isoformat())
        if invalid == "history_race": history.append_message(role="user", channel="matrix",
            content="Πήγαμε μαζί τελικά", timestamp=NOW, db_path=path)
        return SimpleNamespace(text=json.dumps(payload))
    monkeypatch.setattr(extractor, "safe_gemini_call", model)
    assert not extractor.resolve_daily_context_before_question(("partner_with_user",), now=NOW,
        still_current=lambda: invalid != "snapshot_race", channel="matrix", conversation_db_path=path)
    assert db.get_context_state("routine_context_duration_proof") is None
