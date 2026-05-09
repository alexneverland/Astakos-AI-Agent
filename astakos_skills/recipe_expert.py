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

HISTORY_FILE = r'C:\astakos_v2\astakos_skills\food_history.json'

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
def recipe_expert(query: str = None, ingredients: str = None, user_context: str = ""):
    """
    Universal εργαλείο για συνταγές και προτάσεις γευμάτων.
    query: Συγκεκριμένο φαγητό ή επιθυμία (π.χ. 'Συνταγή για μουσακά' ή 'κάτι ελαφρύ').
    ingredients: Λίστα με υλικά που υπάρχουν (π.χ. 'κοτόπουλο, πιπεριές, φέτα').
    user_context: Πληροφορίες από τη μνήμη (RAG) για το τι τρώει η οικογένεια.
    """
    recent = get_recent_meals()
    
    # Το εργαλείο επιστρέφει το "πλαίσιο" και το Brain (Gemini) αναλαμβάνει τη δημιουργία
    instruction = f"""
    Είσαι ο Chef του σπιτιού. Λειτούργησε βάσει των εξής:
    
    1. ΠΕΡΙΟΡΙΣΜΟΙ/ΠΡΟΤΙΜΗΣΕΙΣ (Από Μνήμη): {user_context}
    2. ΠΡΟΣΦΑΤΑ ΓΕΥΜΑΤΑ (Απόφυγέ τα): {', '.join(recent)}
    3. ΔΙΑΘΕΣΙΜΑ ΥΛΙΚΑ: {ingredients if ingredients else 'Δεν ορίστηκαν'}
    4. ΑΙΤΗΜΑ: {query if query else 'Πρόταση 3 γευμάτων'}
    
    ΟΔΗΓΙΕΣ ΕΚΤΕΛΕΣΗΣ:
    - Αν υπάρχουν υλικά, πρότεινε συνταγές που τα χρησιμοποιούν.
    - Αν ζητήθηκε συγκεκριμένη συνταγή, δώσε αναλυτικά υλικά και εκτέλεση, προσαρμοσμένα ώστε να τα τρώνε ο Αλέξανδρος και η Μαρία.
    - Αν το αίτημα είναι γενικό, δώσε 3 επιλογές (Το Σίγουρο, Το Γρήγορο, Το Διαφορετικό).
    - Πάντα να λαμβάνεις υπόψη ότι ο Αλέξανδρος τρώει μόνο φακές/φασόλια από όσπρια.
    """
    return instruction

@tool
def log_meal(meal_name: str):
    """
    Καταγράφει οριστικά το φαγητό που επιλέχθηκε στο food_history.json.
    """
    history = []
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