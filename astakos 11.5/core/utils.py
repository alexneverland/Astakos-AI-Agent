# ================================================================
# Project: Astakos AI Agent 🦞
# Developer: Lazaros (Piston-7)
# Description: Modular LLM-agnostic multi-agent framework
# Copyright (c) 2026 - All Rights Reserved
# ================================================================

import re
import json
import os
import threading
from datetime import datetime
from typing import Annotated
from typing_extensions import TypedDict, NotRequired
from langgraph.graph.message import add_messages
from langchain_core.messages import HumanMessage, ToolMessage

# ────────────────────────────────────────────────────────────────
# 1. STATE & TYPES
# ────────────────────────────────────────────────────────────────

class AgentState(TypedDict):
    """Το State που μοιράζονται όλοι οι Agents."""
    messages: Annotated[list, add_messages]
    next_agent: NotRequired[str]
    current_agent: NotRequired[str]

# ────────────────────────────────────────────────────────────────
# 2. MESSAGE HELPERS (Mastro-Shield)
# ────────────────────────────────────────────────────────────────

def clean_message(msg_content):
    """Μετατρέπει ΠΑΝΤΑ σε κείμενο (Υποστήριξη Gemini 3.1 Multimodal)."""
    if msg_content is None: 
        return ""
    if isinstance(msg_content, str): 
        return msg_content.strip()
    
    if isinstance(msg_content, list):
        parts = []
        for item in msg_content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                # Παίρνουμε το 'text', αγνοούμε τα multimodal extras
                val = item.get("text", "")
                if val: parts.append(str(val))
        return " ".join(parts).strip()
    
    return str(msg_content).strip()

def filter_messages(messages: list, k: int = 40) -> list:
    """
    Mastro-Shield v2: Καθαρίζει το ιστορικό από σφάλματα που σπάνε το Gemini API.
    
    Κανόνες:
    1. Αφαιρεί κενά ToolMessages
    2. Αφαιρεί κενά AI μηνύματα χωρίς tool_calls
    3. [ΚΡΙΣΙΜΟ] Αφαιρεί AI μηνύματα με tool_calls αν ΔΕΝ ακολουθεί ToolMessage
       (αλλιώς το Gemini πετάει 400 INVALID_ARGUMENT)
    """
    if not messages:
        return []

    safe_list = list(messages[-k:])
    cleaned_list = []

    # Πρώτο πέρασμα: βασικός καθαρισμός
    for msg in safe_list:
        msg_type = getattr(msg, "type", "")

        if msg_type == "tool":
            if not msg.content or str(msg.content).strip() == "":
                msg = ToolMessage(
                    content="System Error: Το εργαλείο δεν επέστρεψε δεδομένα.",
                    tool_call_id=msg.tool_call_id,
                    name=getattr(msg, "name", "unknown")
                )
            cleaned_list.append(msg)

        elif msg_type == "ai":
            if not msg.content and not getattr(msg, "tool_calls", None):
                continue  # Αδειο AI μήνυμα — πέταξέ το
            cleaned_list.append(msg)

        else:
            cleaned_list.append(msg)

    # Δεύτερο πέρασμα: [MASTRO-FIX] Αφαίρεση "ορφανών" tool_calls
    # Το Gemini απαιτεί: AIMessage(tool_calls) → ToolMessage(s) → AIMessage
    # Αν λείπει το ToolMessage μετά από tool_calls, σκάει με 400.
    final_list = []
    i = 0
    while i < len(cleaned_list):
        msg = cleaned_list[i]
        msg_type = getattr(msg, "type", "")
        tool_calls = getattr(msg, "tool_calls", None)

        if msg_type == "ai" and tool_calls:
            # Ελέγχουμε αν υπάρχει ToolMessage αμέσως μετά
            has_tool_response = (
                i + 1 < len(cleaned_list) and
                getattr(cleaned_list[i + 1], "type", "") == "tool"
            )
            if not has_tool_response:
                # Ορφανό tool_call — μετατρέπουμε σε απλό AI μήνυμα
                # κρατώντας το content αν υπάρχει, αλλιώς το παρακάμπτουμε
                if msg.content:
                    from langchain_core.messages import AIMessage
                    final_list.append(AIMessage(content=clean_message(msg.content)))
                # Αν δεν έχει content, το πετάμε τελείως
                i += 1
                continue

        final_list.append(msg)
        i += 1

    # Αν ξεκινά με ToolMessage (χωρίς προηγούμενο AI), κόψε το
    while final_list and getattr(final_list[0], "type", "") == "tool":
        final_list.pop(0)

    return final_list

# ────────────────────────────────────────────────────────────────
# 3. PROMPT LOADING ENGINE
# ────────────────────────────────────────────────────────────────

def load_agent_prompt(agent_name: str, default_fallback: str = "") -> str:
    """Διαβάζει οδηγίες από το prompts.json."""
    try:
        core_dir = os.path.dirname(os.path.abspath(__file__))
        json_path = os.path.join(core_dir, "prompts.json")
        if not os.path.exists(json_path):
            return default_fallback
            
        with open(json_path, "r", encoding="utf-8") as f:
            prompts = json.load(f)
        return prompts.get(agent_name, default_fallback)
    except Exception as e:
        print(f"⚠️ Error loading prompt {agent_name}: {e}")
        return default_fallback

# ────────────────────────────────────────────────────────────────
# 4. THE BRAIN (Build Prompt)
# ────────────────────────────────────────────────────────────────

def build_prompt(state_messages, agent_role="") -> str:
    """
    Η κεντρική μηχανή σύνθεσης Prompt - Αναβαθμισμένη για προτεραιότητα Vision.
    """
    from config import WORKING_MEMORY_FILE, BASE_DIR
    from memory.vector_store import vector_store, vector_lock
    from memory.working_memory import get_capability_context
    from memory.session_memory import load_last_session_hint
    import os
    import json

    # 1. Προετοιμασία Ταυτότητας
    identity = load_agent_prompt("identity_block", "Είσαι ο Αστακός, ο AI συνεργάτης του Λάζαρου.")
    identity = identity.replace("{BASE_DIR}", BASE_DIR)

    # 2. Ανίχνευση Vision Context
    last_msg = clean_message(state_messages[-1].content) if state_messages else ""
    is_vision = "[ΟΠΤΙΚΗ ΑΝΑΛΥΣΗ]" in last_msg or "[CURRENT_PHOTO_PATH]" in last_msg
    has_current_photo = "[CURRENT_PHOTO_PATH]" in last_msg
    
# 3. Similarity Search (Mastro-Logic)
    memories_str = ""
    clean_text = last_msg.strip().lower()
    
    # [MASTRO-FIX]: Εμπλουτισμένη λίστα για κοφτές εντολές
    ignore_words = [
        "ναι", "όχι", "οχι", "οκ", "ok", "έγινε", "εγινε", "καλά", "τέλεια", 
        "ευχαριστώ", "γεια", "σωστά", "ναι αρχειοθέτησε", "αρχειοθέτησέ το", 
        "ναι σώστο", "σώστο", "αποθήκευσέ το", "ναι αποθήκευσε", "προχωράμε",
        "αρχειοθέτηση", "σώσε το"
    ]

    # Αν έχουμε ΤΩΡΙΝΗ φωτογραφία, ΜΗΝ ψάχνεις μνήμες — ο agent βλέπει ήδη τα πάντα
    # Αν βλέπουμε εικόνα (χωρίς current photo), μειώνουμε k=3
    k_value = 0 if has_current_photo else (3 if is_vision else 8)

    # Έξυπνο φίλτρο: Αγνοεί το search αν το κείμενο είναι στη λίστα ή ξεκινάει με "ναι"/"όχι"
    is_routine_command = clean_text in ignore_words or clean_text.startswith(("ναι ", "οχι ", "όχι "))

    # Ψάχνουμε ΜΟΝΟ αν δεν είναι εντολή ρουτίνας, και οι χαρακτήρες είναι > 10
    if k_value > 0 and len(clean_text) > 10 and not is_routine_command:
        try:
            with vector_lock:
                results = vector_store.similarity_search(last_msg, k=k_value)
                if results:
                    memories_str = "\n📜 ═══ ΙΣΤΟΡΙΚΟ ΑΡΧΕΙΟ ΜΝΗΜΗΣ (Παλιές Αναμνήσεις) ═══\n"
                    for res in results:
                        memories_str += f" • {res.page_content}\n"
                    memories_str += "⚠️ Σημείωση: Τα παραπάνω είναι αναμνήσεις, όχι η τρέχουσα κατάσταση.\n"
        except Exception as e:
            print(f"⚠️ Memory Search Error: {e}")

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")

    # 4. Σύνθεση του Βασικού Prompt με Κανόνα Πραγματικότητας
    prompt = f"{identity}\n"
    prompt += f"Σήμερα: {now_str}.\n"
    prompt += f"ΡΟΛΟΣ ΤΩΡΑ: {agent_role}\n\n"

    # Εμβόλιμος Κανόνας αν υπάρχει Vision
    if is_vision:
        prompt += (
            "🚨 ΚΑΝΟΝΑΣ ΠΡΑΓΜΑΤΙΚΟΤΗΤΑΣ (CRITICAL):\n"
            "Αυτή τη στιγμή έχεις μπροστά σου μια ΟΠΤΙΚΗ ΑΝΑΛΥΣΗ. Αυτή είναι η ΤΩΡΙΝΗ πραγματικότητα.\n"
            "Αν οι παλιές μνήμες (π.χ. για κύπελλα ποδοσφαίρου) έρχονται σε σύγκρουση με αυτό που βλέπεις (π.χ. τριανταφυλλιές),\n"
            "ΠΡΕΠΕΙ να αγνοήσεις το ιστορικό αρχείο και να εστιάσεις ΜΟΝΟ στην εικόνα.\n\n"
        )

    # 5. Προσθήκη Context από προηγούμενες συνεδρίες
    session_hint = load_last_session_hint()
    if session_hint:
        prompt += f"[ΣΥΝΕΧΕΙΑ ΑΠΟ ΠΡΟΗΓΟΥΜΕΝΗ SESSION]\n{session_hint}\n\n"

    # 6. Προσθήκη Αυτογνωσίας
    cap_context = get_capability_context()
    if cap_context:
        prompt += f"[ΑΥΤΟΓΝΩΣΙΑ]\n{cap_context}\n\n"

    # 7. Προσθήκη Working Memory
    if os.path.exists(WORKING_MEMORY_FILE):
        try:
            with open(WORKING_MEMORY_FILE, "r", encoding="utf-8") as f:
                work_mem = json.load(f)
                if work_mem:
                    prompt += "═══ ΤΡΕΧΟΝ CONTEXT (Προσκήνιο) ═══\n"
                    prompt += "\n".join([f" • {m['tag']}" for m in work_mem]) + "\n"
                    prompt += "══════════════════════════════════\n\n"
        except: pass

    # 8. Hardcoded οδηγίες
    prompt += (
        "ΚΑΝΟΝΑΣ ΜΝΗΜΗΣ: Αν σου ζητηθεί πληροφορία που λείπει, κάλεσε το 'search_memory'.\n"
        "ΚΑΝΟΝΑΣ ΦΩΤΟΓΡΑΦΙΩΝ: Αν ζητηθεί φωτό, κάλεσε το 'retrieve_photo' και συμπεριέλαβε το [SEND_PHOTO: path] στην απάντηση.\n\n"
    )

    # 9. Τελικό κόλλημα των αναμνήσεων
    prompt += memories_str

    return prompt