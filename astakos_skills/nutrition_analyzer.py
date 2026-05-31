# ================================================================
# Project: Astakos AI Agent 🦞
# Skill:   Nutrition Analyzer — /nutrition
# Ανάλυση συστατικών τροφίμου από φωτογραφία (ετικέτα/συσκευασία).
# ================================================================

import os
import base64
import requests
from datetime import datetime
from config import BASE_DIR

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN") or ""


def analyze_nutrition(image_path: str, product_hint: str = "") -> str:
    """
    Παίρνει path φωτογραφίας, στέλνει στο Vision LLM και επιστρέφει
    ανάλυση διατροφικής αξίας / υγιεινότητας σε Ελληνικά.
    """
    from core.brain import llm
    from core.agents import clean_message
    from langchain_core.messages import HumanMessage

    if not os.path.exists(image_path):
        return f"❌ Δεν βρέθηκε η φωτογραφία: {image_path}"

    with open(image_path, "rb") as f:
        img_b64 = base64.b64encode(f.read()).decode("utf-8")

    hint_line = f"Το προϊόν είναι: {product_hint}." if product_hint else ""

    prompt = f"""Είσαι ειδικός ανάλυσης συστατικών και ασφάλειας προϊόντων. Αναλύεις ετικέτες από οποιοδήποτε προϊόν.
{hint_line}

Βήμα 1: Προσδιόρισε την κατηγορία: ΤΡΟΦΙΜΟ / ΚΑΛΛΥΝΤΙΚΟ / ΟΙΚΙΑΚΟ / ΦΑΡΜΑΚΟ / ΑΛΛΟ
Βήμα 2: Αναγνώρισε τα συστατικά που βλέπεις.
Βήμα 3: Αξιολόγησε 1-10 ανάλογα με κατηγορία:
  - Τρόφιμο: υγιεινότητα, additives, ζάχαρη, αλάτι
  - Καλλυντικό: ασφάλεια δέρματος, παραβένες, αρώματα, allergens
  - Οικιακό: τοξικότητα, περιβαλλοντικό αποτύπωμα
Βήμα 4: Σχόλιο για παιδιά (6 ετών) αν είναι σχετικό.

Απάντησε ΑΠΟΚΛΕΙΣΤΙΚΑ με αυτή τη μορφή (Ελληνικά):

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
