# ================================================================
# Project: Astakos AI Agent 🦞
# Developer: Lazaros (Piston-7)
# Description: Modular LLM-agnostic multi-agent framework
# Copyright (c) 2026 - All Rights Reserved
# ================================================================

import time
from google import genai
from config import GEMINI_API_KEY


def safe_gemini_call(prompt: str, retries: int = 4, base_delay: float = 2.0):
    """
    Mastro-Shield v2: Exponential backoff retry για το Gemini API.
    - 429 (quota)  → περιμένει περισσότερο
    - 5xx (server) → retry κανονικά
    - Άλλο error   → raise αμέσως
    """
    client = genai.Client(api_key=GEMINI_API_KEY)

    for attempt in range(retries):
        try:
            response = client.models.generate_content(
                model="gemini-3.1-flash-lite",
                contents=prompt
            )
            return response

        except Exception as e:
            err_str = str(e).lower()
            is_quota   = "429" in err_str or "quota" in err_str or "resource exhausted" in err_str
            is_server  = "500" in err_str or "503" in err_str or "502" in err_str
            is_timeout = "timeout" in err_str or "deadline" in err_str

            if attempt >= retries - 1:
                print(f"\033[91m❌ [Gemini Fatal]: Κατέρρευσε μετά από {retries} προσπάθειες: {e}\033[0m")
                raise e

            if is_quota:
                # Quota → πολύ μεγαλύτερη αναμονή
                wait = base_delay * (4 ** attempt)  # 8s, 32s, 128s...
                print(f"\033[93m⚠️ [Gemini 429]: Quota limit! Αναμονή {wait:.0f}s... ({attempt+1}/{retries})\033[0m")
            elif is_server or is_timeout:
                # Server error → exponential backoff
                wait = base_delay * (2 ** attempt)  # 2s, 4s, 8s...
                print(f"\033[93m⚠️ [Gemini Retry]: Server error ({e}). Αναμονή {wait:.0f}s... ({attempt+1}/{retries})\033[0m")
            else:
                # Άγνωστο error → raise αμέσως, μην χάνεις χρόνο
                print(f"\033[91m❌ [Gemini Error]: Μη αναμενόμενο σφάλμα: {e}\033[0m")
                raise e

            time.sleep(wait)