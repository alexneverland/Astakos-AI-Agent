# ================================================================
# Project: Astakos AI Agent 🦞
# Description: Modular LLM-agnostic multi-agent framework
# Copyright (c) 2026 - All Rights Reserved
# ================================================================

import os
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# ==========================================
# 1. CREDENTIALS & API KEYS
# ==========================================
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "vertex").lower()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY", "")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
EMAIL_ADDRESS = os.getenv("EMAIL_ADDRESS", "")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD", "")
VACUUM_IP = os.getenv("VACUUM_IP", "")
VACUUM_TOKEN = os.getenv("VACUUM_TOKEN", "")
LINKEDIN_TOKEN = os.getenv("LINKEDIN_TOKEN")
PROJECT_ID = os.getenv("PROJECT_ID", "your-gcp-project-id")
LOCATION = os.getenv("LOCATION", "us-central1")

# ==========================================
# 2. DIRECTORIES
# ==========================================
WORKSPACE_DIR     = os.path.join(BASE_DIR, "astakos_skills")
PHOTOS_DIR        = os.path.join(BASE_DIR, "telegram_photos")
CHROMA_DB_DIR     = os.path.join(BASE_DIR, "chroma_db")
UPLOADS_DIR       = os.path.join(BASE_DIR, "telegram_uploads")  # ← main uploads folder
MEMORY_AUDIT_DIR  = os.path.join(BASE_DIR, "logs", "memory_audit")
WATCH_DIR         = os.path.join(BASE_DIR, "watch_folder")
CREDENTIALS_DIR   = os.path.join(BASE_DIR, "credentials")
TOKEN_PATH        = os.path.join(CREDENTIALS_DIR, "token.json")
CREDENTIALS_PATH  = os.path.join(CREDENTIALS_DIR, "credentials.json")

for directory in [WORKSPACE_DIR, PHOTOS_DIR, CHROMA_DB_DIR, UPLOADS_DIR, MEMORY_AUDIT_DIR, WATCH_DIR, CREDENTIALS_DIR]:
    os.makedirs(directory, exist_ok=True)

# ==========================================
# 3. MEMORY FILES & JSON (PATHS)
# ==========================================
# All memory JSONs are in the ROOT folder (BASE_DIR)
WORKING_MEMORY_FILE  = os.path.join(BASE_DIR, "astakos_working_memory.json")
PHOTOS_INDEX_FILE    = os.path.join(BASE_DIR, "astakos_photos_index.json")
DOCS_INDEX_FILE      = os.path.join(BASE_DIR, "astakos_docs_index.json")    
EMBEDDINGS_CACHE_FILE= os.path.join(BASE_DIR, "astakos_embeddings_cache.json")  # legacy, unused
PROJECT_ACCESS_FILE  = os.path.join(BASE_DIR, "project_access.json")
EMBEDDINGS_CACHE_DB  = os.path.join(BASE_DIR, "astakos_embeddings_cache.db")
PROFILE_DB           = os.path.join(BASE_DIR, "astakos_profile.db")
ROUTINES_DB          = os.path.join(BASE_DIR, "astakos_routines.db")
SESSIONS_FILE        = os.path.join(BASE_DIR, "astakos_sessions.json")
CONVERSATION_DB_FILE = os.path.join(BASE_DIR, "astakos_conversation_history.db")
# GPS: Home coordinates for location reminders (reminders now live in STATE_DB)
# Coords moved to USER SETTINGS block
CAPABILITIES_FILE    = os.path.join(BASE_DIR, "astakos_capabilities.json")
MESSENGER_DRAFT_FILE = os.path.join(BASE_DIR, "messenger_draft.json")
MESSENGER_DRAFT_TTL_SECONDS = int(os.getenv("MESSENGER_DRAFT_TTL_SECONDS", "1800"))
LINKEDIN_DRAFT_FILE  = os.path.join(BASE_DIR, "linkedin_draft.json")

STATE_DB             = os.path.join(BASE_DIR, "astakos_state.db")

GPS_STORAGE_FILE     = os.path.join(BASE_DIR, "last_location.json")

# ==========================================
# 4. AI SETTINGS
# ==========================================
SIM_THRESHOLD_DISTANCE = 0.30
SIM_THRESHOLD          = 0.88

# ==========================================
# 5. ROUTINES SETTINGS
# ==========================================
# If the bot was offline and a routine was missed, it sends a deferred follow-up
# only if the missed trigger is not older than X minutes.
ROUTINE_MISS_GRACE_MINUTES = 90

import json
import logging

# ==========================================
# 6. USER SETTINGS
# ==========================================

PERSONA_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "persona.md")
USER_PERSONA = "• User"
if os.path.exists(PERSONA_FILE):
    with open(PERSONA_FILE, "r", encoding="utf-8") as f:
        USER_PERSONA = f.read().strip()

SETTINGS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "astakos_settings.json")
RESPONSE_LANGUAGE = "Greek" # Default fallback
USER_NAME = "User" # Default fallback
PARTNER_NAME = "Partner"
KID1_NAME = "Kid1"
KID2_NAME = "Kid2"
BOT_NAME = "Astakos"
DEVELOPER_NAME = "LocalUser"
DEFAULT_CITY = "London"
SENTIMENTAL_OVERRIDE_KEYWORDS = ()
SENTIMENTAL_CONTEXT_NOTE_PROBABILITY = 0.70
BACKUP_DRIVE_FOLDER_ID = ""
if os.path.exists(SETTINGS_FILE):
    try:
        with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
            _settings = json.load(f)
            RESPONSE_LANGUAGE = _settings.get("response_language", "Greek")
            USER_NAME = _settings.get("user_name", "User")
            PARTNER_NAME = _settings.get("partner_name", "Partner")
            KID1_NAME = _settings.get("kid1_name", "Kid1")
            KID2_NAME = _settings.get("kid2_name", "Kid2")
            BOT_NAME = _settings.get("bot_name", "Astakos")
            DEVELOPER_NAME = _settings.get("developer_name", "LocalUser")
            DEFAULT_CITY = _settings.get("default_city", "London")
            BACKUP_DRIVE_FOLDER_ID = _settings.get("backup_drive_folder_id", "")
            SENTIMENTAL_OVERRIDE_KEYWORDS = tuple(_settings.get("sentimental_override_keywords", []))
            try:
                SENTIMENTAL_CONTEXT_NOTE_PROBABILITY = min(
                    1.0,
                    max(
                        0.0,
                        float(
                            _settings.get(
                                "sentimental_context_note_probability",
                                SENTIMENTAL_CONTEXT_NOTE_PROBABILITY,
                            )
                        ),
                    ),
                )
            except (TypeError, ValueError):
                pass
    except Exception as e:
        print(f"⚠️ Error reading settings: {e}")

HOME_COORDS = tuple(_settings.get("home_coords", [0.0, 0.0])) if "_settings" in locals() else (0.0, 0.0)
HOME_RADIUS_M = _settings.get("home_radius_m", 150) if "_settings" in locals() else 150
WORK_COORDS = tuple(_settings.get("work_coords", [0.0, 0.0])) if "_settings" in locals() else (0.0, 0.0)
WORK_RADIUS_M = _settings.get("work_radius_m", 300) if "_settings" in locals() else 300

# ==========================================
# 7. NLP DICTIONARY (astakos_nlp.json)
# ==========================================
def _deep_merge_dicts(base: dict, custom: dict) -> dict:
    merged = dict(base)
    for key, value in custom.items():
        if isinstance(merged.get(key), dict) and isinstance(value, dict):
            merged[key] = _deep_merge_dicts(merged[key], value)
        elif isinstance(merged.get(key), list) and isinstance(value, list):
            merged[key] = list(dict.fromkeys(merged[key] + value))
        else:
            merged[key] = value
    return merged

def _load_nlp_config() -> dict:
    lang_code = "el" if RESPONSE_LANGUAGE.lower() == "greek" else "en"
    base_path = os.path.join(BASE_DIR, "core", f"intents_{lang_code}.json")
    custom_path = os.path.join(BASE_DIR, "astakos_custom_intents.json")
    legacy_path = os.path.join(BASE_DIR, "astakos_nlp.json")

    data = {}
    for path in (base_path, legacy_path, custom_path):
        if not os.path.exists(path):
            continue
        try:
            with open(path, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            data = _deep_merge_dicts(data, loaded)
        except Exception as e:
            print(f"⚠️ Error reading NLP config {path}: {e}")
    return data

NLP_CONFIG = _load_nlp_config()
# ==========================================
# 7. CONTEXT SCHEMA
# ==========================================
CONTEXT_SCHEMA_FILE = os.path.join(BASE_DIR, "astakos_context_schema.json")
CONTEXT_SCHEMA = {}
CANONICAL_CONTEXT_KEYS = set()

if os.path.exists(CONTEXT_SCHEMA_FILE):
    try:
        with open(CONTEXT_SCHEMA_FILE, "r", encoding="utf-8") as f:
            CONTEXT_SCHEMA = json.load(f)
            flags = CONTEXT_SCHEMA.get("flags", [])
            for flag in flags:
                if "key" in flag:
                    CANONICAL_CONTEXT_KEYS.add(flag["key"])
    except Exception as e:
        logging.error(f"Failed to load {CONTEXT_SCHEMA_FILE}: {e}")
        
if not CANONICAL_CONTEXT_KEYS:
    # Fallback default canonical keys if file is missing
    CANONICAL_CONTEXT_KEYS = {
        "user_out_of_home",
        "kid1_away_from_home",
        "family_at_home",
        "partner_with_user",
        "current_shift",
        "football_season"
    }
