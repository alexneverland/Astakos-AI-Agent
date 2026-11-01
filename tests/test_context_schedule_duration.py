"""Scheduled bounds augment owner-day evidence without renewing observations."""
from datetime import datetime, timedelta
from pathlib import Path
import json
from types import SimpleNamespace
from typing import Any

import pytest

from memory.routine_context_clarification import ATHENS

pytestmark = pytest.mark.usefixtures("offline_behavioral_io")
NOW = datetime(2026, 10, 15, 10, 46, tzinfo=ATHENS)


@pytest.fixture
def episode(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Any, ...]:
    """Create an isolated schedule and the exact two morning owner reports."""
    from memory import conversation_history as history, routine_db as db
    from services import context_extractor as extractor
    path = str(tmp_path / "history.db")
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "routine.db"))
    monkeypatch.setattr(extractor.config, "CONVERSATION_DB_FILE", path)
    monkeypatch.setattr("services.routine_context.GPS_STORAGE_FILE", str(tmp_path / "gps.json"))
    db.setup_db()
    db.import_declared_routines([{"day": "Everyday", "time": "15:30", "event": "σχόλασμα από τη δουλειά", "type": "work"}])
    schedule_id = db.get_routines_for_day("Thursday")[0]["id"]
    plan = history.append_message(role="user", channel="matrix", timestamp=NOW.replace(hour=6, minute=21),
        content="Έφυγα φίλε στο δρόμο είμαι κρύο σήμερα πολύ. Η σοφία δουλεύει σήμερα και τα παιδιά σχολείο", db_path=path)
    arrived = history.append_message(role="user", channel="web", timestamp=NOW.replace(hour=7, minute=11),
        content="εφτασα δουλεια φιλε", db_path=path)
    at = datetime.fromisoformat(arrived["timestamp"]).replace(tzinfo=ATHENS)
    db.set_context_states_if_unchanged({"partner_with_user": ("false", NOW.date().isoformat())},
        {"partner_with_user": None}, recorded_at=at)
    return extractor, history, db, path, plan, arrived, schedule_id


def decision(plan: dict, arrived: dict, schedule_id: int) -> dict:
    """Represent a semantic decision grounded in the supplied owner reports."""
    return {"flags": {"partner_with_user": False}, "event_rowid": arrived["rowid"],
        "support_rowids": [plan["rowid"], arrived["rowid"]], "duration_source_rowids": [plan["rowid"]],
        "schedule_routine_id": schedule_id, "valid_until": NOW.replace(hour=15, minute=30).isoformat()}


def test_morning_episode_uses_canonical_schedule_before_question(
    episode: tuple[Any, ...], tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Exercise real inference validation, proof persistence and clarification poll."""
    from services.routine_context import build_routine_context_evidence
    from services.routine_context_clarification import RoutineCandidate
    from services.routine_context_clarification_poll import PollSnapshot, run_clarification_poll
    from memory.routine_context_clarification import ClarificationStore
    extractor, history, db, path, plan, arrived, schedule_id = episode
    original = db.get_context_state("partner_with_user")
    def model(prompt: str) -> SimpleNamespace:
        assert '"daily_schedule"' in prompt and 'σχόλασμα από τη δουλειά' in prompt
        assert arrived["content"] in prompt and plan["content"] in prompt
        return SimpleNamespace(text=json.dumps(decision(plan, arrived, schedule_id)))
    monkeypatch.setattr(extractor, "safe_gemini_call", model)
    candidate = RoutineCandidate("4", "Μήνυμα στη Σοφία", NOW + timedelta(minutes=14), ({
        "condition_type": "context_flag", "condition_mode": "suppress_when_true",
        "condition_payload": {"flag": "partner_with_user", "equals": True}},))
    def snapshot(now: datetime) -> PollSnapshot:
        return PollSnapshot((candidate,), {}, build_routine_context_evidence(now, gps_loader=lambda: None),
            str(history.get_max_rowid(db_path=path)))
    assert run_clarification_poll(store=ClarificationStore(tmp_path / "questions.json"), clock=lambda: NOW,
        selected_channel=lambda: "matrix", snapshot_loader=snapshot, unavailable=lambda: False,
        classify=lambda _: pytest.fail("Already grounded context needs no question"), budget=lambda: True,
        sender=lambda *a: pytest.fail("No outbound question"), record=lambda **k: None,
        resolve_context=lambda state, now, fresh: extractor.resolve_daily_context_before_question(
            ("partner_with_user",), now=now, still_current=fresh, channel="matrix", conversation_db_path=path)) == "not_due"
    assert db.get_context_state("partner_with_user") == original
    assert snapshot(NOW).evidence["partner_with_user"].effective_value is False
    assert snapshot(NOW.replace(hour=15, minute=30)).evidence["partner_with_user"].effective_value is None
    db.update_routine_db(schedule_id, new_time="16:00")
    assert snapshot(NOW).evidence["partner_with_user"].effective_value is None


@pytest.mark.parametrize("damage", ["wrong_id", "bool_id", "invented_end", "external_schedule",
    "schedule_race", "history_race", "state_race", "paused", "wrong_shift", "unknown_presence"])
def test_schedule_bound_cannot_outlive_its_sources(
    episode: tuple[Any, ...], monkeypatch: pytest.MonkeyPatch, damage: str,
) -> None:
    """Untrusted schedules, invented hours and racing inputs cannot persist proof."""
    extractor, history, db, path, plan, arrived, schedule_id = episode
    payload = decision(plan, arrived, schedule_id)
    if damage == "wrong_id": payload["schedule_routine_id"] = 999999
    if damage == "bool_id": payload["schedule_routine_id"] = True
    if damage == "invented_end": payload["valid_until"] = NOW.replace(hour=17).isoformat()
    if damage == "external_schedule":
        db.upsert_routine(day="Everyday", time="15:30", event="σχόλασμα από τη δουλειά",
                          external_content_sources=["browse_url"])
    if damage == "paused": db.set_routine_paused_until(schedule_id, (NOW + timedelta(days=1)).isoformat())
    if damage == "wrong_shift": db.set_routine_condition(schedule_id, condition_type="shift_mode",
        condition_payload='{"flag":"current_shift","equals":"afternoon"}', condition_mode="allow_when_true")
    if damage == "unknown_presence": db.set_routine_condition(schedule_id, condition_type="context_flag",
        condition_payload='{"flag":"partner_with_user","equals":true}', condition_mode="suppress_when_true")
    def model(_: str) -> SimpleNamespace:
        if damage == "schedule_race": db.update_routine_db(schedule_id, new_time="16:00")
        if damage == "history_race": history.append_message(role="user", channel="matrix", timestamp=NOW,
            content="Ήρθε εδώ η Σοφία τελικά", db_path=path)
        if damage == "state_race": db.set_context_state("partner_with_user", "true", NOW.date().isoformat())
        return SimpleNamespace(text=json.dumps(payload))
    monkeypatch.setattr(extractor, "safe_gemini_call", model)
    assert not extractor.resolve_daily_context_before_question(("partner_with_user",), now=NOW,
        still_current=lambda: True, channel="matrix", conversation_db_path=path)
    assert db.get_context_state("routine_context_duration_proof") is None


@pytest.mark.parametrize("problem", ["missing_type", "unknown_type", "gps_conflict", "stale_partner"])
@pytest.mark.parametrize("stage", ["creation", "read"])
def test_review_schedule_applicability_requires_current_evidence(
    episode: tuple[Any, ...], monkeypatch: pytest.MonkeyPatch, problem: str, stage: str,
) -> None:
    """Reject invalid applicability during native proof creation and later reads."""
    from services.routine_context import build_routine_context_evidence
    extractor, history, db, path, plan, arrived, rid = episode
    monkeypatch.setattr(extractor, "safe_gemini_call", lambda _: SimpleNamespace(
        text=json.dumps(decision(plan, arrived, rid))))
    def resolve() -> bool:
        """Use the actual guarded native proof writer."""
        return extractor.resolve_daily_context_before_question(("partner_with_user",), now=NOW,
            still_current=lambda: True, channel="matrix", conversation_db_path=path)
    if stage == "read":
        assert resolve()
    conditions = [{"condition_type": None if problem == "missing_type" else "unrecognized"}]
    if problem in {"gps_conflict", "stale_partner"}:
        flag = "user_out_of_home" if problem == "gps_conflict" else "partner_at_work"
        value = "false" if problem == "gps_conflict" else "true"
        stamp = NOW - timedelta(minutes=5) if problem == "gps_conflict" else NOW - timedelta(hours=3)
        db.set_context_states_if_unchanged({flag: (value, NOW.date().isoformat())},
            {flag: db.get_context_state(flag)}, recorded_at=stamp)
        conditions = [{"condition_type": "context_flag", "condition_mode": "allow_when_true",
                       "condition_payload": {"flag": flag, "equals": value == "true"}}]
        if problem == "gps_conflict":
            import services.routine_context as context
            Path(context.GPS_STORAGE_FILE).write_text(json.dumps({"lat": 1, "lon": 1,
                "timestamp": NOW.timestamp()}), encoding="utf-8")
            monkeypatch.setattr("services.location_update.location_is_home", lambda *a: False)
    real_conditions = db.get_routine_conditions
    monkeypatch.setattr(db, "get_routine_conditions", lambda selected: conditions if selected == rid else real_conditions(selected))
    if stage == "creation":
        assert not resolve()
        assert db.get_context_state("routine_context_duration_proof") is None
    else:
        assert build_routine_context_evidence(NOW, gps_loader=lambda: None)["partner_with_user"].effective_value is None


@pytest.mark.parametrize("change", ["gps_conflict", "age"])
def test_existing_schedule_proof_loses_applicability_without_schedule_edit(
    episode: tuple[Any, ...], monkeypatch: pytest.MonkeyPatch, change: str,
) -> None:
    """The same condition cannot sustain a proof after GPS conflict or aging."""
    from services.routine_context import build_routine_context_evidence
    import services.routine_context as context
    extractor, history, db, path, plan, arrived, rid = episode
    flag = "user_out_of_home" if change == "gps_conflict" else "partner_at_work"
    value = "false" if change == "gps_conflict" else "true"
    db.set_context_states_if_unchanged({flag: (value, NOW.date().isoformat())}, {flag: None},
        recorded_at=NOW-timedelta(minutes=5))
    db.set_routine_condition(rid, condition_type="context_flag", condition_mode="allow_when_true",
        condition_payload=json.dumps({"flag": flag, "equals": value == "true"}))
    monkeypatch.setattr(extractor, "safe_gemini_call", lambda _: SimpleNamespace(
        text=json.dumps(decision(plan, arrived, rid))))
    assert extractor.resolve_daily_context_before_question(("partner_with_user",), now=NOW,
        still_current=lambda: True, channel="matrix", conversation_db_path=path)
    assert build_routine_context_evidence(NOW, gps_loader=lambda: None)["partner_with_user"].effective_value is False
    later = NOW+timedelta(hours=2) if change == "age" else NOW
    if change == "gps_conflict":
        Path(context.GPS_STORAGE_FILE).write_text(json.dumps({"lat": 1, "lon": 1,
            "timestamp": NOW.timestamp()}), encoding="utf-8")
        monkeypatch.setattr("services.location_update.location_is_home", lambda *a: False)
    assert build_routine_context_evidence(later, gps_loader=lambda: None)["partner_with_user"].effective_value is None
