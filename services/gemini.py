# ================================================================
# Project: Astakos AI Agent 🦞
# Developer: Lazaros (Piston-7)
# Description: Modular LLM-agnostic multi-agent framework
# Copyright (c) 2026 - All Rights Reserved
# ================================================================

import time
from core.brain import llm
from core.utils import clean_message  # [MASTRO-FIX]: Φέρνουμε την ασπίδα εδώ!

class MastroResponse:
    """
    [MASTRO-WRAPPER]
    Wrapper που προσομοιώνει τη δομή του native GenAI SDK response.
    Εξασφαλίζει ότι το property '.text' θα είναι ΠΑΝΤΑ καθαρό string, 
    αποτρέποντας τα 'list object has no attribute strip' σε όλο το σύστημα.
    """
    def __init__(self, text):
        # [MASTRO-FIX]: Ό,τι και να στείλει η Google (λίστα, dict, null), 
        # το clean_message το κάνει πεντακάθαρο string.
        self.text = clean_message(text)

def safe_gemini_call(prompt: str, retries: int = 4, base_delay: float = 2.0):
    """
    Mastro-Shield v3: Exponential backoff retry που χρησιμοποιεί κεντρικά 
    το llm object του brain.py.
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
            is_timeout = "timeout" in err_str or "deadline" in err_str

            if attempt >= retries - 1:
                print(f"\n\033[91m❌ [Gemini Fatal]: Κατέρρευσε μετά από {retries} προσπάθειες: {e}\033[0m")
                raise e

            if is_quota:
                wait = base_delay * (4 ** attempt)
                print(f"\033[93m⚠️ [Gemini 429]: Quota limit! Αναμονή {wait:.0f}s... ({attempt+1}/{retries})\033[0m")
            elif is_server or is_timeout:
                wait = base_delay * (2 ** attempt)
                print(f"\033[93m⚠️ [Gemini 5xx]: Server error. Αναμονή {wait:.0f}s... ({attempt+1}/{retries})\033[0m")
            else:
                print(f"\033[91m❌ [Gemini Error]: Άγνωστο σφάλμα: {e}\033[0m")
                raise e

            time.sleep(wait)