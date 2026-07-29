"""Strict LLM adapter for natural-language routine-completion decisions."""
from __future__ import annotations

import json

from core.i18n import load_prompt
from services.gemini import safe_gemini_call
from services.routine_completion_helper import CandidatePool, RoutineSelection


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
    if action not in ("complete", "dismiss"):
        return _none_selection()
    if type(routine_id) is not int or routine_id not in candidates:
        return _none_selection()
    if action == "dismiss" and pool != "pending":
        return _none_selection()

    return RoutineSelection(action=action, routine_id=routine_id)
