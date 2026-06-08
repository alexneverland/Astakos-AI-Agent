# ================================================================
# Project: Astakos AI Agent 🦞
# Developer: Lazaros (Piston-7)
# Description: Modular LLM-agnostic multi-agent framework
# Copyright (c) 2026 - All Rights Reserved
# ================================================================

import os
import json
import re
import unicodedata
from datetime import datetime
from langchain_core.tools import tool
from config import BASE_DIR

# Mastro-Import: Φέρνουμε τον εγκέφαλο μέσα στο εργαλείο!
from core.brain import llm
from core.utils import clean_message 

HISTORY_FILE = os.path.join(BASE_DIR, "astakos_skills", "food_history.json")

_MEAL_STOPWORDS = {
    "με", "και", "στο", "στον", "στη", "στην", "το", "τη", "την", "τα", "ο", "η",
    "οι", "σε", "για", "απο", "από", "μεσημερι", "βραδυ", "σημερα", "αυριο"
}


def _normalize_meal_name(meal_name: str) -> set[str]:
    text = meal_name.lower().strip()
    text = "".join(
        char for char in unicodedata.normalize("NFD", text)
        if unicodedata.category(char) != "Mn"
    )
    text = re.sub(r"[^a-zα-ω0-9]+", " ", text)
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
def recipe_expert(query: str, user_context: str, ingredients: str = ""):
    """
    ⚠️ SOS: ΚΑΛΕΣΕ ΑΥΤΟ ΤΟ ΕΡΓΑΛΕΙΟ ΥΠΟΧΡΕΩΤΙΚΑ για κάθε ερώτηση σχετικά με φαγητό, μενού ή συνταγές.
    ΠΑΡΑΓΕΙ ΤΗΝ ΤΕΛΙΚΗ ΑΠΑΝΤΗΣΗ ΠΟΥ ΠΡΕΠΕΙ ΝΑ ΔΩΣΕΙΣ. ΑΠΑΓΟΡΕΥΕΤΑΙ ΝΑ ΑΠΑΝΤΗΣΕΙΣ ΑΠΟ ΤΟ ΚΕΦΑΛΙ ΣΟΥ.
    query: Η ερώτηση του χρήστη (π.χ. 'Τι να μαγειρέψω;')
    user_context: Αντίγραψε εδώ τις ΜΝΗΜΕΣ που είδες για τις προτιμήσεις της οικογένειας.
    ingredients: (Προαιρετικό) Διαθέσιμα υλικά.
    """
    recent = get_recent_meals()
    print(f"\n[Tool Debug] 👨‍🍳 Ο Chef Αστακός ετοιμάζει προτάσεις...")
    # Το εργαλείο εκτελεί την κλήση εσωτερικά... (Ο υπόλοιπος κώδικας μένει ίδιος)
    prompt = f"""
    Είσαι ο Chef του σπιτιού. Λειτούργησε βάσει των εξής:
    
    1. ΠΕΡΙΟΡΙΣΜΟΙ/ΠΡΟΤΙΜΗΣΕΙΣ (Από Μνήμη): {user_context}
    2. ΠΡΟΣΦΑΤΑ ΓΕΥΜΑΤΑ (Απόφυγέ τα αυστηρά): {', '.join(recent)}
    3. ΔΙΑΘΕΣΙΜΑ ΥΛΙΚΑ: {ingredients if ingredients else 'Δεν ορίστηκαν'}
    4. ΑΙΤΗΜΑ: {query if query else 'Πρόταση 3 γευμάτων'}
    
    ΟΔΗΓΙΕΣ ΕΚΤΕΛΕΣΗΣ:
    - Αν υπάρχουν υλικά, πρότεινε συνταγές που τα χρησιμοποιούν.
    - Αν ζητήθηκε συγκεκριμένη συνταγή, δώσε αναλυτικά υλικά και εκτέλεση, προσαρμοσμένα ώστε να τα τρώνε τα παιδιά (ειδικά ο Αλέξανδρος που τρώει μόνο φακές/φασόλια από όσπρια).
    - Αν το αίτημα είναι γενικό, δώσε 3 επιλογές (Το Σίγουρο, Το Γρήγορο, Το Διαφορετικό).
    """
    
    try:
        # Το εργαλείο κάνει τη δική του κλήση στο Gemini!
        response = llm.invoke(prompt)
        # [MASTRO-SHIELD]: clean_message αντί για raw .content
        # ώστε να χειριστεί σωστά λίστες parts από Gemini 3.x
        return clean_message(response.content)
    except Exception as e:
        return f"❌ Σφάλμα κατά την παραγωγή της συνταγής από τον Chef: {str(e)}"


@tool
def log_meal(meal_name: str):
    """
    Καταγράφει οριστικά το φαγητό που επιλέχθηκε στο food_history.json.
    """
    history = []
    print(f"\n[Tool Debug] 📝 Καταγραφή γεύματος στο JSON: {meal_name}")
    
    now = datetime.now()
    today_str = now.strftime("%Y-%m-%d")
    
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, 'r', encoding='utf-8') as f:
                history = json.load(f)
        except: pass
        
    meal_name = meal_name.strip()
    if not meal_name:
        return "⚠️ Δεν δόθηκε όνομα γεύματος για καταγραφή."

    # [MASTRO-FIX]: Έλεγχος αν παρόμοιο γεύμα έχει ήδη καταγραφεί ΣΗΜΕΡΑ
    for meal in history:
        # Παίρνουμε το YYYY-MM-DD από το "2026-05-21 21:30"
        meal_date = meal.get("date", "").split(" ")[0] 
        existing_name = meal.get("name", "")
        if (meal_date == today_str and _is_same_meal(existing_name, meal_name)) or _is_recent_same_meal(meal, meal_name, now):
            print("⚠️ Αποτροπή διπλοεγγραφής γεύματος!")
            return (
                f"⚠️ Παρόμοιο γεύμα έχει ΗΔΗ καταγραφεί πρόσφατα: "
                f"'{existing_name}'. Μην το ξαναγράφεις."
            )
        
    history.append({
        "name": meal_name, 
        "date": now.strftime("%Y-%m-%d %H:%M")
    })
    
    with open(HISTORY_FILE, 'w', encoding='utf-8') as f:
        json.dump(history[-30:], f, ensure_ascii=False, indent=4)
        
    return f"✅ Το γεύμα '{meal_name}' καταγράφηκε επιτυχώς."
