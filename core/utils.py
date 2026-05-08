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
    """Κρατάει το ιστορικό καθαρό από σφάλματα και κενά εργαλεία."""
    if not messages: 
        return []
    
    safe_list = list(messages[-k:])
    cleaned_list = []
    
    for msg in safe_list:
        if msg.type == "tool" and (not msg.content or str(msg.content).strip() == ""):
            msg = ToolMessage(
                content="System Error: Το εργαλείο δεν επέστρεψε δεδομένα.",
                tool_call_id=msg.tool_call_id,
                name=msg.name
            )
        elif msg.type == "ai" and not msg.content and not getattr(msg, "tool_calls", None):
            continue
        cleaned_list.append(msg)
    
    return cleaned_list

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
    Η κεντρική μηχανή σύνθεσης Prompt.
    Συνδυάζει: Ταυτότητα, Similarity Search, Working Memory και Session Hints.
    """
    # Lazy imports για αποφυγή circular imports
    from config import WORKING_MEMORY_FILE, BASE_DIR
    from memory.vector_store import vector_store, vector_lock
    from memory.working_memory import get_capability_context
    from memory.session_memory import load_last_session_hint

    # 1. Προετοιμασία Ταυτότητας (από το prompts.json)
    # Εδώ βάζεις το 'identity_block' στο JSON σου με όλα τα ονόματα.
    identity = load_agent_prompt("identity_block", "Είσαι ο Αστακός, ο AI συνεργάτης του Λάζαρου.")
    # Αντικατάσταση του path αν υπάρχει στο identity block
    identity = identity.replace("{BASE_DIR}", BASE_DIR if 'BASE_DIR' in locals() else "C:\\astakos_v2")

    # 2. Similarity Search (Ανάκτηση αναμνήσεων)
    last_msg = clean_message(state_messages[-1].content) if state_messages else ""
    memories_str = ""
    if last_msg.strip():
        try:
            with vector_lock:
                results = vector_store.similarity_search(last_msg, k=8)
                if results:
                    memories_str = "\n═══ ΜΝΗΜΕΣ (Αυτά που θυμάμαι) ═══\n"
                    for res in results:
                        memories_str += f" • {res.page_content}\n"
        except Exception as e:
            print(f"⚠️ Memory Search Error: {e}")

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")

    # 3. Σύνθεση του Βασικού Prompt
    prompt = (
        f"{identity}\n"
        f"Σήμερα: {now_str}.\n"
        f"ΡΟΛΟΣ ΤΩΡΑ: {agent_role}\n\n"
    )

    # 4. Προσθήκη Context από προηγούμενες συνεδρίες
    session_hint = load_last_session_hint()
    if session_hint:
        prompt += f"[ΣΥΝΕΧΕΙΑ ΑΠΟ ΠΡΟΗΓΟΥΜΕΝΗ SESSION]\n{session_hint}\n\n"

    # 5. Προσθήκη Αυτογνωσίας (Capabilities)
    cap_context = get_capability_context()
    if cap_context:
        prompt += f"[ΑΥΤΟΓΝΩΣΙΑ]\n{cap_context}\n\n"

    # 6. Προσθήκη Working Memory (Τι συμβαίνει τώρα)
    if os.path.exists(WORKING_MEMORY_FILE):
        try:
            with open(WORKING_MEMORY_FILE, "r", encoding="utf-8") as f:
                work_mem = json.load(f)
                if work_mem:
                    prompt += "═══ ΤΡΕΧΟΝ CONTEXT (Προσκήνιο) ═══\n"
                    prompt += "\n".join([f" • {m['tag']}" for m in work_mem]) + "\n"
                    prompt += "══════════════════════════════════\n\n"
        except: pass

    # 7. Κανόνες Εργαλείων & Φωτογραφιών (Hardcoded οδηγίες λειτουργίας)
    prompt += (
        "ΚΑΝΟΝΑΣ ΜΝΗΜΗΣ: Αν σου ζητηθεί πληροφορία που λείπει, κάλεσε το 'search_memory'.\n"
        "ΚΑΝΟΝΑΣ ΦΩΤΟΓΡΑΦΙΩΝ: Αν ζητηθεί φωτό, κάλεσε το 'retrieve_photo' και συμπεριέλαβε το [SEND_PHOTO: path] στην απάντηση.\n\n"
    )

    # 8. Τελικό κόλλημα των αναμνήσεων από τη ChromaDB
    prompt += memories_str

    return prompt