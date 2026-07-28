"""
LLM adapter for the routine completion selector.

This is the ONLY module that loads the prompt file and invokes the
safe Gemini convention.  It produces a ``Callable[[str, dict[int, str]], int | None]``
suitable for injection into :func:`routine_completion_helper.decide_completion`.

Strict JSON contract::

    {"routine_id": <integer>}
    or
    {"routine_id": null}

Malformed output, unknown IDs, duplicate/invalid values, or exceptions â†’ ``None``.
"""
from __future__ import annotations

import json
from typing import TYPE_CHECKING

from core.i18n import load_prompt
from services.gemini import safe_gemini_call

if TYPE_CHECKING:
    pass


def _build_routines_block(candidates: dict[int, str]) -> str:
    """Format candidate map into the prompt block."""
    return "\n".join(f'- ID {cid}: "{name}"' for cid, name in candidates.items())


def select_routine(user_text: str, candidates: dict[int, str]) -> int | None:
    """Call the LLM to select exactly one routine from *candidates*.

    Parameters
    ----------
    user_text:
        The cleaned user message containing a completion statement.
    candidates:
        ``{routine_id: event_name}`` â€” the candidate pool.

    Returns
    -------
    int | None
        A routine ID that exists in *candidates*, or ``None`` if the LLM
        cannot decide, returns garbage, or any exception occurs.
    """
    if not candidates:
        return None

    prompt_template = load_prompt("routine_completion_selector.md")
    prompt = prompt_template.replace("{routines_block}", _build_routines_block(candidates))
    prompt = prompt.replace("{user_text}", user_text)

    try:
        response = safe_gemini_call(prompt)
        raw = response.text.strip()

        # Strip markdown fences if the LLM wraps its response.
        if raw.startswith("```"):
            lines = raw.splitlines()
            lines = [ln for ln in lines if not ln.startswith("```")]
            raw = "\n".join(lines).strip()

        def _strict_hook(pairs):
            d = {}
            for k, v in pairs:
                if k in d:
                    raise ValueError(f"Duplicate key: {k}")
                d[k] = v
            return d

        parsed = json.loads(raw, object_pairs_hook=_strict_hook)

        if parsed is None:
            return None

        if not isinstance(parsed, dict):
            return None

        if len(parsed) != 1 or "routine_id" not in parsed:
            return None

        rid = parsed["routine_id"]

        if rid is None:
            return None

        # Must be exactly an integer, not a bool (bool is a subclass of int in python, so we check type exactly)
        if type(rid) is not int:
            return None

        # ID validation: must exist in the supplied candidates.
        if rid not in candidates:
            return None

        return rid

    except Exception:
        return None
