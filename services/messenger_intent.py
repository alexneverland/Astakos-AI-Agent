from __future__ import annotations

from dataclasses import dataclass, field
import unicodedata
import re


@dataclass
class MessengerIntentResult:
    intent: str
    confidence: float
    signals: list[str] = field(default_factory=list)


_DRAFT_CREATE_PATTERNS = (
    "γραψε",
    "ετοιμασε",
    "φτιαξε",
    "στελ",
    "στειλ",
    "μηνυμα",
    "draft",
    "προσχεδιο",
)

_DRAFT_CONFIRM_PATTERNS = (
    "στειλε",
    "στειλτο",
    "ναι στειλε",
    "ναι",
    "οκ στειλε",
    "βαρα το",
    "φυγαμε",
)

_DRAFT_CLARIFY_PATTERNS = (
    "ποιο μηνυμα",
    "τι μηνυμα",
    "ποιο draft",
    "τι draft",
    "τι εννοεις",
    "ποιο λες",
    "ποιο απο ολα",
    "δεν καταλαβα",
)

_DRAFT_CLEAR_PATTERNS = (
    "αυτο το εχουμε στειλει",
    "αυτο σταλθηκε",
    "το εχουμε στειλει",
    "το στειλαμε",
    "κλειστο",
    "κλεισε το",
    "αστο",
    "αδειασε το",
    "σβηστο",
    "σβησε το draft",
    "μην το κρατας",
    "δεν το θελω",
)

_GENERAL_SHORT = {
    "ναι", "οχι", "οκ", "οκευ", "εγινε", "καλα"
}


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

    if _has_any(normalized, _DRAFT_CLEAR_PATTERNS):
        return MessengerIntentResult("clear_draft", 0.98, ["clear_phrase"])

    if _has_any(normalized, _DRAFT_CLARIFY_PATTERNS):
        return MessengerIntentResult("clarify_draft", 0.96, ["clarify_phrase"])

    if has_active_draft and _has_any(normalized, _DRAFT_CONFIRM_PATTERNS):
        return MessengerIntentResult("confirm_send", 0.95, ["confirm_phrase", "active_draft"])

    has_create = _has_any(normalized, _DRAFT_CREATE_PATTERNS)
    has_message_shape = ("μηνυμα" in normalized or "draft" in normalized or "προσχεδιο" in normalized)

    if has_create and has_message_shape:
        return MessengerIntentResult("create_draft", 0.90, ["draft_create_phrase"])

    if normalized in _GENERAL_SHORT:
        return MessengerIntentResult("general_chat", 0.85, ["short_chat"])

    return MessengerIntentResult("general_chat", 0.60, ["fallback"])
