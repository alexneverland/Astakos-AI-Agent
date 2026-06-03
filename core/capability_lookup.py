# ================================================================
# Project: Astakos AI Agent 🦞
# Module:  Capability Registry Lookup
# Πρώτο φίλτρο routing — keyword match πριν πάει στο LLM Supervisor.
# Αν βρει ξεκάθαρο match → επιστρέφει agent αμέσως.
# Αν όχι → None (LLM αποφασίζει κανονικά).
# ================================================================

import os
import json
import re

_REGISTRY_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "capability_registry.json")
_registry: list[dict] = []

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

def lookup_agent(user_message: str) -> str | None:
    """
    Ψάχνει στο registry για keyword match.
    Επιστρέφει agent name (π.χ. 'Home_Agent') ή None αν δεν βρει.

    Χρησιμοποιεί priority για disambiguation αν υπάρχουν πολλά matches.
    """
    _load_registry()
    if not _registry:
        return None

    msg = _normalize(user_message)
    matches = []

    for cap in _registry:
        triggers = cap.get("triggers", [])
        for trigger in triggers:
            t = _normalize(trigger)
            # Ελέγχουμε αν το trigger υπάρχει ως λέξη/φράση στο μήνυμα
            if re.search(r'\b' + re.escape(t) + r'\b', msg) or t in msg:
                matches.append({
                    "name":     cap["name"],
                    "agent":    cap["agent"],
                    "priority": cap.get("priority", 5),
                    "trigger":  trigger,
                })
                break  # Ένα match ανά capability αρκεί

    if not matches:
        return None

    # Αν υπάρχουν πολλά matches, παίρνουμε το υψηλότερο priority
    best = sorted(matches, key=lambda x: x["priority"], reverse=True)[0]
    print(f"🎯 [CapabilityRegistry]: '{best['trigger']}' → {best['agent']} ({best['name']})")
    return best["agent"]


def get_all_capabilities() -> list[dict]:
    """Επιστρέφει όλες τις capabilities για debug/dashboard."""
    _load_registry()
    return _registry


def reload_registry():
    """Force reload — για hot-reload χωρίς restart."""
    global _registry
    _registry = []
    _load_registry()
