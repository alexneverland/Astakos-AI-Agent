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
        return f"❌ Δεν βρέθηκε η φωτογραφία: {image_path}"

    with open(image_path, "rb") as f:
        img_b64 = base64.b64encode(f.read()).decode("utf-8")

    hint_line = f"Το προϊόν είναι: {product_hint}." if product_hint else ""

    prompt = f"""You are an expert in ingredient analysis and product safety. You analyze labels from any product.
{hint_line}

Step 1: Identify the category: FOOD / COSMETIC / HOUSEHOLD / MEDICINE / OTHER
Step 2: Identify the ingredients you see.
Step 3: Evaluate on a scale of 1-10 based on the category:
  - Food: healthiness, additives, sugar, salt
  - Cosmetic: skin safety, parabens, fragrances, allergens
  - Household: toxicity, environmental footprint
Step 4: Add a comment for children (around 6 years old) if relevant.

IMPORTANT RULE: You MUST answer EXCLUSIVELY in {RESPONSE_LANGUAGE}, using EXACTLY the following format:

🏷️ **[Όνομα προϊόντος] — [Κατηγορία]**

📋 **Συστατικά που εντόπισα:** [λίστα]

⭐ **Βαθμολογία:** X/10 [🟢≥7 / 🟡4-6 / 🔴≤3]

✅ **Καλό:**
- ...

⚠️ **Πρόσεξε:**
- ...

👶 **Για παιδιά:** [σχόλιο ή "Δεν εφαρμόζεται"]

💡 **Σύσταση:** [1 πρόταση]"""

    vision_msg = HumanMessage(content=[
        {"type": "text",      "text": prompt},
        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"}}
    ])

    try:
        response = llm.invoke([vision_msg])
        return clean_message(response.content)
    except Exception as e:
        return f"❌ Σφάλμα ανάλυσης: {e}"
