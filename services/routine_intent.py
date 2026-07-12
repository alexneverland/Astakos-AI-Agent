from __future__ import annotations

from dataclasses import dataclass, field
import re
import unicodedata
from core import nl_config

@dataclass
class RoutineIntentResult:
    intent: str
    confidence: float
    signals: list[str] = field(default_factory=list)
    matched_routine_hint: str | None = None


_MANUAL_VERB_PATTERNS = nl_config.RI_CONTROL_VERBS

_MANUAL_CONTROL_HINTS = (
    "condition",
    "schedule",
    "cooldown",
) + nl_config.RI_ROUTINE_NOUNS + nl_config.RI_TIME_CONDITION_WORDS + nl_config.RI_COOLDOWN_RESET_WORDS

_CONTEXT_PATTERNS = nl_config.RI_CONTEXT_UPDATE_PHRASES

_GENERAL_CHAT_SHORT = set(nl_config.RI_FILLER_ACKS)

_STOPWORDS = nl_config.RI_STOP_WORDS


def _normalize(text: str) -> str:
    raw = str(text or "").strip().lower()
    normalized = unicodedata.normalize("NFD", raw)
    return "".join(ch for ch in normalized if not unicodedata.combining(ch))


def _has_any(text: str, patterns: tuple[str, ...]) -> bool:
    return any(p in text for p in patterns)


def _tokenize(text: str) -> list[str]:
    compact = re.sub(r"[^\w\s]", " ", _normalize(text))
    tokens = []
    for tok in compact.split():
        if len(tok) < 3:
            continue
        if tok in _STOPWORDS:
            continue
        tokens.append(tok)
    return tokens


def _extract_routine_hint(normalized: str, routine_names: list[str] | None) -> str | None:
    if not routine_names:
        return None

    msg_tokens = set(_tokenize(normalized))
    if not msg_tokens:
        return None

    best_name = None
    best_score = 0.0

    for name in routine_names:
        name_tokens = set(_tokenize(name))
        if not name_tokens:
            continue

        overlap = len(msg_tokens & name_tokens) / max(len(name_tokens), 1)
        if overlap > best_score:
            best_score = overlap
            best_name = name

    return best_name if best_score >= 0.5 else None


def _looks_like_general_chat(normalized: str) -> bool:
    return normalized.strip() in _GENERAL_CHAT_SHORT


def _looks_like_manual_routine_control(
    normalized: str,
    routine_hint: str | None,
) -> tuple[bool, list[str]]:
    signals: list[str] = []

    has_manual_verb = _has_any(normalized, _MANUAL_VERB_PATTERNS)
    has_control_hint = _has_any(normalized, _MANUAL_CONTROL_HINTS)
    has_routine_hint = routine_hint is not None

    if has_manual_verb:
        signals.append("manual_verb")
    if has_control_hint:
        signals.append("control_hint")
    if has_routine_hint:
        signals.append("matched_routine_hint")

    strong_manual = has_manual_verb and (has_control_hint or has_routine_hint)
    return strong_manual, signals


def _looks_like_context_update(
    normalized: str,
    routine_hint: str | None,
) -> tuple[bool, list[str]]:
    signals: list[str] = []

    has_context_language = _has_any(normalized, _CONTEXT_PATTERNS)
    has_manual_verb = _has_any(normalized, _MANUAL_VERB_PATTERNS)

    if has_context_language:
        signals.append("context_language")
    if routine_hint is not None:
        signals.append("matched_routine_hint")
    if not has_manual_verb:
        signals.append("no_manual_verb")

    strong_context = has_context_language and not has_manual_verb
    return strong_context, signals


def classify_routine_intent(
    message: str,
    routine_names: list[str] | None = None,
) -> RoutineIntentResult:
    normalized = _normalize(message)

    if not normalized:
        return RoutineIntentResult(
            intent="general_chat",
            confidence=0.50,
            signals=["empty"],
        )

    if _looks_like_general_chat(normalized):
        return RoutineIntentResult(
            intent="general_chat",
            confidence=0.95,
            signals=["short_chat"],
        )

    routine_hint = _extract_routine_hint(normalized, routine_names)

    is_manual, manual_signals = _looks_like_manual_routine_control(normalized, routine_hint)
    if is_manual:
        return RoutineIntentResult(
            intent="manual_routine_control",
            confidence=0.92,
            signals=manual_signals,
            matched_routine_hint=routine_hint,
        )

    is_context, context_signals = _looks_like_context_update(normalized, routine_hint)
    if is_context:
        return RoutineIntentResult(
            intent="context_update",
            confidence=0.88,
            signals=context_signals,
            matched_routine_hint=routine_hint,
        )

    return RoutineIntentResult(
        intent="general_chat",
        confidence=0.60,
        signals=["fallback_general"],
        matched_routine_hint=routine_hint,
    )
