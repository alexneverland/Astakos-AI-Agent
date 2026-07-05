import json
from services.gemini import safe_gemini_call
from core.utils import clean_message
from memory.routine_db import set_context_state
from datetime import datetime

_CONTEXT_EXTRACTION_PROMPT = """
Είσαι ο Αστακός, ένα AI assistant. Ο χρήστης (Λάζαρος) σου στέλνει ένα μήνυμα.
Πρέπει να καταλάβεις από τα συμφραζόμενα αν αλλάζει κάποια από τις παρακάτω καταστάσεις (Context Flags).

Διαθέσιμα flags:
1. "user_out_of_home": (boolean) Ο χρήστης είναι εκτός σπιτιού (π.χ. βόλτα, ψώνια, ταξίδι, μπάνιο).
2. "family_at_home": (boolean) Η οικογένεια είναι στο σπίτι.
3. "sofia_with_user": (boolean) Η σύζυγος (Σοφία) είναι ΜΑΖΙ με τον χρήστη τώρα. (π.χ. "είμαστε μαζί", "οικογενειακώς", "πάμε μπάνιο όλοι").
4. "alexandros_away_from_home": (boolean) Ο γιος (Αλέξανδρος) λείπει από το σπίτι μόνος του ή σε δραστηριότητα (και ΔΕΝ είναι με τον χρήστη). Αν είναι όλοι μαζί βόλτα, αυτό το flag δεν αλλάζει, ή είναι false.
5. "user_at_work": (boolean) Ο χρήστης είναι στη δουλειά του τώρα.

ΑΝ δεν μπορείς να συμπεράνεις με βεβαιότητα την κατάσταση για κάποιο flag, ΜΗΝ το συμπεριλάβεις στο JSON. 
Επέστρεψε ΜΟΝΟ ένα JSON object με τα flags που ΕΧΟΥΝ ΑΛΛΑΞΕΙ ή που ΕΠΙΒΕΒΑΙΩΝΟΝΤΑΙ ξεκάθαρα από το μήνυμα.

Παράδειγμα 1:
Μήνυμα: "Καλημέρα ξεκινήσαμε είμαστε στο δρόμο πάμε για μπάνιο. Έχει και περίοδο η Σοφία."
Απάντηση:
{{"user_out_of_home": true, "sofia_with_user": true, "family_at_home": false}}

Παράδειγμα 2:
Μήνυμα: "Έφτασα γραφείο τα λέμε"
Απάντηση:
{{"user_at_work": true, "user_out_of_home": true, "sofia_with_user": false}}

Παράδειγμα 3:
Μήνυμα: "Τι καιρό θα κάνει;"
Απάντηση:
{{}}

Μήνυμα Χρήστη: "{user_text}"
Απάντηση AI (πρόσφατη/τρέχουσα): "{ai_text}"
"""

def extract_and_update_context_flags(user_text: str, ai_text: str = ""):
    """
    Calls the LLM to extract context flags based on the user's message,
    and directly updates astakos_routines.db context states.
    """
    if not user_text or len(user_text.strip()) < 3:
        return

    prompt = _CONTEXT_EXTRACTION_PROMPT.format(user_text=user_text, ai_text=ai_text)
    
    try:
        response = safe_gemini_call(prompt)
        text = response.text if hasattr(response, "text") else str(response)
        cleaned = clean_message(text).strip()

        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start == -1 or end == -1 or end <= start:
            return # No JSON found
            
        payload = json.loads(cleaned[start:end + 1])
        
        # Validate and apply only known flags
        valid_keys = {
            "user_out_of_home", "family_at_home", 
            "sofia_with_user", "alexandros_away_from_home", 
            "user_at_work"
        }
        
        # Only update if the payload is a dictionary
        if not isinstance(payload, dict):
            return
            
        # Get current date for expiration of certain daily flags
        # Usually these states reset the next day, so we could set an expires_at to midnight,
        # but for now, we just set them. The existing rules or nightly reset will clear them.
        today_str = datetime.now().strftime("%Y-%m-%d")
            
        for key, value in payload.items():
            if key in valid_keys and isinstance(value, bool):
                # Save to database
                str_val = "true" if value else "false"
                set_context_state(key, str_val, expires_at=today_str)
                print(f"🤖 [ContextExtractor] Updated {key} = {str_val}")

    except Exception as exc:
        print(f"[ContextExtractor Error]: {exc}")
