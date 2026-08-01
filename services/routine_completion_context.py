"""Trusted graph context for already-recorded routine decisions."""
from __future__ import annotations

from langchain_core.messages import BaseMessage, SystemMessage

from core.i18n import load_prompt
from services.messenger_intent import MESSENGER_ROUTINE_DRAFT_OFFER_MARKER


def build_routine_completion_context() -> SystemMessage:
    """Create fixed trusted context without embedding user-derived routine data."""
    template = load_prompt("routine_completion_context.md")
    return SystemMessage(content=template)


def build_messenger_draft_offer_context() -> SystemMessage:
    """Create trusted graph context after a user accepts a pending message routine offer."""
    template = load_prompt("routine_messenger_draft_offer.md")
    return SystemMessage(content=f"{MESSENGER_ROUTINE_DRAFT_OFFER_MARKER}\n{template}")


def append_routine_completion_context(
    messages: list[BaseMessage],
    context: SystemMessage | None,
) -> list[BaseMessage]:
    """Append trusted completion context to one graph message list when present."""
    return messages + [context] if context is not None else messages
