"""Offline final-state regressions for dated shift reconciliation."""

import json
from datetime import datetime
from types import SimpleNamespace

import pytest

from memory import routine_db
from services import routine_reconciler as reconciler
from services.routine_context import resolve_current_shift


@pytest.fixture
def shift_store(monkeypatch, tmp_path):
    """Use isolated persistence and replace only the model/telemetry boundaries."""
    import core.brain as brain

    monkeypatch.setattr(routine_db, "DB_PATH", str(tmp_path / "routines.db"))
    routine_db.setup_db()
    monkeypatch.setattr("memory.event_log.log_event", lambda *a, **k: None)
    model = SimpleNamespace(invoke=lambda messages: SimpleNamespace(content="[]"))
    monkeypatch.setattr(brain, "llm", model)
    return model


def shift_impact(until: str | None, value: object = "afternoon") -> dict:
    """Represent a structured semantic decision, without parsing user words."""
    return {
        "entity": "lazaros", "activity": "work_shift",
        "aliases": ["δουλει", "βαρδι", "lazaros"],
        "impact": "live_context", "context_key": "current_shift",
        "context_value": value, "until_date": until,
        "reason": "shift_schedule",
    }


@pytest.mark.parametrize("fact", [
    "[USER_FACT]: Στις 2026-10-04, από αύριο δουλεύω απογευματινή βάρδια όλη την εβδομάδα.",
    "[USER_FACT]: Στις 2026-10-04, Σημειώθηκε. Καλή δύναμη με τις απογευματινές βάρδιες από αύριο.",
])
def test_recording_date_cannot_overwrite_semantic_week_end(shift_store, fact):
    """A correct semantic result survives the historical fallback's second write."""
    shift_store.invoke = lambda messages: SimpleNamespace(content=json.dumps([shift_impact("2026-10-09")]))
    reconciler.reconcile_fact_to_routines(
        fact, category="work", reason="user_stated", now=datetime(2026, 10, 4, 22, 22),
    )
    assert routine_db.get_context_state("current_shift")["expires_at"] == "2026-10-09"
    assert resolve_current_shift(datetime(2026, 10, 5, 6, 15)) == "afternoon"


def test_semantic_daily_scope_is_not_extended_to_friday(shift_store):
    """An undated statement with a one-day decision must not become a week."""
    shift_store.invoke = lambda messages: SimpleNamespace(content=json.dumps([shift_impact("2026-10-05")]))
    reconciler.reconcile_fact_to_routines(
        "[USER_FACT]: Αυτή την εβδομάδα μόνο τη Δευτέρα δουλεύω απογευματινή βάρδια.",
        category="work", reason="user_stated", now=datetime(2026, 10, 5, 8),
    )
    assert routine_db.get_context_state("current_shift")["expires_at"] == "2026-10-05"
    assert resolve_current_shift(datetime(2026, 10, 6, 8)) is None


@pytest.mark.parametrize("response", ["[]", "broken", "failure"])
@pytest.mark.parametrize("fact", [
    "[USER_FACT]: Στις 2026-10-04, από αύριο δουλεύω απογευματινή βάρδια αυτή την εβδομάδα.",
    "[USER_FACT]: Στις 2026-10-04, Σημειώθηκε. Καλή δύναμη με τις απογευματινές βάρδιες από αύριο.",
])
def test_uncertain_dated_fact_leaves_existing_week_unchanged(shift_store, response, fact):
    """Without a semantic decision, a recording date cannot manufacture a scope."""
    routine_db.set_context_state("current_shift", "afternoon", "2026-10-09")

    def invoke(messages):
        if response == "failure":
            raise RuntimeError("synthetic offline model failure")
        return SimpleNamespace(content=response)

    shift_store.invoke = invoke
    reconciler.reconcile_fact_to_routines(
        fact,
        category="work", reason="user_stated", now=datetime(2026, 10, 4, 22, 22),
    )
    assert routine_db.get_context_state("current_shift")["expires_at"] == "2026-10-09"


@pytest.mark.parametrize("until,value", [
    (None, "afternoon"), ("invalid", "afternoon"),
    ("2026-10-03", "afternoon"), ("2026-10-09", "invalid"),
    ("2026-10-9", "afternoon"), ("2026-10-09", ["afternoon"]),
])
def test_invalid_semantic_shift_does_not_replace_existing_schedule(shift_store, until, value):
    """Validate the structured date/value contract, not natural-language phrases."""
    routine_db.set_context_state("current_shift", "morning", "2026-10-09")
    shift_store.invoke = lambda messages: SimpleNamespace(content=json.dumps([shift_impact(until, value)]))
    reconciler.reconcile_fact_to_routines(
        "[USER_FACT] Work schedule recorded on 2026-10-04 for Lazaros.",
        category="work", reason="user_stated", now=datetime(2026, 10, 4, 22),
    )
    assert routine_db.get_context_state("current_shift")["value"] == "morning"


def test_explicit_semantic_correction_can_shorten_and_change_shift(shift_store):
    """Do not mask a real correction by always keeping the longest expiry."""
    routine_db.set_context_state("current_shift", "afternoon", "2026-10-09")
    shift_store.invoke = lambda messages: SimpleNamespace(content=json.dumps([shift_impact("2026-10-05", "morning")]))
    reconciler.reconcile_fact_to_routines(
        "[USER_FACT] Lazaros changed the work schedule recorded on 2026-10-05.",
        category="work", reason="user_stated", now=datetime(2026, 10, 5, 8),
    )
    stored = routine_db.get_context_state("current_shift")
    assert (stored["value"], stored["expires_at"]) == ("morning", "2026-10-05")


def test_semantic_shift_needs_no_owner_name_or_work_keyword(shift_store):
    """Canonical extraction handles natural references, including night shifts."""
    impact = shift_impact("2026-10-09", "night")
    impact["aliases"] = []
    shift_store.invoke = lambda messages: SimpleNamespace(content=json.dumps([impact]))
    reconciler.reconcile_fact_to_routines(
        "[USER_FACT]: Από αύριο όλη την εβδομάδα θα είμαι στα βραδινά.",
        category="work", reason="user_stated", now=datetime(2026, 10, 4, 22),
    )
    stored = routine_db.get_context_state("current_shift")
    assert (stored["value"], stored["expires_at"]) == ("night", "2026-10-09")
