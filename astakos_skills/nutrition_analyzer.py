# ================================================================
# Project: Astakos AI Agent 🦞
# Skill:   Nutrition Analyzer — /nutrition
# Analysis of food ingredients from a photo (label/packaging).
# ================================================================

import os
import base64
import requests
from datetime import datetime
from config import BASE_DIR, RESPONSE_LANGUAGE

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN") or ""


def analyze_nutrition(image_path: str, product_hint: str = "") -> str:
    """
    Takes a photo path, sends it to the Vision LLM, and returns
    a nutritional value / healthiness analysis in {RESPONSE_LANGUAGE}.
    """
    from core.brain import llm
    from core.agents import clean_message
    from langchain_core.messages import HumanMessage

    if not os.path.exists(image_path):
        return t("skills.nutrition_analyzer.msg_photo_not_found", path=image_path)

    with open(image_path, "rb") as f:
        img_b64 = base64.b64encode(f.read()).decode("utf-8")

    hint_line = f"The product is: {product_hint}." if product_hint else ""

    from core.i18n import load_prompt
    prompt = load_prompt("nutrition_analyzer.md").format(
        hint_line=hint_line,
        RESPONSE_LANGUAGE=RESPONSE_LANGUAGE
    )

    vision_msg = HumanMessage(content=[
        {"type": "text",      "text": prompt},
        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"}}
    ])

    try:
        response = llm.invoke([vision_msg])
        return clean_message(response.content)
    except Exception as e:
        return t("skills.nutrition_analyzer.msg_analysis_error", e=e)
