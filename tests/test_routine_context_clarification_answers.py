"""Semantic clarification replies use the real canonical temporary context store."""

from types import SimpleNamespace

import pytest

from memory import routine_db
from services import context_extractor as extractor


@pytest.fixture
def context_pipeline(tmp_path, monkeypatch):
    """Keep provider calls and all persistence outside live user data."""
    import socket

    def forbidden(*args, **kwargs):
        raise AssertionError("Unexpected outbound network call")

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(routine_db, "DB_PATH", str(tmp_path / "routines.db"))
    routine_db.setup_db()
    monkeypatch.setattr(extractor, "load_recent_state_messages", lambda **_: [])
    monkeypatch.setattr(extractor, "infer_routine_reconciliation_directives", forbidden)
    return {"question": "Είναι η Σοφία μαζί σου τώρα;", "flags": ["partner_with_user"]}


@pytest.mark.parametrize("channel", ["web", "telegram", "matrix"])
def test_short_related_reply_persists_through_canonical_extractor(context_pipeline, monkeypatch, channel):
    """A short reply in any channel refreshes the requested relationship flag."""
    monkeypatch.setattr(extractor, "safe_gemini_call", lambda _: SimpleNamespace(
        text='{"relation":"related","flags":{"partner_with_user":false}}'))
    result = extractor.extract_and_update_context_flags(
        "no", channel=channel, clarification_context=context_pipeline)
    assert result.relation == "related"
    assert result.applied_flags == frozenset({"partner_with_user"})
    assert routine_db.get_context_state("partner_with_user")["value"] == "false"


@pytest.mark.parametrize("relation", ["unrelated", "uncertain", "refused"])
def test_nonanswer_never_applies_proposed_flags(context_pipeline, monkeypatch, relation):
    """An unrelated message or refusal cannot supply missing relationship evidence."""
    monkeypatch.setattr(extractor, "safe_gemini_call", lambda _: SimpleNamespace(
        text='{"relation":"' + relation + '","flags":{"partner_with_user":true}}'))
    result = extractor.extract_and_update_context_flags(
        "Άστο προς το παρόν", clarification_context=context_pipeline)
    assert result.relation == relation
    assert not result.applied_flags
    assert routine_db.get_context_state("partner_with_user") is None


@pytest.mark.parametrize("payload", [
    '{"relation":"related","flags":{"partner_with_user":"true"}}',
    '{"relation":"related","flags":{"quiet_hours":true}}',
    '{"relation":"related","flags":{"partner_with_user":true},"execute":"send"}',
])
def test_invalid_or_out_of_scope_model_result_is_not_persisted(context_pipeline, monkeypatch, payload):
    """Structured validation rejects coercion, unrelated flags and extra actions."""
    monkeypatch.setattr(extractor, "safe_gemini_call", lambda _: SimpleNamespace(text=payload))
    result = extractor.extract_and_update_context_flags(
        "Ναι", clarification_context=context_pipeline)
    assert result.relation == "uncertain"
    assert not result.applied_flags
    assert routine_db.get_context_state("partner_with_user") is None


def test_question_becomes_stale_during_classification(context_pipeline, monkeypatch):
    """A post-model freshness check precedes every context write."""
    monkeypatch.setattr(extractor, "safe_gemini_call", lambda _: SimpleNamespace(
        text='{"relation":"related","flags":{"partner_with_user":true}}'))
    result = extractor.extract_and_update_context_flags(
        "Ναι", clarification_context=context_pipeline, clarification_still_current=lambda: False)
    assert result.relation == "uncertain"
    assert routine_db.get_context_state("partner_with_user") is None


def test_failed_persistence_does_not_report_resolution(context_pipeline, monkeypatch):
    """A failed canonical write does not acknowledge a resolved clarification."""
    monkeypatch.setattr(extractor, "safe_gemini_call", lambda _: SimpleNamespace(
        text='{"relation":"related","flags":{"partner_with_user":true}}'))

    def fail(*args, **kwargs):
        raise OSError("temporary database failure")

    monkeypatch.setattr(extractor, "set_context_states_if_unchanged", fail)
    result = extractor.extract_and_update_context_flags("Ναι", clarification_context=context_pipeline)
    assert result.relation == "uncertain"
    assert not result.applied_flags


def test_question_is_bounded_untrusted_reference_not_an_instruction(context_pipeline, monkeypatch):
    """Persisted question text cannot become an executable instruction."""
    prompts = []

    def model(prompt):
        prompts.append(prompt)
        return SimpleNamespace(text='{"relation":"uncertain","flags":{}}')

    monkeypatch.setattr(extractor, "safe_gemini_call", model)
    extractor.extract_and_update_context_flags("Δεν ξέρω", clarification_context=context_pipeline)
    assert "UNTRUSTED" in prompts[0]
    assert "relation" in prompts[0]


def test_batch_write_failure_is_not_an_acknowledged_answer(context_pipeline, monkeypatch):
    """Failed batch persistence must not acknowledge or retain partial evidence."""
    context_pipeline["flags"].append("kid1_with_user")
    monkeypatch.setattr(extractor, "safe_gemini_call", lambda _: SimpleNamespace(
        text='{"relation":"related","flags":{"partner_with_user":true,"kid1_with_user":true}}'))
    def write(*args, **kwargs):
        raise OSError("batch write failed")

    monkeypatch.setattr(extractor, "set_context_states_if_unchanged", write)
    result = extractor.extract_and_update_context_flags("Ναι μαζί μου", clarification_context=context_pipeline)
    assert result.relation == "uncertain"
    assert not result.applied_flags
    assert routine_db.get_context_state("partner_with_user") is None
    assert routine_db.get_context_state("kid1_with_user") is None


def test_invalid_question_contract_never_contacts_provider(context_pipeline, monkeypatch):
    """A persisted structured identifier cannot expand the writable scope."""
    context_pipeline["flags"] = ["quiet_hours"]

    def forbidden(*args, **kwargs):
        raise AssertionError("Invalid context must be rejected before classification")

    monkeypatch.setattr(extractor, "safe_gemini_call", forbidden)
    result = extractor.extract_and_update_context_flags("Ναι", clarification_context=context_pipeline)
    assert not result.applied_flags


def test_enum_question_is_not_a_supported_clarification(context_pipeline, monkeypatch):
    """Only bounded volatile booleans can be requested by this question flow."""
    context_pipeline["flags"] = ["current_shift"]

    def forbidden(*args, **kwargs):
        raise AssertionError("An enum question cannot contact the provider")

    monkeypatch.setattr(extractor, "safe_gemini_call", forbidden)
    result = extractor.extract_and_update_context_flags("Πρωί", clarification_context=context_pipeline)
    assert not result.applied_flags


def test_mixed_answer_preserves_extra_current_facts(context_pipeline, monkeypatch):
    """The same guarded write retains facts outside the question's flag list."""
    monkeypatch.setattr(extractor, "safe_gemini_call", lambda _: SimpleNamespace(text=
        '{"relation":"related","flags":{"partner_with_user":false,'
        '"partner_at_work":true},"continue_conversation":true}'))
    result = extractor.extract_and_update_context_flags(
        "Όχι, η Σοφία δουλεύει. Θυμήσου ότι αύριο έχω ρεπό και βάλε reminder στις έξι.",
        clarification_context=context_pipeline)
    assert result.continue_conversation is True
    assert "partner_at_work" in result.applied_flags
    assert routine_db.get_context_state("partner_at_work")["value"] == "true"
    assert routine_db.get_context_state("partner_with_user")["value"] == "false"


def test_mixed_answer_never_retries_stale_flags(context_pipeline, monkeypatch):
    """Continuation survives a lost context commit without retrying its writes."""
    monkeypatch.setattr(extractor, "safe_gemini_call", lambda _: SimpleNamespace(text=
        '{"relation":"related","flags":{"partner_with_user":false,'
        '"partner_at_work":true},"continue_conversation":true}'))
    result = extractor.extract_and_update_context_flags(
        "Όχι, είναι στη δουλειά. Βάλε reminder.", clarification_context=context_pipeline,
        clarification_commit=lambda persist: None)
    assert result.continue_conversation is True
    assert not result.applied_flags
    assert routine_db.get_context_state("partner_at_work") is None


@pytest.mark.parametrize("extra", [
    '"continue_conversation":"true"',
    '"continue_conversation":true,"execute":"send"',
])
def test_continuation_schema_cannot_coerce_or_authorize(context_pipeline, monkeypatch, extra):
    """Continuation is a boolean routing decision, never tool authority."""
    monkeypatch.setattr(extractor, "safe_gemini_call", lambda _: SimpleNamespace(text=
        '{"relation":"related","flags":{"partner_with_user":false},' + extra + '}'))
    result = extractor.extract_and_update_context_flags("Όχι", clarification_context=context_pipeline)
    assert result.relation == "uncertain"
    assert not result.applied_flags


@pytest.mark.parametrize("flags", [
    '{"partner_with_user":false,"owner_approved":true}',
    '{"partner_with_user":false,"current_shift":"anything"}',
    '{"partner_with_user":false,"partner_work_mode":true}',
])
def test_extra_current_facts_remain_bounded(context_pipeline, monkeypatch, flags):
    """Routing continuation cannot grant arbitrary state or coerce enum values."""
    monkeypatch.setattr(extractor, "safe_gemini_call", lambda _: SimpleNamespace(text=
        '{"relation":"related","flags":' + flags + ',"continue_conversation":true}'))
    result = extractor.extract_and_update_context_flags("Όχι, βάλε reminder", clarification_context=context_pipeline)
    assert result.relation == "uncertain" and not result.applied_flags
    assert routine_db.get_context_state("partner_with_user") is None
