"""High-confidence intent checks for the local meal-history workflow."""

from __future__ import annotations

import re
import unicodedata


_MEAL_REPORT_VERBS = frozenset({
    "φαγαμε", "εφαγαμε", "φαγα", "εφαγα", "φαγατε", "εφαγες",
    "μαγειρεψα", "μαγειρεψαμε", "μαγειρεψες", "εφτιαξα", "εφτιαξαμε",
})
_RECIPE_REQUEST_PHRASES = (
    "συνταγη", "ιδεα για φαγητο", "τι να φαμε", "τι να μαγειρεψ",
    "προτεινε", "προταση για φαγητο", "τι να φτιαξ",
)


def _normalize(text: str) -> str:
    """Normalize Greek accents and punctuation for conservative intent checks."""
    decomposed = unicodedata.normalize("NFD", str(text or "").lower())
    without_accents = "".join(
        char for char in decomposed if unicodedata.category(char) != "Mn"
    )
    return " ".join(re.findall(r"[^\W_]+", without_accents, flags=re.UNICODE))


def is_meal_report(text: str) -> bool:
    """Return whether a statement clearly reports a meal that was eaten/cooked."""
    if "?" in str(text or ""):
        return False
    return bool(set(_normalize(text).split()) & _MEAL_REPORT_VERBS)


def is_recipe_request(text: str) -> bool:
    """Return whether the user explicitly asks for a recipe or food suggestion."""
    normalized = _normalize(text)
    return any(phrase in normalized for phrase in _RECIPE_REQUEST_PHRASES)
