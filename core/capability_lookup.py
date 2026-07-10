# ================================================================
# Project: Astakos AI Agent 🦞
# Module:  Capability Registry Lookup
# First routing filter — keyword match before going to the LLM Supervisor.
# If a clear match is found → returns agent immediately.
# If not → None (LLM decides normally).
# ================================================================

import os
import json
import re

_REGISTRY_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "capability_registry.json")
_registry: list[dict] = []

_GIT_TRIGGERS = [
    "git commit",
    "git push",
    "git pull",
    "git log",
    "git status",
    "git diff",
    "git show",
    "git branch",
    "origin/main",
    "δες commit",
    "τελευταία commit",
    "τελευταία commits",
    "ιστορικό commit",
]

_LINKEDIN_CREATION = [
    "φτιάξε", "γράψε", "ανέβασε", "post", "ποστ",
    "δημιούργησε", "σκέψου", "βάλε", "φτιαξε",
]

_PLACE_SEARCH_ACTIONS = {
    "βρες", "βρεισ", "ψαξε", "ψάξε", "προτεινε", "πρότεινε", "δωσε", "δώσε",
}

_PLACE_SEARCH_NOUNS = {
    "μερος", "μέρος", "μαγαζι", "μαγαζί", "εστιατοριο", "εστιατόριο", "ταβερνα", "ταβέρνα",
    "ψαροταβερνα", "ψαροταβέρνα", "καφε", "καφέ", "μπαρ", "bar", "cafe", "restaurant",
}

_PLACE_SEARCH_QUALIFIERS = {
    "κοντα", "κοντά", "χαρτη", "χάρτη", "maps", "rating", "review", "reviews",
    "ησυχο", "ήσυχο", "παιδια", "παιδιά", "οικογενεια", "οικογένεια", "ρομαντικο", "ρομαντικό",
}


def _looks_like_place_search(msg: str) -> bool:
    tokens = set(re.findall(r"[^\W_]+", msg.lower(), flags=re.UNICODE))
    has_action = bool(tokens & _PLACE_SEARCH_ACTIONS)
    has_place_noun = bool(tokens & _PLACE_SEARCH_NOUNS)
    has_qualifier = bool(tokens & _PLACE_SEARCH_QUALIFIERS)
    return has_action and (has_place_noun or has_qualifier)

def _load_registry():
    global _registry
    if _registry:
        return
    try:
        with open(_REGISTRY_PATH, "r", encoding="utf-8") as f:
            _registry = json.load(f)
    except Exception as e:
        print(f"⚠️ [CapabilityRegistry] Αποτυχία φόρτωσης: {e}")
        _registry = []

def _normalize(text: str) -> str:
    return text.lower().strip()


def _matches_trigger(msg: str, trigger: str) -> bool:
    t = _normalize(trigger)
    # Word boundary only — we avoid substring matches (e.g., "git" inside "github")
    return bool(re.search(r'(?<!\w)' + re.escape(t) + r'(?!\w)', msg))

def lookup_agent(user_message: str) -> str | None:
    """
    Searches the registry for a keyword match.
    Returns the agent name (e.g., 'Home_Agent') or None if not found.

    Uses priority for disambiguation if there are multiple matches.
    """
    _load_registry()
    if not _registry:
        return None

    msg = _normalize(user_message)

    # LinkedIn check FIRST — override everything else
    if _matches_trigger(msg, "linkedin"):
        for ct in _LINKEDIN_CREATION:
            if _matches_trigger(msg, ct):
                print(f"🎯 [CapabilityRegistry]: 'linkedin+{ct}' → Web_Agent (linkedin_post)")
                return "Web_Agent"

    # Place-finding queries should prefer Web_Agent over generic food/home routing.
    if _looks_like_place_search(msg):
        print("🎯 [CapabilityRegistry]: place-search heuristic → Web_Agent (maps_places)")
        return "Web_Agent"

    for trigger in _GIT_TRIGGERS:
        if _matches_trigger(msg, trigger):
            print(f"🎯 [CapabilityRegistry]: '{trigger}' → Git_Agent (git_ops)")
            return "Git_Agent"

    matches = []

    for cap in _registry:
        triggers = cap.get("triggers", [])
        for trigger in triggers:
            # Check if the trigger exists as a word/phrase in the message
            if _matches_trigger(msg, trigger):
                matches.append({
                    "name":     cap["name"],
                    "agent":    cap["agent"],
                    "priority": cap.get("priority", 5),
                    "trigger":  trigger,
                })
                break  # One match per capability is enough

    if not matches:
        return None

    # If there are multiple matches, we take the one with the highest priority
    best = sorted(matches, key=lambda x: x["priority"], reverse=True)[0]
    print(f"🎯 [CapabilityRegistry]: '{best['trigger']}' → {best['agent']} ({best['name']})")
    return best["agent"]


def get_all_capabilities() -> list[dict]:
    """Returns all capabilities for debug/dashboard."""
    _load_registry()
    return _registry


def reload_registry():
    """Force reload — for hot-reloading without restart."""
    global _registry
    _registry = []
    _load_registry()
