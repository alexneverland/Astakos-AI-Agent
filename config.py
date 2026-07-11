# ================================================================
# Project: Astakos AI Agent 🦞
# Developer: Lazaros (Piston-7)
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
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY", "")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
EMAIL_ADDRESS = os.getenv("EMAIL_ADDRESS", "")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD", "")
VACUUM_IP = os.getenv("VACUUM_IP", "")
VACUUM_TOKEN = os.getenv("VACUUM_TOKEN", "")
LINKEDIN_TOKEN = os.getenv("LINKEDIN_TOKEN")
PROJECT_ID = os.getenv("PROJECT_ID", "astakos-finall")
LOCATION = os.getenv("LOCATION", "us-central1")

# ==========================================
# 2. DIRECTORIES
# ==========================================
WORKSPACE_DIR     = os.path.join(BASE_DIR, "astakos_skills")
PHOTOS_DIR        = os.path.join(BASE_DIR, "telegram_photos")
CHROMA_DB_DIR     = os.path.join(BASE_DIR, "chroma_db")
UPLOADS_DIR       = os.path.join(BASE_DIR, "telegram_uploads")  # ← main uploads folder
MEMORY_AUDIT_DIR  = os.path.join(BASE_DIR, "logs", "memory_audit")

for directory in [WORKSPACE_DIR, PHOTOS_DIR, CHROMA_DB_DIR, UPLOADS_DIR, MEMORY_AUDIT_DIR]:
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

# ==========================================
# 6. USER SETTINGS
# ==========================================
SETTINGS_FILE = os.path.join(BASE_DIR, "astakos_settings.json")
RESPONSE_LANGUAGE = "Greek" # Default fallback
USER_NAME = "User" # Default fallback
SENTIMENTAL_OVERRIDE_KEYWORDS = ()
if os.path.exists(SETTINGS_FILE):
    try:
        with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
            _settings = json.load(f)
            RESPONSE_LANGUAGE = _settings.get("response_language", "Greek")
            USER_NAME = _settings.get("user_name", "User")
            SENTIMENTAL_OVERRIDE_KEYWORDS = tuple(_settings.get("sentimental_override_keywords", []))
    except Exception as e:
        print(f"⚠️ Error reading settings: {e}")

HOME_COORDS = tuple(_settings.get("home_coords", [40.646558, 22.939036])) if "_settings" in locals() else (40.646558, 22.939036)
HOME_RADIUS_M = _settings.get("home_radius_m", 150) if "_settings" in locals() else 150
WORK_COORDS = tuple(_settings.get("work_coords", [40.690914, 22.929607])) if "_settings" in locals() else (40.690914, 22.929607)
WORK_RADIUS_M = _settings.get("work_radius_m", 300) if "_settings" in locals() else 300

# ==========================================
# 7. NLP DICTIONARY (astakos_nlp.json)
# ==========================================
NLP_FILE = os.path.join(BASE_DIR, "astakos_nlp.json")
NLP_CONFIG = {}
if os.path.exists(NLP_FILE):
    try:
        with open(NLP_FILE, "r", encoding="utf-8") as f:
            NLP_CONFIG = json.load(f)
    except Exception as e:
        print(f"⚠️ Error reading NLP config: {e}")
