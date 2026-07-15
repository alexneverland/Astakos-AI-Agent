# ================================================================
# Project: Astakos AI Agent 🦞
# Description: Gemini Service Handler (Multimodal Optimized)
# Copyright (c) 2026 - All Rights Reserved
# ================================================================

import time
from core.brain import llm
from core.utils import clean_message

class MastroResponse:
    """
    [MASTRO-RESPONSE v4]: Hybrid structure for full Multimodal support.
    Keeps '.text' as a string for compatibility with Firewalls/Sifters,
    but also keeps the original '.content' (list or dict) intact.
    """
    def __init__(self, content):
        # We keep the Google structure intact for future use (e.g., images/tools)
        self.content = content
        # We use the Smart Parser to ALWAYS have a clean string ready
        self.text = clean_message(content)

def safe_gemini_call(prompt: str, retries: int = 4, base_delay: float = 2.0):
    """
    Mastro-Shield v4: Exponential backoff retry for out-of-band helper 
    calls (Sifters, Firewalls) with full support for the new data structures.
    """
    for attempt in range(retries):
        try:
            # Execution of call via the unified brain (LangChain)
            response = llm.invoke(prompt)
            return MastroResponse(response.content)

        except Exception as e:
            err_str = str(e).lower()
            is_quota   = "429" in err_str or "quota" in err_str or "resource exhausted" in err_str
            is_server  = "500" in err_str or "503" in err_str or "502" in err_str
            is_timeout = any(t in err_str for t in (
                "timeout", "deadline", "transport", "connection refused",
                "connection reset", "remote disconnected", "eof occurred",
                "10060", "10054"
            ))

            if attempt >= retries - 1:
                print(f"\n\033[91m❌ [Gemini Fatal]: Crashed after {retries} attempts: {e}\033[0m")
                raise e

            if is_quota:
                wait = base_delay * (4 ** attempt)
                print(f"\033[93m⚠️ [Gemini 429]: Quota limit! Waiting {wait:.1f}s before attempt {attempt+2}/{retries}...\033[0m")
                time.sleep(wait)
            elif is_server or is_timeout:
                wait = base_delay * (2 ** attempt)
                print(f"\033[93m⚠️ [Gemini Server/Timeout]: Waiting {wait:.1f}s before attempt {attempt+2}/{retries}...\033[0m")
                time.sleep(wait)
            else:
                raise e