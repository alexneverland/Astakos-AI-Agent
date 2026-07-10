import json
import os
from langchain_core.tools import tool
from config import LINKEDIN_DRAFT_FILE

MEMORY_FILE = LINKEDIN_DRAFT_FILE

@tool
def update_pending_linkedin_post(draft_text: str, photo_path: str = "") -> str:
    """Saves the LinkedIn post draft. photo_path is optional — if the image failed, save without it and stop."""
    data = {}
    if os.path.exists(MEMORY_FILE):
        with open(MEMORY_FILE, 'r', encoding='utf-8') as f:
            try:
                data = json.load(f)
            except json.JSONDecodeError:
                pass
    
    data["text"] = draft_text
    data["content"] = draft_text
    data["image_path"] = photo_path
    data['pending_linkedin_post'] = {
        'text': draft_text,
        'photo_path': photo_path
    }
    
    with open(MEMORY_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=4, ensure_ascii=False)
    payload = {
        "status": "success",
        "kind": "linkedin_draft_saved",
        "draft_text": draft_text,
        "photo_path": photo_path or "",
    }
    return "SUCCESS_JSON:" + json.dumps(payload, ensure_ascii=False)

@tool
def process_and_clear_linkedin_post() -> str:
    """Reads the pending post, publishes it to LinkedIn, and clears the memory."""
    if not os.path.exists(MEMORY_FILE):
        return "Σφάλμα: Δεν υπάρχει αρχείο μνήμης."

    with open(MEMORY_FILE, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    post_data = data.get('pending_linkedin_post')
    
    if not post_data:
        return "Δεν υπάρχει εκκρεμές post για δημοσίευση."

    try:
        # [MASTRO-FIX 1]: Correct import of the tool from system.py!
        from tools.system import post_to_linkedin
        
        # [MASTRO-FIX 2]: Since it is a @tool, we call it with .invoke()
        result = post_to_linkedin.invoke({
            "text": post_data['text'], 
            "image_path": post_data.get('photo_path')
        })
        if isinstance(result, str) and result.strip().startswith("❌"):
            return result
    except Exception as e:
        return f"Σφάλμα κατά τη δημοσίευση: {e}"
    
    # Cleanup
    data.pop('pending_linkedin_post', None)
    data.pop('text', None)
    data.pop('content', None)
    data.pop('image_path', None)
    
    with open(MEMORY_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=4, ensure_ascii=False)
    
    return "Το post δημοσιεύτηκε επιτυχώς και η μνήμη καθαρίστηκε."
