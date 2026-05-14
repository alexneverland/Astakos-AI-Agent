import json
import os
from langchain_core.tools import tool

# Το αρχείο που θα σώζεται το draft
MEMORY_FILE = 'linkedin_draft.json'

@tool
def update_pending_linkedin_post(draft_text: str, photo_path: str) -> str:
    """Αποθηκεύει το draft του LinkedIn και το path της φωτό στο working_memory."""
    data = {}
    if os.path.exists(MEMORY_FILE):
        with open(MEMORY_FILE, 'r', encoding='utf-8') as f:
            try:
                data = json.load(f)
            except json.JSONDecodeError:
                pass
    
    data['pending_linkedin_post'] = {
        'text': draft_text,
        'photo_path': photo_path
    }
    
    with open(MEMORY_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=4, ensure_ascii=False)
    
    return "Το draft είναι έτοιμο και παρκαρισμένο, δώσε μου το ΟΚ να το ανεβάσω."

@tool
def process_and_clear_linkedin_post() -> str:
    """Διαβάζει το pending post, το δημοσιεύει στο LinkedIn και καθαρίζει τη μνήμη."""
    if not os.path.exists(MEMORY_FILE):
        return "Σφάλμα: Δεν υπάρχει αρχείο μνήμης."

    with open(MEMORY_FILE, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    post_data = data.get('pending_linkedin_post')
    
    if not post_data:
        return "Δεν υπάρχει εκκρεμές post για δημοσίευση."

    try:
        # [MASTRO-FIX 1]: Σωστό import του εργαλείου από το system.py!
        from tools.system import post_to_linkedin
        
        # [MASTRO-FIX 2]: Επειδή είναι @tool, το καλούμε με .invoke()
        post_to_linkedin.invoke({
            "text": post_data['text'], 
            "image_path": post_data.get('photo_path')
        })
    except Exception as e:
        return f"Σφάλμα κατά τη δημοσίευση: {e}"
    
    # Καθαρισμός
    del data['pending_linkedin_post']
    
    with open(MEMORY_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=4, ensure_ascii=False)
    
    return "Το post δημοσιεύτηκε επιτυχώς και η μνήμη καθαρίστηκε."