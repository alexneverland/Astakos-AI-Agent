"""Isolated tests for the Telegram routine guard without starting its bot runtime."""

import ast
from pathlib import Path
from types import SimpleNamespace
from typing import Callable


def _load_proactive_guard() -> Callable[[str, dict], str | None]:
    """Execute only the guard function to avoid importing live bot transports."""
    source = Path(__file__).resolve().parents[1] / "clients" / "telegram_bot.py"
    tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
    guard = next(
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "_force_proactive_skip_from_state"
    )
    module = ast.Module(body=[guard], type_ignores=[])
    namespace = {
        "t": lambda key: "[CONTEXT_SKIP]" if key.endswith(("9b132d", "9fbd6e")) else "__not_event__",
        "config": SimpleNamespace(PARTNER_NAME="__partner__"),
    }
    exec(compile(module, str(source), "exec"), namespace)
    return namespace["_force_proactive_skip_from_state"]


def test_park_and_football_guard_require_confirmed_absence() -> None:
    """School or a short outing must not be treated as family absence."""
    guard = _load_proactive_guard()
    for event_name in ("park", "training"):
        school = {
            "kid1_away_from_home": {"value": "true"},
            "kid1_away_reason": {"value": "school"},
        }
        camp = {
            "kid1_away_from_home": {"value": "true"},
            "kid1_away_reason": {"value": "camp"},
        }
        assert guard(event_name, school) is None
        assert guard(event_name, camp) == "[CONTEXT_SKIP]"
