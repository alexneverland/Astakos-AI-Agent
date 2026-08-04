from core.i18n import t
import os
import json
import config

_intents = None


def _load_base_intents(language_code: str) -> dict:
    """Load one bundled intent catalog without applying the user-specific overlay."""
    base_intents_path = os.path.join(
        os.path.dirname(__file__),
        f"intents_{language_code}.json",
    )
    try:
        with open(base_intents_path, "r", encoding="utf-8") as file:
            return json.load(file)
    except Exception as error:
        print(t("core.nl_config.error_loading", e=error))
        return {}


def _deep_merge_dicts(base: dict, custom: dict) -> dict:
    """Deep merges custom dict into base dict. For lists, extends the base list."""
    merged = base.copy()
    for key, value in custom.items():
        if key in merged:
            if isinstance(merged[key], dict) and isinstance(value, dict):
                merged[key] = _deep_merge_dicts(merged[key], value)
            elif isinstance(merged[key], list) and isinstance(value, list):
                # Using a set to avoid exact duplicates while preserving order via list
                merged[key] = list(dict.fromkeys(merged[key] + value))
            else:
                merged[key] = value
        else:
            merged[key] = value
    return merged

def load_intents() -> dict:
    global _intents
    if _intents is None:
        lang_code = "el" if config.RESPONSE_LANGUAGE.lower() == "greek" else "en"
        custom_intents_path = config.get_custom_intents_path()
        _intents = _load_base_intents(lang_code)
            
        if os.path.exists(custom_intents_path):
            try:
                with open(custom_intents_path, "r", encoding="utf-8") as f:
                    custom_intents = json.load(f)
                _intents = _deep_merge_dicts(_intents, custom_intents)
            except Exception as e:
                print(f"Error loading custom intents: {e}")
                
    return _intents

def get_intent_list(module: str, key: str) -> list:
    intents = load_intents()
    return intents.get(module, {}).get(key, [])


def get_live_input_guard_list(module: str, key: str) -> list:
    """Return deduplicated bundled-language and custom markers for live input guards."""
    markers = []
    for language_code in ("el", "en"):
        markers.extend(
            _load_base_intents(language_code).get(module, {}).get(key, [])
        )
    markers.extend(get_intent_list(module, key))
    return list(
        dict.fromkeys(
            marker for marker in markers if isinstance(marker, str) and marker
        )
    )


def get_intent_dict(module: str, key: str) -> dict:
    intents = load_intents()
    return intents.get(module, {}).get(key, {})

def get_utils_intents():
    return load_intents().get("utils", {})

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

PLAN_JUDGE_SEQUENCE_WORDS = tuple(get_intent_list("plan_judge", "sequence_words"))
PLANNER_FAILURE_WORDS = tuple(get_intent_list("planner", "failure_words"))
LOOP_GUARD_INSTANT_WORDS = tuple(get_intent_list("tool_loop_guard", "instant_notification_words"))

# Context Builder
CB_YESTERDAY_WORDS = tuple(get_intent_list("context_builder", "yesterday_words"))
CB_MORNING_WORDS = tuple(get_intent_list("context_builder", "morning_words"))
CB_KID1_WORDS = tuple(get_intent_list("context_builder", "kid1_words"))
CB_SOCCER_WORDS = tuple(get_intent_list("context_builder", "soccer_words"))
CB_PARTNER_GIFT_WORDS = tuple(get_intent_list("context_builder", "partner_gift_words"))
CB_PARTNER_GIFT_CONTEXT = tuple(get_intent_list("context_builder", "partner_gift_context"))
CB_UTILITY_MARKERS = tuple(get_intent_list("context_builder", "utility_markers"))
CB_MEMORY_MARKERS = tuple(load_intents().get("context_builder", {}).get("memory_correction", {}).get("memory_markers", []))
CB_FIXUP_MARKERS = tuple(load_intents().get("context_builder", {}).get("memory_correction", {}).get("fixup_markers", []))
CB_FOOD_REGEX = load_intents().get('context_builder', {}).get('food_regex', rf'\b{t("core.nl_config.food_regex_ti")}\b.*\b{t("core.nl_config.food_regex_fag")}[\w]*')
CB_REMINDER_CONTAINS = tuple(get_intent_list('context_builder', 'reminder_contains'))
CB_REMINDER_STARTS = tuple(get_intent_list('context_builder', 'reminder_starts'))
CB_DIRECT_WEB_RESEARCH_MARKERS = tuple(
    marker.strip().lower()
    for marker in get_intent_list(
        "context_builder",
        "direct_web_research_markers",
    )
    if isinstance(marker, str) and marker.strip()
)


# Force preload on import
load_intents()

# Context Extractor Intents
CE_IN_A_WHILE = tuple(get_intent_list('context_extractor', 'in_a_while_words'))
CE_LEAVING = tuple(get_intent_list('context_extractor', 'leaving_words'))
CE_PARK = tuple(get_intent_list('context_extractor', 'park_words'))
CE_NOW_SITTING = tuple(get_intent_list('context_extractor', 'now_sitting_words'))
CE_FOUND_THEM = tuple(get_intent_list('context_extractor', 'found_them_words'))
CE_ALL_TOGETHER = tuple(get_intent_list('context_extractor', 'all_together_words'))
CE_FAMILY_GROUP = tuple(
    get_intent_list("context_extractor", "family_group_words")
)
CE_RETURN_TOGETHER = tuple(
    get_intent_list("context_extractor", "return_together_words")
)
CE_HOME = tuple(get_intent_list('context_extractor', 'home_words'))
CE_COMMUNICATION_VERBS = tuple(
    get_live_input_guard_list("context_extractor", "communication_verbs")
)
CE_STRONG_PRESENCE = tuple(
    get_live_input_guard_list("context_extractor", "strong_presence_phrases")
)
CE_PARTNER_NAMES = (config.PARTNER_NAME.lower(),) + tuple(get_intent_list('context_extractor', 'partner_names'))
CE_KID1_NAMES = (config.KID1_NAME.lower(),) + tuple(get_intent_list('context_extractor', 'kid1_names'))

# Working-memory operational guards
WM_ROUTINE_REFERENCE_MARKERS = tuple(
    get_live_input_guard_list("working_memory", "routine_reference_markers")
)
WM_ROUTINE_ADMIN_MARKERS = tuple(
    get_live_input_guard_list("working_memory", "routine_admin_markers")
)
WM_OPERATIONAL_AI_MARKERS = tuple(
    get_live_input_guard_list("working_memory", "operational_ai_markers")
)

# Routine Intents
RI_CONTROL_VERBS = tuple(get_intent_list('routine_intent', 'control_verbs'))
RI_ROUTINE_NOUNS = tuple(get_intent_list('routine_intent', 'routine_nouns'))
RI_TIME_CONDITION_WORDS = tuple(get_intent_list('routine_intent', 'time_condition_words'))
RI_COOLDOWN_RESET_WORDS = tuple(get_intent_list('routine_intent', 'cooldown_reset_words'))
RI_CONTEXT_UPDATE_PHRASES = tuple(get_intent_list('routine_intent', 'context_update_phrases'))
RI_FILLER_ACKS = tuple(get_intent_list('routine_intent', 'filler_acks'))
RI_STOP_WORDS = set(get_intent_list('routine_intent', 'stop_words'))
RI_FOLLOWUP_NEXT_DAY_WORDS = tuple(get_intent_list('routine_intent', 'followup_next_day_words'))
RI_FOLLOWUP_SAME_DAY_EVENING_WORDS = tuple(get_intent_list('routine_intent', 'followup_same_day_evening_words'))

# Messenger Intents
MI_COMPOSE_WORDS = tuple(get_intent_list('messenger_intent', 'compose_words'))
MI_SEND_APPROVAL_WORDS = tuple(get_intent_list('messenger_intent', 'send_approval_words'))
MI_DRAFT_OFFER_AFFIRMATIVES = tuple(get_live_input_guard_list('messenger_intent', 'draft_offer_affirmatives'))
MI_DRAFT_REQUEST_NEGATIONS = tuple(get_live_input_guard_list('messenger_intent', 'draft_request_negations'))
MI_DRAFT_REQUEST_ACTION_VERBS = tuple(get_live_input_guard_list('messenger_intent', 'draft_request_action_verbs'))
MI_DRAFT_REQUEST_OBJECTS = tuple(get_live_input_guard_list('messenger_intent', 'draft_request_objects'))
MI_CLARIFICATION_WORDS = tuple(get_intent_list('messenger_intent', 'clarification_words'))
MI_CLEANUP_WORDS = tuple(get_intent_list('messenger_intent', 'cleanup_words'))
MI_GENERAL_CHAT_SHORT = set(get_intent_list('messenger_intent', 'general_chat_short'))

# Routine Reconciler Intents
RR_STOPWORDS = set(get_intent_list('routine_reconciler', 'stopwords'))
RR_IN_DAYS_REGEX = load_intents().get('routine_reconciler', {}).get('in_days_regex', t("prompts.ext_s_d_1_2_s"))

# System Tool Intents
ST_FAMILY_MARKERS = tuple(get_intent_list('system_tool', 'family_markers'))
ST_PROJECT_MARKERS = tuple(get_intent_list('system_tool', 'project_markers'))
ST_HOME_MARKERS = tuple(get_intent_list('system_tool', 'home_markers'))
ST_LESSON_MARKERS = tuple(get_intent_list('system_tool', 'lesson_markers'))
ST_SHOPPING_MARKERS = tuple(get_intent_list('system_tool', 'shopping_markers'))
ST_MEMORY_STOP_WORDS = set(get_intent_list('system_tool', 'memory_stop_words'))
ST_REGEX_CLEANUP_PATTERNS = load_intents().get('system_tool', {}).get('regex_cleanup_patterns', {})
ST_ROUTINE_MANAGEMENT_TOKENS = tuple(get_intent_list('system_tool', 'routine_management_tokens'))

