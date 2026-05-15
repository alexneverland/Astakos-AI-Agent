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
from langchain_core.messages import HumanMessage
from config import WORKING_MEMORY_FILE, CAPABILITIES_FILE
from memory.vector_store import memory, is_semantically_duplicate, memory_lock  # [MASTRO-FIX]: ΕΝΑ lock, όχι δύο


# ════════════════════════════════════════════════════════════════
# WORKING MEMORY — "Προσκήνιο" (τι κάνει ο Λάζαρος ΤΩΡΑ)
# ════════════════════════════════════════════════════════════════

def update_working_memory(user_text: str, ai_text: str):
    """Εξάγει ακαριαία context tags από τον διάλογο."""
    try:
        print("\033[90m[System]: Ξεκίνησε η ανάλυση Προσκηνίου...\033[0m")

        from core.brain import llm

        prompt = f"""
        Ανάλυσε τον διάλογο και βγάλε 1-2 πολύ σύντομα tags για το τρέχον context (τι κάνει ο χρήστης τώρα).
        Ακόμα κι αν είναι κάτι απλό (π.χ. "Ο Λάζαρος φτιάχνει καφέ", "Ο Λάζαρος κάνει διάλειμμα"), ΓΡΑΨΕ ΤΟ.
        Απάντησε ΜΟΝΟ με τα tags χωρισμένα με κόμμα. 
        Απάντησε "ΚΕΝΟ" ΜΟΝΟ αν ο χρήστης λέει σκέτο "ΟΚ", "Ναι", ή "Ευχαριστώ".
        Λάζαρος: {user_text[:200]}
        Αστακός: {ai_text[:200]}
        """

        response = llm.invoke([HumanMessage(content=prompt)])
        raw_content = response.content

        if isinstance(raw_content, list):
            parts = []
            for item in raw_content:
                if isinstance(item, dict) and 'text' in item:
                    parts.append(str(item['text']))
                elif isinstance(item, str):
                    parts.append(item)
            new_tags = " ".join(parts).strip()
        else:
            new_tags = str(raw_content).strip()

        print(f"\n\033[94m[DEBUG Προσκήνιο]: '{new_tags}'\033[0m")

        if "ΚΕΝΟ" in new_tags.upper() or not new_tags:
            print("Λάζαρος: ", end="", flush=True)
            return

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
    if not os.path.exists(CAPABILITIES_FILE):
        return default
    try:
        with open(CAPABILITIES_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        data["can_do"] = data.get("can_do", [])[-20:]
        data["cannot_do"] = data.get("cannot_do", [])[-20:]
        return data
    except:
        return default


def _save_capability(capability_type: str, description: str):
    # [MASTRO-FIX]: Χρήση του memory_lock από vector_store — ένα lock για όλα
    with memory_lock:
        data = _load_capabilities()

        if capability_type == "can":
            new_cannot_do = []
            for old_cap in data.get("cannot_do", []):
                if not is_semantically_duplicate(description, [old_cap], threshold=0.80):
                    new_cannot_do.append(old_cap)
            data["cannot_do"] = new_cannot_do
            key = "can_do"
        else:
            key = "cannot_do"

        # Threshold 0.88 ΟΚ για capabilities (γενικές ικανότητες)
        if is_semantically_duplicate(description, data[key], threshold=0.88):
            return

        data[key].append(description)
        data[key] = data[key][-20:]

        with open(CAPABILITIES_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)


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
Ανάλυσε τη συνομιλία και εντόπισε ΝΕΕΣ ικανότητες (can_do) ή συγκεκριμένες αποτυχίες (cannot_do).
Απάντησε ΜΟΝΟ με JSON:
{{
  "can_do": "Σύντομη περιγραφή",
  "cannot_do": "Σύντομη περιγραφή"
}}
Αν δεν υπάρχει νέα πληροφορία, βάλε null.
ΠΡΟΣΟΧΗ: Γράψε τις προτάσεις γενικά, όχι για τη συγκεκριμένη στιγμή.

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
        if raw.lower() == "null":
            return
            
        data = json.loads(raw)

        if data.get("can_do") and str(data["can_do"]).lower() != "null":
            _save_capability("can", data["can_do"])
            print(f"\033[96m[Αυτογνωσία]: ✅ can_do: {data['can_do']}\033[0m")
            
        if data.get("cannot_do") and str(data["cannot_do"]).lower() != "null":
            _save_capability("cannot", data["cannot_do"])
            print(f"\033[91m[Αυτογνωσία]: ❌ cannot_do: {data['cannot_do']}\033[0m")
            
    except Exception as e:
        print(f"\033[90m[Αυτογνωσία Error]: {e}\033[0m")