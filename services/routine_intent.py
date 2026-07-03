from __future__ import annotations

from dataclasses import dataclass, field
import re
import unicodedata


@dataclass
class RoutineIntentResult:
    intent: str
    confidence: float
    signals: list[str] = field(default_factory=list)
    matched_routine_hint: str | None = None


_MANUAL_VERB_PATTERNS = (
    "βαλε",
    "βγαλε",
    "αλλαξε",
    "σβησε",
    "παγωσε",
    "ξεπαγωσε",
    "σιγασε",
    "ενεργοποιησε",
    "απενεργοποιησε",
    "προσθεσε",
    "αφαιρεσε",
    "ρυθμισε",
    "κανε",
    "στειλ",
    "στελν",
    "μηδενισ",
    "reset",
)

_MANUAL_CONTROL_HINTS = (
    "ρουτιν",
    "υπενθυμι",
    "ειδοποιησ",
    "condition",
    "schedule",
    "ωρα",
    "μεχρι",
    "απο ",
    "να μην ενεργοποι",
    "να ενεργοποι",
    "οταν ",
    "μονο οταν",
    "καθε ",
    "cooldown",
    "να ξανασταλει",
    "να ξαναστειλει",
    "βγαλτο απο cooldown",
    "βγαλτο από cooldown",
)

_CONTEXT_PATTERNS = (
    "ειμαι",
    "ειμαστε",
    "ειναι",
    "θα ειμαι",
    "θα ειμαστε",
    "γυρισαμε",
    "γυρισε",
    "επεστρεψε",
    "φυγαμε",
    "εφυγε",
    "λειπει",
    "δεν εχει",
    "σταματησε",
    "ειναι καλοκαιρι",
    "ειμαστε εξω",
    "ειμαστε σπιτι",
    "θα παει",
    "δεν θα παει",
    "θα παμε",
    "δεν θα παμε",
    "απο αυριο",
    "αυτη την εβδομαδα",
)

_GENERAL_CHAT_SHORT = {
    "ναι", "οχι", "οκ", "οκευ", "εγινε", "καλα", "τελεια", "σωστα", "μμ", "χαχα"
}

_STOPWORDS = {
    "το", "τη", "την", "τα", "τον", "στη", "στο", "στις", "στην",
    "με", "και", "να", "σε", "για", "απο", "ως", "μια", "ενα",
}


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
