# ================================================================
# Project: Astakos AI Agent 🦞
# Developer: Lazaros (Piston-7)
# Description: Modular LLM-agnostic multi-agent framework
# Copyright (c) 2026 - All Rights Reserved
# ================================================================

import os
from dotenv import load_dotenv

# Φορτώνουμε τα απόρρητα από το .env μια και καλή
load_dotenv()
# Βρίσκει αυτόματα τον φάκελο στον οποίο βρίσκεται το project
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
# Βρίσκει αυτόματα πού βρίσκεται το project (absolute path)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

WORKSPACE_DIR = os.path.join(BASE_DIR, "astakos_skills")
PHOTOS_DIR = os.path.join(BASE_DIR, "telegram_photos")
CHROMA_DB_DIR = os.path.join(BASE_DIR, "chroma_db")

# Πατέντα: Αν δεν υπάρχουν οι φάκελοι, τους φτιάχνει αυτόματα μόλις τρέξει το project!
for directory in [WORKSPACE_DIR, PHOTOS_DIR, CHROMA_DB_DIR]:
    os.makedirs(directory, exist_ok=True)

# ==========================================
# 3. ΑΡΧΕΙΑ ΜΝΗΜΗΣ & JSON (PATHS)
# ==========================================
WORKING_MEMORY_FILE = os.path.join(BASE_DIR, "astakos_working_memory.json")
PHOTOS_INDEX_FILE = os.path.join(BASE_DIR, "astakos_photos_index.json")
EMBEDDINGS_CACHE_FILE = os.path.join(BASE_DIR, "astakos_embeddings_cache.json")
PROFILE_FILE = os.path.join(BASE_DIR, "astakos_profile.json")
SESSIONS_FILE = os.path.join(BASE_DIR, "astakos_sessions.json")
REMINDERS_FILE = os.path.join(BASE_DIR, "astakos_reminders.json")
LISTS_FILE = os.path.join(BASE_DIR, "astakos_lists.json")
CAPABILITIES_FILE = os.path.join(BASE_DIR, "astakos_capabilities.json")

# ==========================================
# 4. ΡΥΘΜΙΣΕΙΣ AI
# ==========================================
SIM_THRESHOLD_DISTANCE = 0.30
SIM_THRESHOLD = 0.88