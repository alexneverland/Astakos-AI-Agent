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
# UTILS & STATE (Εδώ σπάμε το Circular Import)
from core.utils import AgentState, filter_messages, build_prompt, clean_message

# MEMORY
from memory.vector_store import vector_store, vector_lock
from memory.working_memory import get_capability_context
from memory.session_memory import load_last_session_hint

# TOOLS (Importing all the logic)
from tools.system import (
    search_memory, save_to_memory, delete_from_memory, retrieve_photo,
    set_local_reminder, set_reminder, manage_list,
    google_calendar_tool, google_tasks_tool, drive_manager,
    read_local_file, write_code, run_code, write_custom_tool,
    mail_manager, github_manager, control_vacuum, control_spotify, create_file_tool
)
from tools.web import (
    get_news, get_weather_forecast, search_supermarket_offers,
    search_goldmall_offers, send_messenger_message, get_navigation_info
)
from langchain_community.tools import DuckDuckGoSearchRun





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
    
    router_llm = llm.with_structured_output(Router)

    # Χρησιμοποιούμε την clean_message που ήδη φτιάξαμε για να καθαρίσουμε 
    # το multimodal content (Gemini 3.1) με μία γραμμή.
    last_content = clean_message(state['messages'][-1].content)

    # 1. Φορτώνουμε τις οδηγίες από το JSON
    system_base = load_agent_prompt("supervisor", "Είσαι ο Εργοδηγός του Αστακού.")
    
    # [MASTRO-FIX]: Αντικατάσταση του placeholder με το πραγματικό path του project
    system_base = system_base.replace("{BASE_DIR}", BASE_DIR)
    
    # 2. Συνθέτουμε το τελικό prompt με το τρέχον input του χρήστη
    full_prompt = f"{system_base}\n\nΧρήστης: '{str(last_content)[:500]}'"

    decision = router_llm.invoke(full_prompt)
    print(f"\033[95m[Τροχονόμος]: -> {decision.next_agent}\033[0m")
    return {"next_agent": decision.next_agent}


# ────────────────────────────────────────────────────────────────
# AGENT NODES
# ────────────────────────────────────────────────────────────────

def dev_agent_node(state):
    from core.utils import load_agent_prompt
    from config import BASE_DIR  
    from langchain_core.messages import SystemMessage, HumanMessage, AIMessage, ToolMessage
    
    # 1. Φιλτράρισμα - ΠΡΟΣΟΧΗ: Το filter_messages δεν πρέπει να σπάει τα ζευγάρια AI <-> Tool
    messages = state["messages"]
    
    # Κρατάμε τα τελευταία μηνύματα αλλά φροντίζουμε να μην έχουμε SystemMessages μέσα στο history
    # Το Gemini θέλει ΜΟΝΟ ΕΝΑ SystemMessage και ΠΑΝΤΑ στην αρχή (index 0).
    history = [m for m in messages if not isinstance(m, SystemMessage)]
    
    # Κρατάμε π.χ. τα τελευταία 20 μηνύματα για να μην βαραίνει το context
    history = history[-20:]
    
    # 2. Φορτώνουμε και προετοιμάζουμε το Prompt
    system_base = load_agent_prompt("Dev_Agent", "Είσαι ο Dev_Agent, ο Αρχιμηχανικός Προγραμματιστής του Αστακού.")
    system_base = system_base.replace("{BASE_DIR}", BASE_DIR)
    
    # Χτίζουμε το prompt (το build_prompt σου πρέπει να επιστρέφει string)
    prompt_content = build_prompt(history, system_base)
    
    # 3. Η ΚΡΙΣΙΜΗ ΣΥΝΘΕΣΗ
    # Φτιάχνουμε τη λίστα έτσι ώστε το SystemMessage να είναι ΠΡΩΤΟ και μετά όλο το ιστορικό.
    # Αυτό εγγυάται ότι δεν θα υπάρχει SystemMessage ανάμεσα σε AI και Tool calls.
    clean_history = [SystemMessage(content=prompt_content)] + history

    # 4. Εκτέλεση με τα Tools
    tools = [
        write_code, run_code, read_local_file, write_custom_tool,
        delete_from_memory, search_memory, save_to_memory,
        send_messenger_message, control_spotify, control_vacuum, get_navigation_info, recipe_expert, log_meal
    ]
    
    # Χρησιμοποιούμε llm_heavy.bind_tools
    # [MASTRO-FIX]: Χρήση του llm (Gemini 3.1) για σταθερά αλυσιδωτά tool calls
    response = llm.bind_tools(tools).invoke(clean_history)

    return {"current_agent": "Dev_Agent", "messages": [response]}


def chat_agent_node(state: AgentState):
    """
    Ο κεντρικός Agent του Αστακού. 
    Διαχειρίζεται το chat, την έξυπνη όραση, την επιλεκτική αρχειοθέτηση κ.λπ.
    """
    from core.utils import load_agent_prompt, clean_message
    from config import BASE_DIR, PHOTOS_DIR 
    import re
    import os
    import base64
    
    # 1. Προετοιμασία ιστορικού
    history = filter_messages(state["messages"])
    # [MASTRO-FIX]: Χρήση της clean_message για σίγουρο string (Gemini 3.1)
    last_msg_text = clean_message(history[-1].content) if history else ""

    # 2. --- [SMART-VISION & FILE LOGIC]: Ανίχνευση Αρχείου ---
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

    # 3. --- SYSTEM PROMPT ΑΠΟ JSON ---
    vision_context = ""
    if pre_baked_analysis:
        vision_context = f"\n[CONTEXT ΑΡΧΕΙΟΥ/ΦΩΤΟΓΡΑΦΙΑΣ]: Έχεις ήδη αυτή την περιγραφή/πληροφορία: '{pre_baked_analysis}'.\n"

    # Φορτώνουμε τη βάση του prompt από το JSON
    json_base = load_agent_prompt("Chat_Agent", "Είσαι ο Αστακός, το έμπιστο φιλαράκι του Λάζαρου.")
    
    # [MASTRO-FIX]: Αντικατάσταση του placeholder με το πραγματικό path
    json_base = json_base.replace("{BASE_DIR}", BASE_DIR)
    
    # Συνθέτουμε το τελικό prompt κολλώντας το vision_context αν υπάρχει
    system_prompt_text = f"{json_base}{vision_context}"
    system_prompt = build_prompt(history, system_prompt_text)

    # 4. --- ΣΥΝΤΑΞΗ ΜΗΝΥΜΑΤΩΝ ---
    final_messages = [SystemMessage(content=system_prompt)] + history
    
    if image_part:
        final_messages[-1] = HumanMessage(content=[
            {"type": "text", "text": last_msg_text},
            image_part
        ])

    # 5. --- BIND TOOLS & ΕΚΤΕΛΕΣΗ ---
    from tools.system import archive_file, retrieve_photo, save_to_memory, search_memory, control_spotify
    from tools.web import search_supermarket_offers, send_messenger_message
    from langchain_community.tools import DuckDuckGoSearchRun
    
    web_search = DuckDuckGoSearchRun()
    
    chat_tools = [
        send_messenger_message, search_supermarket_offers, control_spotify,
        search_memory, save_to_memory, retrieve_photo, archive_file, web_search, recipe_expert,
    log_meal
    ]
    
    response = llm.bind_tools(chat_tools).invoke(final_messages)

    return {
        "current_agent": "Chat_Agent",
        "messages": [response]
    }

def home_agent_node(state):
    from core.utils import load_agent_prompt
    from config import BASE_DIR  
    history = filter_messages(state["messages"])

    tools_to_bind = [
        manage_list, set_reminder, set_local_reminder, delete_from_memory, search_memory,
        search_supermarket_offers, control_spotify, control_vacuum,
        search_goldmall_offers, get_navigation_info,
        google_calendar_tool, google_tasks_tool, recipe_expert, log_meal
    ]

    # 1. Τραβάμε τις οδηγίες από το JSON
    system_base = load_agent_prompt("Home_Agent", "Είσαι ο Home_Agent του Piston-7.")
    
    # [MASTRO-FIX]: Αντικατάσταση του placeholder για να παίζουν τα paths παντού
    system_base = system_base.replace("{BASE_DIR}", BASE_DIR)
    
    # 2. Χτίζουμε το prompt μαζί με το ιστορικό
    system_prompt = build_prompt(history, system_base)

    return {
        "current_agent": "Home_Agent",
        "messages": [llm.bind_tools(tools_to_bind).invoke([SystemMessage(content=system_prompt)] + history)]
    }


def web_agent_node(state: AgentState):
    """
    Ο Agent του Internet με υποστήριξη Vision (Mastro-Vision).
    """
    from core.utils import load_agent_prompt, clean_message
    from config import BASE_DIR, PHOTOS_DIR 
    import re
    import os
    import base64

    history = filter_messages(state["messages"])
    # Παίρνουμε το τελευταίο μήνυμα για να δούμε αν έχει φωτό
    last_msg_text = clean_message(history[-1].content) if history else ""

    # [MASTRO-VISION]: Ανίχνευση αν υπάρχει φωτογραφία στο τρέχον context
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

    # 1. Τραβάμε τις οδηγίες από το JSON
    system_base = load_agent_prompt("Web_Agent", "Είσαι ο Web_Agent.")
    system_base = system_base.replace("{BASE_DIR}", BASE_DIR)
    
    # 2. Χτίζουμε το prompt (με τον νέο build_prompt που θα φτιάξουμε παρακάτω)
    system_prompt = build_prompt(history, system_base)
    
    # Προετοιμασία των μηνυμάτων
    final_messages = [SystemMessage(content=system_prompt)] + history
    
    # Αν υπάρχει φωτό, μετατρέπουμε το τελευταίο HumanMessage σε Multimodal
    if image_part:
        final_messages[-1] = HumanMessage(content=[
            {"type": "text", "text": last_msg_text},
            image_part
        ])

    web_tools = [
        get_news, get_weather_forecast, DuckDuckGoSearchRun(), 
        search_memory, get_navigation_info, retrieve_photo, read_local_file
    ]

    return {
        "current_agent": "Web_Agent",
        "messages": [llm.bind_tools(web_tools).invoke(final_messages)]
    }


def tech_agent_node(state: AgentState):
    """
    Ο τεχνικός Agent της Piston-7. 
    Πλέον έχει και αυτός 'μάτια', διαβάζει έγγραφα (PDF/Excel) και αρχειοθετεί αρχεία.
    """
    from core.utils import load_agent_prompt, clean_message
    from config import BASE_DIR, PHOTOS_DIR  
    import re
    import os
    import base64
    
    # 1. Φιλτράρισμα & Καθαρισμός ιστορικού
    history = filter_messages(state["messages"])
    # [MASTRO-FIX]: Χρήση της clean_message για σίγουρο string (αποφυγή list/strip errors)
    last_msg_text = clean_message(history[-1].content) if history else ""

    # 2. --- [SMART-VISION & FILE LOGIC]: Ανίχνευση αρχείου ---
    analysis_match = re.search(r"\[ANALYSIS\]:\s*(.*)", last_msg_text)
    path_match = re.search(r"\[(?:PHOTO PATH|USER_UPLOADED_PHOTO|USER_UPLOADED_FILE)\]:\s*([^\s\n\]]+)", last_msg_text)
    
    pre_baked_analysis = analysis_match.group(1).strip() if analysis_match else None
    image_part = None

    # Φόρτωση pixels αν ο Λάζαρος ζητάει τεχνική λεπτομέρεια
    tech_keywords = ["κώδικας", "σφάλμα", "διάβασε", "τι γράφει", "error", "log"]
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

    # 3. --- SYSTEM PROMPT ΑΠΟ JSON ---
    vision_info = f"\n[CONTEXT ΑΡΧΕΙΟΥ/ΦΩΤΟ]: Έχεις ήδη αυτή την ανάλυση/πληροφορία: '{pre_baked_analysis}'.\n" if pre_baked_analysis else ""
    
    # Φορτώνουμε τη βάση του prompt από το JSON
    json_base = load_agent_prompt("Tech_Agent", "Είσαι ο Tech_Agent, ο τεχνικός εμπειρογνώμονας του Λάζαρου.")
    
    # [MASTRO-FIX]: Δυναμική αντικατάσταση του path στο prompt
    json_base = json_base.replace("{BASE_DIR}", BASE_DIR)
    
    system_prompt_text = f"{json_base}{vision_info}"
    system_prompt = build_prompt(history, system_prompt_text)

    # 4. --- ΠΡΟΕΤΟΙΜΑΣΙΑ ΜΗΝΥΜΑΤΩΝ ---
    final_messages = [SystemMessage(content=system_prompt)] + history
    if image_part:
        # Αντικαθιστούμε το τελευταίο μήνυμα με Multimodal αν έχουμε εικόνα
        final_messages[-1] = HumanMessage(content=[
            {"type": "text", "text": last_msg_text},
            image_part
        ])

    # 5. --- BIND TOOLS ---
    from tools.system import (
        read_local_file, drive_manager, archive_file, search_memory, save_to_memory, create_file_tool
    )
    
    tech_tools = [
        archive_file,
        read_local_file, 
        drive_manager,
        search_memory,
        save_to_memory,
        create_file_tool
    ]
    
    response = llm_heavy.bind_tools(tech_tools).invoke(final_messages)

    return {
        "current_agent": "Tech_Agent",
        "messages": [response]
    }

def git_agent_node(state):
    from core.utils import load_agent_prompt
    from config import BASE_DIR  
    
    history = filter_messages(state["messages"])
    
    # 1. Φορτώνουμε τις οδηγίες από το JSON
    system_base = load_agent_prompt("Git_Agent", "Είσαι ο Git_Agent. Διαχειρίζεσαι GitHub repos.")
    
    # [MASTRO-FIX]: Δυναμική αντικατάσταση του path
    system_base = system_base.replace("{BASE_DIR}", BASE_DIR)
    
    # 2. Χτίζουμε το prompt
    system_prompt = build_prompt(history, system_base)
    
    return {
        "current_agent": "Git_Agent",
        "messages": [llm.bind_tools([
            github_manager, read_local_file, search_memory
        ]).invoke([SystemMessage(content=system_prompt)] + history)]
    }


def mail_agent_node(state):
    from core.utils import load_agent_prompt
    from config import BASE_DIR  
    
    history = filter_messages(state["messages"])
    
    # 1. Φορτώνουμε τις οδηγίες από το JSON
    system_base = load_agent_prompt("Mail_Agent", "Είσαι ο Mail_Agent. Διαχειρίζεσαι το Gmail.")
    
    # [MASTRO-FIX]: Δυναμική αντικατάσταση του path στο prompt
    system_base = system_base.replace("{BASE_DIR}", BASE_DIR)
    
    # 2. Χτίζουμε το τελικό prompt
    system_prompt = build_prompt(history, system_base)
    
    return {
        "current_agent": "Mail_Agent",
        "messages": [llm.bind_tools([
            mail_manager, search_memory
        ]).invoke([SystemMessage(content=system_prompt)] + history)]
    }


# ────────────────────────────────────────────────────────────────
# TOOL ROUTER (για επιστροφή μετά από tool call)
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
# ALL TOOLS LIST (για το ToolNode)
# ────────────────────────────────────────────────────────────────

all_tools = [
    manage_list, set_reminder, set_local_reminder, read_local_file, github_manager,
    mail_manager, get_news, drive_manager, get_weather_forecast,
    google_calendar_tool, save_to_memory, google_tasks_tool, delete_from_memory,
    search_memory, retrieve_photo, write_code, run_code, write_custom_tool,
    control_vacuum, get_navigation_info, search_supermarket_offers,
    control_spotify, search_goldmall_offers, send_messenger_message, 
    recipe_expert, log_meal, create_file_tool,
    DuckDuckGoSearchRun()
]