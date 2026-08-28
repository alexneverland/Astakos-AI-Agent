from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable
import unicodedata
import re
from core import nl_config

@dataclass
class MessengerIntentResult:
    intent: str
    confidence: float
    signals: list[str] = field(default_factory=list)


_DRAFT_CREATE_PATTERNS = nl_config.MI_COMPOSE_WORDS

_DRAFT_CONFIRM_PATTERNS = nl_config.MI_SEND_APPROVAL_WORDS

_DRAFT_OFFER_AFFIRMATIVES = nl_config.MI_DRAFT_OFFER_AFFIRMATIVES

_DRAFT_REQUEST_NEGATIONS = nl_config.MI_DRAFT_REQUEST_NEGATIONS

_DRAFT_REQUEST_ACTION_VERBS = nl_config.MI_DRAFT_REQUEST_ACTION_VERBS

_DRAFT_REQUEST_OBJECTS = nl_config.MI_DRAFT_REQUEST_OBJECTS

_DRAFT_EDIT_PATTERNS = nl_config.MI_DRAFT_EDIT_PATTERNS

_DRAFT_CLARIFY_PATTERNS = nl_config.MI_CLARIFICATION_WORDS

_DRAFT_CLEAR_PATTERNS = nl_config.MI_CLEANUP_WORDS

_GENERAL_SHORT = nl_config.MI_GENERAL_CHAT_SHORT

MESSENGER_ROUTINE_DRAFT_OFFER_MARKER = "[MESSENGER_ROUTINE_DRAFT_OFFER_ACCEPTED]"


def _normalize(text: str) -> str:
    raw = str(text or "").strip().lower()
    normalized = unicodedata.normalize("NFD", raw)
    normalized = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    normalized = re.sub(r"[^\w\s]", " ", normalized)
    normalized = " ".join(normalized.split())
    return normalized


def _has_any(text: str, patterns: tuple[str, ...]) -> bool:
    return any(p in text for p in patterns)


def _has_token_or_phrase(text: str, patterns: tuple[str, ...]) -> bool:
    """Return whether normalized text contains an exact configured token or phrase."""
    tokens = text.split()
    for pattern in patterns:
        pattern_tokens = _normalize(pattern).split()
        if not pattern_tokens:
            continue
        if len(pattern_tokens) == 1 and pattern_tokens[0] in tokens:
            return True
        if any(
            tokens[index:index + len(pattern_tokens)] == pattern_tokens
            for index in range(len(tokens) - len(pattern_tokens) + 1)
        ):
            return True
    return False


def _has_leading_draft_creation_verb(text: str) -> bool:
    """Return whether a creation verb follows conversational filler, not another subject."""
    action_verbs = {
        token
        for pattern in _DRAFT_REQUEST_ACTION_VERBS
        for token in _normalize(pattern).split()
    }
    tokens = text.split()
    for index, token in enumerate(tokens):
        prefix = " ".join(tokens[:index])
        if (
            token in action_verbs
            and not _has_token_or_phrase(prefix, _DRAFT_REQUEST_NEGATIONS)
            and not _has_token_or_phrase(prefix, _DRAFT_REQUEST_OBJECTS)
        ):
            return True
    return False


def is_draft_offer_acceptance(text: str) -> bool:
    """Return whether text is a bare configured affirmative for a pending draft offer."""
    normalized = _normalize(text)
    return any(normalized == _normalize(pattern) for pattern in _DRAFT_OFFER_AFFIRMATIVES)


def has_accepted_routine_draft_offer(
    messages: Iterable[Any],
    *,
    state_authorized: bool | None = None,
) -> bool:
    """Return whether the current graph run has a trusted routine-draft acceptance.

    ``None`` preserves the legacy system-marker lookup.  A supplied boolean is
    authoritative so a consumed one-shot authorization cannot be revived by
    an older marker still present in the graph history.
    """
    if state_authorized is not None:
        return state_authorized is True
    return any(
        getattr(message, "type", "") == "system"
        and str(getattr(message, "content", "")).startswith(MESSENGER_ROUTINE_DRAFT_OFFER_MARKER)
        for message in messages
    )


def classify_messenger_intent(text: str, has_active_draft: bool = False) -> MessengerIntentResult:
    normalized = _normalize(text)

    if not normalized:
        return MessengerIntentResult("general_chat", 0.50, ["empty"])

    has_draft_word = any(word in normalized for word in ("draft",) + nl_config.MI_COMPOSE_WORDS)
    if has_draft_word and _has_any(normalized, _DRAFT_CLEAR_PATTERNS):
        return MessengerIntentResult("clear_draft", 0.98, ["clear_phrase"])

    if _has_any(normalized, _DRAFT_CLARIFY_PATTERNS):
        return MessengerIntentResult("clarify_draft", 0.96, ["clarify_phrase"])

    word_count = len(normalized.split())
    if has_active_draft and word_count <= 4 and _has_any(normalized, _DRAFT_CONFIRM_PATTERNS):
        return MessengerIntentResult("confirm_send", 0.95, ["confirm_phrase", "active_draft", "short_confirm"])

    has_create = _has_any(normalized, _DRAFT_CREATE_PATTERNS)
    has_message_shape = any(w in normalized for w in ("draft",) + nl_config.MI_COMPOSE_WORDS)

    if has_create and has_message_shape:
        return MessengerIntentResult("create_draft", 0.90, ["draft_create_phrase"])

    if normalized in _GENERAL_SHORT:
        return MessengerIntentResult("general_chat", 0.85, ["short_chat"])

    return MessengerIntentResult("general_chat", 0.60, ["fallback"])

def is_create_draft_intent(text: str) -> bool:
    """Return whether text explicitly requests a new Messenger draft."""
    return classify_messenger_intent(text).intent == "create_draft"


def is_active_draft_edit_intent(text: str) -> bool:
    """Return whether text asks to revise the currently active Messenger draft."""
    normalized = _normalize(text)
    tokens = normalized.split()
    for pattern in _DRAFT_EDIT_PATTERNS:
        pattern_tokens = _normalize(pattern).split()
        if not pattern_tokens:
            continue
        for index in range(len(tokens) - len(pattern_tokens) + 1):
            if tokens[index:index + len(pattern_tokens)] != pattern_tokens:
                continue
            if not _has_token_or_phrase(
                " ".join(tokens[:index]),
                _DRAFT_REQUEST_NEGATIONS,
            ):
                return True
    return False


def is_unambiguous_active_draft_edit_intent(text: str) -> bool:
    """Return whether text clearly refers to revising the active Messenger draft."""
    normalized = _normalize(text)
    explicit_references = (
        "message", "μηνυμα", "draft", "προσχεδιο",
        "change the ending", "edit the ending",
    )
    if not _has_token_or_phrase(normalized, explicit_references):
        return False
    if is_active_draft_edit_intent(text):
        return True
    explicit_edit_actions = (
        "change", "edit", "rewrite", "make", "translate",
        "αλλαξε", "διορθωσε", "καν", "καντο", "βαλε", "βγαλε",
    )
    return _has_token_or_phrase(normalized, explicit_edit_actions)


def has_immediately_preceding_messenger_draft_write(messages: Iterable[Any]) -> bool:
    """Return whether the latest user turn directly follows a saved-draft display."""
    from core.untrusted_content import is_direct_user_message
    from core.utils import clean_message, looks_like_messenger_draft_ready_reply

    found_latest_user = False
    for message in reversed(list(messages)):
        if is_direct_user_message(message):
            if found_latest_user:
                return False
            found_latest_user = True
            continue
        if not found_latest_user:
            continue
        if (
            getattr(message, "type", "") in {"ai", "assistant"}
            and looks_like_messenger_draft_ready_reply(
                clean_message(getattr(message, "content", "")),
            )
        ):
            return True
    return False


def is_contextually_grounded_active_draft_edit(
    text: str,
    messages: Iterable[Any],
) -> bool:
    """Allow shorthand draft edits only as the immediate reply to a saved draft."""
    return (
        is_unambiguous_active_draft_edit_intent(text)
        or (
            is_active_draft_edit_intent(text)
            and has_immediately_preceding_messenger_draft_write(messages)
        )
    )


def is_explicit_draft_creation_request(text: str) -> bool:
    """Return whether text has affirmative configured draft action and object terms."""
    raw_text = str(text).strip()
    question_text = raw_text.rstrip("\"'”’ ")
    if question_text.endswith(("?", ";")) and not any(
        quote in raw_text for quote in ("\"", "'", "“", "”", "‘", "’")
    ):
        return False
    normalized = _normalize(text)
    if _has_token_or_phrase(normalized, _DRAFT_REQUEST_NEGATIONS):
        return False
    return (
        _has_leading_draft_creation_verb(normalized)
        and _has_token_or_phrase(normalized, _DRAFT_REQUEST_OBJECTS)
    )
