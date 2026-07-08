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
from core.brain import llm, llm_heavy, safe_llm_invoke
from astakos_skills.recipe_expert import recipe_expert, log_meal
# UTILS & STATE
from core.utils import AgentState, filter_messages, build_prompt, clean_message, sanitize_history_for_gemini
from astakos_skills.linkedin_state_manager import update_pending_linkedin_post, process_and_clear_linkedin_post
# MEMORY
from memory.vector_store import vector_store, vector_lock
from memory.working_memory import get_capability_context
from memory.session_memory import load_last_session_hint
from astakos_skills.search_flights import search_flights
from astakos_skills.repo_mapper import repo_mapper
# TOOLS
from tools.system import (
    search_memory, save_to_memory, delete_from_memory, retrieve_photo,
    set_local_reminder, manage_list,
    google_calendar_tool, google_tasks_tool, drive_manager,
    read_local_file, write_code, run_code, write_custom_tool, register_tool,
    mail_manager, github_manager, control_vacuum, control_spotify, learn_routine, edit_routine, delete_routine, get_routines, control_routine_notifications, control_routine_schedule, control_routine_condition, control_routine_cooldown, control_pending_followup, create_file_tool, run_terminal_command, generate_image_tool, post_to_linkedin, get_current_location, get_fit_summary,
    save_goal_tool, update_goal_status_tool, tool_stats, system_doctor, memory_review,
)
from tools.web import (
    get_news, get_weather_forecast,
    search_goldmall_offers, execute_local_pipeline, get_navigation_info, relay_local_payload, search_google_places, browse_url, duckduckgo_search, search_supermarket_prices
)
from tools.project_tools import (
    grant_project_access, list_project_files, read_project_file,
    edit_project_file, write_project_file, grep_project_files,
    list_recent_files,
)

from time import perf_counter

def _attach_phase_timing(message, key: str, duration_ms: int):
    try:
        existing = dict(getattr(message, "_astakos_phase_timings", {}) or {})
        existing[key] = int(duration_ms)
        setattr(message, "_astakos_phase_timings", existing)
    except Exception:
        pass
    return message


def _merge_phase_timings(target, source):
    try:
        source_timings = dict(getattr(source, "_astakos_phase_timings", {}) or {})
        if not source_timings:
            return target
        target_timings = dict(getattr(target, "_astakos_phase_timings", {}) or {})
        target_timings.update(source_timings)
        setattr(target, "_astakos_phase_timings", target_timings)
    except Exception:
        pass
    return target

# ────────────────────────────────────────────────────────────────
# [GEMINI-FIX]: Force text response after tool execution
# ────────────────────────────────────────────────────────────────
def _ensure_text_response(response, llm_instance, system_prompt: str, safe_history: list):
    """
    Gemini quirk: μετά από tool execution επιστρέφει μερικές φορές κενό content.
    Retry μέχρι 3 φορές με escalating instruction.
    """
    ensure_started = perf_counter()
    retry_count = 0

    if clean_message(response.content).strip() or getattr(response, "tool_calls", []):
        _attach_phase_timing(response, "ensure_text_ms", int((perf_counter() - ensure_started) * 1000))
        _attach_phase_timing(response, "ensure_text_retries", retry_count)
        return response  # Όλα ΟΚ

    suffixes = [
        "\n\n[ΑΠΑΡΑΙΤΗΤΟ]: Πρέπει να απαντήσεις με κείμενο στον χρήστη. Ενημέρωσέ τον για ό,τι έγινε.",
        "\n\n[ΚΡΙΣΙΜΟ]: Γράψε ΑΜΕΣΩΣ μια σύνοψη των αποτελεσμάτων που βρήκες. Μην κάνεις άλλα tool calls.",
        "\n\n[ΤΕΛΙΚΟ]: Δώσε μια σύντομη απάντηση έστω 1 πρότασης στον χρήστη τώρα.",
    ]
    for attempt, suffix in enumerate(suffixes, 1):
        print(f"\033[93m[Gemini-Fix]: Κενό response — retry {attempt}/3...\033[0m")
        retry_started = perf_counter()
        retry_count += 1
        retry_response = llm_instance.invoke([
            SystemMessage(content=system_prompt + suffix),
            *safe_history
        ])
        _attach_phase_timing(retry_response, f"ensure_text_retry_{retry_count}_ms", int((perf_counter() - retry_started) * 1000))
        if clean_message(retry_response.content).strip():
            _merge_phase_timings(retry_response, response)
            _attach_phase_timing(retry_response, "ensure_text_ms", int((perf_counter() - ensure_started) * 1000))
            _attach_phase_timing(retry_response, "ensure_text_retries", retry_count)
            return retry_response
    
    _attach_phase_timing(response, "ensure_text_ms", int((perf_counter() - ensure_started) * 1000))
    _attach_phase_timing(response, "ensure_text_retries", retry_count)
    return response  # Επιστρέφουμε το original αν όλα αποτύχουν

# ────────────────────────────────────────────────────────────────
# [MASTRO-SHIELD]: Κεντρικός καθαρισμός ορφανών tool_calls
# Χρησιμοποιείται από ΟΛΟΥΣ τους agents για να αποφύγουν το 400 INVALID_ARGUMENT
# ────────────────────────────────────────────────────────────────

def clean_orphan_tool_calls(history: list, k: int = 40) -> list:
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
        tool_calls = getattr(msg, "tool_calls", [])
        expected_ids = set(tc.get("id") for tc in tool_calls if isinstance(tc, dict) and tc.get("id"))

        # Έλεγχος 2: function_call/tool_use parts μέσα στο content list (Gemini 3.x)
        has_inline_fc = False
        raw_content = getattr(msg, "content", None)
        if isinstance(raw_content, list):
            for part in raw_content:
                if isinstance(part, dict) and part.get("type") in ("function_call", "tool_use"):
                    has_inline_fc = True
                    break

        if expected_ids or has_inline_fc:
            found_ids = set()
            next_idx = i + 1
            while next_idx < len(history):
                nxt_msg = history[next_idx]
                if getattr(nxt_msg, "type", "") == "tool":
                    tc_id = getattr(nxt_msg, "tool_call_id", None)
                    if tc_id:
                        found_ids.add(tc_id)
                    next_idx += 1
                else:
                    break
            
            missing_ids = expected_ids - found_ids
            next_is_tool = (i + 1 < len(history) and getattr(history[i + 1], "type", "") == "tool")
            
            if missing_ids or (has_inline_fc and not next_is_tool):
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

    # ── /plan: υψηλότερη προτεραιότητα από όλα ────────────────────
    # Χρησιμοποιούμε regex γιατί το server βάζει timestamp [HH:MM] πριν το μήνυμα
    import re as _re
    if _re.search(r'(?:^|\])\s*/plan', last_content.strip()):
        print(f"\033[95m[Τροχονόμος]: -> planner (/plan command)\033[0m")
        return {"next_agent": "planner"}

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

    decision = safe_llm_invoke(router_llm, full_prompt)
    print(f"\033[95m[Τροχονόμος]: -> {decision.next_agent} (llm)\033[0m")
    return {"next_agent": decision.next_agent}


# ────────────────────────────────────────────────────────────────
# AGENT NODES
# ────────────────────────────────────────────────────────────────

def dev_agent_node(state):
    from core.utils import load_agent_prompt
    from config import BASE_DIR  
    
    # [MASTRO-SHIELD]: Καθαρισμός ορφανών tool_calls — ίδιο με όλους τους agents
    history = clean_orphan_tool_calls(state["messages"], k=40)
    
    system_base = load_agent_prompt("Dev_Agent", "Είσαι ο Dev_Agent, ο Αρχιμηχανικός Προγραμματιστής του Αστακού.")
    system_base = system_base.replace("{BASE_DIR}", BASE_DIR)
    prompt_content = build_prompt(history, system_base, channel=state.get("channel"))

    tools = [
        write_code, run_code, read_local_file, write_custom_tool, register_tool,
        delete_from_memory, search_memory, save_to_memory,
        execute_local_pipeline, control_spotify, control_vacuum, 
        get_navigation_info, recipe_expert, log_meal, 
        generate_image_tool, search_flights, run_terminal_command, learn_routine, edit_routine, delete_routine, get_routines, control_routine_notifications, control_routine_schedule, control_routine_condition, control_routine_cooldown, control_pending_followup,
        save_goal_tool, update_goal_status_tool,
        duckduckgo_search,
        # Project tools — code navigation & editing
        grant_project_access, list_project_files, read_project_file,
        edit_project_file, write_project_file, grep_project_files, repo_mapper,
        list_recent_files,
    ]
    
    safe_history = sanitize_history_for_gemini(history)
    response = llm_heavy.bind_tools(tools).invoke(
        [SystemMessage(content=prompt_content)] + safe_history
    )
    response = _ensure_text_response(response, llm_heavy, prompt_content, safe_history)
    return {"current_agent": "Dev_Agent", "messages": [response]}


def chat_agent_node(state: AgentState):
    from core.utils import load_agent_prompt, clean_message
    from config import BASE_DIR, PHOTOS_DIR 
    import re
    import os
    import base64
    
    # [MASTRO-SHIELD]: Καθαρισμός ορφανών tool_calls
    history = clean_orphan_tool_calls(state["messages"], k=40)
    last_msg_text = clean_message(history[-1].content) if history else ""
    latest_user_text = ""
    for msg in reversed(history):
        if getattr(msg, "type", "") == "human":
            latest_user_text = clean_message(getattr(msg, "content", ""))
            break

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
    system_prompt = build_prompt(history, system_prompt_text, channel=state.get("channel"))

    safe_history = sanitize_history_for_gemini(history)
    final_messages = [SystemMessage(content=system_prompt)] + safe_history
    
    if image_part:
        final_messages[-1] = HumanMessage(content=[
            {"type": "text", "text": last_msg_text},
            image_part
        ])

    from tools.system import archive_file, retrieve_photo, save_to_memory, delete_from_memory, search_memory, control_spotify, get_current_location, read_local_file
    from tools.web import execute_local_pipeline, relay_local_payload, search_supermarket_prices

    # [FAREWELL GUARD]: Αν ο χρήστης αποχαιρετά, αφαιρούμε archive_file
    # ώστε το LLM να μην αρχειοθετεί αυτόματα αρχεία που βρίσκονται στο context.
    _FAREWELL_WORDS = (
        "καληνύχτα", "καλη νύχτα", "gn ", "good night", "αντίο", "bye",
        "ta leme", "τα λέμε", "γεια σου", "γεια χαρα", "ciao", "adio",
    )
    _is_farewell = any(w in last_msg_text.lower() for w in _FAREWELL_WORDS)

    chat_tools = [
        get_current_location, control_spotify,
        search_memory, save_to_memory, delete_from_memory, retrieve_photo, duckduckgo_search,
        recipe_expert, log_meal, relay_local_payload, learn_routine, edit_routine, delete_routine, get_routines, control_routine_notifications, control_routine_schedule, control_routine_condition, control_routine_cooldown, control_pending_followup, search_supermarket_prices,
        read_local_file, generate_image_tool, get_fit_summary,
        *([archive_file] if not _is_farewell else []),
    ]

    bind_started = perf_counter()
    bound_llm = llm.bind_tools(chat_tools)
    bind_ms = int((perf_counter() - bind_started) * 1000)

    invoke_started = perf_counter()
    response = bound_llm.invoke(final_messages)
    invoke_ms = int((perf_counter() - invoke_started) * 1000)

    _attach_phase_timing(response, "chat_bind_ms", bind_ms)
    _attach_phase_timing(response, "chat_invoke_ms", invoke_ms)

    ensure_started = perf_counter()
    response = _ensure_text_response(response, llm, system_prompt, safe_history)
    ensure_wrapper_ms = int((perf_counter() - ensure_started) * 1000)

    _attach_phase_timing(response, "chat_ensure_wrapper_ms", ensure_wrapper_ms)
    return {"current_agent": "Chat_Agent", "messages": [response]}


def home_agent_node(state):
    from core.utils import load_agent_prompt
    from config import BASE_DIR
    from langchain_core.messages import SystemMessage
    
    from tools.system import (
        manage_list, set_local_reminder, delete_from_memory,
        search_memory, control_spotify, control_vacuum, get_current_location
    )
    from tools.web import get_navigation_info, search_goldmall_offers
    from astakos_skills.recipe_expert import recipe_expert, log_meal
    
    # [MASTRO-SHIELD]: Καθαρισμός ορφανών tool_calls
    history = clean_orphan_tool_calls(state["messages"], k=40)

    tools_to_bind = [
        get_current_location,
        manage_list, set_local_reminder, delete_from_memory, search_memory,
        control_spotify, control_vacuum,
        search_goldmall_offers, get_navigation_info,
        google_calendar_tool, google_tasks_tool, recipe_expert, log_meal, learn_routine, edit_routine, delete_routine, get_routines, control_routine_notifications, control_routine_schedule, control_routine_condition, control_routine_cooldown, control_pending_followup, search_supermarket_prices,
        get_fit_summary
    ]

    system_base = load_agent_prompt("Home_Agent", "Είσαι ο Home_Agent του Piston-7.")
    system_base = system_base.replace("{BASE_DIR}", BASE_DIR)
    system_prompt = build_prompt(history, system_base, channel=state.get("channel"))

    safe_history = sanitize_history_for_gemini(history)
    bind_started = perf_counter()
    bound_llm = llm.bind_tools(tools_to_bind)
    bind_ms = int((perf_counter() - bind_started) * 1000)

    invoke_started = perf_counter()
    response = bound_llm.invoke(
        [SystemMessage(content=system_prompt)] + safe_history
    )
    invoke_ms = int((perf_counter() - invoke_started) * 1000)

    _attach_phase_timing(response, "home_bind_ms", bind_ms)
    _attach_phase_timing(response, "home_invoke_ms", invoke_ms)

    ensure_started = perf_counter()
    response = _ensure_text_response(response, llm, system_prompt, safe_history)
    ensure_wrapper_ms = int((perf_counter() - ensure_started) * 1000)

    _attach_phase_timing(response, "home_ensure_wrapper_ms", ensure_wrapper_ms)

    return {"current_agent": "Home_Agent", "messages": [response]}


def web_agent_node(state: AgentState):
    from core.utils import (
        load_agent_prompt,
        clean_message,
        filter_recent_web_tool_results,
        looks_like_web_tool_error,
        build_web_failure_reply,
        looks_like_terminal_linkedin_draft_result,
        build_linkedin_draft_ready_reply,
        is_reply_to_recent_linkedin_prompt,
        should_attach_linkedin_draft_reply,
    )
    from config import BASE_DIR, PHOTOS_DIR 
    import re
    import os
    import base64

    # [MASTRO-SHIELD]: Καθαρισμός ορφανών tool_calls
    history = clean_orphan_tool_calls(state["messages"], k=40)
    last_msg_text = clean_message(history[-1].content) if history else ""
    latest_user_text = ""
    for msg in reversed(history):
        if getattr(msg, "type", "") == "human":
            latest_user_text = clean_message(getattr(msg, "content", ""))
            break

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

    recent_web_tool_results = filter_recent_web_tool_results(history)
    web_errors = [(name, text) for name, text in recent_web_tool_results if looks_like_web_tool_error(text)]
    web_successes = [(name, text) for name, text in recent_web_tool_results if not looks_like_web_tool_error(text)]
    linkedin_terminal_results = [
        text for _, text in recent_web_tool_results
        if looks_like_terminal_linkedin_draft_result(text)
    ]

    linkedin_prompt_active = is_reply_to_recent_linkedin_prompt(history)

    if should_attach_linkedin_draft_reply(
        latest_user_text or last_msg_text,
        linkedin_terminal_results,
        recent_linkedin_prompt_active=linkedin_prompt_active,
    ):
        from langchain_core.messages import AIMessage as _AIMsg
        return {
            "messages": [_AIMsg(content=build_linkedin_draft_ready_reply(linkedin_terminal_results))],
            "current_agent": "Web_Agent",
        }

    system_base = load_agent_prompt("Web_Agent", "Είσαι ο Web_Agent.")
    system_base = system_base.replace("{BASE_DIR}", BASE_DIR)
    system_prompt = build_prompt(history, system_base, channel=state.get("channel"))
    
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
        process_and_clear_linkedin_post, search_google_places, execute_local_pipeline, browse_url, search_supermarket_prices, relay_local_payload
    ]

    result = llm.bind_tools(web_tools).invoke(final_messages)
    content = clean_message(result.content).strip() if result.content else ""
    has_tool_calls = bool(getattr(result, "tool_calls", None))

    if web_errors and not web_successes:
        guarded_reply = build_web_failure_reply(last_msg_text, recent_web_tool_results)
        from langchain_core.messages import AIMessage as _AIMsg
        return {"messages": [_AIMsg(content=guarded_reply)], "current_agent": "Web_Agent"}

    # [MASTRO-FIX]: Αν η σύνθεση είναι κενή (blocked server-side) και υπάρχουν
    # tool results στο history, επιστρέφουμε τα raw αποτελέσματα ως fallback.
    if not content and not has_tool_calls:
        tool_results = [m for m in history if getattr(m, "type", "") == "tool"]
        if tool_results:
            print(f"\033[93m[Web_Agent]: ⚠️ Κενή σύνθεση — fallback σε raw tool results.\033[0m")
            parts = []
            for tm in tool_results[-3:]:
                raw = clean_message(tm.content).strip()[:900]
                if raw:
                    parts.append(raw)
            if parts:
                from langchain_core.messages import AIMessage as _AIMsg
                result = _AIMsg(content="📊 " + "\n\n".join(parts))

    return {
        "current_agent": "Web_Agent",
        "messages": [result]
    }


def tech_agent_node(state: AgentState):
    from core.utils import load_agent_prompt, build_prompt, clean_message
    from config import BASE_DIR, PHOTOS_DIR 
    from langchain_core.messages import SystemMessage, HumanMessage
    import re
    import os
    import base64
    
    # [MASTRO-SHIELD]: Καθαρισμός ορφανών tool_calls — αυτό έλυσε το 400 error
    history = clean_orphan_tool_calls(state["messages"], k=40)
    last_msg_text = clean_message(history[-1].content) if history else ""

    analysis_match = re.search(r"\[ANALYSIS\]:\s*(.*)", last_msg_text)
    path_match = re.search(r"\[(?:PHOTO PATH|USER_UPLOADED_PHOTO|USER_UPLOADED_FILE)\]:\s*([^\s\n\]]+)", last_msg_text)
    
    pre_baked_analysis = analysis_match.group(1).strip() if analysis_match else None
    image_part = None

    tech_keywords = ["κώδικας", "σφάλμα", "διάβασε", "τι γράφει", "error", "logs", "σχέδιο"]
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
    system_prompt = build_prompt(history, system_prompt_text, channel=state.get("channel"))

    safe_history = sanitize_history_for_gemini(history)
    final_messages = [SystemMessage(content=system_prompt)] + safe_history
    if image_part:
        final_messages[-1] = HumanMessage(content=[
            {"type": "text", "text": last_msg_text},
            image_part
        ])

    from tools.system import (
        read_local_file, drive_manager, archive_file, search_memory,
        save_to_memory, create_file_tool, get_current_location, tool_stats, system_doctor, memory_review
    )

    tech_tools = [
        get_current_location,
        archive_file,
        read_local_file,
        drive_manager,
        search_memory,
        save_to_memory,
        create_file_tool,
        tool_stats,
        system_doctor,
        memory_review
    ]
    
    response = llm_heavy.bind_tools(tech_tools).invoke(final_messages)
    return {"current_agent": "Tech_Agent", "messages": [response]}




def git_agent_node(state):
    from core.utils import load_agent_prompt, build_prompt
    from config import BASE_DIR

    # [MASTRO-SHIELD v5]: Ενιαία ασπίδα για όλους τους agents
    history = clean_orphan_tool_calls(state["messages"], k=40)
    safe_history = sanitize_history_for_gemini(history)

    system_base = load_agent_prompt("Git_Agent", "Είσαι ο Git_Agent. Διαχειρίζεσαι GitHub repos.")
    system_base = system_base.replace("{BASE_DIR}", BASE_DIR)
    system_prompt = build_prompt(history, system_base, channel=state.get("channel"))

    git_llm = llm.bind_tools([
        github_manager, search_memory, run_terminal_command, list_recent_files
    ])
    response = safe_llm_invoke(git_llm, [SystemMessage(content=system_prompt)] + safe_history)
    response = _ensure_text_response(response, git_llm, system_prompt, safe_history)

    return {"current_agent": "Git_Agent", "messages": [response]}


def mail_agent_node(state):
    from core.utils import load_agent_prompt, extract_list_selection_index
    from config import BASE_DIR  
    
    # [MASTRO-SHIELD]: Καθαρισμός ορφανών tool_calls
    history = clean_orphan_tool_calls(state["messages"], k=40)
    
    system_base = load_agent_prompt("Mail_Agent", "Είσαι ο Mail_Agent. Διαχειρίζεσαι το Gmail.")
    system_base = system_base.replace("{BASE_DIR}", BASE_DIR)
    system_prompt = build_prompt(history, system_base, channel=state.get("channel"))

    # [MASTRO-FIX v4]: Inject known email IDs into system_prompt.
    # Prefer newest IDs from recent turns, so "διάβασέ το" keeps working on
    # the mail the user just discussed instead of an older email in history.
    import re as _re_mail
    _known_ids = []
    for _hmsg in reversed(history):
        _hc = clean_message(getattr(_hmsg, 'content', '') or '')
        for _hm in _re_mail.finditer(r'ID: ([a-f0-9]{16})', _hc):
            _heid = _hm.group(1)
            if _heid not in _known_ids:
                _known_ids.append(_heid)
    if _known_ids:
        _top_id = _known_ids[0]
        _id_str = ', '.join("'" + e + "'" for e in _known_ids[:5])
        system_prompt = system_prompt + ('\n\n[EMAIL IDs APO ANAZHTHSH]: '
            + _id_str + '. An thelei na diavazeis email, kalese AMESA '
            'mail_manager(action="read_full" ή "read_thread" για όλη τη συνομιλία, email_id=' + _top_id + '). '
            'MHN kaneis search xana.')

    # [MASTRO-FIX v3]: Elegxos MONO tool results apo to trexon turn
    # (meta to teleutaio human message) — apofigee cross-turn triggering
    # pou mplokarei to read action prin kathesei na ginei.
    last_human_idx = next(
        (len(history) - 1 - i for i, m in enumerate(reversed(history))
         if getattr(m, "type", "") == "human"),
        0
    )
    mail_tool_results = []
    for msg in history[last_human_idx:]:
        if getattr(msg, "type", "") == "tool":
            content = clean_message(getattr(msg, "content", "")).strip()
            if content.startswith("ID: ") or content.startswith("📩 Περιεχόμενο:") or content.startswith("📩 Ολόκληρη η"):
                mail_tool_results.append(content)

    if mail_tool_results:
        # [MASTRO-FIX v2]: Bypass sanitize_history - to LLM antigrafe to
        # "[Klisi Ergaleiou: mail_manager]" pou paragei sanitize_history gia to
        # proto tool-call AIMessage. Ant autou: katharo 2-msg prompt me embedded results.
        # [MASTRO-FIX v4 auto-read]: An mono search results, auto-do read
        import re as _re_ar
        _search_hits = [r for r in mail_tool_results if r.startswith('ID: ')]
        _read_hits = [r for r in mail_tool_results
                      if 'Περιεχόμενο:' in r or 'Ολόκληρη η συνομιλία' in r]
        # Guard: if read_full already dispatched this turn, skip auto-read
        _read_dispatched = any(
            any(tc.get('args', {}).get('action') in ['read_full', 'read_thread']
                for tc in (getattr(msg, 'tool_calls', None) or []))
            for msg in history[last_human_idx:]
            if getattr(msg, 'type', '') == 'ai'
        )
        # Έλεγχος πρόθεσης χρήστη
        user_q = next(
            (clean_message(m.content) for m in reversed(history)
             if getattr(m, "type", "") == "human"),
            ""
        )
        user_wants_read = any(kw in user_q.lower() for kw in ["διάβασ", "διαβασ", "άνοιξ", "ανοιξ", "τι λέει", "τι λεει", "περισσότερα", "δες το", "λεπτομέρεια"])
        selected_idx = extract_list_selection_index(user_q)

        if _search_hits and not _read_hits and not _read_dispatched and user_wants_read:
            user_wants_thread = any(kw in user_q.lower() for kw in ["όλη τη", "ολη τη", "συνομιλία", "συζήτηση", "thread", "όλα τα", "ολα τα"])
            action_to_use = "read_thread" if user_wants_thread else "read_full"
            chosen_hit = _search_hits[selected_idx] if selected_idx is not None and 0 <= selected_idx < len(_search_hits) else _search_hits[0]

            _ar_match = _re_ar.search(r'ID: ([a-f0-9]{16})', chosen_hit)
            if _ar_match:
                _ar_eid = _ar_match.group(1)
                _auto_msg = AIMessage(
                    content='',
                    tool_calls=[{
                        'name': 'mail_manager',
                        'id': 'auto-read-' + _ar_eid[:8],
                        'args': {'action': action_to_use, 'email_id': _ar_eid}
                    }]
                )
                return {'current_agent': 'Mail_Agent', 'messages': [_auto_msg]}
        elif not _read_hits and not _read_dispatched and user_wants_read and _known_ids:
            user_wants_thread = any(kw in user_q.lower() for kw in ["όλη τη", "ολη τη", "συνομιλία", "συζήτηση", "thread", "όλα τα", "ολα τα"])
            action_to_use = "read_thread" if user_wants_thread else "read_full"
            _ar_eid = _known_ids[selected_idx] if selected_idx is not None and 0 <= selected_idx < len(_known_ids) else _known_ids[0]
            _auto_msg = AIMessage(
                content='',
                tool_calls=[{
                    'name': 'mail_manager',
                    'id': 'auto-read-' + _ar_eid[:8],
                    'args': {'action': action_to_use, 'email_id': _ar_eid}
                }]
            )
            return {'current_agent': 'Mail_Agent', 'messages': [_auto_msg]}
        # Has read results or no valid ID -> synthesize below
        joined_results = "\n\n".join(mail_tool_results[:5])[:4000]
        user_q = next(
            (clean_message(m.content) for m in reversed(history)
             if getattr(m, "type", "") == "human"),
            "Τι βρήκες;"
        )
        synthesis_prompt = (
            f"{system_base}\n\n"
            "ΑΠΟΤΕΛΕΣΜΑΤΑ ΑΝΑΖΗΤΗΣΗΣ EMAIL (από mail_manager):\\n"
            f"{joined_results}\n\n"
            "Με βάση τα παραπάνω, δώσε σύντομη καθαρή απάντηση στον Λάζαρο. "
            "ΜΗΝ καλέσεις εργαλεία. Απλή περίληψη στα Ελληνικά, με 2-4 πρακτικά "
            "next steps αν το email ζητά ενέργεια."
        )
        response = safe_llm_invoke(llm, [
            SystemMessage(content=synthesis_prompt),
            HumanMessage(content=user_q),
        ])
        resp_text = clean_message(getattr(response, "content", "")).strip()
        # An to LLM epistrefei tool-call string, xrisimopoioume ta raw results
        if not resp_text or resp_text.startswith("[Κλήση Εργαλείου:"):
            resp_text = "📩 " + "\n\n".join(mail_tool_results[:3])[:1500]
            response = AIMessage(content=resp_text)
        return {"current_agent": "Mail_Agent", "messages": [response]}

    mail_llm = llm.bind_tools([mail_manager])
    response = safe_llm_invoke(mail_llm, [SystemMessage(content=system_prompt)] + sanitize_history_for_gemini(history))
    response = _ensure_text_response(response, mail_llm, system_prompt, sanitize_history_for_gemini(history))

    return {
        "current_agent": "Mail_Agent",
        "messages": [response]
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
    manage_list, set_local_reminder, read_local_file, github_manager,
    mail_manager, get_news, drive_manager, get_weather_forecast,
    google_calendar_tool, save_to_memory, google_tasks_tool, delete_from_memory,
    search_memory, retrieve_photo, write_code, run_code, write_custom_tool,
    control_vacuum, get_navigation_info,
    control_spotify, search_goldmall_offers, execute_local_pipeline, get_current_location,
    recipe_expert, log_meal, create_file_tool, run_terminal_command, search_google_places, search_flights, learn_routine, edit_routine, delete_routine, get_routines, control_routine_notifications, control_routine_schedule, control_routine_condition, control_routine_cooldown, control_pending_followup, browse_url,
    duckduckgo_search, search_supermarket_prices, tool_stats, system_doctor
]
