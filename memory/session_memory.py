# ================================================================
# Project: Astakos AI Agent 🦞
# Developer: Lazaros (Piston-7)
# Description: Modular LLM-agnostic multi-agent framework
# Copyright (c) 2026 - All Rights Reserved
# ================================================================

import os
import json
from datetime import datetime
from memory.vector_store import memory
from services.gemini import safe_gemini_call
import re
from config import PHOTOS_INDEX_FILE, PHOTOS_DIR, SESSIONS_FILE
# ════════════════════════════════════════════════════════════════
# SESSION SUMMARY — "Ημερολόγιο Συνεργάτη"
# ════════════════════════════════════════════════════════════════

SESSION_LOG: list[dict] = []


def log_exchange(user_text: str, ai_text: str, agent: str):
    """Προσθέτει ένα ζεύγος ερώτησης-απάντησης στο session log."""
    SESSION_LOG.append({
        "time": datetime.now().strftime("%H:%M"),
        "agent": agent,
        "user": user_text[:300],
        "ai": ai_text[:300],
    })


def load_last_session_hint() -> str:
    """Φορτώνει το hint της τελευταίας session."""
    try:
        import os
        if not os.path.exists(SESSIONS_FILE):
            return ""
        with open(SESSIONS_FILE, "r", encoding="utf-8") as f:
            sessions = json.load(f)
        if not sessions:
            return ""
        last = sessions[-1]
        hint = last.get("next_session_hint", "")
        pending = last.get("pending", [])
        date = last.get("date", "")
        if not hint and not pending:
            return ""
        parts = [f"[Τελευταία session: {date}]"]
        if hint:
            parts.append(f"Να θυμάσαι: {hint}")
        if pending:
            parts.append(f"Εκκρεμή: {', '.join(pending[:3])}")
        return " | ".join(parts)
    except:
        return ""


is_summarizing = False  # Πρέπει να οριστεί έξω από τη συνάρτηση

def _run_session_summary():
    """Αρχειοθετεί τη συνεδρία με προστασία από διπλοεγγραφές."""
    global is_summarizing, SESSION_LOG
    
    # 1. Ασπίδα: Αν ήδη τρέχει ή αν δεν υπάρχουν μηνύματα, βγες αμέσως
    if is_summarizing or not SESSION_LOG:
        return

    try:
        is_summarizing = True
        print("\n\033[94m[Session]: Έναρξη αρχειοθέτησης συνεδρίας...\033[0m")
        
        # 2. Αδειάζουμε το κεντρικό log ΑΜΕΣΩΣ για να μην το ξαναπιάσει άλλος worker
        current_batch = list(SESSION_LOG)
        SESSION_LOG.clear()

        dialogue_text = "\n".join([
            f"[{e['time']} / {e['agent']}] Λάζαρος: {e['user']} | Αστακός: {e['ai']}"
            for e in current_batch
        ])

        # 3. Το prompt με αυστηρό format ημερομηνίας (για να ταιριάζει με τα παλιά σου logs)
        summary_prompt = f"""
Ανάλυσε αυτή τη συνομιλία μεταξύ Λάζαρου και Αστακού και συμπλήρωσε ένα JSON αναφοράς.
Απάντησε ΜΟΝΟ με το JSON.

{{
  "date": "{datetime.now().strftime('%Y-%m-%d %H:%M')}",
  "summary": "2-3 προτάσεις τι συζητήθηκε σήμερα",
  "completed": ["λίστα από πράγματα που ολοκληρώθηκαν"],
  "pending": ["λίστα από πράγματα που έμειναν ημιτελή"],
  "next_session_hint": "Τι πρέπει να θυμάται ο Αστακός για την επόμενη φορά",
  "mood": "productive|relaxed|debugging|planning"
}}

[ΣΥΝΟΜΙΛΙΑ]
{dialogue_text}
"""
        response = safe_gemini_call(summary_prompt)
        raw = re.sub(r"```json|```", "", response.text.strip()).strip()

        try:
            summary = json.loads(raw)
        except json.JSONDecodeError:
            # Αν αποτύχει, ξαναβάζουμε τα μηνύματα πίσω για να μην τα χάσουμε
            SESSION_LOG.extend(current_batch)
            print("\033[91m[Session]: Μη έγκυρο format. Τα μηνύματα επεστράφησαν στο log.\033[0m")
            return

        # 4. Εμπλουτισμός του κειμένου για τη Vector DB
        session_text = (
            f"[SESSION {summary.get('date', '')}] {summary.get('summary', '')} "
            f"Εκκρεμότητες: {', '.join(summary.get('pending', [])) if summary.get('pending') else 'καμία'}. "
            f"Hint: {summary.get('next_session_hint', '')}"
        )

        # 5. Αποθήκευση (Εδώ ο MemoryManager θα κάνει και το overwrite αν χρειαστεί)
        memory.save(memory_type="session", summary=summary, session_text=session_text)
        print(f"\033[92m[Session]: ✅ Αρχειοθετήθηκε επιτυχώς! Mood: {summary.get('mood', '?')}\033[0m")

    except Exception as e:
        # Recovery σε περίπτωση σφάλματος
        SESSION_LOG.extend(current_batch)
        print(f"\033[91m[Session Error]: {e}\033[0m")
    finally:
        is_summarizing = False


# ════════════════════════════════════════════════════════════════
# MEMORY SIFTER — "Αρχειοθέτης"
# ════════════════════════════════════════════════════════════════

def _run_memory_sifter(user_text: str, ai_text: str, agent_name: str = "Unknown"):
    """
    Αναλύει τον διάλογο, εξάγει μνήμες για τη ChromaDB 
    και ενημερώνει το JSON index φωτογραφιών με πλήρη ανάλυση.
    """
    MEMORY_CATS = {
        "lazaros":  "Προτιμήσεις, συνήθειες, τρόπος σκέψης, δουλειά του Λάζαρου",
        "family":   "Πληροφορίες για Σοφία, Αλέξανδρο, Μαρία, κατοικίδια",
        "projects": "Mastroapp, PraxisERP, Αστακός, Paletes, Shiftmaster",
        "home":     "Σπίτι, εξοπλισμός, συσκευές, Piston-7",
        "lesson":   "Τεχνικά μαθήματα, λύσεις bugs, κανόνες για τον Αστακό",
        "photos":   "Φωτογραφίες, περιγραφή και paths",
    }

    try:
        # 1. Προετοιμασία Prompt για το Gemini
        cats_desc = "\n".join([f'  - "{k}": {v}' for k, v in MEMORY_CATS.items()])
        
        sifter_prompt = f"""
Είσαι ο Αρχειοθέτης του Αστακού. Εξάγεις ΜΟΝΟ αξιόλογες, νέες μνήμες.

Αν ο χρήστης ανέβασε φωτογραφία (σήμα [USER_UPLOADED_PHOTO] ή [PHOTO PATH]), ΠΡΕΠΕΙ να βγάλεις:
- caption: Μια σύντομη λεζάντα στα Ελληνικά (π.χ. 'Ο Αλέξανδρος και το κουνέλι').
- analysis: Μια πλήρη περιγραφή στα Αγγλικά βασισμένη σε όσα είπε ο Αστακός.

ΚΑΤΗΓΟΡΙΕΣ:
{cats_desc}

ΚΑΝΟΝΕΣ:
1. Κάθε μνήμη (fact) ΠΡΕΠΕΙ να ξεκινάει με: [USER_FACT], [CAPABILITY], [LESSON], ή [PHOTO].
2. ΜΟΡΦΗ JSON array: [{{"fact": "[TAG]: ...", "category": "...", "caption": "...", "analysis": "..."}}]
3. Αν δεν υπάρχει νέα πληροφορία → απάντησε ΜΟΝΟ: ΚΕΝΟ.

[Agent: {agent_name}]
Λάζαρος: {user_text}
Αστακός: {ai_text}
"""
        response = safe_gemini_call(sifter_prompt)
        raw_text = response.text.strip()
        
        if "ΚΕΝΟ" in raw_text or not raw_text:
            return

        raw_clean = re.sub(r"```json|```", "", raw_text).strip()
        if not raw_clean.startswith("["):
            return
            
        # --- [MASTRO-JSON-SHIELD]: Αυτόματη διόρθωση για ξεχασμένα κόμματα του LLM ---
        try:
            memories = json.loads(raw_clean)
        except json.JSONDecodeError:
            try:
                # Καθαρίζουμε trailing commas πριν από κλείσιμο λίστας ή αντικειμένου
                fixed_raw = re.sub(r',\s*\]', ']', raw_clean)
                fixed_raw = re.sub(r',\s*\}', '}', fixed_raw)
                memories = json.loads(fixed_raw)
                print("\033[93m[Sifter Fixer]: ✅ Το JSON επισκευάστηκε αυτόματα!\033[0m")
            except:
                print("\033[91m⚠️ [Sifter Error]: Το LLM έβγαλε εντελώς κακογραμμένο JSON. Παράκαμψη εγγραφής.\033[0m")
                return

        for mem in memories:
            fact = mem.get("fact", "").strip()
            category = mem.get("category", "lazaros")
            
            # 2. --- ΤΟ ΣΩΣΤΟ JSON INDEXING (Mastro-Restore) ---
            if "[PHOTO]" in fact or category == "photos":
                # Regex για να βρούμε το filename από το user_text
                match = re.search(r"(?:USER_UPLOADED_PHOTO|PHOTO PATH)\]:\s*([^\s\n\]]+)", user_text)
                if match:
                    filename = os.path.basename(match.group(1).strip().replace("]", ""))
                else:
                    filename = os.path.basename(fact.split(":")[-1].strip().replace("]", ""))
                
                file_path = os.path.join(PHOTOS_DIR, filename)

                # Αν το Gemini δεν έβγαλε analysis, παίρνουμε την απάντηση του AI ως analysis
                analysis_val = mem.get("analysis")
                if not analysis_val or analysis_val == "No analysis provided.":
                    analysis_val = ai_text # Backup από τον διάλογο

                photo_entry = {
                    "file_path": file_path,
                    "analysis": analysis_val,
                    "caption": mem.get("caption", "Φωτογραφία από τον Λάζαρο"),
                    "date": datetime.now().strftime("%Y-%m-%d"),
                    "timestamp": datetime.now().isoformat()
                }

                # Φόρτωση και ενημέρωση του κεντρικού JSON
                photo_index = []
                if os.path.exists(PHOTOS_INDEX_FILE):
                    with open(PHOTOS_INDEX_FILE, "r", encoding="utf-8") as f:
                        try: photo_index = json.load(f)
                        except: photo_index = []
                
                if not any(p.get("file_path") == file_path for p in photo_index):
                    photo_index.append(photo_entry)
                    with open(PHOTOS_INDEX_FILE, "w", encoding="utf-8") as f:
                        json.dump(photo_index, f, indent=4, ensure_ascii=False)
                    print(f"\033[92m📸 [Index]: Η φωτογραφία {filename} αρχειοθετήθηκε επιτυχώς.\033[0m")

            # 3. Αποθήκευση στη ChromaDB
            memory.save(
                memory_type="fact",
                fact=fact,
                category=category,
                agent_name=agent_name
            )

    except Exception as e:
        print(f"⚠️ [Sifter Error]: {e}")


def trigger_memory_sifter(user_text: str, ai_text: str, agent_name: str = "Unknown"):
    """Wrapper — εκτελείται μέσω Queue Worker."""
    _run_memory_sifter(user_text, ai_text, agent_name)