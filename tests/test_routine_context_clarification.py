"""Choose context questions only when scoped uncertainty changes a routine."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from services.routine_context_evidence import ContextEvidence
from services.routine_context_clarification import consequential_unknown_flags
from services.routine_context_clarification import RoutineCandidate, prepare_question


NOW = datetime(2026, 10, 6, 10, 0, tzinfo=ZoneInfo("Europe/Athens"))


def evidence(**values: bool | None) -> dict[str, ContextEvidence]:
    """Build only the scoped evidence required for a routine decision."""
    return {key: ContextEvidence(effective_value=value,
                                 status="known" if value is not None else "unknown")
            for key, value in values.items()}


def condition(flag: str, mode: str = "allow_when_true") -> dict:
    """Represent an existing structured routine condition."""
    return {"condition_type": "context_flag",
            "condition_payload": {"flag": flag, "equals": True},
            "condition_mode": mode}


def test_stale_owner_location_matters_to_home_routine():
    """Unknown owner location changes whether the routine is permitted."""
    result = consequential_unknown_flags(
        [condition("user_out_of_home", "suppress_when_true")],
        {"user_out_of_home": True}, evidence(user_out_of_home=None), now=NOW,
    )
    assert result == ("user_out_of_home",)


def test_null_suppression_still_matters():
    """A legacy condition allowing null must not silently imply safe delivery."""
    result = consequential_unknown_flags(
        [condition("partner_with_user", "suppress_when_true")],
        {"partner_with_user": None}, evidence(partner_with_user=None), now=NOW,
    )
    assert result == ("partner_with_user",)


def test_independently_blocked_routine_does_not_ask():
    """A known false prerequisite makes another unknown irrelevant."""
    result = consequential_unknown_flags(
        [condition("partner_with_user", "suppress_when_true"),
         condition("school_open")],
        {"school_open": False}, evidence(partner_with_user=None), now=NOW,
    )
    assert result == ()


def test_unrelated_null_does_not_trigger_question():
    """An unknown family flag has no effect on an owner-only condition."""
    result = consequential_unknown_flags(
        [condition("user_out_of_home", "suppress_when_true")],
        {"user_out_of_home": False},
        evidence(user_out_of_home=False, partner_with_user=None), now=NOW,
    )
    assert result == ()


def test_two_unknowns_are_both_consequential():
    """Question planning may coalesce multiple scoped dependencies."""
    result = consequential_unknown_flags(
        [condition("user_out_of_home", "suppress_when_true"),
         condition("partner_with_user", "suppress_when_true")],
        {}, evidence(user_out_of_home=None, partner_with_user=None), now=NOW,
    )
    assert result == ("user_out_of_home", "partner_with_user")


def test_existing_noncontext_shift_block_prevents_question():
    """Scoped context cannot override an unrelated shift condition."""
    result = consequential_unknown_flags(
        [condition("partner_with_user", "suppress_when_true"),
         {"condition_type": "shift_mode", "condition_payload":
          {"flag": "current_shift", "equals": "morning"},
          "condition_mode": "allow_when_true"}],
        {"current_shift": "afternoon"}, evidence(partner_with_user=None), now=NOW,
    )
    assert result == ()


def test_location_condition_uses_canonical_owner_flag():
    """A structured user-at-home condition depends on owner location."""
    result = consequential_unknown_flags(
        [{"condition_type": "location", "condition_payload":
          {"flag": "user_at_home", "equals": True},
          "condition_mode": "allow_when_true"}],
        {}, evidence(user_out_of_home=None), now=NOW,
    )
    assert result == ("user_out_of_home",)


def test_question_generation_uses_validated_candidate_and_flag():
    """The model can phrase a question only for supplied routine/flag IDs."""
    candidate = RoutineCandidate(
        id="park-return", name="Evening activity", slot_at=NOW.replace(minute=12),
        conditions=(condition("user_out_of_home", "suppress_when_true"),),
    )
    proposal = prepare_question(
        candidates=[candidate], runtime_context={}, evidence=evidence(user_out_of_home=None),
        channel="matrix", now=NOW, history_marker="row-42",
        classify=lambda packet: {"routine_ids": ["park-return"],
                                 "flags": ["user_out_of_home"],
                                 "question": "Γυρίσατε σπίτι;"},
        still_current=lambda: True,
    )
    assert proposal is not None
    assert proposal.routine_ids == ("park-return",)
    assert proposal.flags == ("user_out_of_home",)


def test_model_cannot_invent_dependency_or_stale_question():
    """Unexpected IDs and changed state cannot authorize a question."""
    candidate = RoutineCandidate(
        id="one", name="Reminder", slot_at=NOW.replace(minute=12),
        conditions=(condition("partner_with_user", "suppress_when_true"),),
    )
    kwargs = dict(candidates=[candidate], runtime_context={},
                  evidence=evidence(partner_with_user=None), channel="matrix",
                  now=NOW, history_marker="row-42")
    assert prepare_question(
        **kwargs,
        classify=lambda _: {"routine_ids": ["other"], "flags": ["partner_with_user"],
                            "question": "Είναι μαζί σας;"},
        still_current=lambda: True,
    ) is None
    assert prepare_question(
        **kwargs,
        classify=lambda _: {"routine_ids": ["one"], "flags": ["partner_with_user"],
                            "question": "Είναι μαζί σας;"},
        still_current=lambda: False,
    ) is None


def test_model_failure_or_unrelated_routine_does_not_ask():
    """A blocked routine never invokes the model or produces a question."""
    candidate = RoutineCandidate(
        id="one", name="Reminder", slot_at=NOW.replace(minute=12),
        conditions=(condition("partner_with_user", "suppress_when_true"),
                    condition("school_open")),
    )

    def forbidden(_):
        raise AssertionError("No model call for a blocked routine")

    assert prepare_question(
        candidates=[candidate], runtime_context={"school_open": False},
        evidence=evidence(partner_with_user=None), channel="matrix", now=NOW,
        history_marker="row-42", classify=forbidden, still_current=lambda: True,
    ) is None


def test_same_snapshot_is_not_classified_on_every_poll(tmp_path):
    """The real temporary ledger deduplicates model evaluation across calls."""
    from memory.routine_context_clarification import ClarificationStore

    store = ClarificationStore(tmp_path / "clarification.json")
    candidate = RoutineCandidate(
        id="one", name="Reminder", slot_at=NOW.replace(minute=12),
        conditions=(condition("partner_with_user", "suppress_when_true"),),
    )
    calls = []

    def classify(packet):
        calls.append(packet)
        return {"routine_ids": [], "flags": [], "question": ""}

    kwargs = dict(candidates=[candidate], runtime_context={},
                  evidence=evidence(partner_with_user=None), channel="matrix",
                  now=NOW, history_marker="row-42", classify=classify,
                  still_current=lambda: True, evaluation_claim=store.claim_evaluation)
    assert prepare_question(**kwargs) is None
    assert prepare_question(**kwargs) is None
    assert len(calls) == 1


def test_known_evidence_change_invalidates_cached_decision(tmp_path):
    """An unchanged unknown does not hide a changed known household value."""
    from memory.routine_context_clarification import ClarificationStore

    store = ClarificationStore(tmp_path / "state.json")
    candidate = RoutineCandidate("one", "Reminder", NOW.replace(minute=12),
                                 (condition("partner_with_user", "suppress_when_true"),))
    calls = []
    for owner_away in (False, True):
        prepare_question(candidates=[candidate], runtime_context={},
            evidence=evidence(partner_with_user=None, user_out_of_home=owner_away),
            channel="matrix", now=NOW, history_marker="row-42",
            classify=lambda packet: calls.append(packet), still_current=lambda: True,
            evaluation_claim=store.claim_evaluation)
    assert len(calls) == 2


def test_model_cannot_select_candidate_omitted_from_bounded_packet():
    """Only the five candidates actually supplied to the model are selectable."""
    candidates = [RoutineCandidate(str(i), "Reminder", NOW.replace(minute=12),
                  (condition("partner_with_user", "suppress_when_true"),)) for i in range(6)]
    assert prepare_question(candidates=candidates, runtime_context={},
        evidence=evidence(partner_with_user=None), channel="matrix", now=NOW,
        history_marker="row-42", still_current=lambda: True,
        classify=lambda _: {"routine_ids": ["5"], "flags": ["partner_with_user"],
                            "question": "Είναι μαζί σας;"}) is None
