# ================================================================
# Project: Astakos AI Agent 🦞
# Developer: Lazaros (Piston-7)
# Description: Modular LLM-agnostic multi-agent framework
# Copyright (c) 2026 - All Rights Reserved
# ================================================================

import os
import json
import threading
from datetime import datetime
import sqlite3
from langchain_core.messages import HumanMessage
from config import WORKING_MEMORY_FILE, STATE_DB
from memory.vector_store import memory, is_semantically_duplicate, memory_lock  # [MASTRO-FIX]: ΕΝΑ lock, όχι δύο
from core.utils import clean_message

# ════════════════════════════════════════════════════════════════
# WORKING MEMORY — "Προσκήνιο" (τι κάνει ο Λάζαρος ΤΩΡΑ)
# ════════════════════════════════════════════════════════════════

def update_working_memory(user_text, ai_text):
    """Εξάγει ακαριαία context tags από τον διάλογο."""
    try:
        print("\033[90m[System]: Ξεκίνησε η ανάλυση Προσκηνίου...\033[0m")
        from core.brain import llm, safe_llm_invoke

        # Φοράμε τα "γυαλιά" (Smart Parser) πριν κόψουμε τους χαρακτήρες
        safe_user = clean_message(user_text)
        safe_ai = clean_message(ai_text)

        # Επιλέγουμε τους τελευταίους 400 χαρακτήρες
        user_context = safe_user[-400:] if len(safe_user) > 400 else safe_user
        ai_context = safe_ai[-400:] if len(safe_ai) > 400 else safe_ai

        prompt = f"""
Είσαι ο μηχανισμός μνήμης (Memory Sifter) του συστήματος.
Ανάλυσε τον παρακάτω διάλογο και εξήγαγε 1 έως 3 σύντομα tags (ετικέτες) που αφορούν αποκλειστικά:

1. Τι κάνει/θέλει ο Λάζαρος ΤΩΡΑ (π.χ. "Refactoring", "Αναζήτηση συνταγής").
2. Αποφάσεις / Συμφωνίες (π.χ. "Ασφάλεια: Ολοκληρώθηκε", "MastroApp: Παγωμένο").
3. Κόκκινες γραμμές / Τι ΔΕΝ θέλει να ξανακούσει (π.χ. "Όχι άλλη θεωρία").

ΑΥΣΤΗΡΟΙ ΚΑΝΟΝΕΣ ΕΞΟΔΟΥ:
- Απάντησε ΑΥΣΤΗΡΑ ΚΑΙ ΜΟΝΟ με τα tags χωρισμένα με κόμμα (π.χ. Tag1, Tag2, Tag3).
- ΑΠΑΓΟΡΕΥΕΤΑΙ οποιαδήποτε άλλη λέξη, εισαγωγή ή επεξήγηση.
- Αν ο Λάζαρος λέει απλώς λέξεις επιβεβαίωσης όπως "ΟΚ", "Ναι", "Έγινε", "Τέλεια", ή "Ευχαριστώ" χωρίς νέα πληροφορία, απάντησε ΜΟΝΟ με τη λέξη: ΚΕΝΟ.

ΔΙΑΛΟΓΟΣ ΓΙΑ ΑΝΑΛΥΣΗ:
Λάζαρος: {user_context}
Αστακός: {ai_context}
"""

        response = safe_llm_invoke(llm, [HumanMessage(content=prompt)])
        
        # [MASTRO-CLEAN]: Χρησιμοποιούμε τον Smart Parser ΚΑΙ στην έξοδο! 
        # Τέλος τα "isinstance(list)" και οι λούπες.
        new_tags = clean_message(response.content)

        print(f"\n\033[94m[DEBUG Προσκήνιο]: '{new_tags}'\033[0m")

        if "ΚΕΝΟ" in new_tags.upper() or not new_tags:
            print("Λάζαρος: ", end="", flush=True)
            return

        from memory.vector_store import memory # Φρόντισε να υπάρχει αυτό το import
        memory.save(memory_type="working", new_tags=new_tags)
        print(f"\033[92m[Προσκήνιο JSON]: ΓΡΑΦΤΗΚΕ -> {new_tags}\033[0m")
        print("Λάζαρος: ", end="", flush=True)

    except Exception as e:
        print(f"\n\033[91m[Working Memory Error]: {e}\033[0m")
        print("Λάζαρος: ", end="", flush=True)


# ════════════════════════════════════════════════════════════════
# CAPABILITIES LOG — "Αυτογνωσία"
# ════════════════════════════════════════════════════════════════

def _load_capabilities() -> dict:
    default = {"can_do": [], "cannot_do": []}
    conn = None
    try:
        conn = sqlite3.connect(STATE_DB)
        cursor = conn.cursor()
        cursor.execute("SELECT type, description FROM capabilities ORDER BY created_at ASC")
        rows = cursor.fetchall()
        for cap_type, desc in rows:
            if cap_type in ("can_do", "can"):
                default["can_do"].append(desc)
            elif cap_type in ("cannot_do", "cannot"):
                default["cannot_do"].append(desc)
        
        default["can_do"] = default["can_do"][-20:]
        default["cannot_do"] = default["cannot_do"][-20:]
    except Exception as e:
        print(f"Error loading capabilities: {e}")
    finally:
        if conn:
            conn.close()
    return default


def _save_capability(capability_type: str, description: str) -> str:
    # [MASTRO-FIX]: Χρήση του memory_lock από vector_store — ένα lock για όλα
    with memory_lock:
        data = _load_capabilities()
        conn = None
        try:
            conn = sqlite3.connect(STATE_DB)
            cursor = conn.cursor()

            if capability_type == "can":
                new_cannot_do = []
                for old_cap in data.get("cannot_do", []):
                    if not is_semantically_duplicate(description, [old_cap], threshold=0.80):
                        new_cannot_do.append(old_cap)
                    else:
                        cursor.execute(
                            "DELETE FROM capabilities WHERE type IN ('cannot_do', 'cannot') AND description=?",
                            (old_cap,),
                        )
                data["cannot_do"] = new_cannot_do
                key = "can_do"
                db_type = "can_do"
            else:
                key = "cannot_do"
                db_type = "cannot_do"

            # Threshold 0.88 ΟΚ για capabilities (γενικές ικανότητες)
            if is_semantically_duplicate(description, data[key], threshold=0.88):
                conn.commit()
                return "duplicate"

            cursor.execute("INSERT INTO capabilities (type, description) VALUES (?, ?)", (db_type, description))
            
            cursor.execute("SELECT id FROM capabilities WHERE type=? ORDER BY created_at DESC LIMIT -1 OFFSET 20", (db_type,))
            old_ids = cursor.fetchall()
            for (old_id,) in old_ids:
                cursor.execute("DELETE FROM capabilities WHERE id=?", (old_id,))

            conn.commit()
            return "inserted"
        except Exception as e:
            print(f"Error saving capability: {e}")
            return "error"
        finally:
            if conn:
                conn.close()
    return "error"


_USER_SUBJECT_MARKERS = (
    "ο λάζαρος", "ο λαζαρος", "η σοφία", "η σοφια", "ο αλέξανδρος", "ο αλεξανδρος",
    "του λάζαρου", "του λαζαρου", "της σοφίας", "της σοφιας", "του αλέξανδρου", "του αλεξανδρου",
    "τον γιο του", "το παιδί του", "το παιδι του", "την οικογένεια", "την οικογενεια",
)

_ASSISTANT_SUBJECT_MARKERS = (
    "ο αστακός", "ο αστακος", "το σύστημα", "το συστημα", "ο assistant",
    "δυνατότητα", "δυνατοτητα",
    "εργαλείο", "εργαλειο", "api", "tool", "pipeline",
)


def _looks_like_user_fact_not_capability(description: str) -> bool:
    """Prevent personal/family facts from being stored as Astakos capabilities."""
    text = str(description or "").strip().lower()
    if not text:
        return True
    if any(marker in text for marker in _ASSISTANT_SUBJECT_MARKERS):
        return False
    return any(marker in text for marker in _USER_SUBJECT_MARKERS)


def get_capability_context() -> str:
    data = _load_capabilities()
    parts = []
    if data.get("can_do"):
        can = [str(c) for c in data["can_do"][-5:]]
        parts.append("Γνωστές δυνατότητές μου: " + " | ".join(can))
    if data.get("cannot_do"):
        cannot = [str(c) for c in data["cannot_do"][-3:]]
        parts.append("Γνωστοί περιορισμοί μου: " + " | ".join(cannot))
    return "\n".join(parts) if parts else ""


def update_capabilities_from_exchange(user_text: str, ai_text: str, agent: str):
    import re
    import json
    try:
        cap_prompt = f"""
Ανάλυσε τη συνομιλία και εντόπισε ΝΕΕΣ ικανότητες ΤΟΥ ΑΣΤΑΚΟΥ (can_do) ή συγκεκριμένες αποτυχίες ΤΟΥ ΑΣΤΑΚΟΥ (cannot_do).
Απάντησε ΜΟΝΟ με JSON:
{{
  "can_do": "Σύντομη περιγραφή",
  "cannot_do": "Σύντομη περιγραφή"
}}
Αν δεν υπάρχει νέα πληροφορία, βάλε null.
ΠΡΟΣΟΧΗ: Γράψε τις προτάσεις γενικά, όχι για τη συγκεκριμένη στιγμή.
ΑΠΑΓΟΡΕΥΕΤΑΙ να γράψεις ως can_do/cannot_do πράγματα που κάνει, μπορεί ή έζησε ο Λάζαρος, η Σοφία, ο Αλέξανδρος ή η οικογένεια. Αυτά είναι USER_FACT, όχι αυτογνωσία.
Παραδείγματα που ΠΡΕΠΕΙ να είναι null:
- "Ο Λάζαρος μπορεί να πηγαίνει τον γιο του στο σχολείο"
- "Ο Αλέξανδρος ξεκινάει δημοτικό"
- "Η Σοφία είναι σπίτι"
Παραδείγματα έγκυρου can_do:
- "Ο Αστακός μπορεί να στέλνει μήνυμα Messenger μετά από approval"
- "Ο Αστακός μπορεί να αναζητά shared SQLite history και Chroma memories"

[Agent: {agent}]
Λάζαρος: {user_text[:500]}
Αστακός: {ai_text[:500]}
"""
        from services.gemini import safe_gemini_call
        response = safe_gemini_call(cap_prompt)
        
        resp_text = response.text if hasattr(response, 'text') else str(response)
        if not resp_text or resp_text.strip().lower() == "null":
            return
            
        raw = re.sub(r"```json|```", "", resp_text.strip()).strip()
        start = raw.find('{')
        end = raw.rfind('}')
        if start != -1 and end != -1:
            raw = raw[start:end+1]
            
        if raw.lower() == "null" or not raw:
            return
            
        data = json.loads(raw)

        if data.get("can_do") and str(data["can_do"]).lower() != "null":
            if _looks_like_user_fact_not_capability(data["can_do"]):
                print(f"\033[90m[Αυτογνωσία]: skip user fact, not can_do: {data['can_do']}\033[0m")
            else:
                result = _save_capability("can", data["can_do"])
                if result == "inserted":
                    print(f"\033[96m[Αυτογνωσία]: ✅ can_do: {data['can_do']}\033[0m")
                elif result == "duplicate":
                    print(f"\033[90m[Αυτογνωσία]: skip duplicate can_do: {data['can_do']}\033[0m")
            
        if data.get("cannot_do") and str(data["cannot_do"]).lower() != "null":
            if _looks_like_user_fact_not_capability(data["cannot_do"]):
                print(f"\033[90m[Αυτογνωσία]: skip user fact, not cannot_do: {data['cannot_do']}\033[0m")
            else:
                result = _save_capability("cannot", data["cannot_do"])
                if result == "inserted":
                    print(f"\033[91m[Αυτογνωσία]: ❌ cannot_do: {data['cannot_do']}\033[0m")
                elif result == "duplicate":
                    print(f"\033[90m[Αυτογνωσία]: skip duplicate cannot_do: {data['cannot_do']}\033[0m")
            
    except Exception as e:
        print(f"\033[90m[Αυτογνωσία Error]: {e}\033[0m")
