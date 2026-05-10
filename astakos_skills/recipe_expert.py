# ================================================================
# Project: Astakos AI Agent 🦞
# Developer: Lazaros (Piston-7)
# Description: Modular LLM-agnostic multi-agent framework
# Copyright (c) 2026 - All Rights Reserved
# ================================================================

import os
import json
from datetime import datetime
from langchain_core.tools import tool
from config import BASE_DIR

# Mastro-Import: Φέρνουμε τον εγκέφαλο μέσα στο εργαλείο!
from core.brain import llm 

HISTORY_FILE = os.path.join(BASE_DIR, "astakos_skills", "food_history.json")

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
        return response.content
    except Exception as e:
        return f"❌ Σφάλμα κατά την παραγωγή της συνταγής από τον Chef: {str(e)}"


@tool
def log_meal(meal_name: str):
    """
    Καταγράφει οριστικά το φαγητό που επιλέχθηκε στο food_history.json.
    """
    history = []
    print(f"\n[Tool Debug] 📝 Καταγραφή γεύματος στο JSON: {meal_name}")
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, 'r', encoding='utf-8') as f:
                history = json.load(f)
        except: pass
        
    history.append({
        "name": meal_name, 
        "date": datetime.now().strftime("%Y-%m-%d %H:%M")
    })
    
    with open(HISTORY_FILE, 'w', encoding='utf-8') as f:
        json.dump(history[-30:], f, ensure_ascii=False, indent=4)
        
    return f"✅ Το γεύμα '{meal_name}' καταγράφηκε επιτυχώς."