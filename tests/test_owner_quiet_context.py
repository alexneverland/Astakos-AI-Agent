"""Owner silence and household presence use isolated canonical persistence."""
from datetime import datetime, timedelta
import json
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from memory import conversation_history, routine_db
from services import context_extractor as extractor
from services.routine_context import resolve_quiet_hours

pytestmark = pytest.mark.usefixtures("offline_behavioral_io")
NOW = datetime(2026, 11, 20, 6, 23, tzinfo=ZoneInfo("Europe/Athens"))
REPORT = "είμαι στο δρόμο για την δουλειά φίλε τέτοια ώρα όλοι είναι στο σπίτι κοιμούνται ακόμα"


@pytest.fixture
def context_store(tmp_path, monkeypatch) -> str:
    """Use native stores; replace only the provider and unrelated reconciliation."""
    path = str(tmp_path / "conversation.db")
    monkeypatch.setattr(routine_db, "DB_PATH", str(tmp_path / "routines.db"))
    routine_db.setup_db()
    monkeypatch.setattr(extractor, "reconcile_context_message", lambda *a, **k: None)
    return path


def extract_report(path: str, monkeypatch: pytest.MonkeyPatch, flags: dict, *,
                   text: str = REPORT, clarification: bool = False) -> extractor.ContextExtractionResult | None:
    """Run the real extractor through source validation and canonical writes."""
    row = conversation_history.append_message(role="user", channel="matrix",
        content=text, timestamp=NOW, db_path=path)
    response = ({"relation": "related", "flags": flags, "continue_conversation": True}
        if clarification else {"flags": flags, "event_rowid": row["rowid"],
                               "support_rowids": [row["rowid"]]})
    monkeypatch.setattr(extractor, "safe_gemini_call",
                        lambda _: SimpleNamespace(text=json.dumps(response)))
    return extractor.extract_and_update_context_flags(text, channel="matrix", now=NOW,
        conversation_db_path=path, clarification_context=(
            {"question": "Είναι κανείς άλλος στο σπίτι;", "flags": ["family_at_home"]}
            if clarification else None))


@pytest.mark.parametrize("clarification", [False, True])
@pytest.mark.parametrize("basis", [None, "others_rest"])
def test_commuting_owner_is_not_silenced_or_moved_home(context_store, monkeypatch, clarification, basis) -> None:
    """Family sleeping elsewhere cannot override the owner's personal journey."""
    flags = {"family_at_home": True, "user_out_of_home": True,
             "partner_with_user": False, "kid1_with_user": False, "quiet_hours": True}
    if basis is not None:
        flags["quiet_hours_basis"] = basis
    extract_report(context_store, monkeypatch, flags, clarification=clarification)
    assert routine_db.get_context_state("user_out_of_home")["value"] == "true"
    assert routine_db.get_context_state("partner_with_user")["value"] == "false"
    assert routine_db.get_context_state("kid1_with_user")["value"] == "false"
    assert routine_db.get_context_state("quiet_hours") is None
    assert not resolve_quiet_hours(NOW.replace(hour=11), scheduled=True)


@pytest.mark.parametrize("basis", ["owner_request", "shared_rest"])
@pytest.mark.parametrize("clarification", [False, True])
def test_grounded_owner_quiet_still_blocks_scheduled_routines(context_store, monkeypatch, basis, clarification) -> None:
    """Both explicit silence outside and a shared child's rest remain supported."""
    outside = basis == "owner_request"
    extract_report(context_store, monkeypatch,
        {"quiet_hours": True, "quiet_hours_basis": basis, "user_out_of_home": outside},
        text=("Είμαι έξω, θέλω ησυχία τώρα, μην έρθουν ειδοποιήσεις." if outside
              else "Ο μικρός κοιμήθηκε εδώ δίπλα μου, καθόμαστε ήσυχα."), clarification=clarification)
    assert routine_db.get_context_state("quiet_hours")["value"] == "true"
    assert resolve_quiet_hours(NOW.replace(hour=11), scheduled=True)
    assert routine_db.get_context_state("quiet_hours_basis") is None


def test_unrelated_sleep_report_does_not_cancel_existing_owner_quiet(context_store, monkeypatch) -> None:
    """Rejecting an unsupported mute must preserve a previous valid request."""
    assert routine_db.set_context_states_if_unchanged(
        {"quiet_hours": ("true", NOW.date().isoformat())}, {"quiet_hours": None},
        recorded_at=NOW - timedelta(minutes=1))
    extract_report(context_store, monkeypatch,
                   {"quiet_hours": True, "quiet_hours_basis": "others_rest"})
    assert resolve_quiet_hours(NOW.replace(hour=11), scheduled=True)


def test_explicit_separate_company_survives_family_home(context_store, monkeypatch) -> None:
    """An aggregate home report never overrides explicit relationship facts."""
    extract_report(context_store, monkeypatch, {"family_at_home": True,
        "user_out_of_home": False, "partner_with_user": False, "kid1_with_user": False},
        text="Είμαι σπίτι, οι υπόλοιποι στο άλλο σπίτι, δεν είμαστε μαζί.")
    assert routine_db.get_context_state("partner_with_user")["value"] == "false"
    assert routine_db.get_context_state("kid1_with_user")["value"] == "false"


@pytest.mark.parametrize("basis", [True, [], {}, "", "unknown", "others_rest"])
def test_unsupported_mute_does_not_discard_valid_presence(context_store, monkeypatch, basis) -> None:
    """Missing or malformed scope cannot silence the owner or lose other facts."""
    extract_report(context_store, monkeypatch, {"user_out_of_home": True,
        "quiet_hours": True, "quiet_hours_basis": basis})
    assert routine_db.get_context_state("user_out_of_home")["value"] == "true"
    assert routine_db.get_context_state("quiet_hours") is None


def test_explicit_resume_needs_no_quiet_basis(context_store, monkeypatch) -> None:
    """The owner can release a previous mute without rest metadata."""
    assert routine_db.set_context_states_if_unchanged(
        {"quiet_hours": ("true", NOW.date().isoformat())}, {"quiet_hours": None},
        recorded_at=NOW - timedelta(minutes=1))
    extract_report(context_store, monkeypatch, {"quiet_hours": False},
                   text="Συνέχισε κανονικά τις ειδοποιήσεις τώρα.")
    assert not resolve_quiet_hours(NOW.replace(hour=11), scheduled=True)


def test_morning_question_resolves_without_muting_owner(context_store, tmp_path, monkeypatch) -> None:
    """The reported Matrix reply closes its real ledger question and preserves separation."""
    from memory.routine_context_clarification import ClarificationStore, QuestionRequest
    from services.routine_context_clarification import process_question_answer
    import config

    monkeypatch.setattr(config, "CONVERSATION_DB_FILE", context_store)
    conversation_history.append_message(role="user", channel="matrix",
        content=REPORT, timestamp=NOW, db_path=context_store)
    store = ClarificationStore(tmp_path / "questions.json")
    request = QuestionRequest("morning", "presence", ("6",), ("family_at_home",),
        NOW + timedelta(minutes=12), "Πριν φύγεις για τη βάρδια, είναι κανείς άλλος στο σπίτι;", "matrix")
    assert store.reserve(request, now=NOW)
    assert store.begin_send("morning", now=NOW)
    assert store.mark_sent("morning", external_id="$morning", now=NOW)
    assert store.mark_recorded("morning")
    monkeypatch.setattr(extractor, "safe_gemini_call", lambda _: SimpleNamespace(text=json.dumps({
        "relation": "related", "continue_conversation": True, "flags": {
            "family_at_home": True, "user_out_of_home": True,
            "partner_with_user": False, "kid1_with_user": False,
            "quiet_hours": True, "quiet_hours_basis": "others_rest"}})))
    result = process_question_answer(store=store, user_text=REPORT, channel="matrix",
        now=NOW + timedelta(seconds=1), trusted_owner=True)
    assert result.outcome == "resolved" and result.continue_conversation
    assert store.snapshot()["requests"][0]["status"] == "resolved"
    assert routine_db.get_context_state("partner_with_user")["value"] == "false"
    assert not resolve_quiet_hours(NOW.replace(hour=11), scheduled=True)
