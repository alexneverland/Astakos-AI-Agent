"""
Unit tests for services.routine_completion_helper.

Pure tests — zero Telegram, network, DB, or Gemini imports.
Covers all 22 approved scenarios including Greek morphology regression.
"""
from __future__ import annotations

import pytest

from services.routine_completion_helper import (
    CompletionDecision,
    classify_intent,
    decide_completion,
    match_candidates,
    normalize_text,
)


# ────────────────────────────────────────────────────────────────
# Helper factories
# ────────────────────────────────────────────────────────────────

def _selector_returning(value: int | None):
    """Create a mock selector that returns a fixed value."""
    def _selector(user_text: str, candidates: dict[int, str]) -> int | None:
        return value
    return _selector


def _selector_raising(exc: type = RuntimeError):
    """Create a mock selector that raises."""
    def _selector(user_text: str, candidates: dict[int, str]) -> int | None:
        raise exc("mock error")
    return _selector


# ────────────────────────────────────────────────────────────────
# Test: normalize_text
# ────────────────────────────────────────────────────────────────

class TestNormalizeText:
    def test_strips_accents(self):
        assert normalize_text("Καθάρισα") == "καθαρισα"

    def test_lowercases_english(self):
        assert normalize_text("DONE") == "done"

    def test_empty(self):
        assert normalize_text("") == ""


# ────────────────────────────────────────────────────────────────
# Test: classify_intent
# ────────────────────────────────────────────────────────────────

class TestClassifyIntent:
    def test_specific_completion_greek(self):
        assert classify_intent("το καθάρισα το κουνέλι") == "specific_completion"

    def test_bare_confirm_nai(self):
        assert classify_intent("ναι") == "bare_confirm"

    def test_bare_confirm_done(self):
        assert classify_intent("done") == "bare_confirm"

    def test_bare_confirm_egine(self):
        assert classify_intent("έγινε") == "bare_confirm"

    def test_bare_dismiss_ochi(self):
        assert classify_intent("όχι") == "bare_dismiss"

    def test_bare_dismiss_no(self):
        assert classify_intent("no") == "bare_dismiss"

    def test_future_blocked(self):
        assert classify_intent("θα το καθαρίσω αργότερα") == "none"

    def test_in_progress_blocked(self):
        assert classify_intent("το ξεκίνησα") == "none"

    def test_question_blocked(self):
        assert classify_intent("το καθάρισες;") == "none"

    def test_negation_blocked(self):
        assert classify_intent("δεν το καθάρισα") == "none"

    def test_unrelated(self):
        assert classify_intent("τι κάνεις") == "none"

    def test_uncertainty_blocked(self):
        assert classify_intent("ίσως το καθάρισα") == "none"

    def test_english_specific(self):
        assert classify_intent("cleaned the rabbit cage") == "specific_completion"


# ────────────────────────────────────────────────────────────────
# Test: match_candidates
# ────────────────────────────────────────────────────────────────

class TestMatchCandidates:
    def test_strong_match(self):
        result = match_candidates(
            "πήγαμε στο σούπερ μάρκετ",
            {8: "Σούπερ μάρκετ"},
        )
        assert result == [8]

    def test_no_match_unrelated(self):
        result = match_candidates(
            "το καθάρισα το κλουβί",
            {8: "Σούπερ μάρκετ"},
        )
        assert result == []

    def test_morphology_mismatch_no_deterministic(self):
        """Greek morphology: 'καθάρισα' vs 'Καθάρισμα' = no word-level match."""
        result = match_candidates(
            "το καθάρισα το κουνέλι",
            {5: "Καθάρισμα κλουβιού κουνελιού"},
        )
        # κουνελι is a substring of κουνελιου, so partial match, but
        # 'καθαρισα' is NOT a substring of 'καθαρισμα' and 'κλουβιου'
        # is not in user text. Only 1 of 3 words matches → no match.
        assert result == []

    def test_strict_match_requires_all_words(self):
        """User text has some but not all significant words of candidate."""
        result = match_candidates(
            "i cleaned something else",
            {1: "clean bathroom"},
        )
        assert result == []

    def test_strict_match_token_aware(self):
        """A substring like 'park' shouldn't match 'parking'."""
        result = match_candidates(
            "i am parking the car",
            {2: "park"},
        )
        assert result == []

    def test_strict_match_exact_token(self):
        """Exact token match."""
        result = match_candidates(
            "we went to the park today",
            {2: "park"},
        )
        assert result == [2]


# ────────────────────────────────────────────────────────────────
# Test: decide_completion — 22 approved scenarios
# ────────────────────────────────────────────────────────────────

class TestDecideCompletion:
    """All 22 approved test scenarios."""

    # ── #1: Clear completion, single deterministic match ─────────
    def test_01_clear_completion_single_deterministic(self):
        d = decide_completion(
            "πήγαμε στο σούπερ μάρκετ",
            {8: "Σούπερ μάρκετ"},
            pool="today",
        )
        assert d.action == "complete"
        assert d.routine_id == 8
        assert d.match_method == "deterministic"

    # ── #2: Clear completion, no candidates ──────────────────────
    def test_02_clear_completion_no_candidates(self):
        d = decide_completion(
            "το καθάρισα",
            {},
            pool="today",
        )
        assert d.action == "pass_through"

    # ── #3: Future intent blocked ────────────────────────────────
    def test_03_future_intent_blocked(self):
        d = decide_completion(
            "θα το καθαρίσω αργότερα",
            {5: "Καθάρισμα κλουβιού κουνελιού"},
            pool="today",
        )
        assert d.action == "pass_through"

    # ── #4: In-progress blocked ──────────────────────────────────
    def test_04_in_progress_blocked(self):
        d = decide_completion(
            "το ξεκίνησα",
            {5: "Καθάρισμα κλουβιού κουνελιού"},
            pool="today",
        )
        assert d.action == "pass_through"

    # ── #5: Question blocked ─────────────────────────────────────
    def test_05_question_blocked(self):
        d = decide_completion(
            "το καθάρισες;",
            {5: "Καθάρισμα κλουβιού κουνελιού"},
            pool="today",
        )
        assert d.action == "pass_through"

    # ── #6: Negation blocked ─────────────────────────────────────
    def test_06_negation_blocked(self):
        d = decide_completion(
            "δεν το καθάρισα",
            {5: "Καθάρισμα κλουβιού κουνελιού"},
            pool="today",
        )
        assert d.action == "pass_through"

    def test_06b_negation_anywhere(self):
        for text in [
            "I did not clean the rabbit cage",
            "I haven't cleaned the rabbit cage",
            "όχι, δεν το καθάρισα το κλουβί",
        ]:
            d = decide_completion(
                text,
                {5: "Καθάρισμα κλουβιού κουνελιού"},
                pool="today",
            )
            assert d.action == "pass_through"

    def test_06c_contraction_negation(self):
        for text in [
            "I didn't clean the rabbit cage",
            "I haven't cleaned the rabbit cage",
        ]:
            d = decide_completion(
                text,
                {5: "clean the rabbit cage"},
                pool="today",
            )
            assert d.action == "pass_through"

    # ── #7: Morphology mismatch → selector called, returns ID ────
    def test_07_morphology_mismatch_selector_returns_id(self):
        d = decide_completion(
            "το καθάρισα το κουνέλι",
            {5: "Καθάρισμα κλουβιού κουνελιού"},
            pool="today",
            semantic_selector=_selector_returning(5),
        )
        assert d.action == "complete"
        assert d.routine_id == 5
        assert d.match_method == "semantic"

    # ── #8: Morphology mismatch → selector returns NONE ──────────
    def test_08_morphology_mismatch_selector_returns_none(self):
        d = decide_completion(
            "το καθάρισα το κουνέλι",
            {5: "Καθάρισμα κλουβιού κουνελιού"},
            pool="today",
            semantic_selector=_selector_returning(None),
        )
        assert d.action == "pass_through"

    # ── #9: Selector exception → fail-closed ─────────────────────
    def test_09_selector_exception_fail_closed(self):
        d = decide_completion(
            "το καθάρισα",
            {5: "Καθάρισμα κλουβιού κουνελιού"},
            pool="today",
            semantic_selector=_selector_raising(),
        )
        assert d.action == "pass_through"

    # ── #10: Selector returns unknown ID → fail-closed ───────────
    def test_10_selector_returns_unknown_id(self):
        d = decide_completion(
            "το καθάρισα κάτι",
            {5: "Καθάρισμα κλουβιού κουνελιού"},
            pool="today",
            semantic_selector=_selector_returning(99),
        )
        assert d.action == "pass_through"

    # ── #11: Bare "ναι" + 1 pending ──────────────────────────────
    def test_11_bare_nai_single_pending(self):
        d = decide_completion(
            "ναι",
            {5: "Πάρκο"},
            pool="pending",
        )
        assert d.action == "complete"
        assert d.routine_id == 5
        assert d.match_method == "deterministic"

    # ── #12: Bare "ναι" + 2 pending → clarification ─────────────
    def test_12_bare_nai_multi_pending_clarification(self):
        d = decide_completion(
            "ναι",
            {5: "Πάρκο", 8: "Σούπερ μάρκετ"},
            pool="pending",
        )
        assert d.action == "ask_clarification"
        assert d.routine_id is None
        assert set(d.clarification_candidates.keys()) == {5, 8}

    # ── #13: Bare "όχι" + 1 pending ──────────────────────────────
    def test_13_bare_ochi_single_pending(self):
        d = decide_completion(
            "όχι",
            {5: "Πάρκο"},
            pool="pending",
        )
        assert d.action == "dismiss"
        assert d.routine_id == 5

    # ── #14: Bare "όχι" + 2 pending → clarification ─────────────
    def test_14_bare_ochi_multi_pending_clarification(self):
        d = decide_completion(
            "όχι",
            {5: "Πάρκο", 8: "Σούπερ μάρκετ"},
            pool="pending",
        )
        assert d.action == "ask_clarification"
        assert d.routine_id is None

    # ── #15: Bare "έγινε" + no pending → never selects today ────
    def test_15_bare_egine_no_pending_pass_through(self):
        d = decide_completion(
            "έγινε",
            {5: "Πάρκο"},
            pool="today",
        )
        assert d.action == "pass_through"

    # ── #16: Specific completion + 2 pending, selector picks one ─
    def test_16_specific_multi_pending_selector_picks(self):
        d = decide_completion(
            "καθάρισα το κλουβί",
            {5: "Κλουβί", 8: "Σούπερ μάρκετ"},
            pool="pending",
            semantic_selector=_selector_returning(5),
        )
        assert d.action == "complete"
        assert d.routine_id == 5

    # ── #17: Specific completion + 2 pending, selector NONE → clarification
    def test_17_specific_multi_pending_selector_none(self):
        d = decide_completion(
            "καθάρισα κάτι",
            {5: "Κλουβί κουνελιού", 8: "Σούπερ μάρκετ"},
            pool="pending",
            semantic_selector=_selector_returning(None),
        )
        assert d.action == "ask_clarification"

    # ── #18: English "done" with no pending → pass_through ───────
    def test_18_english_done_no_pending_pass_through(self):
        d = decide_completion(
            "done",
            {3: "rabbit cage"},
            pool="today",
        )
        assert d.action == "pass_through"

    # ── #19: English specific + single match ─────────────────────
    def test_19_english_specific_single_match(self):
        d = decide_completion(
            "cleaned the rabbit cage",
            {3: "rabbit cage"},
            pool="today",
            semantic_selector=_selector_returning(3),
        )
        assert d.action == "complete"
        assert d.routine_id == 3

    # ── #20: Unrelated text ──────────────────────────────────────
    def test_20_unrelated_text(self):
        d = decide_completion(
            "τι κάνεις;",
            {5: "Πάρκο"},
            pool="today",
        )
        assert d.action == "pass_through"

    # ── #21: Greek rabbit regression — selector returns valid ID ─
    def test_21_greek_rabbit_regression_selector_valid(self):
        d = decide_completion(
            "το καθάρισα το κουνέλι",
            {5: "Καθάρισμα κλουβιού κουνελιού", 8: "Σούπερ μάρκετ"},
            pool="today",
            semantic_selector=_selector_returning(5),
        )
        assert d.action == "complete"
        assert d.routine_id == 5
        assert d.match_method == "semantic"
        assert d.source == "today"

    # ── #22: Greek rabbit, selector ambiguous → pass_through ─────
    def test_22_greek_rabbit_selector_none_pass_through(self):
        d = decide_completion(
            "το καθάρισα το κουνέλι",
            {5: "Καθάρισμα κλουβιού κουνελιού", 8: "Σούπερ μάρκετ"},
            pool="today",
            semantic_selector=_selector_returning(None),
        )
        assert d.action == "pass_through"

    # ── #23: Selector returns True, pending pool → fail-closed (clarification) ─────
    def test_23_selector_returns_true_fail_closed_pending(self):
        d = decide_completion(
            "καθάρισα κάτι",
            {1: "Κάτι 1", 2: "Κάτι 2"},
            pool="pending",
            semantic_selector=_selector_returning(True),
        )
        assert d.action == "ask_clarification"
        assert d.routine_id is None

    # ── #24: Selector returns True, today pool → fail-closed (pass_through) ─────
    def test_24_selector_returns_true_fail_closed_today(self):
        d = decide_completion(
            "το καθάρισα κάτι",
            {1: "Κάτι 1", 2: "Κάτι 2"},
            pool="today",
            semantic_selector=_selector_returning(True),
        )
        assert d.action == "pass_through"
        assert d.routine_id is None


    # ── #25: Partial match fails deterministic, falls back to selector ──
    def test_25_partial_match_falls_back_to_selector(self):
        d = decide_completion(
            "i cleaned something else",
            {1: "clean bathroom"},
            pool="pending",
            semantic_selector=_selector_returning(1),
        )
        assert d.action == "complete"
        assert d.routine_id == 1
        assert d.match_method == "semantic"

# ────────────────────────────────────────────────────────────────
# Edge cases
# ────────────────────────────────────────────────────────────────

class TestEdgeCases:
    def test_none_selector_specific_today(self):
        """No selector provided, specific intent, today pool → pass_through."""
        d = decide_completion(
            "καθάρισα το κλουβί",
            {5: "Καθάρισμα κλουβιού κουνελιού"},
            pool="today",
            semantic_selector=None,
        )
        assert d.action == "pass_through"

    def test_none_selector_specific_pending(self):
        """No selector provided, specific intent, pending pool → clarification."""
        d = decide_completion(
            "καθάρισα κάτι",
            {5: "Κλουβί κουνελιού", 8: "Σούπερ μάρκετ"},
            pool="pending",
            semantic_selector=None,
        )
        assert d.action == "ask_clarification"

    def test_dismiss_today_no_effect(self):
        """Bare 'no' with today pool → pass_through (no pending to dismiss)."""
        d = decide_completion(
            "no",
            {5: "Πάρκο"},
            pool="today",
        )
        assert d.action == "pass_through"

# ────────────────────────────────────────────────────────────────
# Test: Selector JSON Validation (routine_completion_selector)
# ────────────────────────────────────────────────────────────────

class TestSelectorJSONValidation:
    """Tests for the strict JSON validation in select_routine."""

    def _run_selector(self, raw_json: str, candidates: dict = None) -> int | None:
        from services.routine_completion_selector import select_routine
        from unittest.mock import patch, MagicMock
        with patch("services.routine_completion_selector.safe_gemini_call") as m_call:
            m_call.return_value = MagicMock(text=raw_json)
            return select_routine("dummy text", candidates or {5: "Test", 8: "Other"})

    def test_valid_integer_id(self):
        assert self._run_selector('{"routine_id": 5}') == 5

    def test_string_id_rejected(self):
        # "5" as string should be rejected
        assert self._run_selector('{"routine_id": "5"}') is None

    def test_duplicate_keys_rejected(self):
        # Duplicate keys must be rejected during JSON decode
        assert self._run_selector('{"routine_id": 5, "routine_id": 8}') is None

    def test_extra_keys_rejected(self):
        # Must have exactly one key
        assert self._run_selector('{"routine_id": 5, "extra": "data"}') is None

    def test_null_value_rejected(self):
        # Null value for routine_id is valid JSON, but returns None
        assert self._run_selector('{"routine_id": null}') is None

    def test_boolean_rejected(self):
        # Booleans are subclass of int, must be rejected
        assert self._run_selector('{"routine_id": true}') is None

    def test_unknown_id_rejected(self):
        assert self._run_selector('{"routine_id": 99}') is None

    def test_malformed_json_rejected(self):
        assert self._run_selector('{"routine_id": 5') is None
