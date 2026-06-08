# ================================================================
# Project: Astakos AI Agent 🦞
# Developer: Lazaros (Piston-7)
# Description: Gemini Service Handler (Multimodal Optimized)
# Copyright (c) 2026 - All Rights Reserved
# ================================================================

import time
from core.brain import llm
from core.utils import clean_message

class MastroResponse:
    """
    [MASTRO-RESPONSE v4]: Υβριδική δομή για πλήρη Multimodal υποστήριξη.
    Διατηρεί το '.text' ως string για συμβατότητα με Firewalls/Sifters,
    αλλά κρατάει και το αυθεντικό '.content' (λίστα ή dict) ανέπαφο.
    """
    def __init__(self, content):
        # Κρατάμε τη δομή της Google αυτούσια για μελλοντική χρήση (π.χ. εικόνες/tools)
        self.content = content
        # Χρησιμοποιούμε τον Smart Parser για να έχουμε ΠΑΝΤΑ έτοιμο και ένα καθαρό string
        self.text = clean_message(content)

def safe_gemini_call(prompt: str, retries: int = 4, base_delay: float = 2.0):
    """
    Mastro-Shield v4: Exponential backoff retry για out-of-band βοηθητικές 
    κλήσεις (Sifters, Firewalls) με πλήρη υποστήριξη των νέων δομών δομών.
    """
    for attempt in range(retries):
        try:
            # Εκτέλεση κλήσης μέσω του ενοποιημένου εγκεφάλου (LangChain)
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
                print(f"\n\033[91m❌ [Gemini Fatal]: Κατέρρευσε μετά από {retries} προσπάθειες: {e}\033[0m")
                raise e

            if is_quota:
                wait = base_delay * (4 ** attempt)
                print(f"\033[93m⚠️ [Gemini 429]: Quota limit! Αναμονή {wait:.1f}s πριν τη δοκιμή {attempt+2}/{retries}...\033[0m")
                time.sleep(wait)
            elif is_server or is_timeout:
                wait = base_delay * (2 ** attempt)
                print(f"\033[93m⚠️ [Gemini Server/Timeout]: Αναμονή {wait:.1f}s πριν τη δοκιμή {attempt+2}/{retries}...\033[0m")
                time.sleep(wait)
            else:
                raise e