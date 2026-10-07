"""Pure structural validation for LLM routine-completion decisions.

Natural-language interpretation belongs exclusively to the external selector
prompt. This module validates only the selector protocol, candidate membership,
and the allowed action for the supplied candidate pool.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import re
from typing import Callable, Literal


SelectorAction = Literal["complete", "acknowledge", "draft", "skip_today", "pause", "none"]
CandidatePool = Literal["pending", "today", "catalog"]


@dataclass(frozen=True)
class RoutineSelection:
    """Validated protocol value returned by the LLM selector adapter."""

    action: SelectorAction
    routine_id: int | None


@dataclass(frozen=True)
class CompletionDecision:
    """Safe routine mutation decision derived from a validated selector value."""

    action: Literal["complete", "acknowledge", "draft", "skip_today", "pause", "pass_through"]
    routine_id: int | None = None
    source: CandidatePool | None = None
    debug_reason: str = ""


Selector = Callable[[str, dict[int, str], CandidatePool], RoutineSelection]


@dataclass(frozen=True)
class DatedRoutineSelection:
    """Strict date-aware feedback; never an authorization for an external action."""

    action: Literal["complete", "acknowledge", "skip_today", "pause", "defer", "clarify", "none"]
    routine_id: int | None = None
    occurrence_date: date | None = None


@dataclass(frozen=True)
class RoutineFeedbackQuestion:
    """A caller-authenticated, exact reminder correlation, not arbitrary history."""

    routine_id: int
    occurrence_date: date
    event_id: str
    question: str


@dataclass(frozen=True)
class RoutineFeedbackGroupQuestion:
    """Several dated routines delivered in one authenticated transport message."""

    routine_ids: tuple[int, ...]
    occurrence_date: date
    event_id: str
    question: str


def validate_dated_selection(
    payload: object, allowed_dates: dict[int, frozenset[date]], *, today: date,
) -> DatedRoutineSelection:
    """Validate identity/calendar bounds, allowing explicit unrecorded completions.

    Known dates constrain every non-completion action. Historical completion
    need not have a delivery row; semantic grounding remains the selector's job.
    """
    none = DatedRoutineSelection("none")
    if not isinstance(payload, dict) or set(payload) != {"action", "routine_id", "occurrence_date"}:
        return none
    action, routine_id, day = payload["action"], payload["routine_id"], payload["occurrence_date"]
    if action == "none":
        return none
    if action not in ("complete", "acknowledge", "skip_today", "pause", "defer", "clarify"):
        return none
    if action == "clarify" and routine_id is None and day is None:
        return DatedRoutineSelection("clarify")
    if type(routine_id) is not int or routine_id not in allowed_dates:
        return none
    if action == "clarify":
        return DatedRoutineSelection("clarify", routine_id) if day is None else none
    if not isinstance(day, str):
        return none
    try:
        occurrence = date.fromisoformat(day)
    except ValueError:
        return none
    if day != occurrence.isoformat() or occurrence > today:
        return none
    if occurrence not in allowed_dates[routine_id] and not (action == "complete" and occurrence < today):
        return none
    if action != "complete" and occurrence != today:
        return none
    return DatedRoutineSelection(action, routine_id, occurrence)


def relevant_catalog_candidates(user_text: str, catalog: dict[int, str]) -> dict[int, str]:
    """Return catalogue routines structurally related to the user's own wording.

    No fixed language trigger list is used. Candidate relevance comes solely
    from names the user has already stored as routines; the LLM then decides
    whether the message is an explicit permanent pause.
    """
    user_tokens = {
        token.casefold()
        for token in re.findall(r"\w+", user_text, flags=re.UNICODE)
        if len(token) > 2
    }
    if not user_tokens:
        return {}
    relevant: dict[int, str] = {}
    for routine_id, event_name in catalog.items():
        event_tokens = {
            token.casefold()
            for token in re.findall(r"\w+", event_name, flags=re.UNICODE)
            if len(token) > 2
        }
        if user_tokens & event_tokens:
            relevant[routine_id] = event_name
    return relevant


def decide_completion(
    user_text: str,
    candidates: dict[int, str],
    pool: CandidatePool,
    semantic_selector: Selector | None,
    *,
    draft_offer_ids: frozenset[int] = frozenset(),
) -> CompletionDecision:
    """Return one safe action for the current message and one candidate pool.

    The helper deliberately performs no text matching. A selector can choose a
    candidate only through the external prompt; this function fails closed on
    malformed values, unknown IDs, unsupported actions, or selector errors.
    """
    if not candidates:
        return CompletionDecision(action="pass_through", debug_reason="no_candidates")
    if semantic_selector is None:
        return CompletionDecision(action="pass_through", debug_reason="no_selector")

    try:
        selection = semantic_selector(user_text, candidates, pool)
    except Exception:
        return CompletionDecision(action="pass_through", debug_reason="selector_error")

    if not isinstance(selection, RoutineSelection):
        return CompletionDecision(action="pass_through", debug_reason="invalid_selector_type")
    if selection.action == "none" and selection.routine_id is None:
        return CompletionDecision(action="pass_through", debug_reason="selector_none")
    if selection.action not in ("complete", "acknowledge", "draft", "skip_today", "pause"):
        return CompletionDecision(action="pass_through", debug_reason="invalid_selector_action")
    if type(selection.routine_id) is not int or selection.routine_id not in candidates:
        return CompletionDecision(action="pass_through", debug_reason="invalid_selector_id")
    if pool == "catalog" and selection.action != "pause":
        return CompletionDecision(action="pass_through", debug_reason="catalog_only_allows_pause")
    if selection.action == "draft" and (
        pool != "pending" or selection.routine_id not in draft_offer_ids
    ):
        return CompletionDecision(action="pass_through", debug_reason="draft_requires_pending_offer")

    return CompletionDecision(
        action=selection.action,
        routine_id=selection.routine_id,
        source=pool,
        debug_reason="selector_valid",
    )
