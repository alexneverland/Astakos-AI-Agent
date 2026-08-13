# ================================================================
# Project: Astakos AI Agent 🦞
# Description: Modular LLM-agnostic multi-agent framework
# Copyright (c) 2026 - All Rights Reserved
# ================================================================

import os
import json
import re
import unicodedata
from datetime import datetime
from langchain_core.tools import tool
from config import BASE_DIR, RESPONSE_LANGUAGE, KID1_NAME

# Mastro-Import: Bringing the brain into the tool!
from core.brain import llm
from core.utils import clean_message 
from core.i18n import t

from astakos_skills.recipe_library import save_generated_recipe, RecipeLibraryError

HISTORY_FILE = os.path.join(BASE_DIR, "astakos_skills", "food_history.json")

_MEAL_STOPWORDS = {
    t("prompts.ext_str_835"), t("prompts.ext_str_776"), t("prompts.ext_str_772"), t("prompts.ext_str_685"), t("prompts.ext_str_804"), t("prompts.ext_str_724"), t("prompts.ext_str_839"), t("prompts.ext_str_832"), t("prompts.ext_str_786"), t("prompts.ext_str_843"), t("prompts.ext_str_846"), t("prompts.ext_str_847"),
    t("prompts.ext_str_831"), t("prompts.ext_str_840"), t("prompts.ext_str_806"), t("prompts.ext_str_800"), t("prompts.ext_str_827"), t("prompts.ext_str_297"), t("prompts.ext_str_590"), t("prompts.ext_str_530"), t("prompts.ext_str_588")
}


def _normalize_meal_name(meal_name: str) -> set[str]:
    text = meal_name.lower().strip()
    text = "".join(
        char for char in unicodedata.normalize("NFD", text)
        if unicodedata.category(char) != "Mn"
    )
    text = re.sub(r"[^\w]+", " ", text)
    return {
        token for token in text.split()
        if len(token) > 1 and token not in _MEAL_STOPWORDS
    }


def _is_same_meal(left: str, right: str) -> bool:
    left_tokens = _normalize_meal_name(left)
    right_tokens = _normalize_meal_name(right)
    if not left_tokens or not right_tokens:
        return left.strip().lower() == right.strip().lower()

    intersection = left_tokens & right_tokens
    shorter = min(len(left_tokens), len(right_tokens))
    longer = max(len(left_tokens), len(right_tokens))

    if shorter >= 2 and len(intersection) == shorter:
        return True
    return len(intersection) / longer >= 0.75


def _parse_meal_datetime(value: str):
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(str(value or "").strip(), fmt)
        except ValueError:
            continue
    return None


def _is_recent_same_meal(existing_meal: dict, meal_name: str, now: datetime, hours: int = 36) -> bool:
    if not _is_same_meal(existing_meal.get("name", ""), meal_name):
        return False
    meal_dt = _parse_meal_datetime(existing_meal.get("date", ""))
    if not meal_dt:
        return False
    delta_hours = (now - meal_dt).total_seconds() / 3600
    return 0 <= delta_hours <= hours


def get_recent_meals():
    if not os.path.exists(HISTORY_FILE):
        return []
    try:
        with open(HISTORY_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
            return [entry['name'] for entry in data[-7:]]
    except:
        return []

@tool
def recipe_expert(
    query: str,
    user_context: str,
    ingredients: str = "",
    recipe_name: str = "",
    external_content_sources_json: str = "",
) -> str:
    """
    ⚠️ SOS: YOU MUST CALL THIS TOOL for every question regarding food, menus, or recipes.
    The tool will return the recipe, but THE USER DOES NOT SEE IT automatically.
    YOU MUST COPY the tool's result INTO your final response!
    DO NOT say 'I left it for you above', because the user cannot see the tool's output!
    query: The user's question (e.g., 'What should I cook?')
    user_context: Copy here the MEMORIES you saw regarding the family's preferences.
    ingredients: (Optional) Available ingredients.
    recipe_name: Set only when generating one complete named recipe. Leave blank for generic three-option suggestions.
    """
    recent = get_recent_meals()
    print(f"\n[Tool Debug] 👨‍🍳 Chef Astakos is preparing suggestions...")
    # The tool executes the call internally... (The rest of the code remains the same)
    from core.i18n import load_prompt
    prompt = load_prompt("recipe_expert.md").format(
        user_context=user_context,
        recent_meals=', '.join(recent),
        ingredients=ingredients if ingredients else 'Not specified',
        query=query if query else 'Suggest 3 meals',
        RESPONSE_LANGUAGE=RESPONSE_LANGUAGE,
        KID1_NAME=KID1_NAME,
        recipe_name=recipe_name.strip() or "Not specified",
    )
    
    try:
        # The tool makes its own call to Gemini!
        response = llm.invoke(prompt)
        # [MASTRO-SHIELD]: clean_message instead of raw .content
        # so as to correctly handle parts lists from Gemini 3.x
        recipe_text = clean_message(response.content)
        if recipe_name.strip():
            try:
                from core.untrusted_content import external_content_sources_from_json

                external_content_sources = external_content_sources_from_json(
                    external_content_sources_json,
                )
                if external_content_sources:
                    save_generated_recipe(
                        recipe_name,
                        recipe_text,
                        external_content_sources=external_content_sources,
                    )
                else:
                    save_generated_recipe(recipe_name, recipe_text)
            except (OSError, RecipeLibraryError) as e:
                print(f"⚠️ Failed to save recipe to library: {e}")
        return recipe_text
    except Exception as e:
        return t("skills.recipe_expert.msg_chef_error", e=str(e))


@tool
def log_meal(meal_name: str):
    """
    Permanently records the selected food in food_history.json.
    """
    history = []
    print(f"\n[Tool Debug] 📝 Logging meal in JSON: {meal_name}")
    
    now = datetime.now()
    today_str = now.strftime("%Y-%m-%d")
    
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, 'r', encoding='utf-8') as f:
                history = json.load(f)
        except: pass
        
    meal_name = meal_name.strip()
    if not meal_name:
        return t("skills.recipe_expert.no_name")

    # [MASTRO-FIX]: Check if a similar meal has already been logged TODAY
    for meal in history:
        # We get the YYYY-MM-DD from "2026-05-21 21:30"
        meal_date = meal.get("date", "").split(" ")[0] 
        existing_name = meal.get("name", "")
        if (meal_date == today_str and _is_same_meal(existing_name, meal_name)) or _is_recent_same_meal(meal, meal_name, now):
            print("⚠️ Preventing duplicate meal entry!")
            return (
                t("skills.recipe_expert.msg_duplicate", name=existing_name)
            )
        
    history.append({
        "name": meal_name, 
        "date": now.strftime("%Y-%m-%d %H:%M")
    })
    
    with open(HISTORY_FILE, 'w', encoding='utf-8') as f:
        json.dump(history[-30:], f, ensure_ascii=False, indent=4)
        
    return t("skills.recipe_expert.msg_recorded", name=meal_name)

