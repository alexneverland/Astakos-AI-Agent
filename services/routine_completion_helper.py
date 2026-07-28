"""
Pure decision helper for routine completion.

This module contains ZERO side effects:
- No database, Telegram, FastAPI, EventBus, network, or Gemini imports.
- No global state access.
- Receives user_text, candidate map, pool type, and an injected selector callable.
- Returns a typed CompletionDecision.
- Validates all selector outputs against the supplied candidate map.

The caller is responsible for all mutations (confirm, decay, mark_triggered_today, etc.).
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Callable, Literal


# ────────────────────────────────────────────────────────────────
# Data Types
# ────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class CompletionDecision:
    """Immutable result from the completion decision engine."""

    action: Literal["complete", "dismiss", "ask_clarification", "pass_through"]
    routine_id: int | None = None
    source: Literal["pending", "today"] | None = None
    match_method: str = ""                         # "deterministic" | "semantic" | ""
    debug_reason: str = ""
    clarification_candidates: dict[int, str] = field(default_factory=dict)


# ────────────────────────────────────────────────────────────────
# Text normalisation (accent-stripped lowercase, Greek-safe)
# ────────────────────────────────────────────────────────────────

def normalize_text(text: str) -> str:
    """Remove diacritics/accents and lowercase — same algorithm used
    everywhere in the Astakos codebase (_normalize_gr, _normalize)."""
    raw = str(text or "").strip().lower()
    nfd = unicodedata.normalize("NFD", raw)
    return "".join(ch for ch in nfd if not unicodedata.combining(ch))


# ────────────────────────────────────────────────────────────────
# Gate 1: Completion Intent Classification
# ────────────────────────────────────────────────────────────────

# Past-tense / done verbs (Greek + English, accent-stripped form).
_COMPLETION_VERBS: tuple[str, ...] = (
    # Greek past tense
    "καθαρισα", "εκανα", "τελειωσα", "πηγα", "πηγαμε",
    "τελειωσε", "ετοιμασα", "εβαλα", "εφτιαξα", "εφερα",
    "πλυνα", "σιδερωσα", "μαγειρεψα", "ταισα", "ποτισα",
    "εβγαλα", "εστειλα", "αγορασα", "παρηγγειλα",
    "εκλεισα", "εκοψα", "εστρωσα", "σκουπισα",
    "πηρα",
    # English
    "cleaned", "finished", "completed", "done", "did",
    "went", "bought", "cooked", "fed", "washed",
)

# Bare confirmation tokens (not specific to any routine).
_BARE_CONFIRM_TOKENS: tuple[str, ...] = (
    "ναι", "νε", "οκ", "εντάξει", "ενταξει", "εγινε",
    "yes", "ok", "sure", "yep", "yeah", "done",
)

# Bare dismissal tokens.
_BARE_DISMISS_TOKENS: tuple[str, ...] = (
    "οχι", "ακυρο", "δεν", "οχ",
    "no", "nope", "cancel", "skip",
)

# Exclusion gates — if ANY of these appears, no completion intent.
_FUTURE_TOKENS: tuple[str, ...] = (
    "θα ", "θα'", "will ", "going to", "gonna",
    "θα το κανω", "θα το καθαρισω", "θα παω",
)
_IN_PROGRESS_TOKENS: tuple[str, ...] = (
    "ξεκινησα", "ξεκιναω", "κανω τωρα", "καθαριζω τωρα",
    "starting", "doing now", "working on",
)
_UNCERTAINTY_TOKENS: tuple[str, ...] = (
    "ισως", "μαλλον", "μπορει", "maybe", "perhaps", "probably",
)
_QUESTION_MARKERS: tuple[str, ...] = (
    "?", ";",  # Greek semicolon is question mark
)


def _strip_punctuation(text: str) -> str:
    """Remove common punctuation for word splitting."""
    return re.sub(r"[,.\-!;?:\"'()]+", " ", text)


def classify_intent(text: str) -> Literal[
    "specific_completion", "bare_confirm", "bare_dismiss", "none"
]:
    """Classify user text into a completion intent category.

    Returns one of:
        - ``"specific_completion"`` — past-tense verb with descriptive content.
        - ``"bare_confirm"`` — vague affirmation (ναι, ok, done …).
        - ``"bare_dismiss"`` — vague negation (όχι, no …).
        - ``"none"`` — no completion intent detected.
    """
    norm = normalize_text(text)

    # Exclusion gates — checked first.
    if any(tok in norm for tok in _FUTURE_TOKENS):
        return "none"
    if any(tok in norm for tok in _IN_PROGRESS_TOKENS):
        return "none"
    if any(tok in norm for tok in _UNCERTAINTY_TOKENS):
        return "none"
    if any(mk in text for mk in _QUESTION_MARKERS):
        return "none"

    words = _strip_punctuation(norm).split()
    raw_words = norm.split()

    # Check for explicit negation tokens anywhere in the message.
    negation_tokens = {"δεν", "δε", "οχι", "not", "no", "nope"}
    contraction_tokens = {"haven't", "didn't", "havent", "didnt"}
    has_negation = any(w in negation_tokens for w in words) or any(w in contraction_tokens for w in raw_words)

    if has_negation:
        # Negation + completion verb = negated completion → no intent.
        if any(verb in norm for verb in _COMPLETION_VERBS):
            return "none"
        # Bare negation without a completion verb ("όχι", "no", "δεν χρειάζεται").
        if len(words) <= 3:
            return "bare_dismiss"
        # Longer negated sentence without a completion verb → no intent.
        return "none"

    # Check for completion verbs.
    has_completion_verb = any(verb in norm for verb in _COMPLETION_VERBS)

    # Check for bare tokens.
    is_bare = (
        len(words) <= 3
        and any(normalize_text(tok) in words for tok in _BARE_CONFIRM_TOKENS)
    )

    if has_completion_verb:
        # Determine if specific or bare.
        # A completion verb with more than just the verb → specific.
        non_verb_words = [
            w for w in words
            if len(w) >= 3 and not any(verb == w or verb in w for verb in _COMPLETION_VERBS)
        ]
        if non_verb_words:
            return "specific_completion"
        # Completion verb alone ("τελείωσα", "done") → bare.
        return "bare_confirm"

    if is_bare:
        return "bare_confirm"

    # Check for bare dismissal that wasn't caught above
    is_bare_dismiss = (
        len(words) <= 3
        and any(normalize_text(tok) in words for tok in _BARE_DISMISS_TOKENS)
    )
    if is_bare_dismiss:
        return "bare_dismiss"

    return "none"


# ────────────────────────────────────────────────────────────────
# Gate 2: Deterministic Candidate Matching
# ────────────────────────────────────────────────────────────────

_MIN_WORD_LEN = 3  # Ignore tiny Greek particles/articles.


def _significant_words(text: str) -> set[str]:
    """Extract significant words (≥ _MIN_WORD_LEN chars) from normalised text."""
    return {
        w for w in _strip_punctuation(normalize_text(text)).split()
        if len(w) >= _MIN_WORD_LEN
    }


def match_candidates(
    user_text: str,
    candidates: dict[int, str],
) -> list[int]:
    """Return candidate IDs that have a strong deterministic match.

    A candidate matches if *all* of its significant event-name
    words appear somewhere in the user text (substring containment, not
    full-word equality) to partially handle Greek inflection.
    """
    user_norm = normalize_text(user_text)
    user_words = set(_strip_punctuation(user_norm).split())
    matched: list[int] = []

    for cid, event_name in candidates.items():
        event_words = _significant_words(event_name)
        if not event_words:
            continue
        hits = sum(1 for ew in event_words if ew in user_words)
        if hits == len(event_words):
            matched.append(cid)

    return matched


# ────────────────────────────────────────────────────────────────
# Main Decision Orchestrator
# ────────────────────────────────────────────────────────────────

def decide_completion(
    user_text: str,
    candidates: dict[int, str],
    pool: Literal["pending", "today"],
    semantic_selector: Callable[[str, dict[int, str]], int | None] | None = None,
) -> CompletionDecision:
    """Produce a single :class:`CompletionDecision` for a user message.

    Parameters
    ----------
    user_text:
        The cleaned user message.
    candidates:
        ``{routine_id: event_name}`` from exactly one pool.
    pool:
        ``"pending"`` (already-notified routines) or ``"today"``
        (pre-emptive, scheduler has not fired yet).
    semantic_selector:
        Optional callable ``(user_text, candidates) -> int | None``.
        Injected by the caller so the helper stays pure.

    Returns
    -------
    CompletionDecision
        Action to take, with the selected routine ID when applicable.
    """
    if not candidates:
        return CompletionDecision(
            action="pass_through",
            debug_reason="no_candidates",
        )

    intent = classify_intent(user_text)

    # ── "none" intent: no completion signal ──────────────────────
    if intent == "none":
        return CompletionDecision(
            action="pass_through",
            debug_reason="no_completion_intent",
        )

    # ── bare_dismiss ─────────────────────────────────────────────
    if intent == "bare_dismiss":
        if pool == "today":
            return CompletionDecision(
                action="pass_through",
                debug_reason="bare_dismiss_no_pending",
            )
        # pending pool
        if len(candidates) == 1:
            rid = next(iter(candidates))
            return CompletionDecision(
                action="dismiss",
                routine_id=rid,
                source="pending",
                match_method="deterministic",
                debug_reason="single_pending_bare_dismiss",
            )
        return CompletionDecision(
            action="ask_clarification",
            source="pending",
            debug_reason="multi_pending_bare_dismiss",
            clarification_candidates=dict(candidates),
        )

    # ── bare_confirm ─────────────────────────────────────────────
    if intent == "bare_confirm":
        if pool == "today":
            # Bare yes/done/έγινε with no pending → never select today.
            return CompletionDecision(
                action="pass_through",
                debug_reason="bare_confirm_no_pending",
            )
        # pending pool
        if len(candidates) == 1:
            rid = next(iter(candidates))
            return CompletionDecision(
                action="complete",
                routine_id=rid,
                source="pending",
                match_method="deterministic",
                debug_reason="single_pending_bare_confirm",
            )
        return CompletionDecision(
            action="ask_clarification",
            source="pending",
            debug_reason="multi_pending_bare_confirm",
            clarification_candidates=dict(candidates),
        )

    # ── specific_completion ──────────────────────────────────────
    assert intent == "specific_completion"

    deterministic_matches = match_candidates(user_text, candidates)

    if len(deterministic_matches) == 1:
        rid = deterministic_matches[0]
        return CompletionDecision(
            action="complete",
            routine_id=rid,
            source=pool,
            match_method="deterministic",
            debug_reason="unique_deterministic_match",
        )

    # 0 matches (morphology) or 2+ matches → use selector.
    if semantic_selector is not None:
        try:
            selected_id = semantic_selector(user_text, candidates)
        except Exception:
            selected_id = None

        if type(selected_id) is int and selected_id in candidates:
            return CompletionDecision(
                action="complete",
                routine_id=selected_id,
                source=pool,
                match_method="semantic",
                debug_reason="selector_chose_valid_id",
            )

    # Selector returned None / invalid / not provided.
    if pool == "pending":
        return CompletionDecision(
            action="ask_clarification",
            source="pending",
            debug_reason="selector_none_pending",
            clarification_candidates=dict(candidates),
        )
    # today pool — pass through silently
    return CompletionDecision(
        action="pass_through",
        debug_reason="selector_none_today",
    )
