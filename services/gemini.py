import re
import time
from google import genai
from config import GEMINI_API_KEY


def safe_gemini_call(prompt: str, retries: int = 3, delay: int = 2):
    """Mastro-Shield: Εκτελεί κλήσεις στο Gemini API με αυτόματο Retry σε περίπτωση αποτυχίας."""
    api_key = GEMINI_API_KEY
    client = genai.Client(api_key=api_key)

    for attempt in range(retries):
        try:
            response = client.models.generate_content(model="gemini-3.1-flash-lite", contents=prompt)
            return response
        except Exception as e:
            if attempt < retries - 1:
                print(f"\033[93m⚠️ [API Retry]: Λόξυγγας στο Gemini ({e}). Προσπάθεια {attempt+2}/{retries} σε {delay}s...\033[0m")
                time.sleep(delay)
            else:
                print(f"\033[91m❌ [API Fatal]: Το Gemini κατέρρευσε μετά από {retries} προσπάθειες.\033[0m")
                raise e