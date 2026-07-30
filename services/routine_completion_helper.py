"""Pure structural validation for LLM routine-completion decisions.

Natural-language interpretation belongs exclusively to the external selector
prompt. This module validates only the selector protocol, candidate membership,
and the allowed action for the supplied candidate pool.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Literal


SelectorAction = Literal["complete", "acknowledge", "skip_today", "pause", "none"]
CandidatePool = Literal["pending", "today"]


@dataclass(frozen=True)
class RoutineSelection:
    """Validated protocol value returned by the LLM selector adapter."""

    action: SelectorAction
    routine_id: int | None


@dataclass(frozen=True)
class CompletionDecision:
    """Safe routine mutation decision derived from a validated selector value."""

    action: Literal["complete", "acknowledge", "skip_today", "pause", "pass_through"]
    routine_id: int | None = None
    source: CandidatePool | None = None
    debug_reason: str = ""


Selector = Callable[[str, dict[int, str], CandidatePool], RoutineSelection]


def decide_completion(
    user_text: str,
    candidates: dict[int, str],
    pool: CandidatePool,
    semantic_selector: Selector | None,
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
    if selection.action not in ("complete", "acknowledge", "skip_today", "pause"):
        return CompletionDecision(action="pass_through", debug_reason="invalid_selector_action")
    if type(selection.routine_id) is not int or selection.routine_id not in candidates:
        return CompletionDecision(action="pass_through", debug_reason="invalid_selector_id")

    return CompletionDecision(
        action=selection.action,
        routine_id=selection.routine_id,
        source=pool,
        debug_reason="selector_valid",
    )
