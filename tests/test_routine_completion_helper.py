"""Focused structural tests for natural-language routine completion decisions."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from services.routine_completion_helper import RoutineSelection, decide_completion, relevant_catalog_candidates
from services.routine_completion_selector import select_routine


def _selector(selection: RoutineSelection):
    """Return a selector stub that always yields one protocol value."""
    def _select(_text: str, _candidates: dict[int, str], _pool: str) -> RoutineSelection:
        """Provide the configured selection without interpreting message language."""
        return selection
    return _select


def test_valid_pending_completion_selects_exact_candidate() -> None:
    """A valid pending completion produces exactly one pending mutation decision."""
    decision = decide_completion(
        "natural message",
        {7: "dynamic routine"},
        "pending",
        _selector(RoutineSelection(action="complete", routine_id=7)),
    )
    assert decision.action == "complete"
    assert decision.routine_id == 7
    assert decision.source == "pending"


def test_valid_pending_skip_selects_exact_candidate() -> None:
    """A valid pending same-day skip selects one exact candidate."""
    decision = decide_completion(
        "natural message",
        {7: "dynamic routine"},
        "pending",
        _selector(RoutineSelection(action="skip_today", routine_id=7)),
    )
    assert decision.action == "skip_today"
    assert decision.routine_id == 7


def test_pending_draft_requires_the_exact_structured_offer() -> None:
    """A selector may authorize a local draft only for a marked pending offer."""
    selection = _selector(RoutineSelection(action="draft", routine_id=7))

    allowed = decide_completion(
        "Ναι φίλε κάνε το πιο γλυκό",
        {7: "Morning message\n[MESSENGER_DRAFT_OFFER]"},
        "pending",
        selection,
        draft_offer_ids=frozenset({7}),
    )
    blocked = decide_completion(
        "Ναι φίλε κάνε το πιο γλυκό",
        {7: "Morning message"},
        "pending",
        selection,
    )

    assert allowed.action == "draft"
    assert blocked.action == "pass_through"
    assert blocked.debug_reason == "draft_requires_pending_offer"


def test_valid_acknowledgement_selects_exact_today_candidate() -> None:
    """A clear future commitment records one routine without completing it."""
    decision = decide_completion(
        "natural message",
        {7: "dynamic routine"},
        "today",
        _selector(RoutineSelection(action="acknowledge", routine_id=7)),
    )

    assert decision.action == "acknowledge"
    assert decision.routine_id == 7
    assert decision.source == "today"


def test_valid_today_skip_selects_exact_candidate() -> None:
    """A clear same-day refusal skips only the selected routine."""
    decision = decide_completion(
        "natural message",
        {7: "dynamic routine"},
        "today",
        _selector(RoutineSelection(action="skip_today", routine_id=7)),
    )

    assert decision.action == "skip_today"
    assert decision.routine_id == 7


def test_valid_pause_selects_exact_candidate() -> None:
    """A clear permanent cancellation pauses only one exact candidate."""
    decision = decide_completion(
        "natural message",
        {7: "dynamic routine"},
        "today",
        _selector(RoutineSelection(action="pause", routine_id=7)),
    )

    assert decision.action == "pause"
    assert decision.routine_id == 7


def test_catalog_only_allows_explicit_permanent_pause() -> None:
    """A catalogue candidate cannot be completed or skipped by the pause path."""
    decision = decide_completion(
        "natural message",
        {7: "dynamic routine"},
        "catalog",
        _selector(RoutineSelection(action="complete", routine_id=7)),
    )
    assert decision.action == "pass_through"
    assert decision.debug_reason == "catalog_only_allows_pause"


def test_catalog_candidates_are_derived_from_stored_routine_names() -> None:
    """The catalogue prefilter contains no language-specific control triggers."""
    candidates = relevant_catalog_candidates(
        "Δεν θέλω άλλο καθάρισμα κλουβιού",
        {7: "Καθάρισμα κλουβιού κουνελιού", 8: "Ψώνια στη λαϊκή"},
    )
    assert candidates == {7: "Καθάρισμα κλουβιού κουνελιού"}


def test_legacy_dismiss_fails_closed() -> None:
    """The retired ambiguous dismissal action never mutates a routine."""
    decision = decide_completion(
        "natural message",
        {7: "dynamic routine"},
        "today",
        _selector(RoutineSelection(action="dismiss", routine_id=7)),
    )
    assert decision.action == "pass_through"
    assert decision.routine_id is None


def test_none_selection_passes_through() -> None:
    """An uncertain selector result leaves the normal chat flow untouched."""
    decision = decide_completion(
        "natural message",
        {7: "dynamic routine"},
        "today",
        _selector(RoutineSelection(action="none", routine_id=None)),
    )
    assert decision.action == "pass_through"


def test_unknown_selector_id_fails_closed() -> None:
    """A selector cannot mutate an ID outside the supplied dynamic candidates."""
    decision = decide_completion(
        "natural message",
        {7: "dynamic routine"},
        "today",
        _selector(RoutineSelection(action="complete", routine_id=8)),
    )
    assert decision.action == "pass_through"
    assert decision.debug_reason == "invalid_selector_id"


def test_selector_error_fails_closed() -> None:
    """Selector exceptions never become routine mutations."""
    def _raising_selector(_text: str, _candidates: dict[int, str], _pool: str) -> RoutineSelection:
        """Raise an intentional failure for the fail-closed contract."""
        raise RuntimeError("selector unavailable")

    decision = decide_completion("natural message", {7: "dynamic routine"}, "today", _raising_selector)
    assert decision.action == "pass_through"
    assert decision.debug_reason == "selector_error"


def test_selector_accepts_only_strict_valid_json() -> None:
    """The adapter accepts one valid dynamic ID and exact two-key JSON schema."""
    response = MagicMock(text='{"action":"complete","routine_id":7}')
    with patch("services.routine_completion_selector.load_prompt", return_value="{pool} {routines_block} {user_text}"), patch(
        "services.routine_completion_selector.safe_gemini_call", return_value=response
    ):
        selection = select_routine("natural message", {7: "dynamic routine"}, "today")
    assert selection == RoutineSelection(action="complete", routine_id=7)


def test_selector_accepts_strict_acknowledgement_json() -> None:
    """The adapter preserves a valid acknowledgement action for an exact candidate."""
    response = MagicMock(text='{"action":"acknowledge","routine_id":7}')
    with patch("services.routine_completion_selector.load_prompt", return_value="{pool} {routines_block} {user_text}"), patch(
        "services.routine_completion_selector.safe_gemini_call", return_value=response
    ):
        selection = select_routine("natural message", {7: "dynamic routine"}, "today")
    assert selection == RoutineSelection(action="acknowledge", routine_id=7)


def test_selector_accepts_draft_only_for_marked_offer() -> None:
    """The selector protocol cannot turn an ordinary pending routine into a draft."""
    response = MagicMock(text='{"action":"draft","routine_id":7}')
    with patch("services.routine_completion_selector.load_prompt", return_value="{pool} {routines_block} {user_text}"), patch(
        "services.routine_completion_selector.safe_gemini_call", return_value=response
    ):
        marked = select_routine(
            "Ναι φίλε κάνε το πιο γλυκό",
            {7: "Morning message\n[MESSENGER_DRAFT_OFFER]"},
            "pending",
        )
        ordinary = select_routine(
            "Ναι φίλε κάνε το πιο γλυκό",
            {7: "Ordinary routine"},
            "pending",
        )

    assert marked == RoutineSelection(action="draft", routine_id=7)
    assert ordinary == RoutineSelection(action="none", routine_id=None)


def test_selector_rejects_malformed_or_extra_json() -> None:
    """Malformed, duplicate, and extra-key selector responses fail closed."""
    invalid_payloads = (
        '{"action":"complete","routine_id":7,}',
        '{"action":"complete","routine_id":7,"extra":true}',
        '{"action":"complete","routine_id":7,"routine_id":7}',
        '{"action":"dismiss","routine_id":7}',
    )
    for payload in invalid_payloads:
        response = MagicMock(text=payload)
        with patch("services.routine_completion_selector.load_prompt", return_value="{pool} {routines_block} {user_text}"), patch(
            "services.routine_completion_selector.safe_gemini_call", return_value=response
        ):
            selection = select_routine("natural message", {7: "dynamic routine"}, "today")
        assert selection == RoutineSelection(action="none", routine_id=None)
