"""Trusted graph context for already-recorded routine decisions."""
from __future__ import annotations

from dataclasses import dataclass
from html import escape
from typing import Mapping

from langchain_core.messages import BaseMessage, SystemMessage

from core.i18n import load_prompt
from services.messenger_intent import MESSENGER_ROUTINE_DRAFT_OFFER_MARKER


@dataclass(frozen=True)
class AcceptedMessengerDraftOffer:
    """Trusted pending routine draft offer accepted by one explicit user reply."""

    routine_id: int
    context: SystemMessage


def build_routine_completion_context() -> SystemMessage:
    """Create fixed trusted context without embedding user-derived routine data."""
    template = load_prompt("routine_completion_context.md")
    return SystemMessage(content=template)


def build_messenger_draft_offer_context(event_name: str) -> SystemMessage:
    """Create trusted graph context for one accepted pending message routine offer."""
    template = load_prompt("routine_messenger_draft_offer.md").format(
        routine_event=escape(event_name, quote=False),
    )
    return SystemMessage(content=f"{MESSENGER_ROUTINE_DRAFT_OFFER_MARKER}\n{template}")


def accept_pending_messenger_draft_offer(
    pending_confirmations: Mapping[int, object],
    user_text: str,
) -> AcceptedMessengerDraftOffer | None:
    """Return one trusted offer acceptance only for a sole persisted structured offer.

    This deliberately relies only on ``draft_offer`` stored at proactive-message
    creation time. It never infers authorization from a routine name or from
    assistant prose, and fails closed for batches and malformed pending data.
    """
    if len(pending_confirmations) != 1:
        return None

    routine_id, pending_data = next(iter(pending_confirmations.items()))
    if type(routine_id) is not int or not isinstance(pending_data, Mapping):
        return None
    if pending_data.get("draft_offer") is not True:
        return None
    event_name = pending_data.get("event")
    if not isinstance(event_name, str) or not event_name.strip():
        return None

    from services.messenger_intent import is_draft_offer_acceptance

    if not is_draft_offer_acceptance(user_text):
        return None
    return AcceptedMessengerDraftOffer(
        routine_id=routine_id,
        context=build_messenger_draft_offer_context(event_name.strip()),
    )


def append_routine_completion_context(
    messages: list[BaseMessage],
    *contexts: SystemMessage | None,
) -> list[BaseMessage]:
    """Append supplied trusted routine contexts to one graph message list."""
    return messages + [context for context in contexts if context is not None]
