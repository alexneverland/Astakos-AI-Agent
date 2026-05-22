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
PROJECT_ID = os.getenv("PROJECT_ID", "gen-lang-client-0647896431")
LOCATION = os.getenv("LOCATION", "us-central1")

# ==========================================
# 2. ΦΑΚΕΛΟΙ (DIRECTORIES)
# ==========================================
WORKSPACE_DIR     = os.path.join(BASE_DIR, "astakos_skills")
PHOTOS_DIR        = os.path.join(BASE_DIR, "telegram_photos")
CHROMA_DB_DIR     = os.path.join(BASE_DIR, "chroma_db")
UPLOADS_DIR       = os.path.join(BASE_DIR, "telegram_uploads")  # ← κεντρικός uploads φάκελος

for directory in [WORKSPACE_DIR, PHOTOS_DIR, CHROMA_DB_DIR, UPLOADS_DIR]:
    os.makedirs(directory, exist_ok=True)

# ==========================================
# 3. ΑΡΧΕΙΑ ΜΝΗΜΗΣ & JSON (PATHS)
# ==========================================
# Όλα τα JSON μνήμης είναι στον ROOT φάκελο (BASE_DIR)
WORKING_MEMORY_FILE  = os.path.join(BASE_DIR, "astakos_working_memory.json")
PHOTOS_INDEX_FILE    = os.path.join(BASE_DIR, "astakos_photos_index.json")
DOCS_INDEX_FILE      = os.path.join(BASE_DIR, "astakos_docs_index.json")    
EMBEDDINGS_CACHE_FILE= os.path.join(BASE_DIR, "astakos_embeddings_cache.json")
PROFILE_FILE         = os.path.join(BASE_DIR, "astakos_profile.json")
SESSIONS_FILE        = os.path.join(BASE_DIR, "astakos_sessions.json")
REMINDERS_FILE       = os.path.join(BASE_DIR, "astakos_reminders.json")
# GPS: Συντεταγμένες σπιτιού για location reminders
HOME_COORDS   = (40.646558, 22.939036)   # Piston 7 — διόρθωσε αν χρειαστεί
HOME_RADIUS_M = 150                   # trigger εντός 150 μέτρων
LISTS_FILE           = os.path.join(BASE_DIR, "astakos_lists.json")
CAPABILITIES_FILE    = os.path.join(BASE_DIR, "astakos_capabilities.json")
LINKEDIN_DRAFT_FILE  = os.path.join(BASE_DIR, "linkedin_draft.json")
GPS_STORAGE_FILE     = os.path.join(BASE_DIR, "last_location.json")

# ==========================================
# 4. ΡΥΘΜΙΣΕΙΣ AI
# ==========================================
SIM_THRESHOLD_DISTANCE = 0.30
SIM_THRESHOLD          = 0.88