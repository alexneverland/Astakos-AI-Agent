# ================================================================
# Project: Astakos AI Agent 🦞
# Developer: Lazaros (Piston-7)
# Description: Modular LLM-agnostic multi-agent framework
# Copyright (c) 2026 - All Rights Reserved
# ================================================================

import os
import re
import json
import sys
import math
import subprocess
import base64
from datetime import datetime, timedelta
from langchain_core.tools import tool
from pypdf import PdfReader
from github import Github
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from google_auth_oauthlib.flow import InstalledAppFlow
from miio import Device
import spotipy
from spotipy.oauth2 import SpotifyOAuth
import docx
import pandas as pd
from config import (
    REMINDERS_FILE, LISTS_FILE, WORKSPACE_DIR, PHOTOS_INDEX_FILE, PHOTOS_DIR,
    EMAIL_ADDRESS, EMAIL_PASSWORD, GITHUB_TOKEN, VACUUM_IP, VACUUM_TOKEN, GPS_STORAGE_FILE
)
from astakos_skills.linkedin_state_manager import update_pending_linkedin_post, process_and_clear_linkedin_post
from memory.vector_store import vector_store, vector_lock, memory
from services.embeddings import embeddings
from tools.web import (
    get_news, get_weather_forecast, search_supermarket_prices,
    search_goldmall_offers, execute_local_pipeline, get_navigation_info,
    relay_local_payload, search_google_places, browse_url, duckduckgo_search
)
from astakos_skills.search_flights import search_flights
from astakos_skills.recipe_expert import recipe_expert, log_meal

# ────────────────────────────────────────────────────────────────
# CREDENTIALS PATHS
# ────────────────────────────────────────────────────────────────
_BASE = os.path.dirname(os.path.abspath(__file__))
TOKEN_PATH = os.path.join(_BASE, '..', 'credentials', 'token.json')
CREDS_PATH = os.path.join(_BASE, '..', 'credentials', 'credentials.json')

# ────────────────────────────────────────────────────────────────
# PROTECTED SANDBOX
# ────────────────────────────────────────────────────────────────
PROTECTED_FILES = ["main.py", "telegram_bot.py", "update.py", ".env"]
DANGEROUS_WORDS = [
    "os.remove", "os.rmdir", "shutil.rmtree", "format c:",
    "exec(", "eval(", "compile(", "__import__", "subprocess.run",
    "subprocess.call", "subprocess.Popen", "os.system"
]


# ────────────────────────────────────────────────────────────────
# MEMORY TOOLS
# ────────────────────────────────────────────────────────────────
@tool
def archive_file(filename: str, content_summary: str) -> str:
    """
    Αρχειοθετεί μόνιμα ένα αρχείο (φωτογραφία, έγγραφο, PDF) στη μνήμη (JSON + ChromaDB).
    filename: Το ακριβές τεχνικό όνομα του αρχείου (π.χ. web_xxx.pdf ή web_xxx.png).
    content_summary: Σύνοψη του περιεχομένου του εγγράφου ή η ανάλυση της εικόνας.
    """
    try:
        import os
        from config import BASE_DIR, PHOTOS_DIR
        from memory.vector_store import memory

        search_dirs = [
            PHOTOS_DIR,
            os.path.join(BASE_DIR, "outputs"),
            os.path.join(BASE_DIR, "telegram_uploads"),
            os.path.join(BASE_DIR, "telegram_photos"),
            os.path.join(BASE_DIR, "uploads")
        ]

        full_path = None
        for d in search_dirs:
            test_path = os.path.join(d, filename)
            if os.path.exists(test_path) and os.path.isfile(test_path):
                full_path = test_path
                break

        if not full_path:
            return f"❌ Σφάλμα: Το αρχείο {filename} δεν βρέθηκε."

        ext = os.path.splitext(full_path)[1].lower()
        m_type = "photo" if ext in [".jpg", ".jpeg", ".png", ".webp", ".gif"] else "document"

        memory.save(
            memory_type=m_type,
            file_path=full_path,
            analysis=content_summary,
            caption=f"Αρχειοθέτηση ({m_type}): {filename}"
        )
        return f"✅ Έγινε, Μάστορα! Το αρχείο {filename} ({m_type}) αρχειοθετήθηκε μόνιμα με τη σύνοψη που έδωσες."
    except Exception as e:
        return f"❌ Σφάλμα αρχειοθέτησης: {str(e)}"

# Channel για Memory Provenance — ορίζεται από server.py/telegram_bot.py
_CURRENT_CHANNEL: str = "unknown"

@tool
def search_memory(query: str, category: str = "") -> str:
    """Αναζήτηση στη μακροπρόθεσμη μνήμη. Κάλεσέ το ΜΙΑ ΦΟΡΑ ΜΟΝΟ. Αν έχεις ήδη [Πληροφορία από αναζήτηση] στο context ΜΗΝ ξανακαλέσεις. Χρησιμοποίησέ το πριν απαντήσεις σε:
    1. Ερωτήσεις για τον Λάζαρο, την οικογένεια, το σπίτι, τις συνήθειες ή τα projects.
    2. Ζητήματα που απαιτούν προτάσεις, συμβουλές ή λύσεις.
    3. Αναφορές στο παρελθόν ή στον εξοπλισμό που υπάρχει.

    Args:
        query: Keywords (π.χ. 'Αλέξανδρος φαγητό', 'Mastroapp backend')
        category: Προαιρετικό φίλτρο: 'lazaros', 'family', 'projects', 'home', 'lesson', 'photos'
    """
    VALID_CATS = {"lazaros", "family", "projects", "home", "lesson", "session", "photos"}
    try:
        with vector_lock:
            if category and category in VALID_CATS:
                results = vector_store.similarity_search(query, k=6, filter={"category": category})
            else:
                results = vector_store.similarity_search(query, k=6)

        if not results:
            return "System: Δεν βρέθηκε καμία σχετική μνήμη. Απάντα με τις γενικές σου γνώσεις."

        # bump retrieval_count για τα αποτελέσματα
        try:
            from memory.vector_store import bump_retrieval_count
            with vector_lock:
                kwargs = {"n_results": min(6, len(results))}
                if category and category in VALID_CATS:
                    kwargs["where"] = {"category": category}
                raw = vector_store._collection.query(
                    query_embeddings=[embeddings.embed_query(query)], **kwargs
                )
            if raw.get("ids") and raw["ids"][0]:
                bump_retrieval_count(raw["ids"][0])
        except Exception as _be:
            pass

        by_cat: dict = {}
        for res in results:
            cat = res.metadata.get("category", "general")
            content = res.page_content
            photo_path = res.metadata.get("photo_path")
            if photo_path:
                content += f" [PHOTO_PATH: {photo_path}]"
            by_cat.setdefault(cat, []).append(content)

        output = "ΜΝΗΜΕΣ ΠΟΥ ΒΡΕΘΗΚΑΝ:\n"
        for cat, facts in by_cat.items():
            output += f"\n[{cat.upper()}]\n"
            for f in facts:
                output += f"  • {f}\n"
        return output.strip()
    except Exception as e:
        return f"Error: Σφάλμα ανάκλησης μνήμης: {str(e)}"
@tool
def run_terminal_command(command: str, already_approved: bool = False) -> str:
    """
    Εκτελεί εντολές PowerShell στο PC του Λάζαρου (Piston-7) και επιστρέφει το αποτέλεσμα.
    Ιδανικό για:
    - Ανάγνωση logs (π.χ. 'Get-Content C:\\path\\to\\mastroapp\\logs\\error.log -Tail 50').
    - Έλεγχο ports (π.χ. 'netstat -ano | findstr 8000').
    - Εκτέλεση tests (π.χ. 'python manage.py test').
    already_approved=True: παρακάμπτει μόνο το confirmation gate, όχι BLOCKED εντολές.
    """
    import subprocess
    from core.safe_executor import safe_execute, classify_command, ExecPolicy
    print(f"\033[93m[Terminal Execution]: {command}\033[0m")

    def _executor(cmd):
        try:
            result = subprocess.run(
                ["powershell", "-Command", cmd],
                capture_output=True, text=True, timeout=30,
                encoding='utf-8', errors='ignore'
            )
            output = result.stdout or ""
            if result.returncode != 0:
                output += f"\nERROR:\n{result.stderr}"
            elif result.stderr:
                output += f"\nWARNINGS:\n{result.stderr}"

            if not output.strip():
                return {"status": "ok", "output": "Εκτελέστηκε επιτυχώς (δεν επέστρεψε output)."}

            if len(output) > 10000:
                output = output[:10000] + "\n... [output truncated]"

            return {"status": "ok", "output": f"💻 Terminal Output:\n{output}"}
        except subprocess.TimeoutExpired:
            return {"status": "ok", "output": "❌ Timeout: >30 δευτερόλεπτα."}
        except Exception as e:
            return {"status": "ok", "output": f"❌ Terminal Error: {str(e)}"}

    # Ακόμη και μετά από approval, τα hard-blocked commands δεν εκτελούνται ποτέ.
    if already_approved:
        policy, reason = classify_command(command)
        if policy == ExecPolicy.BLOCKED:
            result = {"status": "blocked", "reason": reason}
        else:
            result = _executor(command)
    else:
        result = safe_execute(command, _executor)

    if result.get("status") == "blocked":
        return f"🛡️ [SAFE EXECUTOR - BLOCKED]: {result['reason']}"
    if result.get("status") == "cancelled":
        return f"⚠️ [SAFE EXECUTOR]: Η εντολή απαιτεί επιβεβαίωσή σου. Ξαναστείλε με `/confirm {command}`"
    return result.get("output", "")

@tool
def save_to_memory(fact: str, entities: str = "", category: str = "general", reason: str = "agent_inferred") -> str:
    """
    Αποθηκεύει πληροφορίες ΣΗΜΑΣΙΟΛΟΓΙΚΑ.
    fact: Το γεγονός (π.χ. "Ο Αλέξανδρος τρώει μόνο φακές").
    entities: Λέξεις-κλειδιά χωρισμένες με κόμμα (π.χ. "Αλέξανδρος, Φαγητό, Προτίμηση").
    category: Η κατηγορία (π.χ. 'family', 'home', 'lazaros', 'tech', 'work').
    reason: Γιατί αποθηκεύεται — 'user_stated' αν το είπε ρητά ο χρήστης, 'agent_inferred' αλλιώς.
    """
    import datetime
    from memory.vector_store import vector_store

    try:
        semantic_payload = f"{fact} [Tags: {entities}]"

        # [MASTRO-DEDUP]: Έλεγχος για duplicate πριν αποθηκευτεί
        with vector_lock:
            existing = vector_store._collection.query(
                query_embeddings=[embeddings.embed_query(semantic_payload)],
                n_results=1
            )
        if (existing['ids'] and existing['ids'][0] and
                existing['distances'] and existing['distances'][0] and
                existing['distances'][0][0] < 0.10):
            print(f"\033[93m⚠️ [Semantic Graph]: Duplicate skip → {fact[:50]}\033[0m")
            return f"ℹ️ Η μνήμη υπάρχει ήδη (dist: {existing['distances'][0][0]:.3f})."

        # Προσπαθούμε να πάρουμε το channel από το context (αν υπάρχει)
        from tools import system as _self; _source = _self._CURRENT_CHANNEL
        vector_store.add_texts(
            texts=[semantic_payload],
            metadatas=[{
                "category": category,
                "entities": entities,
                "timestamp": datetime.datetime.now().timestamp(),
                "type": "semantic_node",
                "source": _source,
                "reason": reason,
                "retrieval_count": 0,
            }]
        )

        print(f"\033[95m🧠 [Semantic Graph]: Καρφώθηκε -> {entities}\033[0m")
        return f"✅ System: Η σημασιολογική μνήμη καρφώθηκε! Ταμπέλες: [{entities}]"
    except Exception as e:
        return f"❌ Error saving to semantic memory: {str(e)}"


@tool
def delete_from_memory(query: str) -> str:
    """Διαγράφει μια πληροφορία από τη μνήμη."""
    try:
        query_emb = embeddings.embed_query(query)
        with vector_lock:
            collection = vector_store._collection
            results = collection.query(query_embeddings=[query_emb], n_results=1)

            if not results['ids'] or not results['ids'][0]:
                return "Δεν βρήκα κάτι σχετικό για διαγραφή."

            content = results['documents'][0][0]
            distance = results['distances'][0][0] if 'distances' in results and results['distances'] else 1.0

            if distance > 0.40:
                return (
                    f"⚠️ Δεν το διέγραψα. Το πιο κοντινό (Απόσταση: {distance:.2f}): "
                    f"'{content}'. Γίνε πιο συγκεκριμένος."
                )

            target_id = results['ids'][0][0]
            collection.delete(ids=[target_id])

        print(f"\n🔥 [DATABASE ACTION]: ΔΙΕΓΡΑΦΗΚΕ (Dist: {distance:.2f}): {content}")
        return f"Η μνήμη '{content}' διαγράφηκε επιτυχώς."
    except Exception as e:
        return f"Σφάλμα διαγραφής: {e}"


@tool
def retrieve_photo(query: str) -> str:
    """Ανακτά φωτογραφία από τη μνήμη. ΟΤΑΝ επιστρέψει [SEND_PHOTO: path], ΣΥΜΠΕΡΙΛΑΒΕ ΤΟ ΑΥΤΟΥΣΙΟ στην απάντησή σου."""
    try:
        import numpy as np

        with vector_lock:
            results = vector_store.similarity_search(query, k=10)

        for doc in results:
            photo_path = doc.metadata.get("photo_path")
            if photo_path and os.path.exists(photo_path):
                return (
                    f"Βρήκα τη φωτογραφία!\n"
                    f"Περιγραφή: {doc.page_content}\n"
                    f"[SEND_PHOTO: {photo_path}]"
                )

        if os.path.exists(PHOTOS_INDEX_FILE):
            with open(PHOTOS_INDEX_FILE, "r", encoding="utf-8") as f:
                index = json.load(f)

            if index:
                query_emb = np.array(embeddings.embed_query(query))
                best_score = -1.0
                best_entry = None

                for entry in index:
                    candidate = f"{entry.get('caption', '')} {entry.get('analysis', '')}".strip()
                    if not candidate:
                        continue
                    cand_emb = np.array(embeddings.embed_query(candidate))
                    norm_q = np.linalg.norm(query_emb)
                    norm_c = np.linalg.norm(cand_emb)
                    if norm_q and norm_c:
                        sim = float(np.dot(query_emb, cand_emb) / (norm_q * norm_c))
                        if sim > best_score:
                            best_score = sim
                            best_entry = entry

                if best_score < 0.35:
                    return "System: Δεν βρέθηκε σχετική φωτογραφία για το query αυτό."

                if best_entry:
                    fp = best_entry.get("file_path", "")
                    note = "" if best_score >= 0.5 else " (Δεν βρήκα ακριβή αντιστοιχία — δίνω την πιο κοντινή.)"
                    if not fp:
                        best_entry = index[-1]
                        fp = best_entry.get("file_path", "")
                        note = " (Fallback: πιο πρόσφατη φωτογραφία.)"

                    if fp and os.path.exists(fp):
                        return (
                            f"Βρήκα φωτογραφία από {best_entry.get('date', 'άγνωστη ημερομηνία')}{note}\n"
                            f"[SEND_PHOTO: {fp}]"
                        )

        return "System: Δεν βρέθηκε φωτογραφία."

    except Exception as e:
        return f"Error: Σφάλμα ανάκτησης φωτογραφίας: {str(e)}"


# ────────────────────────────────────────────────────────────────
# REMINDERS & LISTS
# ────────────────────────────────────────────────────────────────

@tool
def set_local_reminder(task: str, minutes_from_now: int = 0, exact_time: str = None, action: str = "add", location: str = None) -> str:
    """
    Διαχειρίζεται τοπικές υπενθυμίσεις.
    action: 'add' (νέα), 'read' (ανάγνωση ΜΟΝΟ pending), 'done' (ολοκλήρωση)
    task: Για 'add' → περιγραφή. Για 'done' → keyword της υπενθύμισης που κλείνει.
    location: ΜΟΝΟ για τοποθεσία-based υπενθυμίσεις. Χρησιμοποίησε 'home' όταν
              ο Λάζαρος λέει 'όταν φτάσω σπίτι', 'μόλις πάω σπίτι' κλπ.
              Όταν δίνεται location, ΜΗΝ δίνεις minutes_from_now ή exact_time.
    """
    try:
        rems = []
        if os.path.exists(REMINDERS_FILE):
            with open(REMINDERS_FILE, "r", encoding="utf-8") as f:
                try:
                    rems = json.load(f)
                except (json.JSONDecodeError, ValueError):
                    pass

        # ── READ: Επιστρέφει ΜΟΝΟ pending ──────────────────────
        if action == "read":
            pending = [r for r in rems if r.get("status") == "pending"]
            if not pending:
                return "✅ Δεν υπάρχουν εκκρεμείς υπενθυμίσεις."
            lines = []
            for r in pending:
                if r.get("type") == "location":
                    lines.append(f"• [📍 {r.get('location','home')}] {r['task']}")
                else:
                    lines.append(f"• [{r['time']}] {r['task']}")
            return "📋 Εκκρεμείς υπενθυμίσεις:\n" + "\n".join(lines)

        # ── DONE: Κλείνει υπενθύμιση με keyword ────────────────
        elif action == "done":
            found = False
            for r in rems:
                if task.lower() in r.get("task", "").lower() and r.get("status") == "pending":
                    r["status"] = "done"
                    found = True
                    break
            if not found:
                return f"⚠️ Δεν βρήκα pending υπενθύμιση με '{task}'."
            with open(REMINDERS_FILE, "w", encoding="utf-8") as f:
                json.dump(rems, f, ensure_ascii=False, indent=4)
            return f"✅ Η υπενθύμιση '{task}' ολοκληρώθηκε."

        # ── ADD: Νέα υπενθύμιση ─────────────────────────────────
        else:
            from datetime import datetime, timedelta

            if minutes_from_now > 0:
                target_time = (datetime.now() + timedelta(minutes=minutes_from_now)).strftime("%Y-%m-%d %H:%M")
            elif exact_time:
                exact_time = exact_time.strip()
                if len(exact_time) <= 5 and ":" in exact_time:
                    today_str = datetime.now().strftime("%Y-%m-%d")
                    target_time = f"{today_str} {exact_time}"
                else:
                    try:
                        datetime.strptime(exact_time, "%Y-%m-%d %H:%M")
                        target_time = exact_time
                    except ValueError:
                        return "Σφάλμα: Η ακριβής ώρα (exact_time) πρέπει να είναι ΜΟΝΟ ώρα (HH:MM) ή πλήρης ημερομηνία (YYYY-MM-DD HH:MM)."
            elif location:
                rems.append({"task": task, "type": "location", "location": location, "status": "pending"})
                with open(REMINDERS_FILE, "w", encoding="utf-8") as f:
                    json.dump(rems, f, ensure_ascii=False, indent=4)
                return f"✅ Υπενθύμιση τοποθεσίας αποθηκεύτηκε! Θα χτυπήσει όταν φτάσεις {location}."
            else:
                return "Σφάλμα: Πρέπει να δώσεις λεπτά, ακριβή ώρα, ή τοποθεσία (π.χ. location='home')."

            rems.append({"task": task, "time": target_time, "status": "pending"})
            with open(REMINDERS_FILE, "w", encoding="utf-8") as f:
                json.dump(rems, f, ensure_ascii=False, indent=4)
            return f"✅ Υπενθύμιση ρυθμίστηκε για τις {target_time}!"

    except Exception as e:
        return f"Σφάλμα υπενθύμισης: {e}"
from langchain_core.tools import tool
from memory.routine_db import upsert_routine

@tool
def learn_routine(day_of_week: str, time_str: str, event_name: str, event_type: str = "general") -> str:
    """
    [CRITICAL]: Χρησιμοποίησέ το ΟΤΑΝ ο Λάζαρος αναφέρει μια συνήθεια,
    μια ρουτίνα ή κάτι που επαναλαμβάνεται (π.χ. "Κάθε Παρασκευή στις 13:00 πάω λαϊκή").

    ΚΑΝΟΝΕΣ ΓΙΑ ΤΑ ΟΡΙΣΜΑΤΑ:
    - day_of_week: Αγγλικό canonical ("Monday"…"Sunday") ή "Everyday" για καθημερινή ρουτίνα.
    - time_str: Ώρα σε HH:MM (π.χ. "13:00"). Αν δεν αναφέρεται ώρα, ΜΗΝ καλέσεις το tool.
    - event_name: ΣΥΝΤΟΜΗ canonical περιγραφή σε 2-4 λέξεις (π.χ. "μήνυμα Κώστα", "λαϊκή αγορά",
      "γυμναστήριο"). ΜΗΝ βάλεις "Κάθε μέρα", "Κάθε πρωί" ή χρονικές φράσεις — αυτές ανήκουν
      στο day_of_week/time_str. Το event_name πρέπει να είναι ΣΤΑΘΕΡΟ για την ίδια δραστηριότητα.
    - event_type: "family", "work", "hobby", "general".

    ΠΡΟΣΟΧΗ: Κάλεσέ το ΜΟΝΟ για recurring δραστηριότητες. Αγνόησε one-off γεγονότα
    ("σήμερα πήγα…", "αύριο έχω…").
    """
    from datetime import datetime

    VALID_DAYS = {"Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday", "Everyday"}
    VALID_TYPES = {"family", "work", "hobby", "general"}

    if day_of_week not in VALID_DAYS:
        return f"❌ Μη έγκυρη μέρα: '{day_of_week}'. Χρησιμοποίησε αγγλικό όνομα (π.χ. 'Friday') ή 'Everyday'."

    try:
        datetime.strptime(time_str, "%H:%M")
    except ValueError:
        return f"❌ Λάθος format ώρας: '{time_str}'. Χρησιμοποίησε 'HH:MM'."

    if len(event_name.strip()) < 3:
        return "❌ Το event_name είναι πολύ σύντομο. Δώσε 2-4 λέξεις περιγραφή."

    if event_type not in VALID_TYPES:
        event_type = "general"

    try:
        res = upsert_routine(day_of_week, time_str, event_name, event_type, confidence_boost=0.3)

        if res == "created":
            return f"✅ Ρουτίνα '{event_name}' καταγράφηκε (θα ενεργοποιηθεί μετά από 2η επιβεβαίωση)."
        elif res == "merged":
            return f"✅ Ρουτίνα '{event_name}' αναγνωρίστηκε ως παρόμοια με υπάρχουσα και ενοποιήθηκε."
        else:
            return f"✅ Ρουτίνα '{event_name}' ενισχύθηκε! (Confidence Boosted)."
    except Exception as e:
        return f"❌ Σφάλμα αποθήκευσης ρουτίνας: {e}"
@tool
def get_routines(day_of_week: str) -> str:
    """
    [QUERY]: Επιστρέφει τις καταγεγραμμένες ρουτίνες για μια συγκεκριμένη μέρα.
    Χρησιμοποίησέ το όταν ο Λάζαρος ρωτάει "τι έχω την Παρασκευή;" ή "ποιες ρουτίνες ξέρεις;".
    - day_of_week: π.χ. "Monday", "Friday", "Everyday"
    """
    try:
        from memory.routine_db import get_routines_for_day
        routines = get_routines_for_day(day_of_week)
        if not routines:
            return f"Δεν έχω καταγεγραμμένες ρουτίνες για {day_of_week}."
        
        lines = [f"📅 Ρουτίνες για {day_of_week}:"]
        for r in routines:
            conf_pct = int(r['confidence'] * 100)
            mentions = r.get('mentions', 1)
            lines.append(f"  • {r['time']} — {r['event']} ({r['type']}, {conf_pct}% conf, {mentions}x αναφ.)")
        return "\n".join(lines)
    except Exception as e:
        return f"❌ Σφάλμα ανάκτησης ρουτινών: {e}"
@tool
def set_reminder(task: str, time_str: str) -> str:
    """Δημιουργεί τοπική υπενθύμιση (format time_str: 'YYYY-MM-DD HH:MM')."""
    from datetime import datetime

    try:
        datetime.strptime(time_str, "%Y-%m-%d %H:%M")
    except ValueError:
        return f"❌ Λάθος format: '{time_str}'. Χρησιμοποίησε 'YYYY-MM-DD HH:MM'."

    rems = []
    if os.path.exists(REMINDERS_FILE):
        with open(REMINDERS_FILE, "r", encoding="utf-8") as f:
            try:
                rems = json.load(f)
            except (json.JSONDecodeError, ValueError):
                pass

    rems.append({"task": task, "time": time_str, "status": "pending"})

    with open(REMINDERS_FILE, "w", encoding="utf-8") as f:
        json.dump(rems, f, ensure_ascii=False, indent=4)

    return f"✅ Υπενθύμιση '{task}' στις {time_str} καταχωρήθηκε."


@tool
def manage_list(action: str, list_name: str, item: str = "") -> str:
    """Διαχειρίζεται λίστες. Actions: 'add', 'remove', 'read', 'clear', 'delete'.
    Για πολλά αντικείμενα ταυτόχρονα, χώρισέ τα με κόμμα (item='γάλα, τυρί')."""
    try:
        lists_db = {}
        if os.path.exists(LISTS_FILE):
            with open(LISTS_FILE, "r", encoding="utf-8") as f:
                try:
                    loaded = json.load(f)
                    if isinstance(loaded, dict):
                        lists_db = loaded
                except (json.JSONDecodeError, ValueError):
                    pass

        if list_name not in lists_db:
            list_name_lower = list_name.lower()
            for existing_key in lists_db.keys():
                if list_name_lower in existing_key.lower() or existing_key.lower().startswith(list_name_lower):
                    list_name = existing_key
                    break

        if action == "read":
            current = lists_db.get(list_name, [])
            if not current:
                return f"Η λίστα '{list_name}' είναι άδεια."
            return f"Περιεχόμενα '{list_name}':\n" + "\n".join([f"- {i}" for i in current])

        to_process = [i.strip() for i in item.split(",")] if item else []

        if action == "add":
            if list_name not in lists_db:
                lists_db[list_name] = []
            for obj in to_process:
                if obj and obj not in lists_db[list_name]:
                    lists_db[list_name].append(obj)
        elif action == "remove":
            for obj in to_process:
                if obj in lists_db.get(list_name, []):
                    lists_db[list_name].remove(obj)
        elif action == "clear":
            lists_db[list_name] = []
        elif action == "delete":
            if list_name in lists_db:
                del lists_db[list_name]

        with open(LISTS_FILE, "w", encoding="utf-8") as f:
            json.dump(lists_db, f, ensure_ascii=False, indent=4)

        added_str = ", ".join(to_process) if to_process else "κανένα"
        return f"System: Η ενέργεια '{action}' ολοκληρώθηκε (Αντικείμενα: {added_str})."
    except Exception as e:
        return f"Error: Σφάλμα λίστας: {str(e)}"


# ────────────────────────────────────────────────────────────────
# GOOGLE SERVICES
# ────────────────────────────────────────────────────────────────

@tool
def google_calendar_tool(action: str, summary: str, start_time: str, end_time: str = None) -> str:
    """Διαχειρίζεται το Google Calendar. action: 'create' για νέο ραντεβού."""
    try:
        print(f"\033[93m[Calendar]: Δημιουργία ραντεβού '{summary}'...\033[0m")
        creds = Credentials.from_authorized_user_file(TOKEN_PATH, ['https://www.googleapis.com/auth/calendar'])
        service = build('calendar', 'v3', credentials=creds)
        if action == "create":
            event = {'summary': summary, 'start': {'dateTime': start_time}, 'end': {'dateTime': end_time or start_time}}
            service.events().insert(calendarId='primary', body=event).execute()
            return f"Το ραντεβού '{summary}' δημιουργήθηκε επιτυχώς!"
        return f"System Error: Υποστηρίζεται ΜΟΝΟ action='create'. Έστειλες: '{action}'."
    except Exception as e:
        return f"Calendar Error: {str(e)}"


@tool
def google_tasks_tool(action: str, title: str, due: str = None) -> str:
    """
    Διαχειρίζεται τα Google Tasks. action: 'create' για νέα υπενθύμιση.
    🚨 [MASTRO-RULE ΓΙΑ ΤΟΝ ΤΙΤΛΟ]: Η παράμετρος 'title' ΠΡΕΠΕΙ να περιγράφει ξεκάθαρα την εργασία (π.χ. 'Φροντίδα τριανταφυλλιάς').
    ΑΠΑΓΟΡΕΥΕΤΑΙ ΑΥΣΤΗΡΑ να χρησιμοποιείς ρήματα της εντολής (π.χ. 'βάλε', 'κάνε', 'θύμισέ μου', 'υπενθύμιση') ως τίτλο. 
    Αν ο χρήστης λέει απλά 'βάλε μια υπενθύμιση' χωρίς να διευκρινίζει το θέμα, ΜΗΝ καλείς αυτό το εργαλείο. Ρώτα τον πρώτα τι θέλει να γράψεις!
    """
    try:
        print(f"\033[93m[Tasks]: Δημιουργία υπενθύμισης '{title}'...\033[0m")
        creds = Credentials.from_authorized_user_file(TOKEN_PATH, ['https://www.googleapis.com/auth/tasks'])
        service = build('tasks', 'v1', credentials=creds)
        
        if action == "create":
            # Αν το due είναι μόνο ημερομηνία, μετατρέψτο σε RFC3339
            if due and len(due) == 10:  # format: YYYY-MM-DD
                due = f"{due}T00:00:00.000Z"
            task = {'title': title, 'due': due}
            service.tasks().insert(tasklist='@default', body=task).execute()
            return f"Η υπενθύμιση '{title}' προστέθηκε στα Google Tasks!"
            
        return f"System Error: Υποστηρίζεται ΜΟΝΟ action='create'. Έστειλες: '{action}'."
    except Exception as e:
        return f"Tasks Error: {str(e)}"

@tool
def create_file_tool(file_type: str, filename: str, data: str) -> str:
    """
    Δημιουργεί τοπικά αρχεία DOCX, PDF, XLSX ή TXT.
    file_type: 'docx', 'pdf', 'xlsx', 'txt'
    filename: Το όνομα του αρχείου (π.χ. 'report.docx')
    data: Το περιεχόμενο. Για XLSX, στείλε JSON string από λίστα/dict.
    """
    import os
    import json
    from config import BASE_DIR

    output_dir = os.path.realpath(os.path.join(BASE_DIR, "outputs"))
    os.makedirs(output_dir, exist_ok=True)

    # [SECURITY]: basename + resolve check — αποτρέπει path traversal (π.χ. ../config.py)
    safe_filename = os.path.basename(filename)
    if not safe_filename:
        return "❌ Σφάλμα: Μη έγκυρο όνομα αρχείου."
    full_path = os.path.realpath(os.path.join(output_dir, safe_filename))
    if not full_path.startswith(output_dir + os.sep) and full_path != output_dir:
        return "❌ Σφάλμα: Το path εκτός outputs δεν επιτρέπεται."
    file_type = file_type.lower()

    try:
        if file_type == "docx":
            import docx
            doc = docx.Document()
            for line in data.split("\n"):
                doc.add_paragraph(line)
            doc.save(full_path)

        elif file_type == "xlsx":
            import pandas as pd
            try:
                content = json.loads(data)
                df = pd.DataFrame(content)
            except (json.JSONDecodeError, ValueError):
                df = pd.DataFrame([data], columns=["Content"])
            df.to_excel(full_path, index=False)

        elif file_type == "pdf":
            from fpdf import FPDF
            font_path = os.path.join(BASE_DIR, "assets", "DejaVuSans.ttf")
            pdf = FPDF()
            pdf.add_page()
            if os.path.exists(font_path):
                pdf.add_font("DejaVu", "", font_path, uni=True)
                pdf.set_font("DejaVu", size=12)
            else:
                # Fallback χωρίς ελληνικά αν λείπει το font
                pdf.set_font("Arial", size=12)
            pdf.multi_cell(0, 10, data)
            pdf.output(full_path)

        elif file_type in ["txt", "json", "csv", "html", "md"]:
            with open(full_path, "w", encoding="utf-8") as f:
                f.write(data)

        else:
            return f"❌ Σφάλμα: Ο τύπος '{file_type}' δεν υποστηρίζεται."

        return f"✅ Έτοιμο Μάστορα! Το αρχείο δημιουργήθηκε επιτυχώς.\n[CREATED_FILE: {full_path}]"

    except Exception as e:
        return f"❌ Σφάλμα κατά τη δημιουργία: {str(e)}"
@tool
def generate_image_tool(prompt: str) -> str:
    """
    Δημιουργεί μια εικόνα βασισμένη σε μια περιγραφή (prompt).
    """
    import os
    import requests
    from slugify import slugify
    from config import BASE_DIR
    import time

    output_dir = os.path.join(BASE_DIR, "outputs")
    os.makedirs(output_dir, exist_ok=True)

    safe_filename = slugify(prompt[:30]) or "gen_image"
    filename = f"{safe_filename}_{int(time.time())}.jpg"
    full_path = os.path.join(output_dir, filename)

    api_url = (
        f"https://image.pollinations.ai/prompt/{requests.utils.quote(prompt)}"
        f"?nologo=true&model=flux&width=1024&height=1024"
    )

    try:
        res = requests.get(api_url, timeout=30)
        if res.status_code == 200:
            content_type = res.headers.get("Content-Type", "")
            if "image" not in content_type:
                return f"❌ Το API επέστρεψε μη αναμενόμενο τύπο: {content_type}"
            with open(full_path, 'wb') as f:
                f.write(res.content)
            return f"✅ Έτοιμο! Η εικόνα δημιουργήθηκε.\n[SEND_PHOTO: {full_path}]"
        return f"❌ Σφάλμα API ({res.status_code}). Η μηχανή μπούκωσε."
    except requests.Timeout:
        return "❌ Timeout: το Pollinations άργησε πάνω από 30 δευτερόλεπτα."
    except Exception as e:
        return f"❌ Σφάλμα: {str(e)}"
@tool
def drive_manager(
    action: str = "list_files",
    file_id: str = None,
    local_path: str = None,
    folder_id: str = "12YrIZ3uAQWmmwIlEkIkDf-4gcz2P8Ktv",
    query: str = None,
    new_name: str = None,
    target_folder_id: str = None,
    share_email: str = None,
    share_role: str = "reader",
) -> str:
    """Διαχειρίζεται το Google Drive του Λάζαρου.

    Actions:
      'list_files'   — Λίστα αρχείων σε folder (default: root astakos folder)
      'search'       — Αναζήτηση με όνομα ή λέξη-κλειδί (χρειάζεται query=)
      'download'     — Κατέβασμα αρχείου (χρειάζεται file_id=)
      'upload'       — Ανέβασμα αρχείου (χρειάζεται local_path=)
      'delete'       — Διαγραφή αρχείου (χρειάζεται file_id=)
      'rename'       — Μετονομασία (χρειάζεται file_id= + new_name=)
      'move'         — Μετακίνηση σε άλλο φάκελο (χρειάζεται file_id= + target_folder_id=)
      'share'        — Κοινή χρήση (χρειάζεται file_id= + share_email= + share_role='reader'/'writer')
      'create_folder'— Δημιουργία φακέλου (χρειάζεται new_name=, προαιρετικά folder_id= για parent)
      'info'         — Πληροφορίες αρχείου (χρειάζεται file_id=)
    """
    try:
        from googleapiclient.http import MediaIoBaseDownload, MediaFileUpload
        import io

        print(f"\033[93m[Drive]: Ενέργεια '{action}'...\033[0m")
        creds   = Credentials.from_authorized_user_file(TOKEN_PATH, SCOPES)
        service = build('drive', 'v3', credentials=creds)

        # ── LIST FILES ───────────────────────────────────────────
        if action == "list_files":
            results = service.files().list(
                q=f"'{folder_id}' in parents and trashed=false",
                fields="files(id, name, mimeType, size, modifiedTime)",
                orderBy="modifiedTime desc",
                pageSize=50
            ).execute()
            items = results.get('files', [])
            if not items:
                return "📁 Ο φάκελος είναι άδειος."
            lines = ["📁 Αρχεία στο Drive:\n"]
            for i in items:
                size_kb = round(int(i.get('size', 0)) / 1024, 1) if i.get('size') else "—"
                mod = i.get('modifiedTime', '')[:10]
                lines.append(f"• {i['name']} | ID: `{i['id']}` | {size_kb} KB | {mod}")
            return "\n".join(lines)

        # ── SEARCH ───────────────────────────────────────────────
        elif action == "search":
            if not query:
                return "❌ Χρειάζεται query= για αναζήτηση."
            q_str = f"name contains '{query}' and trashed=false"
            results = service.files().list(
                q=q_str,
                fields="files(id, name, mimeType, size, modifiedTime, parents)",
                orderBy="modifiedTime desc",
                pageSize=20
            ).execute()
            items = results.get('files', [])
            if not items:
                return f"🔍 Δεν βρέθηκαν αρχεία για '{query}'."
            lines = [f"🔍 Αποτελέσματα για '{query}':\n"]
            for i in items:
                size_kb = round(int(i.get('size', 0)) / 1024, 1) if i.get('size') else "—"
                mod = i.get('modifiedTime', '')[:10]
                lines.append(f"• {i['name']} | ID: `{i['id']}` | {size_kb} KB | {mod}")
            return "\n".join(lines)

        # ── DOWNLOAD ─────────────────────────────────────────────
        elif action == "download":
            if not file_id:
                return "❌ Χρειάζεται file_id=."
            file_metadata = service.files().get(fileId=file_id, fields="name,mimeType").execute()
            mime_type = file_metadata.get('mimeType', '')
            file_name = file_metadata.get('name', 'downloaded_file')

            # Google Docs/Sheets/Slides → export as text/xlsx/pptx
            export_map = {
                'application/vnd.google-apps.document':     ('text/plain', '.txt'),
                'application/vnd.google-apps.spreadsheet':  ('application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', '.xlsx'),
                'application/vnd.google-apps.presentation': ('application/vnd.openxmlformats-officedocument.presentationml.presentation', '.pptx'),
            }
            if mime_type in export_map:
                export_mime, ext = export_map[mime_type]
                request = service.files().export_media(fileId=file_id, mimeType=export_mime)
                if not file_name.endswith(ext):
                    file_name += ext
            else:
                request = service.files().get_media(fileId=file_id)

            fh = io.BytesIO()
            downloader = MediaIoBaseDownload(fh, request)
            done = False
            while not done:
                _, done = downloader.next_chunk()

            save_target = local_path if local_path else os.path.join(r"C:\astakos_v2\outputs", file_name)
            os.makedirs(os.path.dirname(save_target), exist_ok=True)
            with open(save_target, "wb") as f:
                f.write(fh.getvalue())

            # Αν είναι text, επέστρεψε και το περιεχόμενο
            if mime_type == 'application/vnd.google-apps.document' or file_name.endswith('.txt'):
                content = fh.getvalue().decode('utf-8', errors='ignore')[:6000]
                return f"✅ '{file_name}' κατέβηκε → {save_target}\n\n{content}"
            return f"✅ '{file_name}' κατέβηκε → {save_target}"

        # ── UPLOAD ───────────────────────────────────────────────
        elif action == "upload":
            if not local_path or not os.path.exists(local_path):
                return f"❌ Αρχείο δεν βρέθηκε: {local_path}"
            file_metadata = {'name': os.path.basename(local_path), 'parents': [folder_id]}
            media = MediaFileUpload(local_path, resumable=True)
            file = service.files().create(body=file_metadata, media_body=media, fields='id,name').execute()
            return f"✅ '{file.get('name')}' ανέβηκε! (ID: {file.get('id')})"

        # ── DELETE ───────────────────────────────────────────────
        elif action == "delete":
            if not file_id:
                return "❌ Χρειάζεται file_id=."
            meta = service.files().get(fileId=file_id, fields="name").execute()
            service.files().delete(fileId=file_id).execute()
            return f"🗑️ '{meta.get('name')}' διαγράφηκε."

        # ── RENAME ───────────────────────────────────────────────
        elif action == "rename":
            if not file_id or not new_name:
                return "❌ Χρειάζεται file_id= και new_name=."
            service.files().update(fileId=file_id, body={"name": new_name}).execute()
            return f"✏️ Μετονομάστηκε σε '{new_name}'."

        # ── MOVE ─────────────────────────────────────────────────
        elif action == "move":
            if not file_id or not target_folder_id:
                return "❌ Χρειάζεται file_id= και target_folder_id=."
            file = service.files().get(fileId=file_id, fields="parents").execute()
            old_parents = ",".join(file.get('parents', []))
            service.files().update(
                fileId=file_id,
                addParents=target_folder_id,
                removeParents=old_parents,
                fields="id, parents"
            ).execute()
            return f"📦 Αρχείο μετακινήθηκε στον φάκελο {target_folder_id}."

        # ── SHARE ────────────────────────────────────────────────
        elif action == "share":
            if not file_id or not share_email:
                return "❌ Χρειάζεται file_id= και share_email=."
            permission = {"type": "user", "role": share_role, "emailAddress": share_email}
            service.permissions().create(fileId=file_id, body=permission, sendNotificationEmail=False).execute()
            return f"🔗 Κοινοποιήθηκε στον/στην {share_email} ως {share_role}."

        # ── CREATE FOLDER ─────────────────────────────────────────
        elif action == "create_folder":
            if not new_name:
                return "❌ Χρειάζεται new_name= για το όνομα του φακέλου."
            metadata = {
                "name": new_name,
                "mimeType": "application/vnd.google-apps.folder",
                "parents": [folder_id]
            }
            folder = service.files().create(body=metadata, fields="id, name").execute()
            return f"📁 Φάκελος '{folder.get('name')}' δημιουργήθηκε (ID: {folder.get('id')})."

        # ── INFO ─────────────────────────────────────────────────
        elif action == "info":
            if not file_id:
                return "❌ Χρειάζεται file_id=."
            meta = service.files().get(
                fileId=file_id,
                fields="name,mimeType,size,modifiedTime,createdTime,parents,webViewLink,owners"
            ).execute()
            size_kb = round(int(meta.get('size', 0)) / 1024, 1) if meta.get('size') else "—"
            owners = ", ".join(o.get('emailAddress','') for o in meta.get('owners', []))
            return (
                f"📄 *{meta.get('name')}*\n"
                f"Type: {meta.get('mimeType')}\n"
                f"Μέγεθος: {size_kb} KB\n"
                f"Δημιουργήθηκε: {meta.get('createdTime','')[:10]}\n"
                f"Τροποποιήθηκε: {meta.get('modifiedTime','')[:10]}\n"
                f"Ιδιοκτήτης: {owners}\n"
                f"Link: {meta.get('webViewLink','—')}"
            )

        return "❌ Άγνωστο action. Δες το docstring για τις επιλογές."

    except Exception as e:
        return f"❌ Drive Error: {str(e)}"


# ────────────────────────────────────────────────────────────────
# FILE & DEV TOOLS
# ────────────────────────────────────────────────────────────────

@tool
def read_local_file(file_path: str) -> str:
    """Διαβάζει PDF, XLSX, CSV, DOCX, TXT, PY, JS (Mastro-Optimized)."""
    import os
    from config import PHOTOS_DIR
    
    # Καθαρισμός path
    file_path = file_path.strip().strip("'").strip('"')
    filename = os.path.basename(file_path)
    base_dir = os.getcwd()

    # [SECURITY]: Μόνο αυτοί οι φάκελοι επιτρέπονται για ανάγνωση
    _allowed_dirs = [
        os.path.realpath(PHOTOS_DIR),
        os.path.realpath(os.path.join(base_dir, "telegram_uploads")),
        os.path.realpath(os.path.join(base_dir, "telegram_photos")),
        os.path.realpath(os.path.join(base_dir, "uploads")),
        os.path.realpath(os.path.join(base_dir, "outputs")),
        os.path.realpath(os.path.join(base_dir, "watch_folder")),
    ]

    def _in_allowed(path):
        real = os.path.realpath(path)
        return any(real.startswith(d + os.sep) or real == d for d in _allowed_dirs)

    full_path = None
    print(f"\033[93m[Tool Debug]: Ψάχνω το αρχείο: {filename}\033[0m")

    # Αν δόθηκε absolute path, έλεγξε ότι είναι εντός allowed dirs
    if os.path.isabs(file_path):
        if os.path.exists(file_path) and os.path.isfile(file_path) and _in_allowed(file_path):
            full_path = file_path
            print(f"\033[92m[Tool Debug]: ✅ Absolute path εντός allowed -> {full_path}\033[0m")
        elif os.path.exists(file_path):
            return f"❌ Απαγορευμένο path: {os.path.basename(file_path)} βρίσκεται εκτός εγκεκριμένων φακέλων."

    # Αναζήτηση με basename στους allowed dirs
    if not full_path:
        for d in _allowed_dirs:
            test_path = os.path.join(d, filename)
            if os.path.exists(test_path) and os.path.isfile(test_path) and _in_allowed(test_path):
                full_path = test_path
                print(f"\033[92m[Tool Debug]: ✅ Το βρήκα στο -> {full_path}\033[0m")
                break

    if not full_path:
        return f"❌ Error: Το αρχείο {filename} δεν βρέθηκε στους φακέλους αναζήτησης."

    ext = os.path.splitext(full_path)[1].lower()

    try:
        if ext == ".pdf":
            # Χρήση pypdf (πιο αξιόπιστη από PyPDF2)
            try:
                from pypdf import PdfReader
            except ImportError:
                from PyPDF2 import PdfReader # Fallback αν δεν έχεις προλάβει το install
            
            text = ""
            reader = PdfReader(full_path)
            for page in reader.pages:
                extracted = page.extract_text()
                if extracted:
                    text += extracted + "\n"
                if len(text) > 12000: # Όριο για να μην «πνίξουμε» το context
                    break
            
            if not text.strip():
                return f"⚠️ Το PDF ({filename}) φαίνεται να είναι σκαναρισμένο (εικόνα). Χρειάζεται OCR για να διαβαστεί."
                
            return f"📄 PDF ({filename}):\n{text[:12000]}"

        elif ext in [".xlsx", ".xls"]:
            import pandas as pd
            excel_file = pd.ExcelFile(full_path)
            output_text = f"📊 Excel ({filename}) - Φύλλα: {', '.join(excel_file.sheet_names)}\n\n"
            for sheet in excel_file.sheet_names:
                df = pd.read_excel(full_path, sheet_name=sheet).fillna("-")
                output_text += f"═══ Φύλλο: {sheet} ═══\n"
                output_text += df.head(50).to_string(index=False) + "\n\n"
                if len(output_text) > 12000: break
            return output_text[:12000]

        elif ext == ".csv":
            import pandas as pd
            df = pd.read_csv(full_path).fillna("-")
            return f"📊 CSV ({filename}):\n{df.head(100).to_string(index=False)}"

        elif ext == ".docx":
            import docx
            doc = docx.Document(full_path)
            text = "\n".join([p.text for p in doc.paragraphs])
            return f"📝 Word ({filename}):\n{text[:12000]}"

        else: # TXT, PY, JS, κλπ.
            with open(full_path, "r", encoding="utf-8", errors="ignore") as f:
                return f"📄 Αρχείο ({filename}):\n{f.read(12000)}"

    except Exception as e:
        return f"❌ Error ανάγνωσης {filename}: {str(e)}"

@tool
def write_code(filename: str, code: str) -> str:
    """Γράφει κώδικα ΜΟΝΟ μέσα στον φάκελο astakos_skills."""
    safe_filename = os.path.basename(filename)
    if safe_filename in PROTECTED_FILES:
        return f"System Error: ΑΠΑΓΟΡΕΥΕΤΑΙ να τροποποιήσεις το {safe_filename}."

    for word in DANGEROUS_WORDS:
        if word in code:
            return f"System Error: Ο κώδικας απορρίφθηκε ({word})."

    file_path = os.path.join(WORKSPACE_DIR, safe_filename)

    try:
        print(f"\033[93m[Dev]: Αποθήκευση στο {file_path}...\033[0m")
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(code)
        return f"System: Ο κώδικας γράφτηκε στο {file_path}."
    except Exception as e:
        return f"Write Error: {str(e)}"


@tool
def run_code(filename: str, script_args: str = "") -> str:
    """
    Εκτελεί ένα αρχείο Python ΜΟΝΟ από τον φάκελο astakos_skills.
    Μπορείς να περάσεις προαιρετικά ορίσματα (script_args) ως string.
    Παράδειγμα: script_args="SKG KUT 2026-08-09 -r 2026-08-15"
    """
    import os
    import sys
    import subprocess
    from core.safe_executor import safe_execute

    safe_filename = os.path.basename(filename)
    file_path = os.path.join(WORKSPACE_DIR, safe_filename)

    if not os.path.exists(file_path):
        return f"Error: Το αρχείο {file_path} δεν υπάρχει στο Sandbox."

    # ── SafeExec check ───────────────────────────────────────────
    cmd_str = f"python {safe_filename} {script_args}".strip()
    check = safe_execute(cmd_str, lambda c: {"status": "ok"})
    if check.get("status") == "blocked":
        return f"🛡️ [SAFE EXECUTOR - BLOCKED]: {check['reason']}"
    if check.get("status") == "cancelled":
        return f"⚠️ [SAFE EXECUTOR]: Η εκτέλεση απαιτεί επιβεβαίωση. Ξαναστείλε με `/confirm {cmd_str}`"
    # ────────────────────────────────────────────────────────────

    try:
        cmd = [sys.executable, file_path]
        if script_args:
            cmd.extend(script_args.split())

        print(f"\033[93m[Dev]: Εκτέλεση του {safe_filename} με ορίσματα: {script_args}\033[0m")

        res = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
        output = res.stdout if res.stdout else ""
        if res.stderr:
            output += f"\nERRORS:\n{res.stderr}"

        return f"Terminal Output:\n{output[:5000]}" if output else "Εκτελέστηκε επιτυχώς (χωρίς output)."

    except subprocess.TimeoutExpired:
        return "Error: Το script κόλλησε (>20 δευτερόλεπτα) και τερματίστηκε."
    except Exception as e:
        return f"Run Error: {str(e)}"


@tool
def write_custom_tool(tool_name: str, tool_code: str) -> str:
    """Γράφει, τεστάρει και παρουσιάζει νέο tool για έγκριση.
    ΔΕΝ το προσθέτει αυτόματα — ο Λάζαρος κάνει paste αν εγκρίνει."""
    import ast

    clean_code = re.sub(r"```(?:python)?", "", tool_code).replace("```", "").strip()

    dangerous_pattern = r"(subprocess|os\s*\.\s*system|__import__|eval\s*\(|exec\s*\()"
    if re.search(dangerous_pattern, clean_code, re.IGNORECASE):
        return "System Error: Απορρίφθηκε — ανιχνεύτηκε επικίνδυνη εντολή."

    if f"def {tool_name}" not in clean_code:
        return f"System Error: Ο κώδικας πρέπει να περιέχει 'def {tool_name}'."
    if "@tool" not in clean_code:
        return "System Error: Λείπει ο @tool decorator."

    try:
        ast.parse(clean_code)
    except SyntaxError as se:
        return f"❌ Συντακτικό σφάλμα (γραμμή {se.lineno}): {se.msg}\nΚοίτα: {se.text}"

    try:
        temp_path = os.path.join(WORKSPACE_DIR, f"_test_{tool_name}.py")
    except:
        temp_path = f"_test_{tool_name}.py"

    test_script = f"""import math, json, os, requests, inspect
from langchain_core.tools import tool

{clean_code}

if __name__ == "__main__":
    sig = inspect.signature({tool_name}.func if hasattr({tool_name}, 'func') else {tool_name})
    dummy = {{}}
    for p, param in sig.parameters.items():
        ann = param.annotation
        if ann in (int, float):
            dummy[p] = 1.0
        else:
            dummy[p] = "test"
    try:
        target_func = {tool_name}.func if hasattr({tool_name}, 'func') else {tool_name}
        if hasattr({tool_name}, 'invoke'):
            result = {tool_name}.invoke(dummy)
        else:
            result = target_func(**dummy)
        print(f"TEST_OK: {{result}}")
    except Exception as e:
        print(f"TEST_FAIL: {{e}}")
"""

    try:
        with open(temp_path, "w", encoding="utf-8") as f:
            f.write(test_script)

        res = subprocess.run([sys.executable, temp_path], capture_output=True, text=True, timeout=15)
        stdout = res.stdout.strip()
        stderr = res.stderr.strip()

        try:
            os.remove(temp_path)
        except:
            pass

        if "TEST_FAIL" in stdout or (res.returncode != 0 and not stdout):
            error_detail = stdout or stderr
            return f"❌ Tool '{tool_name}' ΔΕΝ πέρασε το test.\nΣφάλμα: {error_detail[:600]}"

        sep = "═" * 62
        paste_code = f"from langchain_core.tools import tool\nimport math\n\n{clean_code}"

        print(f"\n\033[92m{sep}")
        print(f"  ✅  TOOL ΕΤΟΙΜΟ ΓΙΑ PASTE: {tool_name}")
        print(f"  🧪  Test: {stdout}")
        print(sep)
        print(paste_code)
        print(f"{sep}\033[0m\n")
        print("Λάζαρος: ", end="", flush=True)

        return f"✅ Tool '{tool_name}' γράφτηκε και πέρασε το test ({stdout})."

    except subprocess.TimeoutExpired:
        try:
            os.remove(temp_path)
        except:
            pass
        return "❌ Timeout: το test script κόλλησε πάνω από 15 δευτερόλεπτα."
    except Exception as e:
        return f"Error: {str(e)}"


# ────────────────────────────────────────────────────────────────
# EMAIL
# ────────────────────────────────────────────────────────────────
_BASE = os.path.dirname(os.path.abspath(__file__))
TOKEN_PATH = os.path.join(_BASE, '..', 'credentials', 'token.json')
CREDS_PATH = os.path.join(_BASE, '..', 'credentials', 'credentials.json')

SCOPES = [
    'https://www.googleapis.com/auth/gmail.modify',
    'https://www.googleapis.com/auth/drive',
    'https://www.googleapis.com/auth/calendar',
    'https://www.googleapis.com/auth/tasks',
    'https://www.googleapis.com/auth/fitness.activity.read',
    'https://www.googleapis.com/auth/fitness.sleep.read',
    'https://www.googleapis.com/auth/fitness.heart_rate.read',
]

def get_gmail_service():
    """Δημιουργεί το service του Gmail API χρησιμοποιώντας OAuth."""
    creds = None
    if os.path.exists(TOKEN_PATH):
        creds = Credentials.from_authorized_user_file(TOKEN_PATH, SCOPES)

    if not creds or not creds.valid:
        if not os.path.exists(CREDS_PATH):
            raise Exception("Λείπει το αρχείο credentials.json! Κατέβασέ το από το Google Cloud.")

        if creds and creds.expired and creds.refresh_token:
            from google.auth.transport.requests import Request
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(CREDS_PATH, SCOPES)
            creds = flow.run_local_server(port=0, prompt='consent', access_type='offline')

        with open(TOKEN_PATH, 'w') as token:
            token.write(creds.to_json())

    return build('gmail', 'v1', credentials=creds)


def decode_base64(data):
    return base64.urlsafe_b64decode(data.encode("UTF-8")).decode("utf-8", errors="replace")


def extract_body(payload):
    """Εξάγει body με fallback: plain text → HTML → nested parts."""
    import html

    def _parse_part(part):
        mime = part.get('mimeType', '')
        body = part.get('body', {})

        if 'parts' in part:
            for p in part['parts']:
                if p.get('mimeType') == 'text/plain' and 'data' in p.get('body', {}):
                    return decode_base64(p['body']['data'])
            for p in part['parts']:
                if p.get('mimeType') == 'text/html' and 'data' in p.get('body', {}):
                    return _html_to_text(decode_base64(p['body']['data']))
            for p in part['parts']:
                result = _parse_part(p)
                if result:
                    return result

        if 'data' in body:
            if mime == 'text/plain':
                return decode_base64(body['data'])
            elif mime == 'text/html':
                return _html_to_text(decode_base64(body['data']))

        return ""

    def _html_to_text(raw_html):
        # <br> και </p> → newlines για αναγνώσιμο κείμενο
        raw_html = re.sub(r'<br\s*/?>', '\n', raw_html, flags=re.IGNORECASE)
        raw_html = re.sub(r'</p>', '\n', raw_html, flags=re.IGNORECASE)
        text = re.sub(r'<[^>]+>', ' ', raw_html)
        text = html.unescape(text)
        return re.sub(r'\s+', ' ', text).strip()

    return _parse_part(payload)


def clean_text(text):
    """Καθαρίζει whitespace και αφαιρεί quoted replies (γραμμές με >)."""
    lines = text.splitlines()
    lines = [l for l in lines if not l.strip().startswith('>')]
    cleaned = '\n'.join(lines)
    return re.sub(r'\s+', ' ', cleaned).strip()

@tool
def mail_manager(action: str, query: str = None, email_id: str = None,
                 to_email: str = None, subject: str = None, body: str = None,
                 limit: int = 10) -> str:
    """
    Διαχείριση Gmail μέσω Google API. 
    Actions: 'search' (θέλει query), 'read_full' (θέλει email_id), 
             'send' (θέλει to_email, subject, body),
             'reply' (θέλει email_id, body),
             'delete' (θέλει email_id).
    """
    try:
        print(f"\033[94m[Mail API]: Εκτέλεση ενέργειας '{action}'...\033[0m")
        service = get_gmail_service()
        action = action.lower()

        # =========================
        # SEND
        # =========================
        if action == "send":
            if not to_email or not subject or not body:
                return "❌ Για send χρειάζονται: to_email, subject, body."
            message = (
                f"To: {to_email}\r\n"
                f"Subject: {subject}\r\n"
                f"Content-Type: text/plain; charset=utf-8\r\n"
                f"\r\n"
                f"{body}"
            )
            raw = base64.urlsafe_b64encode(message.encode("utf-8")).decode("utf-8")
            service.users().messages().send(userId="me", body={"raw": raw}).execute()
            return "✅ Email στάλθηκε κανονικά."

        # =========================
        # REPLY
        # =========================
        elif action == "reply":
            if not email_id or not body:
                return "❌ Για reply χρειάζεται email_id και body."
            
            original = service.users().messages().get(
                userId="me", id=email_id, format="metadata",
                metadataHeaders=["Subject", "From", "Message-ID", "References"]
            ).execute()
            
            headers = original["payload"]["headers"]
            orig_subject = next((h["value"] for h in headers if h["name"] == "Subject"), "Re: (no subject)")
            orig_from    = next((h["value"] for h in headers if h["name"] == "From"), "")
            orig_msg_id  = next((h["value"] for h in headers if h["name"] == "Message-ID"), "")
            orig_refs    = next((h["value"] for h in headers if h["name"] == "References"), "")
            
            reply_subject = orig_subject if orig_subject.startswith("Re:") else f"Re: {orig_subject}"
            references = f"{orig_refs} {orig_msg_id}".strip()
            
            reply_message = (
                f"To: {orig_from}\r\n"
                f"Subject: {reply_subject}\r\n"
                f"In-Reply-To: {orig_msg_id}\r\n"
                f"References: {references}\r\n"
                f"Content-Type: text/plain; charset=utf-8\r\n"
                f"\r\n"
                f"{body}"
            )
            raw = base64.urlsafe_b64encode(reply_message.encode("utf-8")).decode("utf-8")
            thread_id = original.get("threadId")
            service.users().messages().send(
                userId="me",
                body={"raw": raw, "threadId": thread_id}
            ).execute()
            return f"✅ Reply στάλθηκε στον {orig_from}."

        # =========================
        # SEARCH
        # =========================
        elif action in ["search", "check_emails", "check", "read"]:
            results = service.users().messages().list(userId="me", q=query, maxResults=limit).execute()
            messages = results.get("messages", [])

            if not messages:
                return f"Δεν βρέθηκαν email για την αναζήτηση: {query}"

            output = []
            for msg in messages:
                data = service.users().messages().get(
                    userId="me", id=msg['id'],
                    format="metadata",
                    metadataHeaders=["Subject", "From", "Date"]
                ).execute()
                headers = data['payload']['headers']
                subject_val = next((h['value'] for h in headers if h['name'] == 'Subject'), "No Subject")
                from_val    = next((h['value'] for h in headers if h['name'] == 'From'), "Unknown")
                date_val    = next((h['value'] for h in headers if h['name'] == 'Date'), "")
                output.append(f"ID: {msg['id']} | {date_val} | Από: {from_val} | Θέμα: {subject_val}")

            return "\n".join(output)

        # =========================
        # READ FULL
        # =========================
        elif action == "read_full":
            if not email_id:
                return "❌ Για read_full χρειάζεται email_id."
            data = service.users().messages().get(userId="me", id=email_id, format="full").execute()
            body_text = extract_body(data['payload'])
            return f"📩 Περιεχόμενο:\n{clean_text(body_text)[:5000]}"

        # =========================
        # DELETE
        # =========================
        elif action == "delete":
            if not email_id:
                return "❌ Για delete χρειάζεται email_id."
            service.users().messages().trash(userId="me", id=email_id).execute()
            return f"🗑️ Το email {email_id} μεταφέρθηκε στον κάδο."

        return f"❌ Άγνωστη εντολή: {action}"

    except Exception as e:
        return f"Mail API Error: {str(e)}"

# ────────────────────────────────────────────────────────────────
# GITHUB
# ────────────────────────────────────────────────────────────────

import subprocess
import shlex
from github import Github
from langchain_core.tools import tool

@tool
def github_manager(action: str, repo_name: str = "", target_files: str = "",
                   commit_message: str = "", content: str = "") -> str:
    """
    Manages GitHub operations and local Git commits.
    
    Actions: 
    - 'list_repos', 'read_file', 'create_file', 'update_file' (Cloud API Operations)
    - 'push_local_commits' (Runs local Git CLI commands)
    
    CRITICAL RULES for 'push_local_commits': 
    - target_files MUST be a comma-separated list of exact paths (e.g. "core/brain.py, api/server.py"). 
    - Using "." or "*" or "all" is STRICTLY FORBIDDEN.
    """
    token = os.getenv("GITHUB_TOKEN") 
    if not token:
        return "Error: Missing GITHUB_TOKEN."

    try:
        # ─── 1. LOCAL GIT CLI OPERATIONS (Mastro-Shielded) ──────────────
        if action == "push_local_commits":
            if not target_files or target_files.strip() in [".", "*", "all"]:
                return "🛡️ [GIT OVERRIDE]: Blind sweeps are forbidden. Specify exact file paths."
            if not commit_message:
                return "Error: Commit message is required."

            # ── SafeExec check ───────────────────────────────────────────
            from core.safe_executor import safe_execute
            push_check = safe_execute("git push origin main", lambda c: {"status": "ok"})
            if push_check.get("status") == "blocked":
                return f"🛡️ [SAFE EXECUTOR - BLOCKED]: {push_check['reason']}"
            if push_check.get("status") == "cancelled":
                return "⚠️ [SAFE EXECUTOR]: Το git push απαιτεί επιβεβαίωση. Ξαναστείλε με `/confirm`"
            # ────────────────────────────────────────────────────────────

            files = [f.strip() for f in target_files.split(",") if f.strip()]

            # 1. git add <files>
            add_cmd = ["git", "add"] + files
            subprocess.run(add_cmd, check=True, capture_output=True, text=True)

            # 2. git commit -m "message"
            commit_cmd = ["git", "commit", "-m", commit_message]
            subprocess.run(commit_cmd, check=True, capture_output=True, text=True)

            # 3. git push origin main
            push_cmd = ["git", "push", "origin", "main"]
            subprocess.run(push_cmd, check=True, capture_output=True, text=True)

            return f"System: Local changes successfully pushed!\nFiles: {files}\nMessage: {commit_message}"

        # ─── 2. GITHUB CLOUD API OPERATIONS ─────────────────────────────
        g = Github(token)
        user = g.get_user()

        if action == "list_repos":
            repos = [f"- {r.name} ({'Private' if r.private else 'Public'})" for r in user.get_repos()]
            return f"Found {len(repos)} Repositories:\n" + "\n".join(repos)

        elif action == "read_file":
            repo = g.get_repo(f"{user.login}/{repo_name}")
            file_content = repo.get_contents(target_files)
            return f"Content of {target_files}:\n{file_content.decoded_content.decode('utf-8')[:10000]}"

        elif action in ["create_file", "update_file"]:
            if not content.strip():
                return "🛡️ [GIT OVERRIDE]: Content is empty. Refusing to overwrite file with empty data."
            repo = g.get_repo(f"{user.login}/{repo_name}")
            try:
                file_info = repo.get_contents(target_files)
                repo.update_file(target_files, commit_message, content, file_info.sha)
                return f"System: '{target_files}' in '{repo_name}' updated via API!"
            except:
                repo.create_file(target_files, commit_message, content)
                return f"System: '{target_files}' created in '{repo_name}' via API!"

        else:
            return "Error: Invalid action specified."

    except subprocess.CalledProcessError as e:
        return f"Local Git Command Error: {e.stderr}"
    except Exception as e:
        return f"GitHub API Error: {str(e)}"


# ────────────────────────────────────────────────────────────────
# HARDWARE CONTROL
# ────────────────────────────────────────────────────────────────

@tool
def control_vacuum(action: str) -> str:
    """Ελέγχει τη ρομποτική σκούπα Xiaomi X20+.
    Actions: 'start', 'stop', 'home'."""
    ip = VACUUM_IP
    token = VACUUM_TOKEN

    if not ip or not token:
        return "Σφάλμα: Δεν βρέθηκαν VACUUM_IP ή VACUUM_TOKEN."

    try:
        vac = Device(ip, token)

        if action == "start":
            vac.send("action", {"did": "astakos", "siid": 2, "aiid": 1, "in": []})
            return "Ο Αστακός έδωσε εντολή: Η X20+ ξεκίνησε το σκούπισμα! 🧹"

        elif action == "stop":
            vac.send("action", {"did": "astakos", "siid": 2, "aiid": 2, "in": []})
            return "Ο Αστακός έδωσε εντολή: Η σκούπα σταμάτησε."

        elif action == "home":
            vac.send("action", {"did": "astakos", "siid": 3, "aiid": 1, "in": []})
            return "Ο Αστακός έδωσε εντολή: Η σκούπα επιστρέφει στη βάση. 🏠"

        else:
            return f"Άγνωστη εντολή: {action}."

    except Exception as e:
        return f"Σφάλμα επικοινωνίας με τη σκούπα: {str(e)}"
@tool
def post_to_linkedin(text: str = None, image_path: str = None) -> str:
    """
    Δημοσιεύει κείμενο και προαιρετικά μια εικόνα στο LinkedIn.
    Αν δεν δοθεί text, το τραβάει αυτόματα από το linkedin_draft.json.
    """
    import os
    import json
    import requests
    from dotenv import load_dotenv, find_dotenv
    from config import LINKEDIN_DRAFT_FILE

    # [MASTRO-INTERCEPTOR]: Αυτονομία από τη Working Memory
    if not text:
        if os.path.exists(LINKEDIN_DRAFT_FILE):
            try:
                with open(LINKEDIN_DRAFT_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    text = data.get("content") or data.get("text")
                    if not image_path:
                        image_path = data.get("image_path")
            except Exception as e:
                print(f"⚠️ Σφάλμα ανάγνωσης draft: {e}")

    if not text:
        return "❌ Σφάλμα: Δεν βρέθηκε κείμενο (ούτε στο draft, ούτε στα ορίσματα)."

    # --- LinkedIn API Logic ---
    load_dotenv(find_dotenv(), override=True)
    token = os.getenv("LINKEDIN_TOKEN")
    if not token: return "❌ Λείπει το LINKEDIN_TOKEN."

    headers = {
        "Authorization": f"Bearer {token}",
        "X-Restli-Protocol-Version": "2.0.0",
        "Content-Type": "application/json"
    }

    try:
        # 1. Ταυτοποίηση
        user_res = requests.get("https://api.linkedin.com/v2/userinfo", headers=headers)
        if user_res.status_code != 200: return f"❌ Auth Error: {user_res.text}"
        person_urn = f"urn:li:person:{user_res.json().get('sub')}"
        asset_urn = None

        # 2. Upload Image (αν υπάρχει)
        if image_path and os.path.exists(image_path):
            reg_url = "https://api.linkedin.com/v2/assets?action=registerUpload"
            reg_data = {"registerUploadRequest": {"recipes": ["urn:li:digitalmediaRecipe:feedshare-image"], "owner": person_urn, "serviceRelationships": [{"relationshipType": "OWNER", "identifier": "urn:li:userGeneratedContent"}]}}
            reg_res = requests.post(reg_url, headers=headers, json=reg_data)
            if reg_res.status_code == 200:
                upload_url = reg_res.json()['value']['uploadMechanism']['com.linkedin.digitalmedia.uploading.MediaUploadHttpRequest']['uploadUrl']
                asset_urn = reg_res.json()['value']['asset']
                with open(image_path, 'rb') as f:
                    requests.post(upload_url, headers={"Authorization": f"Bearer {token}"}, data=f.read())

        # 3. Δημιουργία Post
        post_url = "https://api.linkedin.com/v2/ugcPosts"
        media_content = {
            "shareCommentary": {"text": text},
            "shareMediaCategory": "IMAGE" if asset_urn else "NONE"
        }
        if asset_urn:
            media_content["media"] = [{"status": "READY", "media": asset_urn, "title": {"text": "Astakos Post"}}]

        payload = {
            "author": person_urn,
            "lifecycleState": "PUBLISHED",
            "specificContent": {"com.linkedin.ugc.ShareContent": media_content},
            "visibility": {"com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"}
        }

        res = requests.post(post_url, headers=headers, json=payload)
        
        if res.status_code == 201:
            # [MASTRO-CLEANUP]: Καθαρισμός draft μετά την επιτυχία
            if os.path.exists(LINKEDIN_DRAFT_FILE):
                with open(LINKEDIN_DRAFT_FILE, "w", encoding="utf-8") as f:
                    json.dump({}, f)
            return "✅ Το LinkedIn post ανέβηκε και το draft καθαρίστηκε!"
        
        return f"❌ Αποτυχία: {res.text}"

    except Exception as e:
        return f"❌ Κρίσιμο Σφάλμα: {str(e)}"
import math

def _is_home(lat: float, lon: float, home_lat: float = 40.646537, home_lon: float = 22.939025, radius_m: float = 150) -> bool:
    """Ελέγχει αν οι συντεταγμένες είναι εντός 150m από το Piston 7."""
    R = 6371000
    dlat = math.radians(lat - home_lat)
    dlon = math.radians(lon - home_lon)
    a = math.sin(dlat/2)**2 + math.cos(math.radians(home_lat)) * math.cos(math.radians(lat)) * math.sin(dlon/2)**2
    return R * 2 * math.asin(math.sqrt(a)) < radius_m


@tool
def get_current_location() -> str:
    """
    Επιστρέφει το τελευταίο καταγεγραμμένο GPS στίγμα του Λάζαρου από το last_location.json.
    Χρησιμοποιείται για να ξέρουμε πού βρίσκεται ο χρήστης σε πραγματικό χρόνο.
    """
    import json
    import os
    import time
    from datetime import datetime
    from config import GPS_STORAGE_FILE

    if not os.path.exists(GPS_STORAGE_FILE):
        return "📍 Δεν υπάρχει καταγεγραμμένο στίγμα ακόμα. Ζήτα από τον Λάζαρο να στείλει Live Location."

    try:
        with open(GPS_STORAGE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            lat = data.get("lat")
            lon = data.get("lon")
            ts = data.get("timestamp", 0)

            # Υπολογισμός "φρεσκάδας"
            diff_minutes = int((time.time() - ts) / 60)
            last_seen = datetime.fromtimestamp(ts).strftime('%H:%M:%S')

            if diff_minutes > 1440:
                return f"📍 Το στίγμα είναι πολύ παλιό (ηλικίας {diff_minutes // 60}h, τελευταία ενημέρωση {last_seen})."

            maps_link = f"https://maps.google.com/?q={lat},{lon}"
            home_status = "🏠 Είναι ΣΠΙΤΙ" if _is_home(float(lat), float(lon)) else "🚶 Είναι ΕΚΤΟΣ σπιτιού"

            return (
                f"📍 Συντεταγμένες: {lat}, {lon}\n"
                f"{home_status}\n"
                f"🗺️ <a href='{maps_link}'>Δες στον Χάρτη</a>\n"
                f"⏱️ Ενημερώθηκε πριν {diff_minutes} λεπτά (στις {last_seen})."
            )

    except Exception as e:
        return f"❌ Σφάλμα κατά την ανάγνωση του GPS: {str(e)}"

@tool
def control_spotify(
    action: str,
    query: str = ""
) -> str:
    """Ελέγχει το Spotify.
    action: 'play', 'pause', 'next', 'now_playing', 'top_tracks', 'search'
    query: Τίτλος/Καλλιτέχνης για action='search'"""
    try:
        scope = "user-modify-playback-state user-read-playback-state user-top-read user-read-currently-playing"
        sp = spotipy.Spotify(auth_manager=SpotifyOAuth(scope=scope))

        if action == "top_tracks":
            results = sp.current_user_top_tracks(limit=5, time_range='long_term')
            if not results['items']:
                return "Δεν βρέθηκαν δεδομένα για top tracks."
            tracks = [f"{i+1}. {t['name']} - {t['artists'][0]['name']}" for i, t in enumerate(results['items'])]
            return "🎵 Top 5 τραγούδια σου:\n" + "\n".join(tracks)

        elif action == "pause":
            sp.pause_playback()
            return "⏸️ Η μουσική σταμάτησε."

        elif action == "next":
            sp.next_track()
            return "⏭️ Πήγαμε στο επόμενο τραγούδι!"

        elif action == "now_playing":
            current = sp.current_playback()
            if not current or not current.get("item"):
                return "Δεν παίζει τίποτα αυτή τη στιγμή."
            track = current["item"]
            artist = track["artists"][0]["name"]
            name = track["name"]
            playing = "▶️" if current["is_playing"] else "⏸️"
            return f"{playing} {name} — {artist}"

        elif action == "search":
            if not query:
                return "❌ Δώσε τίτλο ή καλλιτέχνη για αναζήτηση."
            res = sp.search(q=query, type='track', limit=1)
            if not res['tracks']['items']:
                return f"❌ Δεν βρήκα το '{query}'."
            track_uri = res['tracks']['items'][0]['uri']
            track_name = res['tracks']['items'][0]['name']
            sp.start_playback(uris=[track_uri])
            return f"▶️ Έβαλα να παίζει: {track_name} 🎵"

        elif action == "play":
            sp.start_playback()
            return "▶️ Η μουσική ξεκίνησε ξανά!"

        return "❌ Άγνωστη εντολή. Δοκίμασε: play, pause, next, now_playing, top_tracks, search."

    except Exception as e:
        return f"⚠️ Spotify Error: {str(e)}. (Μήπως δεν έχεις ανοιχτή την εφαρμογή;)"

@tool
def get_fit_summary(days_ago: int = 1) -> str:
    """
    Επιστρέφει σύνοψη Google Fit για τον Λάζαρο.
    days_ago=0 → σήμερα, days_ago=1 → χθες (default).
    Περιλαμβάνει: βήματα, ύπνο (ώρες + deep/REM), καρδιακούς παλμούς.
    """
    try:
        from astakos_skills.google_fit import get_daily_summary
        return get_daily_summary(days_ago=days_ago)
    except Exception as e:
        return f"❌ Google Fit σφάλμα: {e}"


@tool
def save_goal_tool(project: str, description: str, status: str = "active") -> str:
    """
    Αποθηκεύει ή ενημερώνει ένα long-term goal του Λάζαρου.
    project: Σύντομο όνομα project (π.χ. 'ShiftMaster', 'Astakos', 'PraxisERP').
    description: Τι θέλει να πετύχει (π.χ. 'Να τελειώσει το licensing module').
    status: 'active' (σε εξέλιξη) | 'paused' (στο ράφι) | 'done' (ολοκληρώθηκε).
    """
    from memory.vector_store import save_goal
    ok = save_goal(project=project, description=description, status=status)
    if ok:
        return f"✅ Goal '{project}' αποθηκεύτηκε ({status})."
    return f"❌ Αποτυχία αποθήκευσης goal '{project}'."


@tool
def update_goal_status_tool(project: str, status: str) -> str:
    """
    Ενημερώνει το status ενός υπάρχοντος goal.
    project: Το όνομα του project (π.χ. 'ShiftMaster').
    status: 'active' | 'paused' | 'done'
    """
    from memory.vector_store import update_goal_status
    ok = update_goal_status(project=project, status=status)
    if ok:
        return f"✅ Goal '{project}' → {status}."
    return f"❌ Δεν βρέθηκε goal '{project}'."


all_tools = [
    search_memory, save_to_memory, delete_from_memory, retrieve_photo, update_pending_linkedin_post, process_and_clear_linkedin_post,
    set_local_reminder, set_reminder, manage_list,
    google_calendar_tool, google_tasks_tool, drive_manager,
    read_local_file, write_code, run_code, write_custom_tool,
    mail_manager, github_manager, control_vacuum, control_spotify, recipe_expert, search_flights, search_google_places,
    log_meal, create_file_tool, get_current_location,
    get_news, get_weather_forecast, search_supermarket_prices, relay_local_payload,
    search_goldmall_offers, execute_local_pipeline, archive_file, get_navigation_info, generate