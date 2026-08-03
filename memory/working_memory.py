# ================================================================
# Project: Astakos AI Agent 🦞
# Description: Modular LLM-agnostic multi-agent framework
# Copyright (c) 2026 - All Rights Reserved
# ================================================================

import config
from core.i18n import t
from core import nl_config
import os
import json
import re
import threading
from datetime import datetime
import sqlite3
from typing import Iterable
from langchain_core.messages import HumanMessage
from config import WORKING_MEMORY_FILE, STATE_DB
from memory.vector_store import memory, is_semantically_duplicate, memory_lock  # [MASTRO-FIX]: ONE lock, not two
from core.utils import clean_message, load_agent_prompt
from core.brain import llm, safe_llm_invoke

# ════════════════════════════════════════════════════════════════
# WORKING MEMORY — "Foreground" (what the user is doing now)
# ════════════════════════════════════════════════════════════════

def _validate_working_memory_tags(raw_text: str) -> str:
    """
    Accept only EMPTY or 1-3 short comma-separated tags.
    Reject verbose / explanatory / malformed LLM output.
    """
    text = clean_message(raw_text).strip()
    if not text:
        return ""

    if text.upper() == "EMPTY":
        return "EMPTY"

    if "\n" in text:
        return ""

    # Reject obvious reasoning / prose / markdown / labels
    banned_markers = (
        "because",
        "i think",
        "the user",
        "analysis",
        "reasoning",
        "here are",
        "tags:",
        "1.",
        "2.",
        "- ",
        "* ",
        "```",
    )
    lowered = text.lower()
    if any(marker in lowered for marker in banned_markers):
        return ""

    parts = [part.strip() for part in text.split(",")]
    parts = [part for part in parts if part]

    if not 1 <= len(parts) <= 3:
        return ""

    validated = []
    for part in parts:
        # Short tags only
        word_count = len(part.split())
        if word_count == 0 or word_count > 4:
            return ""

        # Reject long/prosy fragments
        if len(part) > 40:
            return ""

        if any(ch in part for ch in "\n\r\t;{}[]"):
            return ""

        validated.append(part)

    return ", ".join(validated)


def _has_standalone_marker(text: str, markers: tuple[str, ...]) -> bool:
    """Return whether a configured marker appears without being part of a larger word."""
    return any(
        re.search(rf"(?<!\w){re.escape(marker)}(?!\w)", text)
        for marker in markers
    )


def _looks_like_operational_working_memory_exchange(user_text: str, ai_text: str) -> bool:
    """
    Skip foreground-memory extraction for operational routine/tool-management
    exchanges. These are not useful "what the user is doing now" tags and can
    leak internal tool/i18n labels into the working-memory prompt.
    """
    user_norm = clean_message(user_text).strip().lower()
    ai_norm = clean_message(ai_text).strip().lower()
    combined = f"{user_norm}\n{ai_norm}"

    if not combined.strip():
        return False

    internal_label_markers = (
        "_routine_conditions",
        "_shift_only",
        "turn-off_routine",
        "turn_off_routine",
        "[tools.system.",
        "[clients.",
        "[api.",
    )
    if any(marker in combined for marker in internal_label_markers):
        return True

    user_routine_admin = (
        any(marker in user_norm for marker in nl_config.WM_ROUTINE_REFERENCE_MARKERS)
        and _has_standalone_marker(
            user_norm,
            nl_config.WM_ROUTINE_ADMIN_MARKERS,
        )
    )
    if user_routine_admin:
        return True

    if any(marker in ai_norm for marker in nl_config.WM_OPERATIONAL_AI_MARKERS):
        return True

    return False


def update_working_memory(
    user_text: str,
    ai_text: str,
    external_content_sources: Iterable[str] | None = None,
) -> None:
    """Instantly extracts context tags unless the exchange derives from external content."""
    try:
        print("\033[90m[System]: Started Foreground analysis...\033[0m")

        if external_content_sources:
            print("\033[90m[Foreground]: external-derived exchange - skip automatic memory write\033[0m")
            print(f"{config.USER_NAME}: ", end="", flush=True)
            return

        # We put on the "glasses" (Smart Parser) before cutting the characters
        safe_user = clean_message(user_text)
        safe_ai = clean_message(ai_text)

        if _looks_like_operational_working_memory_exchange(safe_user, safe_ai):
            print("\033[90m[Foreground]: operational routine/tool exchange - skip\033[0m")
            print(f"{config.USER_NAME}: ", end="", flush=True)
            return

        # We select the last 400 characters
        user_context = safe_user[-400:] if len(safe_user) > 400 else safe_user
        ai_context = safe_ai[-400:] if len(safe_ai) > 400 else safe_ai

        base_prompt = load_agent_prompt("memory_sifter")
        prompt = base_prompt.format(user_context=user_context, ai_context=ai_context)

        response = safe_llm_invoke(llm, [HumanMessage(content=prompt)])

        raw_tags = clean_message(response.content)
        new_tags = _validate_working_memory_tags(raw_tags)

        print(f"\n\033[94m[DEBUG Foreground Raw]: '{raw_tags}'\033[0m")
        print(f"\033[94m[DEBUG Foreground Validated]: '{new_tags}'\033[0m")

        if new_tags == "EMPTY" or not new_tags:
            print(f"{config.USER_NAME}: ", end="", flush=True)
            return

        from memory.vector_store import memory # Make sure this import exists
        memory.save(memory_type="working", new_tags=new_tags)
        print(f"\033[92m[Foreground JSON]: WRITTEN -> {new_tags}\033[0m")
        print(f"{config.USER_NAME}: ", end="", flush=True)

    except Exception as e:
        print(f"\n\033[91m[Working Memory Error]: {e}\033[0m")
        print(f"{config.USER_NAME}: ", end="", flush=True)


# ════════════════════════════════════════════════════════════════
# CAPABILITIES LOG — "Self-awareness"
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
    # [MASTRO-FIX]: Use of memory_lock from vector_store — one lock for everything
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

            # Threshold 0.88 OK for capabilities (general abilities)
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
    t("prompts.ext_str_252"), t("prompts.ext_str_250"), t("prompts.ext_str_424"), t("prompts.ext_str_381"), t("prompts.ext_str_171"), t("prompts.ext_str_170"),
    t("prompts.ext_str_186"), t("prompts.ext_str_190"), t("prompts.ext_str_224"), t("prompts.ext_str_203"), t("prompts.ext_str_145"), t("prompts.ext_str_137"),
    t("prompts.ext_str_193"), t("prompts.ext_str_178"), t("prompts.ext_str_164"), t("prompts.ext_str_146"), t("prompts.ext_str_136"),
    "kid1", "partner", "owner"
)

_ASSISTANT_SUBJECT_MARKERS = (
    t("prompts.ext_str_247"), t("prompts.ext_str_276"), t("prompts.ext_str_244"), t("prompts.ext_str_237"), t("prompts.ext_assistant"),
    t("prompts.ext_str_219"), t("prompts.ext_str_242"),
    t("prompts.ext_str_332"), t("prompts.ext_str_303"), "api", "tool", "pipeline",
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
        parts.append(t("prompts.ext_str_40") + " | ".join(can))
    if data.get("cannot_do"):
        cannot = [str(c) for c in data["cannot_do"][-3:]]
        parts.append(t("prompts.ext_str_35") + " | ".join(cannot))
    return "\n".join(parts) if parts else ""


def update_capabilities_from_exchange(user_text: str, ai_text: str, agent: str) -> str | None:
    import re
    import json
    try:
        from core.utils import load_agent_prompt
        base_prompt = load_agent_prompt("memory_awareness")
        cap_prompt = base_prompt.format(agent=agent, user_text=user_text[:500], ai_text=ai_text[:500])
        from services.gemini import safe_gemini_call
        response = safe_gemini_call(cap_prompt)
        
        resp_text = response.text if hasattr(response, 'text') else str(response)
        if not resp_text or resp_text.strip().lower() == "null":
            return None
            
        raw = re.sub(r"```json|```", "", resp_text.strip()).strip()
        start = raw.find('{')
        end = raw.rfind('}')
        if start != -1 and end != -1:
            raw = raw[start:end+1]
            
        if raw.lower() == "null" or not raw:
            return None
            
        data = json.loads(raw)

        if data.get("can_do") and str(data["can_do"]).lower() != "null":
            if _looks_like_user_fact_not_capability(data["can_do"]):
                print(f"\033[90m[Self-awareness]: skip user fact, not can_do: {data['can_do']}\033[0m")
            else:
                result = _save_capability("can", data["can_do"])
                if result == "inserted":
                    print(f"\033[96m[Self-awareness]: ✅ can_do: {data['can_do']}\033[0m")
                elif result == "duplicate":
                    print(f"\033[90m[Self-awareness]: skip duplicate can_do: {data['can_do']}\033[0m")
            
        if data.get("cannot_do") and str(data["cannot_do"]).lower() != "null":
            if _looks_like_user_fact_not_capability(data["cannot_do"]):
                print(f"\033[90m[Self-awareness]: skip user fact, not cannot_do: {data['cannot_do']}\033[0m")
            else:
                result = _save_capability("cannot", data["cannot_do"])
                if result == "inserted":
                    print(f"\033[91m[Self-awareness]: ❌ cannot_do: {data['cannot_do']}\033[0m")
                    return str(data["cannot_do"])
                elif result == "duplicate":
                    print(f"\033[90m[Self-awareness]: skip duplicate cannot_do: {data['cannot_do']}\033[0m")
            
    except Exception as e:
        print(f"\033[90m[Self-awareness Error]: {e}\033[0m")

    return None

