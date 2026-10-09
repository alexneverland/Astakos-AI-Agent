"""Strict LLM adapter for natural-language routine-completion decisions."""
from __future__ import annotations

import json
from datetime import date, datetime

from core.i18n import load_prompt
from services.gemini import safe_gemini_call
from services.routine_completion_helper import (
    CandidatePool, DatedRoutineSelection, RoutineFeedbackQuestion, RoutineFeedbackGroupQuestion,
    RoutineSelection, validate_dated_selection,
)
from services.routine_feedback import aware


_DRAFT_OFFER_MARKER = "[MESSENGER_DRAFT_OFFER]"


def _build_routines_block(candidates: dict[int, str]) -> str:
    """Format the dynamic candidate map for the external selector prompt."""
    return "\n".join(f'- ID {candidate_id}: "{event_name}"' for candidate_id, event_name in candidates.items())


def _strip_json_fence(raw: str) -> str:
    """Unwrap one optional Markdown JSON fence without repairing JSON syntax."""
    if not raw.startswith("```"):
        return raw
    lines = raw.splitlines()
    if len(lines) < 2 or not lines[0].lower().startswith("```json") or lines[-1].strip() != "```":
        return raw
    return "\n".join(lines[1:-1]).strip()


def _strict_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    """Reject duplicate JSON keys while constructing an object."""
    parsed: dict[str, object] = {}
    for key, value in pairs:
        if key in parsed:
            raise ValueError("duplicate JSON key")
        parsed[key] = value
    return parsed


def _none_selection() -> RoutineSelection:
    """Return the sole fail-closed selector result."""
    return RoutineSelection(action="none", routine_id=None)


def select_routine(
    user_text: str,
    candidates: dict[int, str],
    pool: CandidatePool,
) -> RoutineSelection:
    """Interpret one current message against one dynamic routine candidate pool."""
    if not candidates:
        return _none_selection()

    prompt_template = load_prompt("routine_completion_selector.md")
    prompt = prompt_template.replace("{routines_block}", _build_routines_block(candidates))
    prompt = prompt.replace("{user_text}", user_text)
    prompt = prompt.replace("{pool}", pool)

    try:
        response = safe_gemini_call(prompt)
        raw = _strip_json_fence(str(response.text).strip())
        parsed = json.loads(raw, object_pairs_hook=_strict_object)
    except Exception:
        return _none_selection()

    if not isinstance(parsed, dict) or set(parsed) != {"action", "routine_id"}:
        return _none_selection()

    action = parsed["action"]
    routine_id = parsed["routine_id"]
    if action == "none" and routine_id is None:
        return _none_selection()
    if action not in ("complete", "acknowledge", "draft", "skip_today", "pause"):
        return _none_selection()
    if type(routine_id) is not int or routine_id not in candidates:
        return _none_selection()
    if action == "draft" and _DRAFT_OFFER_MARKER not in candidates[routine_id]:
        return _none_selection()

    return RoutineSelection(action=action, routine_id=routine_id)


def select_dated_routine(
    user_text: str, candidates: dict[int, str], allowed_dates: dict[int, frozenset[date]],
    *, now: datetime, trusted: bool,
    pending_question: RoutineFeedbackQuestion | RoutineFeedbackGroupQuestion | None = None,
    conversation_context: list[dict] | None = None,
    candidate_evidence: dict[int, dict] | None = None,
) -> DatedRoutineSelection:
    """Interpret trusted feedback with authoritative dates; remain inactive until wired.

    Callers supply known occurrence dates and the authoritative calendar. An
    explicit owner report can complete an unrecorded past day, never invent a
    reminder delivery or apply non-completion feedback to that past day.
    Local-draft offers stay on the existing separate authorization path.
    """
    none = DatedRoutineSelection("none")
    if trusted is not True or not candidates or not isinstance(user_text, str) or not user_text.strip():
        return none
    try:
        now = aware(now)
        eligible = {
            rid: frozenset(day for day in allowed_dates.get(rid, ())
                           if type(day) is date and day <= now.date())
            for rid in candidates if type(rid) is int and rid > 0
        }
        eligible = {rid: days for rid, days in eligible.items() if days}
        if not eligible:
            return none
        pending = None
        if pending_question is not None:
            if not isinstance(pending_question, (RoutineFeedbackQuestion, RoutineFeedbackGroupQuestion)):
                return none
            grouped = isinstance(pending_question, RoutineFeedbackGroupQuestion)
            members = pending_question.routine_ids if grouped else (pending_question.routine_id,)
            if (not isinstance(members, tuple) or not members
                    or (grouped and len(members) < 2)
                    or any(type(rid) is not int for rid in members)
                    or len(set(members)) != len(members)
                    or type(pending_question.occurrence_date) is not date
                    or any(pending_question.occurrence_date not in eligible.get(rid, ()) for rid in members)
                    or not isinstance(pending_question.event_id, str)
                    or not 0 < len(pending_question.event_id.strip()) <= 512
                    or not isinstance(pending_question.question, str)
                    or not 0 < len(pending_question.question.strip()) <= 2000):
                return none
            pending = {("routine_ids" if grouped else "routine_id"):
                           list(members) if grouped else members[0],
                       "occurrence_date": pending_question.occurrence_date.isoformat(),
                       "event_id": pending_question.event_id, "question": pending_question.question}
        data = {"now": now.isoformat(), "timezone": "Europe/Athens",
                "candidates": [{"routine_id": rid, "name": candidates[rid],
                                "allowed_dates": sorted(day.isoformat() for day in days),
                                "identity_evidence": (candidate_evidence or {}).get(rid, {})}
                               for rid, days in eligible.items()], "user_text": user_text,
                "pending_question": pending, "conversation_context": conversation_context or []}
        prompt = load_prompt("routine_feedback_selector.md").replace(
            "{input_json}", json.dumps(data, ensure_ascii=False))
        response = safe_gemini_call(prompt)
        parsed = json.loads(_strip_json_fence(str(response.text).strip()),
                            object_pairs_hook=_strict_object)
        return validate_dated_selection(parsed, eligible, today=now.date())
    except Exception:
        return none
