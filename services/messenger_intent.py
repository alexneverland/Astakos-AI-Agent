from __future__ import annotations

from dataclasses import dataclass, field
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

_DRAFT_CLARIFY_PATTERNS = nl_config.MI_CLARIFICATION_WORDS

_DRAFT_CLEAR_PATTERNS = nl_config.MI_CLEANUP_WORDS

_GENERAL_SHORT = nl_config.MI_GENERAL_CHAT_SHORT


def _normalize(text: str) -> str:
    raw = str(text or "").strip().lower()
    normalized = unicodedata.normalize("NFD", raw)
    normalized = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    normalized = re.sub(r"[^\w\s]", " ", normalized)
    normalized = " ".join(normalized.split())
    return normalized


def _has_any(text: str, patterns: tuple[str, ...]) -> bool:
    return any(p in text for p in patterns)


def classify_messenger_intent(text: str, has_active_draft: bool = False) -> MessengerIntentResult:
    normalized = _normalize(text)

    if not normalized:
        return MessengerIntentResult("general_chat", 0.50, ["empty"])

    has_draft_word = any(word in normalized for word in ("draft",) + nl_config.MI_COMPOSE_WORDS)
    if has_active_draft and has_draft_word and _has_any(normalized, _DRAFT_CLEAR_PATTERNS):
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
