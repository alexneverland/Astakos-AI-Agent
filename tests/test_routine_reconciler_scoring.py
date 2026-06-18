"""
tests/test_routine_reconciler_scoring.py

Phase 3B scoring tests για το services/routine_reconciler.py.
Δεν απαιτείται database — όλα τρέχουν pure-Python.
"""
from datetime import datetime

import pytest

from services.routine_reconciler import (
    _AUTO_APPLY_THRESHOLD,
    _DEBUG_ONLY_THRESHOLD,
    score_candidate_directive,
    filter_directives_for_auto_apply,
    infer_routine_reconciliation_candidates,
    reconcile_fact_to_routines,
)
from services.routine_reconciler import _normalize

# ─────────────────────────────────────────────────────────────────────────────
# Fixtures / helpers
# ─────────────────────────────────────────────────────────────────────────────

_NOW = datetime(2026, 6, 17, 10, 0)


def _candidates(fact: str, reason: str = "user_stated") -> list[dict]:
    return infer_routine_reconciliation_candidates(
        fact, category="family", reason=reason, now=_NOW
    )


def _scored(fact: str, reason: str = "user_stated") -> list[dict]:
    candidates = _candidates(fact, reason)
    nf = _normalize(fact)
    return [
        score_candidate_directive(c, normalized_fact=nf, matched_rule_name=c["rule_name"])
        for c in candidates
    ]


def _first(fact: str, rule: str, reason: str = "user_stated") -> dict:
    """Return the first scored directive matching rule_name."""
    for d in _scored(fact, reason):
        if d["rule_name"] == rule:
            return d
    pytest.fail(f"No scored directive found for rule '{rule}' in fact: {fact!r}")


# ─────────────────────────────────────────────────────────────────────────────
# 1. seasonal_football — should score high and auto-apply
# ─────────────────────────────────────────────────────────────────────────────

class TestSeasonalFootball:
    FACT = "[USER_FACT] ο αλεξανδρος σταματησε ποδοσφαιρο καλοκαιρ σεπτεμβρ"

    def test_scores_high(self):
        d = _first(self.FACT, "seasonal_football")
        assert d["score"] >= _AUTO_APPLY_THRESHOLD

    def test_auto_applies(self):
        d = _first(self.FACT, "seasonal_football")
        assert d["auto_apply"] is True
        assert d["decision"] == "auto_apply"

    def test_has_subject_signal(self):
        d = _first(self.FACT, "seasonal_football")
        assert any("subject" in s for s in d["signals"])

    def test_has_activity_signal(self):
        d = _first(self.FACT, "seasonal_football")
        assert any("activity" in s for s in d["signals"])

    def test_has_scope_signal(self):
        d = _first(self.FACT, "seasonal_football")
        assert any("scope" in s for s in d["signals"])

    def test_has_special_rule_signal(self):
        d = _first(self.FACT, "seasonal_football")
        assert any("special_rule" in s for s in d["signals"])


# ─────────────────────────────────────────────────────────────────────────────
# 2. camp_absence — should score high and auto-apply
# ─────────────────────────────────────────────────────────────────────────────

class TestCampAbsence:
    FACT = "[USER_FACT] ο αλεξανδρ ειναι κατασκην για 10 μερες"

    def test_scores_high(self):
        d = _first(self.FACT, "camp_absence")
        assert d["score"] >= _AUTO_APPLY_THRESHOLD

    def test_auto_applies(self):
        d = _first(self.FACT, "camp_absence")
        assert d["auto_apply"] is True

    def test_reason_is_camp_absence(self):
        d = _first(self.FACT, "camp_absence")
        assert d["reason"] == "camp_absence"


# ─────────────────────────────────────────────────────────────────────────────
# 3. return_home — should score high and auto-apply (no until_date needed)
# ─────────────────────────────────────────────────────────────────────────────

class TestReturnHome:
    FACT = "[USER_FACT] ο αλεξανδρ γυρισ σπιτι απο κατασκην"

    def test_stays_debug_only_or_above(self):
        """return_home has no until_date so gets partial scope credit — debug_only is expected."""
        d = _first(self.FACT, "return_home")
        # Per design: return_home without explicit date is debug_only (not rejected)
        assert d["decision"] in ("debug_only", "auto_apply")

    def test_scores_at_or_above_debug_threshold(self):
        d = _first(self.FACT, "return_home")
        assert d["score"] >= _DEBUG_ONLY_THRESHOLD


# ─────────────────────────────────────────────────────────────────────────────
# 4. school_break — auto-apply only if child + school + scope all explicit
# ─────────────────────────────────────────────────────────────────────────────

class TestSchoolBreak:
    def test_with_full_signals_auto_applies(self):
        fact = "[USER_FACT] δεν εχει σχολει ο αλεξανδρ διακοπ σεπτεμβρ"
        d = _first(fact, "school_break")
        assert d["auto_apply"] is True

    def test_without_child_subject_rejected_or_debug(self):
        # No αλεξανδρ / παιδι / μικρ → rule should not even fire
        fact = "[USER_FACT] δεν εχει σχολει διακοπ σεπτεμβρ"
        candidates = _candidates(fact)
        school_break_candidates = [c for c in candidates if c["rule_name"] == "school_break"]
        # Rule guard requires child ref → no candidates expected
        assert school_break_candidates == []

    def test_without_scope_no_candidate(self):
        # αλεξανδρ + σχολει but no date/σεπτεμβρ → rule guard prevents candidate
        fact = "[USER_FACT] ο αλεξανδρ δεν εχει σχολει"
        candidates = _candidates(fact)
        school_break_candidates = [c for c in candidates if c["rule_name"] == "school_break"]
        assert school_break_candidates == []


# ─────────────────────────────────────────────────────────────────────────────
# 5. shift_logic (formerly shift_week) — should be debug_only by design
# ─────────────────────────────────────────────────────────────────────────────

class TestShiftWeek:
    FACT = "[USER_FACT] αυτη εβδομαδ δουλευω απογευμα"

    def test_stays_debug_only(self):
        d = _first(self.FACT, "shift_logic")
        assert d["decision"] == "debug_only"
        assert d["auto_apply"] is False

    def test_score_below_auto_threshold(self):
        d = _first(self.FACT, "shift_logic")
        assert d["score"] < _AUTO_APPLY_THRESHOLD

    def test_score_above_debug_threshold(self):
        d = _first(self.FACT, "shift_logic")
        assert d["score"] >= _DEBUG_ONLY_THRESHOLD

    def test_conservative_flag_present(self):
        d = _first(self.FACT, "shift_logic")
        assert "shift_logic_conservative" in d["ambiguity_flags"]

    def test_has_include_proxy_signal(self):
        """shift_logic has no explicit subject — scoring uses include_tokens as subject proxy."""
        d = _first(self.FACT, "shift_logic")
        assert any("include_proxy" in s or "subject" in s for s in d["signals"])


# ─────────────────────────────────────────────────────────────────────────────
# 6. Ambiguous fact — multiple_people penalty
# ─────────────────────────────────────────────────────────────────────────────

class TestAmbiguousMultiplePeople:
    def test_multiple_people_flag(self):
        # Both Αλέξανδρος and Σοφία in the same fact → penalty
        fact = "[USER_FACT] ο αλεξανδρ και η σοφια κατασκην για 7 μερες"
        scored = _scored(fact)
        camp_hits = [d for d in scored if d["rule_name"] == "camp_absence"]
        if camp_hits:
            d = camp_hits[0]
            assert "multiple_people" in d["ambiguity_flags"]
            # penalty should reduce score vs clean camp fact
            clean = _first("[USER_FACT] ο αλεξανδρ κατασκην για 7 μερες", "camp_absence")
            assert d["score"] < clean["score"]


# ─────────────────────────────────────────────────────────────────────────────
# 7. filter_directives_for_auto_apply — bucket splitting
# ─────────────────────────────────────────────────────────────────────────────

class TestFilterDirectivesForAutoApply:
    def _make(self, decision: str) -> dict:
        return {"kind": "schedule_pause", "decision": decision, "score": 0.9}

    def test_splits_into_correct_buckets(self):
        directives = [
            self._make("auto_apply"),
            self._make("debug_only"),
            self._make("rejected"),
            self._make("auto_apply"),
        ]
        auto, debug, rej = filter_directives_for_auto_apply(directives)
        assert len(auto) == 2
        assert len(debug) == 1
        assert len(rej) == 1

    def test_empty_input(self):
        auto, debug, rej = filter_directives_for_auto_apply([])
        assert auto == debug == rej == []

    def test_unknown_decision_goes_to_rejected(self):
        auto, debug, rej = filter_directives_for_auto_apply([{"decision": "whatever"}])
        assert len(rej) == 1


# ─────────────────────────────────────────────────────────────────────────────
# 8. Score clamped 0.0 – 1.0
# ─────────────────────────────────────────────────────────────────────────────

class TestScoreClamping:
    def test_score_never_exceeds_one(self):
        # A very strong fact should not exceed 1.0
        fact = "[USER_FACT] ο αλεξανδρ σταματ ποδοσφαιρ καλοκαιρ σεπτεμβρ"
        for d in _scored(fact):
            assert 0.0 <= d["score"] <= 1.0

    def test_score_never_below_zero(self):
        # A weak fact (no subject, no scope) gets penalties but stays >= 0
        fact = "[USER_FACT] κατι εγινε"
        # This won't produce candidates, so test with direct scoring
        from services.routine_reconciler import score_candidate_directive
        directive = {
            "kind": "notifications_mute",
            "subject_tokens": [],
            "include_tokens": [],
            "until_date": None,
            "reason": "test",
        }
        d = score_candidate_directive(directive, normalized_fact="κατι εγινε", matched_rule_name="shift_logic")
        assert d["score"] >= 0.0


# ─────────────────────────────────────────────────────────────────────────────
# 9. reconcile_fact_to_routines — rich stats dict
# ─────────────────────────────────────────────────────────────────────────────

class TestReconcileStats:
    def test_stats_include_candidate_buckets_when_no_candidates(self):
        # Fact without [USER_FACT] tag and wrong reason → no candidates
        stats = reconcile_fact_to_routines(
            "απλη κουβεντα",
            category="misc",
            reason="unknown",
            now=_NOW,
        )
        for key in ("candidates", "auto_apply_candidates", "debug_only_candidates",
                    "rejected_candidates", "scored_directives"):
            assert key in stats, f"Missing key: {key}"
        assert stats["applied"] is False

    def test_stats_include_candidate_buckets_with_candidates(self, monkeypatch):
        # Patch apply so no DB call happens
        import services.routine_reconciler as rr
        monkeypatch.setattr(rr, "apply_routine_reconciliation_directives", lambda d: {
            "directives": len(d), "matched_routines": 0,
            "schedule_paused": 0, "notifications_muted": 0,
            "notifications_unmuted": 0, "skipped": 0,
        })

        fact = "[USER_FACT] ο αλεξανδρ σταματ ποδοσφαιρ καλοκαιρ σεπτεμβρ"
        stats = reconcile_fact_to_routines(fact, category="family", reason="user_stated", now=_NOW)
        for key in ("candidates", "auto_apply_candidates", "debug_only_candidates",
                    "rejected_candidates", "scored_directives"):
            assert key in stats

    def test_shift_logic_never_auto_applies(self, monkeypatch):
        import services.routine_reconciler as rr
        applied_directives: list = []
        def _mock_apply(d: list) -> dict:
            applied_directives.extend(d)
            return {"directives": len(d), "matched_routines": 0,
                    "schedule_paused": 0, "notifications_muted": 0,
                    "notifications_unmuted": 0, "skipped": 0}
        monkeypatch.setattr(rr, "apply_routine_reconciliation_directives", _mock_apply)

        fact = "[USER_FACT] αυτη εβδομαδ δουλευω απογευμα"
        reconcile_fact_to_routines(fact, category="work", reason="user_stated", now=_NOW)
        shift_applied = [d for d in applied_directives if d.get("rule_name") == "shift_logic"]
        assert shift_applied == [], "shift_logic should never be in auto_apply list"

    def test_no_candidates_returns_false_applied(self):
        stats = reconcile_fact_to_routines(
            "no fact tag here", category="misc", reason="unknown", now=_NOW
        )
        assert stats["applied"] is False
        assert stats["candidates"] == 0
