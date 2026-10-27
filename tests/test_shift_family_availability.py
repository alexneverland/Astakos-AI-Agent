"""Offline regressions for shift recording and shared family availability."""

import json
from datetime import datetime, timedelta, tzinfo
from types import SimpleNamespace
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from memory import routine_db
from services import context_extractor as extractor
from services import routine_reconciler as reconciler
from services.routine_conditions import evaluate_routine_conditions
from services.routine_context import resolve_current_shift

ATHENS = ZoneInfo("Europe/Athens")
SUNDAY = datetime(2026, 10, 25, 21, 46, 43, tzinfo=ATHENS)
TUESDAY = datetime(2026, 10, 27, 16, 41, 22, tzinfo=ATHENS)


@pytest.fixture
def isolated_shift(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> tuple:
    """Use native temporary stores with a bounded semantic model boundary."""
    import config
    import core.brain as brain
    from memory import conversation_history as history

    monkeypatch.setattr(routine_db, "DB_PATH", str(tmp_path / "routines.db"))
    routine_db.setup_db()
    path = str(tmp_path / "history.db")
    monkeypatch.setattr(config, "CONVERSATION_DB_FILE", path)
    history.init_db(path)
    model = SimpleNamespace(invoke=lambda messages: SimpleNamespace(content="[]"))
    monkeypatch.setattr(brain, "llm", model)
    return model, history, path


def _shift(until: str | None = "2026-10-30", value: str | None = "morning") -> dict:
    """Use the existing reconciler's structured semantic output contract."""
    return {"entity": "owner", "activity": "work_shift", "aliases": [],
            "impact": "live_context", "context_key": "current_shift",
            "context_value": value, "until_date": until, "reason": "shift_schedule"}


@pytest.mark.usefixtures("offline_behavioral_io")
@pytest.mark.parametrize("now,text", [
    (SUNDAY, "Εγώ στη δουλειά από εβδομάδα είμαι πρωινός."),
    (TUESDAY, "Είμαι σπίτι, όλοι εδώ είμαστε και στη δουλειά βάρδια είμαι πρωινός."),
])
def test_live_semantic_shift_reaches_native_resolver(
    isolated_shift: tuple, now: datetime, text: str,
) -> None:
    """The live caller must not silently skip an already validated shift result."""
    model, _, _ = isolated_shift
    model.invoke = lambda messages: SimpleNamespace(content=json.dumps([_shift()]))
    directives = reconciler.infer_routine_reconciliation_directives(
        text, category="family", reason="live_message_context", now=now)
    reconciler.apply_routine_reconciliation_directives(directives)
    assert routine_db.get_context_state("current_shift")["expires_at"] == "2026-10-30"
    assert resolve_current_shift(TUESDAY) == "morning"


@pytest.mark.usefixtures("offline_behavioral_io")
def test_same_shift_observation_does_not_shorten_week(isolated_shift: tuple) -> None:
    """A live observation is not an explicit revision of a weekly schedule."""
    routine_db.set_context_state("current_shift", "morning", "2026-10-30")
    expected = {"current_shift": routine_db.get_context_state("current_shift")}
    applied = extractor._persist_context_payload({"current_shift": "morning"}, set(),
                                                "2026-10-27", expected)
    assert applied == frozenset({"current_shift"})
    assert resolve_current_shift(TUESDAY + timedelta(days=1)) == "morning"


def _partner_condition() -> dict:
    """Represent the persisted condition shared by both football days."""
    return {"condition_type": "context_flag", "condition_mode": "suppress_when_true",
            "condition_payload": {"flag": "kid1_with_partner", "equals": True},
            "source_memory_ref": "manual_sync"}


@pytest.mark.parametrize("source", ["manual_sync", "llm_agent", "reconciler", None])
def test_shared_family_does_not_exclude_owner(source: str | None) -> None:
    """Presence is not exclusive custody, irrespective of routine or creator."""
    condition = {**_partner_condition(), "source_memory_ref": source}
    context = {"kid1_with_partner": True, "kid1_with_user": True}
    result = evaluate_routine_conditions([condition], context, TUESDAY)
    assert result["allowed"] is True
    assert result["results"][0]["actual_value"] is True


@pytest.mark.parametrize("with_user", [False, None])
def test_child_with_partner_does_not_invent_owner_presence(with_user: bool | None) -> None:
    """Missing or negative owner evidence cannot grant a co-presence exception."""
    context = {"kid1_with_partner": True, "kid1_with_user": with_user}
    assert not evaluate_routine_conditions([_partner_condition()], context)["allowed"]


def test_other_child_activity_guards_still_apply() -> None:
    """A child already away or activity already done must remain blocked."""
    condition = {"condition_type": "context_flag", "condition_mode": "suppress_when_true",
                 "condition_payload": {"flag": "kid1_unavailable_for_routine", "equals": True}}
    assert not evaluate_routine_conditions([_partner_condition(), condition], {
        "kid1_with_partner": True, "kid1_with_user": True,
        "kid1_unavailable_for_routine": True})["allowed"]


@pytest.mark.usefixtures("offline_behavioral_io")
@pytest.mark.parametrize("at,text,flags", [
    (SUNDAY, "Ναι, φάγαμε και βλέπουμε ταινία. Αύριο δεν έχει σχολείο. "
             "Εγώ στη δουλειά από εβδομάδα είμαι πρωινός.", {}),
    (TUESDAY, "Είμαι σπίτι φίλε, φτάσαμε όλοι εδώ και στη δουλειά βάρδια "
              "είμαι πρωινός, δεν το έχεις σημειώσει.",
     {"family_at_home": True, "kid1_with_user": True, "kid1_with_partner": True,
      "current_shift": "morning"}),
])
def test_full_live_extraction_persists_schedule_and_family(
    isolated_shift: tuple, monkeypatch: pytest.MonkeyPatch,
    at: datetime, text: str, flags: dict,
) -> None:
    """Execute both real extraction stages through history, CAS and persistence."""
    model, history, path = isolated_shift
    event = history.append_message(role="user", channel="matrix", content=text,
                                   timestamp=at, db_path=path)

    class Clock(datetime):
        @classmethod
        def now(cls, tz: tzinfo | None = None) -> datetime:
            """Keep both stages on the source day's clock."""
            return at + timedelta(seconds=30)

    monkeypatch.setattr(extractor, "datetime", Clock)
    monkeypatch.setattr(extractor, "_recent_user_context_hint", lambda channel: "")
    envelope = {"flags": flags, "event_rowid": event["rowid"] if flags else None,
                "support_rowids": [event["rowid"]] if flags else []}
    monkeypatch.setattr(extractor, "safe_gemini_call",
                        lambda prompt: SimpleNamespace(text=json.dumps(envelope)))
    model.invoke = lambda messages: SimpleNamespace(content=json.dumps([_shift()]))
    extractor.extract_and_update_context_flags(text, channel="matrix", now=at + timedelta(seconds=30),
                                              conversation_db_path=path)
    stored = routine_db.get_context_state("current_shift")
    assert stored["value"] == "morning"
    assert stored["expires_at"] == "2026-10-30"
    assert datetime.fromisoformat(stored["updated_at"]) == at
    assert resolve_current_shift(TUESDAY) == "morning"
    if flags:
        assert evaluate_routine_conditions([_partner_condition()], {
            key: routine_db.get_context_state(key)["value"]
            for key in ("kid1_with_partner", "kid1_with_user")})["allowed"]


@pytest.mark.usefixtures("offline_behavioral_io")
@pytest.mark.parametrize("race", ["history", "state"])
def test_live_schedule_cannot_overwrite_newer_decision(
    isolated_shift: tuple, monkeypatch: pytest.MonkeyPatch, race: str,
) -> None:
    """A model response cannot outrun a later owner correction or state writer."""
    model, history, path = isolated_shift
    text = "Στη δουλειά αυτή την εβδομάδα είμαι πρωινός."
    now = datetime.now(ATHENS)
    routine_db.set_context_states_if_unchanged(
        {"current_shift": ("night", "2026-10-30")}, {"current_shift": None},
        recorded_at=now-timedelta(hours=1))
    history.append_message(role="user", channel="matrix", content=text,
                           timestamp=now, db_path=path)
    invoked = []

    def reply(messages: list) -> SimpleNamespace:
        """Inject a competing canonical update while the semantic call runs."""
        invoked.append(True)
        if race == "history":
            history.append_message(role="user", channel="web", content="Αλλαγή, τελικά νύχτα.",
                                   timestamp=now + timedelta(seconds=1), db_path=path)
        else:
            routine_db.set_context_state("current_shift", "afternoon", "2026-10-30")
        return SimpleNamespace(content=json.dumps([_shift()]))

    model.invoke = reply
    native_write = extractor.set_context_states_if_unchanged
    writes = []

    def write(*args, **kwargs) -> bool:
        """Observe the real CAS result, not just the pre-seeded final value."""
        result = native_write(*args, **kwargs)
        writes.append(result)
        return result

    monkeypatch.setattr(extractor, "set_context_states_if_unchanged", write)
    extractor.reconcile_context_message(text)
    assert invoked == [True]
    assert writes == ([] if race == "history" else [False])
    assert routine_db.get_context_state("current_shift")["value"] == (
        "night" if race == "history" else "afternoon")


def test_stale_owner_presence_does_not_lift_child_suppression() -> None:
    """Only effective evidence, not a stale stored true, grants shared presence."""
    from services.routine_context import project_routine_context
    from services.routine_context_evidence import evaluate_context_evidence

    evidence = evaluate_context_evidence({
        "kid1_with_partner": {"value": "true", "updated_at": TUESDAY.isoformat()},
        "kid1_with_user": {"value": "true", "updated_at": (TUESDAY-timedelta(hours=3)).isoformat()},
    }, None, now=TUESDAY + timedelta(minutes=1), location_resolver=lambda *a: None)
    projected = project_routine_context({"kid1_with_user": True}, evidence)
    assert not evaluate_routine_conditions([_partner_condition()], projected)["allowed"]


def test_clarification_tracks_owner_presence_dependency() -> None:
    """Clarification sensitivity must include the newly relevant co-presence flag."""
    from services.routine_context_clarification import _condition_flags

    assert _condition_flags(_partner_condition()) == {"kid1_with_partner", "kid1_with_user"}


@pytest.mark.usefixtures("offline_behavioral_io")
@pytest.mark.parametrize("answer", ["[]", "failure", "invalid", "presence_only"])
def test_live_shift_does_not_invent_schedule_or_write_other_context(
    isolated_shift: tuple, answer: str,
) -> None:
    """The semantic live pass is shift-only and does not replace guarded presence."""
    model, _, _ = isolated_shift
    routine_db.set_context_state("current_shift", "night", "2026-10-30")

    def reply(messages: list) -> SimpleNamespace:
        """Supply bounded negative semantic results without cloud access."""
        if answer == "failure":
            raise RuntimeError("offline failure")
        content = json.dumps([{**_shift(), "context_key": "partner_with_user",
                               "context_value": True}]) if answer == "presence_only" else answer
        return SimpleNamespace(content=content)

    model.invoke = reply
    directives = reconciler.infer_routine_reconciliation_directives(
        "Το πρόγραμμα που λέγαμε στις 2026-10-25 δεν έχει επιβεβαιωθεί.",
        category="family", reason="live_message_context", now=TUESDAY)
    reconciler.apply_routine_reconciliation_directives(directives)
    assert routine_db.get_context_state("current_shift")["value"] == "night"
    assert routine_db.get_context_state("partner_with_user") is None


@pytest.mark.usefixtures("offline_behavioral_io")
@pytest.mark.parametrize("external", [True, False])
def test_no_trusted_source_cannot_authorize_live_shift(
    isolated_shift: tuple, external: bool,
) -> None:
    """Neither an external-content row nor absent history grants a durable write."""
    model, history, path = isolated_shift
    text = "Από αυτή την εβδομάδα είμαι πρωινός."
    if external:
        history.append_message(role="user", channel="matrix", content=text,
            db_path=path, metadata={"untrusted_external_tool_names": ["user_provided_asset"]})

    def forbidden(messages: list) -> SimpleNamespace:
        """An ungrounded request must stop before reaching the model."""
        pytest.fail("Ungrounded live shift reached semantic inference")

    model.invoke = forbidden
    extractor.reconcile_context_message(text)
    assert routine_db.get_context_state("current_shift") is None


@pytest.mark.usefixtures("offline_behavioral_io")
@pytest.mark.parametrize("until,value,operation", [
    ("2026-10-27", "morning", "set"),
    (None, None, "clear"),
])
def test_live_semantic_correction_can_shorten_or_cancel_week(
    isolated_shift: tuple, monkeypatch: pytest.MonkeyPatch,
    until: str | None, value: str | None, operation: str,
) -> None:
    """Weekly retention must not override an explicit semantic revision."""
    model, history, path = isolated_shift
    text = "Διόρθωση στο πρόγραμμα που σου έδωσα για αυτή την εβδομάδα."
    routine_db.set_context_states_if_unchanged(
        {"current_shift": ("morning", "2026-10-30")}, {"current_shift": None},
        recorded_at=TUESDAY-timedelta(hours=1))
    history.append_message(role="user", channel="matrix", content=text,
                           timestamp=TUESDAY, db_path=path)

    class Clock(datetime):
        @classmethod
        def now(cls, tz: tzinfo | None = None) -> datetime:
            """Use the report's processing time for both semantic stages."""
            return TUESDAY + timedelta(seconds=30)

    monkeypatch.setattr(extractor, "datetime", Clock)
    decision = {**_shift(until, value), "context_operation": operation, "schedule_revision": True}
    model.invoke = lambda messages: SimpleNamespace(content=json.dumps([decision]))
    extractor.reconcile_context_message(text)
    stored = routine_db.get_context_state("current_shift")
    assert stored["expires_at"] == until
    assert stored["value"] == ("" if operation == "clear" else value)


@pytest.mark.parametrize("payload", [
    {"flag": "kid1_with_partner", "equals": None}, {"kid1_with_partner": True},
    {"kid1_with_partner": True, "family_at_home": True},
])
def test_all_supported_presence_payloads_share_evaluation(payload: dict) -> None:
    """Legacy payload shapes must use the same presence policy and dependencies."""
    from services.routine_context_clarification import _condition_flags
    condition = {**_partner_condition(), "condition_payload": payload}
    assert evaluate_routine_conditions([condition], {"kid1_with_partner": True,
        "kid1_with_user": True, "family_at_home": True})["allowed"]
    assert "kid1_with_user" in _condition_flags(condition)


@pytest.mark.usefixtures("offline_behavioral_io")
@pytest.mark.parametrize("until", ["2026-10-30", None])
def test_live_observation_cannot_shorten_existing_shift(
    isolated_shift: tuple, until: str | None,
) -> None:
    """Both semantic and ordinary writers retain the established observation scope."""
    model, history, path = isolated_shift
    at = datetime.now(ATHENS)
    text = "Η βάρδιά μου εξακολουθεί να είναι πρωινή."
    routine_db.set_context_states_if_unchanged(
        {"current_shift": ("morning", until)}, {"current_shift": None},
        recorded_at=at-timedelta(hours=1))
    history.append_message(role="user", channel="matrix", content=text, timestamp=at, db_path=path)
    model.invoke = lambda messages: SimpleNamespace(content=json.dumps([_shift(at.date().isoformat())]))
    extractor.reconcile_context_message(text)
    assert routine_db.get_context_state("current_shift")["expires_at"] == until
    expected = {"current_shift": routine_db.get_context_state("current_shift")}
    assert extractor._persist_context_payload({"current_shift": "morning"}, set(),
        at.date().isoformat(), expected) == frozenset({"current_shift"})
    assert routine_db.get_context_state("current_shift")["expires_at"] == until


@pytest.mark.usefixtures("offline_behavioral_io")
def test_provider_failure_leaves_diagnostic_receipt(
    isolated_shift: tuple, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A provider error must remain distinguishable from a no-impact decision."""
    model, _, _ = isolated_shift
    events = []
    monkeypatch.setattr("memory.event_log.log_event", lambda *a, **k: events.append((a, k)))

    def fail(messages: list) -> SimpleNamespace:
        raise RuntimeError("offline provider failure")

    model.invoke = fail
    reconciler.infer_routine_reconciliation_directives("Δεν έχω επιβεβαιώσει το πρόγραμμα.",
        category="family", reason="live_message_context", now=TUESDAY)
    assert any(a[1] == "live_shift_inference_failed" for a, k in events)
