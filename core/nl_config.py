import os
import json

_intents = None

def load_intents() -> dict:
    global _intents
    if _intents is None:
        intents_path = os.path.join(os.path.dirname(__file__), "intents.json")
        try:
            with open(intents_path, "r", encoding="utf-8") as f:
                _intents = json.load(f)
        except Exception as e:
            print(f"⚠️ Σφάλμα φόρτωσης intents.json: {e}")
            _intents = {}
    return _intents

def get_intent_list(module: str, key: str) -> list:
    """Επιστρέφει λίστα (list) keywords για το δοθέν module και key."""
    intents = load_intents()
    return intents.get(module, {}).get(key, [])

def get_intent_dict(module: str, key: str) -> dict:
    """Επιστρέφει λεξικό (dict) για το δοθέν module και key."""
    intents = load_intents()
    return intents.get(module, {}).get(key, {})

# Άμεσες μεταβλητές για το core/utils.py
def get_utils_intents():
    return load_intents().get("utils", {})

# Σταθερές για εύκολο import αν προτιμάται:
UTILS_FAST_PATH_BLOCKED_TOKENS = tuple(get_intent_list("utils", "fast_path_blocked_tokens"))
UTILS_MEDIUM_PATH_BLOCKED_TOKENS = tuple(get_intent_list("utils", "medium_path_blocked_tokens"))
UTILS_LOW_SIGNAL_STARTS = tuple(get_intent_list("utils", "low_signal_starts"))
UTILS_ULTRA_LIGHT_ACKS = set(get_intent_list("utils", "ultra_light_acks"))
UTILS_REFLECTIVE_STARTS = tuple(get_intent_list("utils", "reflective_starts"))
UTILS_ORDINAL_WORDS = get_intent_dict("utils", "ordinal_words")
UTILS_IGNORE_WORDS = set(get_intent_list("utils", "ignore_words"))
UTILS_SYSTEM_RESETS = tuple(get_intent_list("utils", "system_resets"))
UTILS_SELF_CAPABILITY_MARKERS = tuple(get_intent_list("utils", "self_capability_markers"))
UTILS_QTY_INTENTS = tuple(get_intent_list('utils', 'qty_intents'))


# Agent keywords
AGENT_TECH_KEYWORDS = get_intent_list("utils", "agent_keywords").get("TECH_KEYWORDS", []) if isinstance(get_intent_dict("utils", "agent_keywords"), dict) else []
# Actually, the JSON structure has them inside "agent_keywords" which is a dict. Let's fix that wrapper.
def _get_agent_keywords(agent_key):
    return get_intent_dict("utils", "agent_keywords").get(agent_key, [])

AGENT_TECH_KEYWORDS = _get_agent_keywords("TECH_KEYWORDS")
AGENT_HOME_KEYWORDS = _get_agent_keywords("HOME_KEYWORDS")
AGENT_WEB_KEYWORDS = _get_agent_keywords("WEB_KEYWORDS")
AGENT_MAIL_KEYWORDS = _get_agent_keywords("MAIL_KEYWORDS")
AGENT_GIT_KEYWORDS = _get_agent_keywords("GIT_KEYWORDS")
AGENT_DEV_KEYWORDS = _get_agent_keywords("DEV_KEYWORDS")

MESSENGER_APPROVAL_TOKENS = set(get_intent_dict("utils", "messenger_draft").get("approval_tokens", []))
MESSENGER_WORKFLOW_TOKENS = get_intent_dict("utils", "messenger_draft").get("is_workflow_tokens", [])
LINKEDIN_MARKERS = get_intent_dict("utils", "linkedin_draft").get("markers", [])
LINKEDIN_NEGATIONS = get_intent_dict("utils", "linkedin_draft").get("negations", [])

# Γρήγορη πρόσβαση για άλλα modules
PLAN_JUDGE_SEQUENCE_WORDS = tuple(get_intent_list("plan_judge", "sequence_words"))
PLANNER_FAILURE_WORDS = tuple(get_intent_list("planner", "failure_words"))
LOOP_GUARD_INSTANT_WORDS = tuple(get_intent_list("tool_loop_guard", "instant_notification_words"))

# Context Builder
CB_YESTERDAY_WORDS = tuple(get_intent_list("context_builder", "yesterday_words"))
CB_MORNING_WORDS = tuple(get_intent_list("context_builder", "morning_words"))
CB_ALEXANDROS_WORDS = tuple(get_intent_list("context_builder", "alexandros_words"))
CB_SOCCER_WORDS = tuple(get_intent_list("context_builder", "soccer_words"))
CB_SOFIA_GIFT_WORDS = tuple(get_intent_list("context_builder", "sofia_gift_words"))
CB_SOFIA_GIFT_CONTEXT = tuple(get_intent_list("context_builder", "sofia_gift_context"))
CB_UTILITY_MARKERS = tuple(get_intent_list("context_builder", "utility_markers"))
CB_MEMORY_MARKERS = tuple(load_intents().get("context_builder", {}).get("memory_correction", {}).get("memory_markers", []))
CB_FIXUP_MARKERS = tuple(load_intents().get("context_builder", {}).get("memory_correction", {}).get("fixup_markers", []))
CB_FOOD_REGEX = load_intents().get('context_builder', {}).get('food_regex', r'\bτι\b.*\bφαγ[α-ω]*')
CB_REMINDER_CONTAINS = tuple(get_intent_list('context_builder', 'reminder_contains'))
CB_REMINDER_STARTS = tuple(get_intent_list('context_builder', 'reminder_starts'))


# Force preload on import
load_intents()

# Context Extractor Intents
CE_IN_A_WHILE = tuple(get_intent_list('context_extractor', 'in_a_while_words'))
CE_LEAVING = tuple(get_intent_list('context_extractor', 'leaving_words'))
CE_PARK = tuple(get_intent_list('context_extractor', 'park_words'))
CE_NOW_SITTING = tuple(get_intent_list('context_extractor', 'now_sitting_words'))
CE_FOUND_THEM = tuple(get_intent_list('context_extractor', 'found_them_words'))
CE_ALL_TOGETHER = tuple(get_intent_list('context_extractor', 'all_together_words'))
CE_HOME = tuple(get_intent_list('context_extractor', 'home_words'))
CE_SOFIA_NAMES = tuple(get_intent_list('context_extractor', 'sofia_names'))
CE_ALEXANDROS_NAMES = tuple(get_intent_list('context_extractor', 'alexandros_names'))

# Routine Intents
RI_CONTROL_VERBS = tuple(get_intent_list('routine_intent', 'control_verbs'))
RI_ROUTINE_NOUNS = tuple(get_intent_list('routine_intent', 'routine_nouns'))
RI_TIME_CONDITION_WORDS = tuple(get_intent_list('routine_intent', 'time_condition_words'))
RI_COOLDOWN_RESET_WORDS = tuple(get_intent_list('routine_intent', 'cooldown_reset_words'))
RI_CONTEXT_UPDATE_PHRASES = tuple(get_intent_list('routine_intent', 'context_update_phrases'))
RI_FILLER_ACKS = tuple(get_intent_list('routine_intent', 'filler_acks'))
RI_STOP_WORDS = set(get_intent_list('routine_intent', 'stop_words'))

# Messenger Intents
MI_COMPOSE_WORDS = tuple(get_intent_list('messenger_intent', 'compose_words'))
MI_SEND_APPROVAL_WORDS = tuple(get_intent_list('messenger_intent', 'send_approval_words'))
MI_CLARIFICATION_WORDS = tuple(get_intent_list('messenger_intent', 'clarification_words'))
MI_CLEANUP_WORDS = tuple(get_intent_list('messenger_intent', 'cleanup_words'))
MI_GENERAL_CHAT_SHORT = set(get_intent_list('messenger_intent', 'general_chat_short'))

# Routine Reconciler Intents
RR_STOPWORDS = set(get_intent_list('routine_reconciler', 'stopwords'))
RR_IN_DAYS_REGEX = load_intents().get('routine_reconciler', {}).get('in_days_regex', r'(?:σε|για)\s+(\d{1,2})\s*(?:μερες|μέρες|ημερες|ημέρες)')

# System Tool Intents
ST_FAMILY_MARKERS = tuple(get_intent_list('system_tool', 'family_markers'))
ST_PROJECT_MARKERS = tuple(get_intent_list('system_tool', 'project_markers'))
ST_HOME_MARKERS = tuple(get_intent_list('system_tool', 'home_markers'))
ST_LESSON_MARKERS = tuple(get_intent_list('system_tool', 'lesson_markers'))
ST_SHOPPING_MARKERS = tuple(get_intent_list('system_tool', 'shopping_markers'))
ST_MEMORY_STOP_WORDS = set(get_intent_list('system_tool', 'memory_stop_words'))
ST_REGEX_CLEANUP_PATTERNS = load_intents().get('system_tool', {}).get('regex_cleanup_patterns', {})
ST_ROUTINE_MANAGEMENT_TOKENS = tuple(get_intent_list('system_tool', 'routine_management_tokens'))
