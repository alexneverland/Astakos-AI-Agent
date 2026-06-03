# ================================================================
# Project: Astakos AI Agent 🦞
# Developer: Lazaros (Piston-7)
# Description: Modular LLM-agnostic multi-agent framework
# Copyright (c) 2026 - All Rights Reserved
# ================================================================

import os
import re
import base64
from datetime import datetime
from typing import Literal
from pydantic import BaseModel, Field
from tools.system import archive_file
# LangChain / LangGraph Imports
from langchain_core.messages import SystemMessage, HumanMessage, ToolMessage, AIMessage
from core.utils import load_agent_prompt
# CONFIG & BRAIN
from config import PHOTOS_DIR, WORKING_MEMORY_FILE
from core.brain import llm, llm_heavy
from astakos_skills.recipe_expert import recipe_expert, log_meal
# UTILS & STATE
from core.utils import AgentState, filter_messages, build_prompt, clean_message, sanitize_history_for_gemini
from astakos_skills.linkedin_state_manager import update_pending_linkedin_post, process_and_clear_linkedin_post
# MEMORY
from memory.vector_store import vector_store, vector_lock
from memory.working_memory import get_capability_context
from memory.session_memory import load_last_session_hint
from astakos_skills.search_flights import search_flights
# TOOLS
from tools.system import (
    search_memory, save_to_memory, delete_from_memory, retrieve_photo,
    set_local_reminder, set_reminder, manage_list,
    google_calendar_tool, google_tasks_tool, drive_manager,
    read_local_file, write_code, run_code, write_custom_tool,
    mail_manager, github_manager, control_vacuum, control_spotify, learn_routine, get_routines, create_file_tool, run_terminal_command, generate_image_tool, post_to_linkedin, get_current_location, get_fit_summary,
    save_goal_tool, update_goal_status_tool,
)
from tools.web import (
    get_news, get_weather_forecast,
    search_goldmall_offers, execute_local_pipeline, get_navigation_info, relay_local_payload, search_google_places, browse_url, duckduckgo_search, search_supermarket_prices
)

# ────────────────────────────────────────────────────────────────
# [GEMINI-FIX]: Force text response after tool execution
# ────────────────────────────────────────────────────────────────
def _ensure_text_response(response, llm_instance, system_prompt: str, safe_history: list):
    """
    Gemini quirk: μετά από tool execution επιστρέφει μερικές φορές κενό content.
    Αν συμβεί αυτό, κάνουμε ένα retry με explicit instruction να απαντήσει.
    """
    if clean_message(response.content).strip() or getattr(response, "tool_calls", []):
        return response  # Όλα ΟΚ, δεν χρειάζεται τίποτα
    # Retry — ο Gemini "σίγησε" μετά από tool
    print("\033[93m[Gemini-Fix]: Κενό response μετά από tool — retry...\033[0m")
    return llm_instance.invoke([
        SystemMessage(content=system_prompt + "\n\n[ΑΠΑΡΑΙΤΗΤΟ]: Πρέπει να απαντήσεις με κείμενο στον χρήστη. Ενημέρωσέ τον για ό,τι έγινε."),
        *safe_history
    ])

# ────────────────────────────────────────────────────────────────
# [MASTRO-SHIELD]: Κεντρικός καθαρισμός ορφανών tool_calls
# Χρησιμοποιείται από ΟΛΟΥΣ τους agents για να αποφύγουν το 400 INVALID_ARGUMENT
# ────────────────────────────────────────────────────────────────

def clean_orphan_tool_calls(history: list, k: int = 20) -> list:
    """
    [MASTRO-SHIELD v5]: Αποστειρωτής για Gemini 3.x sequence errors.

    Αφαιρεί AIMessages που έχουν κλήση εργαλείου και ΔΕΝ ακολουθούνται από
    αντίστοιχο ToolMessage. Το Gemini απαιτεί αυστηρή αλληλουχία:
        AI(tool_call) → Tool(result)
    Αν λείπει το Tool → 400 INVALID_ARGUMENT.

    Δύο τρόποι να εντοπίσει tool call σε AIMessage:
      1. Παραδοσιακός: msg.tool_calls populated (Gemini 1.x/2.x).
      2. [ΝΕΟ v5]: Το content είναι λίστα και περιέχει part τύπου
         "function_call" ή "tool_use" — συμβαίνει με Gemini 3.x όταν το
         langchain_google_genai δεν ξετυλίγει σωστά τα native parts σε
         tool_calls attribute.

    Αν εντοπιστεί ορφανό, κρατάμε μόνο το text part (αν υπάρχει) σαν
    κανονικό AIMessage. Αν δεν υπάρχει text, το πετάμε εντελώς.
    """
    # Πρώτο πέρασμα: βασικό φιλτράρισμα από filter_messages
    history = filter_messages(history, k=k)

    clean = []
    for i, msg in enumerate(history):
        if getattr(msg, "type", "") != "ai":
            clean.append(msg)
            continue

        # Έλεγχος 1: tool_calls attribute (παραδοσιακός τρόπος)
        has_tool_calls = bool(getattr(msg, "tool_calls", None))

        # Έλεγχος 2: function_call/tool_use parts μέσα στο content list (Gemini 3.x)
        has_inline_fc = False
        raw_content = getattr(msg, "content", None)
        if isinstance(raw_content, list):
            for part in raw_content:
                if isinstance(part, dict) and part.get("type") in ("function_call", "tool_use"):
                    has_inline_fc = True
                    break

        if has_tool_calls or has_inline_fc:
            next_is_tool = (
                i + 1 < len(history) and
                getattr(history[i + 1], "type", "") == "tool"
            )
            if not next_is_tool:
                # Ορφανή κλήση εργαλείου — κρατάμε μόνο το text content αν υπάρχει
                text_only = clean_message(raw_content) if raw_content else ""
                if text_only:
                    clean.append(AIMessage(content=text_only))
                # Αν δεν έχει text, το παρακάμπτουμε εντελώς
                continue

        clean.append(msg)
    return clean


# ────────────────────────────────────────────────────────────────
# SUPERVISOR ROUTER
# ────────────────────────────────────────────────────────────────

class Router(BaseModel):
    next_agent: Literal[
        "Home_Agent", "Web_Agent", "Tech_Agent", "Git_Agent",
        "Mail_Agent", "Chat_Agent", "Dev_Agent"
    ] = Field(description="Ποιος θα αναλάβει;")


def supervisor_node(state):
    from core.utils import load_agent_prompt, clean_message
    from config import BASE_DIR
    from core.capability_lookup import lookup_agent

    router_llm = llm.with_structured_output(Router)
    last_content = clean_message(state['messages'][-1].content)

    # ── Capability Registry: πρώτο φίλτρο πριν το LLM ───────────
    registry_agent = lookup_agent(str(last_content))
    if registry_agent:
        print(f"\033[95m[Τροχονόμος]: -> {registry_agent} (registry)\033[0m")
        return {"next_agent": registry_agent}

    # ── LLM fallback: κανονική απόφαση Supervisor ─────────────────
    system_base = load_agent_prompt("supervisor", "Είσαι ο Εργοδηγός του Αστακού.")
    system_base = system_base.replace("{BASE_DIR}", BASE_DIR)

    recent_msgs = state['messages'][-5:-1]
    context_lines = []
    for m in recent_msgs:
        role = "Λάζαρος" if getattr(m, "type", "") == "human" else "Αστακός"
        text = clean_message(m.content)[:150]
        if text:
            context_lines.append(f"{role}: {text}")

    context_str = "\n".join(context_lines) if context_lines else ""

    if context_str:
        full_prompt = f"{system_base}\n\n[ΠΡΟΗΓΟΥΜΕΝΗ ΣΥΝΟΜΙΛΙΑ - για context]\n{context_str}\n\nΝΕΑ ΕΝΤΟΛΗ: '{str(last_content)[:500]}'"
    else:
        full_prompt = f"{system_base}\n\nΧρήστης: '{str(last_content)[:500]}'"

    decision = router_llm.invoke(full_prompt)
    print(f"\033[95m[Τροχονόμος]: -> {decision.next_agent} (llm)\033[0m")
    return {"next_agent": decision.next_agent}


# ────────────────────────────────────────────────────────────────
# AGENT NODES
# ────────────────────────────────────────────────────────────────

def dev_agent_node(state):
    from core.utils import load_agent_prompt
    from config import BASE_DIR  
    
    # [MASTRO-SHIELD]: Καθαρισμός ορφανών tool_calls — ίδιο με όλους τους agents
    history = clean_orphan_tool_calls(state["messages"], k=20)
    
    system_base = load_agent_prompt("Dev_Agent", "Είσαι ο Dev_Agent, ο Αρχιμηχανικός Προγραμματιστής του Αστακού.")
    system_base = system_base.replace("{BASE_DIR}", BASE_DIR)
    prompt_content = build_prompt(history, system_base)

    tools = [
        write_code, run_code, read_local_file, write_custom_tool,
        delete_from_memory, search_memory, save_to_memory,
        execute_local_pipeline, control_spotify, control_vacuum, 
        get_navigation_info, recipe_expert, log_meal, 
        generate_image_tool, search_flights, run_terminal_command, learn_routine, get_routines,
        save_goal_tool, update_goal_status_tool,
        duckduckgo_search
    ]
    
    safe_history = sanitize_history_for_gemini(history)
    response = llm_heavy.bind_tools(tools).invoke(
        [SystemMessage(content=prompt_content)] + safe_history
    )
    return {"current_agent": "Dev_Agent", "messages": [response]}


def chat_agent_node(state: AgentState):
    from core.utils import load_agent_prompt, clean_message
    from config import BASE_DIR, PHOTOS_DIR 
    import re
    import os
    import base64
    
    # [MASTRO-SHIELD]: Καθαρισμός ορφανών tool_calls
    history = clean_orphan_tool_calls(state["messages"], k=20)
    last_msg_text = clean_message(history[-1].content) if history else ""

    analysis_match = re.search(r"\[ANALYSIS\]:\s*(.*)", last_msg_text)
    path_match = re.search(r"\[(?:PHOTO PATH|USER_UPLOADED_PHOTO|USER_UPLOADED_FILE)\]:\s*([^\s\n\]]+)", last_msg_text)
    
    pre_baked_analysis = analysis_match.group(1).strip() if analysis_match else None
    image_part = None

    detailed_keywords = ["τι", "ποιος", "ποια", "δες", "ανάλυσε", "λεπτομέρεια", "διάβασε", "χρώμα"]
    needs_pixels = any(word in last_msg_text.lower() for word in detailed_keywords)

    if path_match and (not pre_baked_analysis or needs_pixels):
        try:
            filename = os.path.basename(path_match.group(1).strip().replace("]", ""))
            file_path = os.path.join(PHOTOS_DIR, filename)
            ext = os.path.splitext(filename)[1].lower()
            image_exts = [".jpg", ".jpeg", ".png", ".webp", ".gif"]
            
            if os.path.exists(file_path) and ext in image_exts:
                with open(file_path, "rb") as image_file:
                    image_data = base64.b64encode(image_file.read()).decode("utf-8")
                    image_part = {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/jpeg;base64,{image_data}"}
                    }
                print(f"\033[92m[Vision]: Pixels loaded for re-analysis: {filename}\033[0m")
            elif os.path.exists(file_path):
                print(f"\033[94m[Agent Logic]: Το {filename} είναι έγγραφο. Παρακάμπτεται το Vision.\033[0m")
        except Exception as e:
            print(f"⚠️ [Vision/File Error]: {e}")

    vision_context = ""
    if pre_baked_analysis:
        vision_context = f"\n[CONTEXT ΑΡΧΕΙΟΥ/ΦΩΤΟΓΡΑΦΙΑΣ]: Έχεις ήδη αυτή την περιγραφή/πληροφορία: '{pre_baked_analysis}'.\n"

    json_base = load_agent_prompt("Chat_Agent", "Είσαι ο Αστακός, το έμπιστο φιλαράκι του Λάζαρου.")
    json_base = json_base.replace("{BASE_DIR}", BASE_DIR)
    system_prompt_text = f"{json_base}{vision_context}"
    system_prompt = build_prompt(history, system_prompt_text)

    safe_history = sanitize_history_for_gemini(history)
    final_messages = [SystemMessage(content=system_prompt)] + safe_history
    
    if image_part:
        final_messages[-1] = HumanMessage(content=[
            {"type": "text", "text": last_msg_text},
            image_part
        ])

    from tools.system import archive_file, retrieve_photo, save_to_memory, search_memory, control_spotify, get_current_location, read_local_file
    from tools.web import execute_local_pipeline, relay_local_payload, search_supermarket_prices

    chat_tools = [
        get_current_location, control_spotify,
        search_memory, save_to_memory, retrieve_photo, archive_file, duckduckgo_search,
        recipe_expert, log_meal, relay_local_payload, learn_routine, get_routines, search_supermarket_prices,
        read_local_file, generate_image_tool, get_fit_summary
    ]
    
    response = llm.bind_tools(chat_tools).invoke(final_messages)
    response = _ensure_text_response(response, llm, system_prompt, safe_history)
    return {"current_agent": "Chat_Agent", "messages": [response]}


def home_agent_node(state):
    from core.utils import load_agent_prompt
    from config import BASE_DIR
    from langchain_core.messages import SystemMessage
    
    from tools.system import (
        manage_list, set_reminder, set_local_reminder, delete_from_memory, 
        search_memory, control_spotify, control_vacuum, get_current_location
    )
    from tools.web import get_navigation_info, search_goldmall_offers
    from astakos_skills.recipe_expert import recipe_expert, log_meal
    
    # [MASTRO-SHIELD]: Καθαρισμός ορφανών tool_calls
    history = clean_orphan_tool_calls(state["messages"], k=20)

    tools_to_bind = [
        get_current_location,
        manage_list, set_reminder, set_local_reminder, delete_from_memory, search_memory,
        control_spotify, control_vacuum,
        search_goldmall_offers, get_navigation_info,
        google_calendar_tool, google_tasks_tool, recipe_expert, log_meal, learn_routine, get_routines, search_supermarket_prices,
        get_fit_summary
    ]

    system_base = load_agent_prompt("Home_Agent", "Είσαι ο Home_Agent του Piston-7.")
    system_base = system_base.replace("{BASE_DIR}", BASE_DIR)
    system_prompt = build_prompt(history, system_base)

    safe_history = sanitize_history_for_gemini(history)
    response = llm.bind_tools(tools_to_bind).invoke(
        [SystemMessage(content=system_prompt)] + safe_history
    )
    response = _ensure_text_response(response, llm, system_prompt, safe_history)

    return {"current_agent": "Home_Agent", "messages": [response]}


def web_agent_node(state: AgentState):
    from core.utils import load_agent_prompt, clean_message
    from config import BASE_DIR, PHOTOS_DIR 
    import re
    import os
    import base64

    # [MASTRO-SHIELD]: Καθαρισμός ορφανών tool_calls
    history = clean_orphan_tool_calls(state["messages"], k=20)
    last_msg_text = clean_message(history[-1].content) if history else ""

    path_match = re.search(r"\[(?:PHOTO PATH|USER_UPLOADED_PHOTO|USER_UPLOADED_FILE)\]:\s*([^\s\n\]]+)", last_msg_text)
    image_part = None

    if path_match:
        try:
            filename = os.path.basename(path_match.group(1).strip().replace("]", ""))
            file_path = os.path.join(PHOTOS_DIR, filename)
            if os.path.exists(file_path) and filename.lower().endswith(('.jpg', '.jpeg', '.png', '.webp')):
                with open(file_path, "rb") as f:
                    img_base64 = base64.b64encode(f.read()).decode("utf-8")
                    image_part = {
                        "type": "image_url", 
                        "image_url": {"url": f"data:image/jpeg;base64,{img_base64}"}
                    }
                print(f"\033[92m[Web-Vision]: Pixels loaded for analysis: {filename}\033[0m")
        except Exception as e:
            print(f"⚠️ Web Vision Error: {e}")

    system_base = load_agent_prompt("Web_Agent", "Είσαι ο Web_Agent.")
    system_base = system_base.replace("{BASE_DIR}", BASE_DIR)
    system_prompt = build_prompt(history, system_base)
    
    safe_history = sanitize_history_for_gemini(history)
    final_messages = [SystemMessage(content=system_prompt)] + safe_history
    
    if image_part:
        final_messages[-1] = HumanMessage(content=[
            {"type": "text", "text": last_msg_text},
            image_part
        ])

    from tools.system import (
        retrieve_photo, read_local_file, post_to_linkedin, 
        generate_image_tool, search_memory, get_current_location 
    )
    from tools.web import (
        get_news, get_weather_forecast, get_navigation_info, 
        relay_local_payload, search_google_places, browse_url, search_supermarket_prices
    )
    
    from tools.web import execute_local_pipeline
    web_tools = [
        get_current_location,
        get_news, get_weather_forecast, duckduckgo_search, 
        search_memory, get_navigation_info, retrieve_photo, read_local_file, 
        post_to_linkedin, generate_image_tool, update_pending_linkedin_post,
        process_and_clear_linkedin_post, search_google_places, execute_local_pipeline, browse_url, search_supermarket_prices
    ]

    return {
        "current_agent": "Web_Agent",
        "messages": [llm.bind_tools(web_tools).invoke(final_messages)]
    }


def tech_agent_node(state: AgentState):
    from core.utils import load_agent_prompt, build_prompt, clean_message
    from config import BASE_DIR, PHOTOS_DIR 
    from langchain_core.messages import SystemMessage, HumanMessage
    import re
    import os
    import base64
    
    # [MASTRO-SHIELD]: Καθαρισμός ορφανών tool_calls — αυτό έλυσε το 400 error
    history = clean_orphan_tool_calls(state["messages"], k=20)
    last_msg_text = clean_message(history[-1].content) if history else ""

    analysis_match = re.search(r"\[ANALYSIS\]:\s*(.*)", last_msg_text)
    path_match = re.search(r"\[(?:PHOTO PATH|USER_UPLOADED_PHOTO|USER_UPLOADED_FILE)\]:\s*([^\s\n\]]+)", last_msg_text)
    
    pre_baked_analysis = analysis_match.group(1).strip() if analysis_match else None
    image_part = None

    tech_keywords = ["κώδικας", "σφάλμα", "διάβασε", "τι γράφει", "error", "log", "σχέδιο"]
    needs_pixels = any(word in last_msg_text.lower() for word in tech_keywords)

    if path_match and (not pre_baked_analysis or needs_pixels):
        try:
            filename = os.path.basename(path_match.group(1).strip().replace("]", ""))
            file_path = os.path.join(PHOTOS_DIR, filename)
            ext = os.path.splitext(filename)[1].lower()
            image_exts = [".jpg", ".jpeg", ".png", ".webp", ".gif"]
            
            if os.path.exists(file_path) and ext in image_exts:
                with open(file_path, "rb") as f:
                    img_base64 = base64.b64encode(f.read()).decode("utf-8")
                    image_part = {
                        "type": "image_url", 
                        "image_url": {"url": f"data:image/jpeg;base64,{img_base64}"}
                    }
                print(f"\033[94m[Tech-Vision]: Pixels loaded for technical analysis: {filename}\033[0m")
            elif os.path.exists(file_path):
                print(f"\033[94m[Agent Logic]: Το {filename} είναι έγγραφο. Παρακάμπτεται το Vision.\033[0m")
        except Exception as e:
            print(f"⚠️ Tech Vision Error: {e}")

    vision_info = f"\n[CONTEXT ΑΡΧΕΙΟΥ/ΦΩΤΟ]: Έχεις ήδη αυτή την ανάλυση: '{pre_baked_analysis}'.\n" if pre_baked_analysis else ""
    json_base = load_agent_prompt("Tech_Agent", "Είσαι ο Tech_Agent, ο τεχνικός εμπειρογνώμονας του Λάζαρου.")
    json_base = json_base.replace("{BASE_DIR}", BASE_DIR)
    system_prompt_text = f"{json_base}{vision_info}"
    system_prompt = build_prompt(history, system_prompt_text)

    safe_history = sanitize_history_for_gemini(history)
    final_messages = [SystemMessage(content=system_prompt)] + safe_history
    if image_part:
        final_messages[-1] = HumanMessage(content=[
            {"type": "text", "text": last_msg_text},
            image_part
        ])

    from tools.system import (
        read_local_file, drive_manager, archive_file, search_memory, 
        save_to_memory, create_file_tool, get_current_location
    )
    
    tech_tools = [
        get_current_location,
        archive_file,
        read_local_file, 
        drive_manager,
        search_memory,
        save_to_memory,
        create_file_tool
    ]
    
    response = llm_heavy.bind_tools(tech_tools).invoke(final_messages)
    return {"current_agent": "Tech_Agent", "messages": [response]}




def git_agent_node(state):
    from core.utils import load_agent_prompt, build_prompt
    from config import BASE_DIR

    # [MASTRO-SHIELD v5]: Ενιαία ασπίδα για όλους τους agents
    history = clean_orphan_tool_calls(state["messages"], k=20)
    safe_history = sanitize_history_for_gemini(history)

    system_base = load_agent_prompt("Git_Agent", "Είσαι ο Git_Agent. Διαχειρίζεσαι GitHub repos.")
    system_base = system_base.replace("{BASE_DIR}", BASE_DIR)
    system_prompt = build_prompt(history, system_base)

    git_llm = llm.bind_tools([
        github_manager, read_local_file, search_memory, run_terminal_command
    ])
    response = git_llm.invoke([SystemMessage(content=system_prompt)] + safe_history)
    response = _ensure_text_response(response, git_llm, system_prompt, safe_history)

    return {"current_agent": "Git_Agent", "messages": [response]}


def mail_agent_node(state):
    from core.utils import load_agent_prompt
    from config import BASE_DIR  
    
    # [MASTRO-SHIELD]: Καθαρισμός ορφανών tool_calls
    history = clean_orphan_tool_calls(state["messages"], k=20)
    
    system_base = load_agent_prompt("Mail_Agent", "Είσαι ο Mail_Agent. Διαχειρίζεσαι το Gmail.")
    system_base = system_base.replace("{BASE_DIR}", BASE_DIR)
    system_prompt = build_prompt(history, system_base)
    
    return {
        "current_agent": "Mail_Agent",
        "messages": [llm.bind_tools([
            mail_manager, search_memory
        ]).invoke([SystemMessage(content=system_prompt)] + sanitize_history_for_gemini(history))]
    }


# ────────────────────────────────────────────────────────────────
# TOOL ROUTER
# ────────────────────────────────────────────────────────────────

AGENT_MAP = {
    "Chat_Agent": chat_agent_node,
    "Home_Agent": home_agent_node,
    "Web_Agent":  web_agent_node,
    "Tech_Agent": tech_agent_node,
    "Git_Agent":  git_agent_node,
    "Mail_Agent": mail_agent_node,
    "Dev_Agent":  dev_agent_node,
}


def tool_router(state):
    from langgraph.graph import END
    current = state.get("current_agent", "Chat_Agent")
    return current if current in AGENT_MAP else END


# ────────────────────────────────────────────────────────────────
# ALL TOOLS LIST
# ────────────────────────────────────────────────────────────────

all_tools = [
    manage_list, set_reminder, set_local_reminder, read_local_file, github_manager,
    mail_manager, get_news, drive_manager, get_weather_forecast,
    google_calendar_tool, save_to_memory, google_tasks_tool, delete_from_memory,
    search_memory, retrieve_photo, write_code, run_code, write_custom_tool,
    control_vacuum, get_navigation_info,
    control_spotify, search_goldmall_offers, execute_local_pipeline, get_current_location,
    recipe_expert, log_meal, create_file_tool, run_terminal_command, search_google_places, search_flights, learn_routine, get_routines, browse_url,
    duckduckgo_search, search_supermarket_prices
]