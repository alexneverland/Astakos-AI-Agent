# ================================================================
# Project: Astakos AI Agent 🦞
# Description: Modular LLM-agnostic multi-agent framework
# Copyright (c) 2026 - All Rights Reserved
# ================================================================

from copy import copy
from core.i18n import t
import os
import config
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
from config import PHOTOS_DIR, WORKING_MEMORY_FILE, RESPONSE_LANGUAGE
from core.brain import llm, llm_heavy, safe_llm_invoke
from astakos_skills.recipe_expert import recipe_expert, log_meal
from astakos_skills.recipe_library import search_recipe_library, get_saved_recipe, mark_recipe_favorite
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
    mail_manager, github_manager, control_vacuum, control_spotify, learn_routine, edit_routine, delete_routine, get_routines, search_routines, control_routine_notifications, control_routine_schedule, control_routine_condition, control_routine_cooldown, control_pending_followup, create_file_tool, run_terminal_command, generate_image_tool, post_to_linkedin, get_current_location, get_fit_summary,
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
from astakos_skills.read_agent_skill import list_agent_skills, read_agent_skill
from astakos_skills.officecli_skill import run_officecli
from astakos_skills.manage_context_flag import manage_context_flag
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
    Gemini quirk: sometimes returns empty content after tool execution.
    Retry up to 3 times with escalating instructions.
    """
    ensure_started = perf_counter()
    retry_count = 0

    if clean_message(response.content).strip() or getattr(response, "tool_calls", []):
        _attach_phase_timing(response, "ensure_text_ms", int((perf_counter() - ensure_started) * 1000))
        _attach_phase_timing(response, "ensure_text_retries", retry_count)
        return response  # All OK

    suffixes = [
        f"\n\n[MANDATORY]: You must reply with text to the user. Inform them about what happened. IMPORTANT: Ignore the language of any internal tool outputs. You MUST respond EXCLUSIVELY in {RESPONSE_LANGUAGE}.",
        f"\n\n[CRITICAL]: Write IMMEDIATELY a summary of the results you found. Do not make any more tool calls. IMPORTANT: Ignore the language of any internal tool outputs. You MUST respond EXCLUSIVELY in {RESPONSE_LANGUAGE}.",
        f"\n\n[FINAL]: Give a short answer, even 1 sentence, to the user right now. IMPORTANT: Ignore the language of any internal tool outputs. You MUST respond EXCLUSIVELY in {RESPONSE_LANGUAGE}.",

    ]
    for attempt, suffix in enumerate(suffixes, 1):
        print(f"\033[93m[Gemini-Fix]: Empty response — retry {attempt}/3...\033[0m")
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
    return response  # We return the original if all else fails

# ────────────────────────────────────────────────────────────────
# [MASTRO-SHIELD]: Central cleanup of orphaned tool_calls
# Used by ALL agents to avoid 400 INVALID_ARGUMENT
# ────────────────────────────────────────────────────────────────

def clean_orphan_tool_calls(history: list, k: int = 40) -> list:
    """
    [MASTRO-SHIELD v5]: Sterilizer for Gemini 3.x sequence errors.

    Removes AIMessages that have a tool call and are NOT followed by a
    corresponding ToolMessage. Gemini requires a strict sequence:
        AI(tool_call) → Tool(result)
    If the Tool is missing → 400 INVALID_ARGUMENT.

    Two ways to detect a tool call in an AIMessage:
      1. Traditional: msg.tool_calls populated (Gemini 1.x/2.x).
      2. [NEW v5]: The content is a list and contains a part of type
         "function_call" or "tool_use" — this happens with Gemini 3.x when
         langchain_google_genai does not properly unpack native parts into
         the tool_calls attribute.

    If an orphan is detected, we keep only the text part (if it exists) as
    a regular AIMessage. If no text exists, we discard it completely.
    """
    # First pass: basic filtering from filter_messages
    history = filter_messages(history, k=k)

    clean = []
    for i, msg in enumerate(history):
        if getattr(msg, "type", "") != "ai":
            clean.append(msg)
            continue

        # Check 1: tool_calls attribute (traditional way)
        tool_calls = getattr(msg, "tool_calls", [])
        expected_ids = set(tc.get("id") for tc in tool_calls if isinstance(tc, dict) and tc.get("id"))

        # Check 2: function_call/tool_use parts within the content list (Gemini 3.x)
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
                # Orphaned tool call — we only keep the text content if it exists_
                text_only = clean_message(raw_content) if raw_content else ""
                if text_only:
                    clean.append(AIMessage(content=text_only))
                # If it doesn't have text, we skip it entirely
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
    ] = Field(description=t("prompts.ext_str_86"))


def supervisor_node(state):
    from core.utils import load_agent_prompt, clean_message
    from config import BASE_DIR
    from core.capability_lookup import lookup_agent

    router_llm = llm.with_structured_output(Router)
    last_content = clean_message(state['messages'][-1].content)

    # ── /plan: higher priority than everything else ────────────────────
    # We use regex because the server prepends a timestamp [HH:MM] to the message
    import re as _re
    if _re.search(r'(?:^|\])\s*/plan', last_content.strip()):
        print(f"\033[95m[Router]: -> planner (/plan command)\033[0m")
        return {"next_agent": "planner"}

    # ── Capability Registry: first filter before the LLM ───────────
    registry_agent = lookup_agent(str(last_content))
    if registry_agent:
        print(f"\033[95m[Router]: -> {registry_agent} (registry)\033[0m")
        return {"next_agent": registry_agent}

    # ── LLM fallback: normal Supervisor decision ─────────────────
    system_base = load_agent_prompt("supervisor", f"You are the {config.BOT_NAME} Supervisor.")
    system_base = system_base.replace("{BASE_DIR}", BASE_DIR)

    recent_msgs = state['messages'][-5:-1]
    context_lines = []
    for m in recent_msgs:
        role = t("prompts.ext_str_437") if getattr(m, "type", "") == "human" else t("prompts.ext_str_350")
        text = clean_message(m.content)[:150]
        if text:
            context_lines.append(f"{role}: {text}")

    context_str = "\n".join(context_lines) if context_lines else ""

    if context_str:
        full_prompt = f"{system_base}\n\n[PREVIOUS CONVERSATION - for context]\n{context_str}\n\nNEW COMMAND: '{str(last_content)[:500]}'\n\nIMPORTANT: Ignore the language of any internal tool outputs. You MUST respond EXCLUSIVELY in {RESPONSE_LANGUAGE}."
    else:
        full_prompt = f"{system_base}\n\nUser: '{str(last_content)[:500]}'\n\nIMPORTANT: Ignore the language of any internal tool outputs. You MUST respond EXCLUSIVELY in {RESPONSE_LANGUAGE}."

    decision = safe_llm_invoke(router_llm, full_prompt)
    print(f"\033[95m[Router]: -> {decision.next_agent} (llm)\033[0m")
    return {"next_agent": decision.next_agent}


# ────────────────────────────────────────────────────────────────
# AGENT NODES
# ────────────────────────────────────────────────────────────────

def dev_agent_node(state):
    from core.utils import load_agent_prompt
    from config import BASE_DIR  
    
    # [MASTRO-SHIELD]: Cleanup of orphan tool_calls — same for all agents
    history = clean_orphan_tool_calls(state["messages"], k=40)
    
    system_base = load_agent_prompt("Dev_Agent", f"You are the Dev_Agent, {config.BOT_NAME}' Chief Developer.")
    system_base = system_base.replace("{BASE_DIR}", BASE_DIR)
    prompt_content = build_prompt(history, system_base, channel=state.get("channel"))

    tools = [
        write_code, run_code, read_local_file, write_custom_tool, register_tool,
        delete_from_memory, search_memory, save_to_memory,
        execute_local_pipeline, control_spotify, control_vacuum, 
        get_navigation_info, recipe_expert, log_meal, 
        generate_image_tool, search_flights, run_terminal_command, learn_routine, edit_routine, delete_routine, get_routines, search_routines, control_routine_notifications, control_routine_schedule, control_routine_condition, control_routine_cooldown, control_pending_followup,
        save_goal_tool, update_goal_status_tool,
        duckduckgo_search,
        # Project tools — code navigation & editing
        grant_project_access, list_project_files, read_project_file,
        edit_project_file, write_project_file, grep_project_files, repo_mapper,
        list_recent_files, list_agent_skills, read_agent_skill, run_officecli, manage_context_flag,
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
    
    # [MASTRO-SHIELD]: Cleanup of orphan tool_calls
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

    detailed_keywords = config.NLP_CONFIG.get("tools", {}).get("detailed_keywords", [])
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
                print(f"\033[94m[Agent Logic]: The {filename} is a document. Bypassing Vision.\033[0m")
        except Exception as e:
            print(f"⚠️ [Vision/File Error]: {e}")

    vision_context = ""
    if pre_baked_analysis:
        vision_context = f"\n[FILE/PHOTO CONTEXT]: You already have this description/information: '{pre_baked_analysis}'.\n"

    json_base = load_agent_prompt("Chat_Agent", f"You are {config.BOT_NAME}, {config.USER_NAME}'s trusted buddy.")
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
    from services.messenger_intent import is_create_draft_intent

    # [FAREWELL GUARD]: If the user says goodbye, we remove archive_file
    # so that the LLM does not automatically archive files that are in the context.
    _FAREWELL_WORDS = tuple(config.NLP_CONFIG.get("tools", {}).get("greetings", []))
    _is_farewell = any(w in last_msg_text.lower() for w in _FAREWELL_WORDS)

    chat_tools = [
        get_current_location, control_spotify,
        search_memory, save_to_memory, delete_from_memory, retrieve_photo, duckduckgo_search,
        recipe_expert, log_meal, search_recipe_library, get_saved_recipe, mark_recipe_favorite, learn_routine, edit_routine, delete_routine, get_routines, search_routines, control_routine_notifications, control_routine_schedule, control_routine_condition, control_routine_cooldown, control_pending_followup, search_supermarket_prices,
        *(
            [relay_local_payload]
            if is_create_draft_intent(last_msg_text)
            else []
        ),
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
        search_memory, control_spotify, control_vacuum, get_current_location,
        learn_routine, edit_routine, delete_routine, get_routines, search_routines,
        control_routine_notifications, control_routine_schedule, control_routine_condition, control_routine_cooldown, control_pending_followup
    )
    from tools.web import get_navigation_info, search_goldmall_offers
    from astakos_skills.recipe_expert import recipe_expert, log_meal
    from astakos_skills.recipe_library import search_recipe_library, get_saved_recipe, mark_recipe_favorite
    
    # [MASTRO-SHIELD]: Cleaning up orphan tool_calls
    history = clean_orphan_tool_calls(state["messages"], k=40)

    tools_to_bind = [
        get_current_location,
        manage_list, set_local_reminder, delete_from_memory, search_memory,
        control_spotify, control_vacuum,
        search_goldmall_offers, get_navigation_info,
        google_calendar_tool, google_tasks_tool, recipe_expert, log_meal, search_recipe_library, get_saved_recipe, mark_recipe_favorite, learn_routine, edit_routine, delete_routine, get_routines, search_routines, control_routine_notifications, control_routine_schedule, control_routine_condition, control_routine_cooldown, control_pending_followup, search_supermarket_prices,
        get_fit_summary, manage_context_flag
    ]

    system_base = load_agent_prompt("Home_Agent", f"You are {config.DEVELOPER_NAME}'s Home_Agent.")
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


_WEB_RESEARCH_TOOL_NAMES = frozenset({
    "duckduckgo_search",
    "browse_url",
})
_WEB_RESEARCH_CALL_BUDGET = 3


def _web_research_tool_call_name(tool_call) -> str:
    """Return a tool-call name from mapping or object response shapes."""
    if isinstance(tool_call, dict):
        return str(tool_call.get("name") or "")
    return str(getattr(tool_call, "name", "") or "")


def _count_web_research_calls(messages: list) -> int:
    """Count generic Web research calls in the current user turn."""
    research_calls = 0

    for message in reversed(messages or []):
        if getattr(message, "type", "") == "human":
            break

        for tool_call in getattr(message, "tool_calls", []) or []:
            if _web_research_tool_call_name(tool_call) in _WEB_RESEARCH_TOOL_NAMES:
                research_calls += 1

    return research_calls


def _has_exhausted_web_research_budget(messages: list) -> bool:
    """Return true when generic Web research reached its current-turn budget."""
    return _count_web_research_calls(messages) >= _WEB_RESEARCH_CALL_BUDGET


def _trim_web_research_tool_calls(response, messages: list):
    """Keep generic Web research calls within the remaining turn budget."""
    tool_calls = getattr(response, "tool_calls", []) or []
    if not tool_calls:
        return response

    remaining_calls = max(
        0,
        _WEB_RESEARCH_CALL_BUDGET - _count_web_research_calls(messages),
    )
    retained_calls = []

    for tool_call in tool_calls:
        if _web_research_tool_call_name(tool_call) in _WEB_RESEARCH_TOOL_NAMES:
            if remaining_calls <= 0:
                continue
            remaining_calls -= 1
        retained_calls.append(tool_call)

    if len(retained_calls) == len(tool_calls):
        return response

    retained_call_ids = {
        (
            tool_call.get("id")
            if isinstance(tool_call, dict)
            else getattr(tool_call, "id", None)
        )
        for tool_call in retained_calls
    }
    retained_call_ids.discard(None)

    trimmed_content = getattr(response, "content", None)
    if isinstance(trimmed_content, list):
        trimmed_content = [
            part
            for part in trimmed_content
            if not (
                isinstance(part, dict)
                and part.get("type") in ("function_call", "tool_use")
                and part.get("id") not in retained_call_ids
            )
        ]

    updates = {
        "content": trimmed_content,
        "tool_calls": retained_calls,
    }
    model_copy = getattr(response, "model_copy", None)
    if callable(model_copy):
        trimmed_response = model_copy(update=updates)
    else:
        trimmed_response = copy(response)
        trimmed_response.content = trimmed_content
        trimmed_response.tool_calls = retained_calls
    return _merge_phase_timings(trimmed_response, response)


def _is_stale_messenger_send_call(response) -> bool:
    """True only when the model tries to send a draft that no longer exists."""
    tool_calls = getattr(response, "tool_calls", []) or []
    if len(tool_calls) != 1:
        return False

    tool_call = tool_calls[0]
    if tool_call.get("name") != "execute_local_pipeline":
        return False

    args = tool_call.get("args", {}) or {}
    if args.get("target_name") or args.get("message"):
        return False

    from core.messenger_draft import active_draft_status

    is_active, _, _ = active_draft_status()
    return not is_active


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

    # [MASTRO-SHIELD]: Cleanup of orphan tool_calls
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

    system_base = load_agent_prompt("Web_Agent", "You are the Web_Agent.")
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
    from astakos_skills.morning_briefing import morning_briefing
    from astakos_skills.hn_briefing import hn_briefing
    web_tools = [
        get_current_location,
        get_news, get_weather_forecast, duckduckgo_search, 
        search_memory, get_navigation_info, retrieve_photo, read_local_file, 
        post_to_linkedin, generate_image_tool, update_pending_linkedin_post,
        process_and_clear_linkedin_post, search_google_places, execute_local_pipeline, browse_url, search_supermarket_prices, relay_local_payload, morning_briefing, hn_briefing
    ]

    if web_errors and not web_successes:
        guarded_reply = build_web_failure_reply(
            last_msg_text,
            recent_web_tool_results,
        )
        from langchain_core.messages import AIMessage as _AIMsg
        return {
            "messages": [_AIMsg(content=guarded_reply)],
            "current_agent": "Web_Agent",
        }

    if _has_exhausted_web_research_budget(history):
        research_synthesis_contract = load_agent_prompt(
            "Web_Research_Synthesis",
        )
        research_synthesis_prompt = "\n\n".join(
            part
            for part in (system_prompt, research_synthesis_contract)
            if part
        )
        result = llm.invoke([
            SystemMessage(content=research_synthesis_prompt),
            *final_messages[1:],
        ])
    else:
        result = llm.bind_tools(web_tools).invoke(final_messages)

    result = _trim_web_research_tool_calls(result, history)

    if _is_stale_messenger_send_call(result):
        print("[Messenger Guard]: blocked stale send call without an active draft.")

        recovery_prompt = (
            system_prompt
            + "\n\n[RUNTIME MESSENGER GUARD]\n"
            + "There is no active Messenger draft. Do not call "
              "execute_local_pipeline and do not mention Messenger or a draft "
              "unless the newest user message explicitly asks about one. "
              "Reply naturally to the newest user message."
        )
        result = llm.invoke([
            SystemMessage(content=recovery_prompt),
            *final_messages[1:],
        ])

    result = _ensure_text_response(result, llm, system_prompt, safe_history)
    content = clean_message(result.content).strip() if result.content else ""
    has_tool_calls = bool(getattr(result, "tool_calls", None))

    if not content and not has_tool_calls:
        fallback = AIMessage(content=t("tools.web.empty_synthesis"))
        _merge_phase_timings(fallback, result)
        _attach_phase_timing(fallback, "web_empty_synthesis_fallback", 1)
        result = fallback

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
    
    # [MASTRO-SHIELD]: Cleaning orphan tool_calls — this resolved the 400 error
    history = clean_orphan_tool_calls(state["messages"], k=40)
    last_msg_text = clean_message(history[-1].content) if history else ""

    analysis_match = re.search(r"\[ANALYSIS\]:\s*(.*)", last_msg_text)
    path_match = re.search(r"\[(?:PHOTO PATH|USER_UPLOADED_PHOTO|USER_UPLOADED_FILE)\]:\s*([^\s\n\]]+)", last_msg_text)
    
    pre_baked_analysis = analysis_match.group(1).strip() if analysis_match else None
    image_part = None

    tech_keywords = config.NLP_CONFIG.get("tools", {}).get("tech_keywords", [])
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
                print(f"\033[94m[Agent Logic]: The {filename} is a document. Bypassing Vision.\033[0m")
        except Exception as e:
            print(f"⚠️ Tech Vision Error: {e}")

    vision_info = f"\n[FILE/PHOTO CONTEXT]: You already have this analysis: '{pre_baked_analysis}'.\n" if pre_baked_analysis else ""
    json_base = load_agent_prompt("Tech_Agent", f"You are the Tech_Agent, {config.USER_NAME}'s technical expert.")
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
        save_to_memory, create_file_tool, get_current_location, tool_stats, system_doctor, memory_review,
        run_terminal_command, write_code, run_code
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
        memory_review,
        run_officecli,
        run_terminal_command,
        write_code,
        run_code
    ]
    
    response = llm_heavy.bind_tools(tech_tools).invoke(final_messages)
    return {"current_agent": "Tech_Agent", "messages": [response]}




def git_agent_node(state):
    from core.utils import load_agent_prompt, build_prompt
    from config import BASE_DIR

    # [MASTRO-SHIELD v5]: Unified shield for all agents
    history = clean_orphan_tool_calls(state["messages"], k=40)
    safe_history = sanitize_history_for_gemini(history)

    system_base = load_agent_prompt("Git_Agent", "You are the Git_Agent. You manage GitHub repos.")
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
    
    # [MASTRO-SHIELD]: Cleanup of orphan tool_calls
    history = clean_orphan_tool_calls(state["messages"], k=40)
    
    system_base = load_agent_prompt("Mail_Agent", "You are the Mail_Agent. You manage Gmail.")
    system_base = system_base.replace("{BASE_DIR}", BASE_DIR)
    system_prompt = build_prompt(history, system_base, channel=state.get("channel"))

    # [MASTRO-FIX v4]: Inject known email IDs into system_prompt.
    # Prefer newest IDs from recent turns, so "read it" keeps working on
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
        system_prompt = system_prompt + ('\n\n[EMAIL IDs FROM SEARCH]: '
            + _id_str + '. If the user wants to read an email, IMMEDIATELY call '
            'mail_manager(action="read_full" or "read_thread" for the entire conversation, email_id=' + _top_id + '). '
            'DO NOT search again.')

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
            if content.startswith("ID: ") or content.startswith(t("prompts.ext_str_147")) or content.startswith(t("prompts.ext_str_165")):
                mail_tool_results.append(content)

    if mail_tool_results:
        # [MASTRO-FIX v2]: Bypass sanitize_history - to LLM antigrafe to
        # "[Klisi Ergaleiou: mail_manager]" pou paragei sanitize_history gia to
        # proto tool-call AIMessage. Ant autou: katharo 2-msg prompt me embedded results.
        # [MASTRO-FIX v4 auto-read]: An mono search results, auto-do read
        import re as _re_ar
        _search_hits = [r for r in mail_tool_results if r.startswith('ID: ')]
        _read_hits = [r for r in mail_tool_results
                      if t("prompts.ext_str_173") in r or t("prompts.ext_str_62") in r]
        # Guard: if read_full already dispatched this turn, skip auto-read
        _read_dispatched = any(
            any(tc.get('args', {}).get('action') in ['read_full', 'read_thread']
                for tc in (getattr(msg, 'tool_calls', None) or []))
            for msg in history[last_human_idx:]
            if getattr(msg, 'type', '') == 'ai'
        )
        # User intent check
        user_q = next(
            (clean_message(m.content) for m in reversed(history)
             if getattr(m, "type", "") == "human"),
            ""
        )
        user_wants_read = any(kw in user_q.lower() for kw in config.NLP_CONFIG.get("intents", {}).get("read_words", []))
        selected_idx = extract_list_selection_index(user_q)

        if _search_hits and not _read_hits and not _read_dispatched and user_wants_read:
            user_wants_thread = any(kw in user_q.lower() for kw in config.NLP_CONFIG.get("intents", {}).get("thread_words", []))
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
            user_wants_thread = any(kw in user_q.lower() for kw in config.NLP_CONFIG.get("intents", {}).get("thread_words", []))
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
            t("prompts.ext_str_233")
        )
        synthesis_prompt = (
            f"{system_base}\n\n"
            "EMAIL SEARCH RESULTS (from mail_manager):\\n"
            f"{joined_results}\n\n"
            f"Based on the above, provide a short, clear answer to {config.USER_NAME}. "
            f"DO NOT call tools. Ignore internal tool language. Simple summary EXCLUSIVELY in {RESPONSE_LANGUAGE}, with 2-4 practical "
            "next steps if the email requires action."
        )
        response = safe_llm_invoke(llm, [
            SystemMessage(content=synthesis_prompt),
            HumanMessage(content=user_q),
        ])
        resp_text = clean_message(getattr(response, "content", "")).strip()
        # An to LLM epistrefei tool-call string, xrisimopoioume ta raw results
        if not resp_text or resp_text.startswith(t("prompts.ext_str_100")):
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
    recipe_expert, log_meal, create_file_tool, run_terminal_command, search_google_places, search_flights, learn_routine, edit_routine, delete_routine, get_routines, search_routines, control_routine_notifications, control_routine_schedule, control_routine_condition, control_routine_cooldown, control_pending_followup, browse_url, duckduckgo_search, manage_context_flag,
    search_supermarket_prices, tool_stats, system_doctor, run_officecli
]
