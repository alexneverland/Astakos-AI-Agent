"""Trusted graph context for already-recorded routine decisions."""
from __future__ import annotations

from langchain_core.messages import BaseMessage, SystemMessage

from core.i18n import load_prompt


def build_routine_completion_context() -> SystemMessage:
    """Create fixed trusted context without embedding user-derived routine data."""
    template = load_prompt("routine_completion_context.md")
    return SystemMessage(content=template)


def append_routine_completion_context(
    messages: list[BaseMessage],
    context: SystemMessage | None,
) -> list[BaseMessage]:
    """Append trusted completion context to one graph message list when present."""
    return messages + [context] if context is not None else messages
