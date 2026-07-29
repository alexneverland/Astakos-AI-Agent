"""Trusted graph context for already-recorded routine decisions."""
from __future__ import annotations

from langchain_core.messages import SystemMessage

from core.i18n import load_prompt


def build_routine_completion_context(action: str, routine_name: str) -> SystemMessage:
    """Create a non-user-visible graph message for one verified routine mutation."""
    template = load_prompt("routine_completion_context.md")
    return SystemMessage(content=template.format(action=action, routine_name=routine_name))
