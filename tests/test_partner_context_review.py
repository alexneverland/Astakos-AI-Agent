"""Partner review regressions with native isolated stores and blocked transports."""
from datetime import datetime, timedelta
import json
from pathlib import Path
from types import ModuleType
from unittest.mock import MagicMock, patch

import pytest

from services.routine_feedback import ATHENS

pytestmark = pytest.mark.usefixtures("offline_behavioral_io")
NOW = datetime(2026, 11, 11, 11, tzinfo=ATHENS)


@pytest.mark.parametrize("outside", [False, True])
def test_off_work_does_not_supply_partner_location(outside: bool) -> None:
    """Only grounded relationship evidence may determine presence or absence."""
    from services.context_extractor import extract_and_update_context_flags
    with (
        patch("services.context_extractor.safe_gemini_call", return_value=MagicMock(
            text=json.dumps({"user_out_of_home": outside, "partner_at_work": False}))),
        patch("services.context_extractor.get_context_state", return_value=None),
        patch("services.context_extractor.set_context_states_if_unchanged", return_value=True) as saved,
        patch("services.context_extractor.infer_routine_reconciliation_directives", return_value=[]),
        patch("services.context_extractor.apply_routine_reconciliation_directives"),
    ):
        extract_and_update_context_flags("My partner has today off; her location is unknown.", now=NOW)
    assert "partner_with_user" not in saved.call_args.args[0]


@pytest.mark.parametrize("mode", [None, "office"])
def test_work_state_does_not_supply_relationship(mode: str | None) -> None:
    """Office work can be shared; a work flag cannot replace relationship evidence."""
    from services.context_extractor import extract_and_update_context_flags
    payload = {"partner_at_work": True}
    if mode:
        payload["partner_work_mode"] = mode
    with (
        patch("services.context_extractor.safe_gemini_call", return_value=MagicMock(text=json.dumps(payload))),
        patch("services.context_extractor.get_context_state", return_value=None),
        patch("services.context_extractor.set_context_states_if_unchanged", return_value=True) as saved,
        patch("services.context_extractor.infer_routine_reconciliation_directives", return_value=[]),
        patch("services.context_extractor.apply_routine_reconciliation_directives"),
    ):
        extract_and_update_context_flags("My partner is working today.", now=NOW)
    flags = saved.call_args.args[0]
    assert "partner_with_user" not in flags
    if mode is None:
        assert "partner_work_mode" not in flags


@pytest.fixture
def partner_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    """Seed a fresh together observation without accessing production persistence."""
    from memory import routine_db as db
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "routines.db"))
    db.setup_db()
    initial = {"user_out_of_home": ("true", NOW.date().isoformat()),
               "partner_at_work": ("false", NOW.date().isoformat()),
               "partner_with_user": ("true", NOW.date().isoformat())}
    assert db.set_context_states_if_unchanged(initial, {key: None for key in initial},
                                             recorded_at=NOW-timedelta(minutes=10))
    return db


def test_same_value_refresh_preserves_explicit_together(partner_store: ModuleType) -> None:
    """Already outside together remains together after a newer location ping."""
    from services.routine_context import build_routine_context_evidence
    db = partner_store
    assert db.set_context_states_if_unchanged(
        {"user_out_of_home": ("true", NOW.date().isoformat())},
        {"user_out_of_home": db.get_context_state("user_out_of_home")}, recorded_at=NOW)
    assert build_routine_context_evidence(NOW, gps_loader=lambda: None)["partner_with_user"].effective_value is True


@pytest.mark.parametrize("invalid", ["expired", "history", "anchor", "malformed"])
def test_invalid_proof_cannot_erase_fresh_presence(partner_store: ModuleType, invalid: str) -> None:
    """A rejected optional proof leaves a fresh direct observation intact."""
    from services.routine_context import build_routine_context_evidence
    from memory import conversation_history as history
    import config
    db = partner_store
    row = history.append_message(role="user", channel="web", content="We remain apart until noon.",
        timestamp=NOW-timedelta(minutes=5), db_path=config.CONVERSATION_DB_FILE)
    proof = {"version": 1, "flags": {"partner_with_user": False},
        "event_at": (NOW-timedelta(minutes=5)).isoformat(),
        "valid_until": (NOW-timedelta(minutes=1) if invalid == "expired" else NOW+timedelta(hours=1)).isoformat(),
        "history_marker": 999 if invalid == "history" else row["rowid"],
        "source_rowids": [row["rowid"]], "anchors": {"partner_with_user": db.get_context_state("partner_with_user")}}
    if invalid == "anchor":
        proof["anchors"]["partner_with_user"] = None
    raw = "{" if invalid == "malformed" else json.dumps(proof)
    db.set_context_state("routine_context_duration_proof", raw, NOW.date().isoformat())
    assert build_routine_context_evidence(NOW, gps_loader=lambda: None)["partner_with_user"].effective_value is True


@pytest.mark.parametrize("writer", ["batch", "single"])
def test_location_roundtrip_cannot_revive_duration(partner_store: ModuleType, writer: str) -> None:
    """A transition invalidates a proof permanently, including between evaluations."""
    from memory import conversation_history as history
    from services.routine_duration_context import DURATION_KEY, apply_duration_evidence
    from services.routine_context_evidence import ContextEvidence
    import config
    db = partner_store
    row = history.append_message(role="user", channel="web", content="We remain apart until noon.",
        timestamp=NOW-timedelta(minutes=20), db_path=config.CONVERSATION_DB_FILE)
    proof = {"version": 1, "flags": {"partner_with_user": False},
        "event_at": (NOW-timedelta(minutes=20)).isoformat(),
        "valid_until": (NOW+timedelta(hours=1)).isoformat(), "history_marker": row["rowid"],
        "source_rowids": [row["rowid"]], "anchors": {key: db.get_context_state(key)
            for key in ("partner_with_user", "user_out_of_home")}}
    db.set_context_state(DURATION_KEY, json.dumps(proof), NOW.date().isoformat())
    for value in ("false", "true"):
        if writer == "single":
            db.set_context_state("user_out_of_home", value, NOW.date().isoformat())
        else:
            assert db.set_context_states_if_unchanged({"user_out_of_home": (value, NOW.date().isoformat())},
                {"user_out_of_home": db.get_context_state("user_out_of_home")}, recorded_at=NOW)
    evidence = {"partner_with_user": ContextEvidence(reason="stale")}
    assert apply_duration_evidence(evidence, now=NOW, state_reader=db.get_context_state,
                                  history_marker=row["rowid"])["partner_with_user"].effective_value is None


@pytest.mark.parametrize("text", ["Είμαι μαζί με τη Σοφία τώρα.",
    "Η Σοφία είναι μαζί μου, ο Αλέξανδρος έφυγε για σχολείο.",
    "Αφού δουλεύουμε χωριστά, πώς γίνεται να είμαι μαζί της;"])
def test_presence_fallback_does_not_reinterpret_words(text: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """When semantic extraction abstains, phrase heuristics cannot assert presence."""
    from services import routine_reconciler as reconciler
    monkeypatch.setattr(reconciler, "_infer_llm_reconciliation_candidates", lambda *a, **k: [])
    result = reconciler.infer_routine_reconciliation_candidates(text, category="family", reason="user_stated", now=NOW)
    assert not any(item.get("key") == "partner_with_user" or
                   item.get("condition_payload", {}).get("flag") == "partner_with_user" for item in result)


@pytest.mark.parametrize("outside", [False, True])
def test_explicit_shared_presence_survives_off_work_report(outside: bool) -> None:
    """Grounded model co-presence survives independent work and location clauses."""
    from services.context_extractor import extract_and_update_context_flags
    with (
        patch("services.context_extractor.safe_gemini_call", return_value=MagicMock(text=json.dumps({
            "user_out_of_home": outside, "partner_at_work": False, "partner_with_user": True}))),
        patch("services.context_extractor.get_context_state", return_value=None),
        patch("services.context_extractor.set_context_states_if_unchanged", return_value=True) as saved,
        patch("services.context_extractor.infer_routine_reconciliation_directives", return_value=[]),
        patch("services.context_extractor.apply_routine_reconciliation_directives"),
    ):
        extract_and_update_context_flags("We are together now. My partner has the day off.", now=NOW)
    assert saved.call_args.args[0]["partner_with_user"][0] == "true"


def test_departure_read_error_still_attempts_duration(
    partner_store: ModuleType, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
) -> None:
    """An optional transition failure cannot skip the independent proof reader."""
    from memory import conversation_history as history
    from services.routine_context import build_routine_context_evidence
    from services.routine_duration_context import DURATION_KEY
    import config
    db = partner_store
    assert db.set_context_states_if_unchanged(
        {"partner_with_user": ("true", NOW.date().isoformat())},
        {"partner_with_user": db.get_context_state("partner_with_user")},
        recorded_at=NOW-timedelta(hours=3))
    row = history.append_message(role="user", channel="web", content="We remain apart until noon.",
        timestamp=NOW-timedelta(minutes=20), db_path=config.CONVERSATION_DB_FILE)
    proof = {"version": 1, "flags": {"partner_with_user": False},
        "event_at": (NOW-timedelta(minutes=20)).isoformat(),
        "valid_until": (NOW+timedelta(hours=1)).isoformat(), "history_marker": row["rowid"],
        "source_rowids": [row["rowid"]], "anchors": {key: db.get_context_state(key)
            for key in ("partner_with_user", "user_out_of_home")}}
    db.set_context_state(DURATION_KEY, json.dumps(proof), NOW.date().isoformat())
    original = db.get_context_state

    def reader(key: str) -> dict | None:
        """Fail only the optional transition metadata read."""
        if key == db.CONTEXT_LOCATION_TRANSITION_KEY:
            raise OSError("synthetic transient read failure")
        return original(key)

    monkeypatch.setattr(db, "get_context_state", reader)
    result = build_routine_context_evidence(NOW, gps_loader=lambda: None)
    assert result["partner_with_user"].effective_value is False
    assert result["partner_with_user"].source == "explicit_duration"
    assert "departure evidence unavailable" in caplog.text


def test_stale_owner_location_rejects_duration_commit(partner_store: ModuleType) -> None:
    """Old location cannot be promoted into current day-long separation."""
    from services.routine_duration_context import DURATION_KEY, commit_duration_resolution
    db = partner_store
    before = NOW-timedelta(hours=3)
    row = {"rowid": 1, "timestamp": before.isoformat()}
    assert db.set_context_states_if_unchanged(
        {"partner_with_user": ("false", NOW.date().isoformat()),
         "user_out_of_home": ("true", NOW.date().isoformat())},
        {key: db.get_context_state(key) for key in ("partner_with_user", "user_out_of_home")},
        recorded_at=before)
    expected = {key: db.get_context_state(key) for key in ("partner_with_user", "user_out_of_home", DURATION_KEY)}
    payload = {"flags": {"partner_with_user": False}, "event_rowid": 1,
        "support_rowids": [1], "duration_source_rowids": [1],
        "valid_until": (NOW+timedelta(hours=1)).isoformat()}
    assert commit_duration_resolution(payload, [row], expected, allowed={"partner_with_user"},
        now=NOW, still_current=lambda: True) is None
    assert db.get_context_state(DURATION_KEY) is None


def test_stale_location_cannot_sustain_existing_proof(partner_store: ModuleType) -> None:
    """A proof expires with its necessary current location, even without writes."""
    from services.routine_duration_context import DURATION_KEY, apply_duration_evidence
    from services.routine_context_evidence import ContextEvidence
    db = partner_store
    proof = {"version": 1, "flags": {"partner_with_user": False},
        "event_at": (NOW-timedelta(minutes=20)).isoformat(),
        "valid_until": (NOW+timedelta(hours=4)).isoformat(), "history_marker": 1,
        "source_rowids": [1], "anchors": {key: db.get_context_state(key)
            for key in ("partner_with_user", "user_out_of_home")}}
    db.set_context_state(DURATION_KEY, json.dumps(proof), NOW.date().isoformat())
    evidence = {"partner_with_user": ContextEvidence(reason="stale")}
    assert apply_duration_evidence(evidence, now=NOW+timedelta(hours=3), state_reader=db.get_context_state,
        history_marker=1)["partner_with_user"].effective_value is None


def test_conflicting_gps_cannot_sustain_location_proof(partner_store: ModuleType) -> None:
    """A fresh stored location is insufficient when current GPS contradicts it."""
    from services.routine_duration_context import DURATION_KEY, apply_duration_evidence
    from services.routine_context_evidence import ContextEvidence
    db = partner_store
    proof = {"version": 1, "flags": {"partner_with_user": False},
        "event_at": (NOW-timedelta(minutes=20)).isoformat(),
        "valid_until": (NOW+timedelta(hours=1)).isoformat(), "history_marker": 1,
        "source_rowids": [1], "anchors": {key: db.get_context_state(key)
            for key in ("partner_with_user", "user_out_of_home")}}
    db.set_context_state(DURATION_KEY, json.dumps(proof), NOW.date().isoformat())
    evidence = {"partner_with_user": ContextEvidence(reason="stale"),
                "user_out_of_home": ContextEvidence(source="conflict", reason="conflict")}
    assert apply_duration_evidence(evidence, now=NOW, state_reader=db.get_context_state,
        history_marker=1)["partner_with_user"].effective_value is None
