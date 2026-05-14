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
import subprocess
import imaplib
import email
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timedelta
from langchain_core.tools import tool
from pypdf import PdfReader
from github import Github
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from miio import Device
import spotipy
from spotipy.oauth2 import SpotifyOAuth
import docx
import pandas as pd
from googleapiclient.discovery import build
from google_auth_oauthlib.flow import InstalledAppFlow
from google.oauth2.credentials import Credentials
import base64
from config import (
    REMINDERS_FILE, LISTS_FILE, WORKSPACE_DIR, PHOTOS_INDEX_FILE,
    EMAIL_ADDRESS, EMAIL_PASSWORD, GITHUB_TOKEN, VACUUM_IP, VACUUM_TOKEN
)
from astakos_skills.linkedin_state_manager import update_pending_linkedin_post, process_and_clear_linkedin_post
from langchain_community.tools import DuckDuckGoSearchRun
from memory.vector_store import vector_store, vector_lock, memory
from services.embeddings import embeddings
from tools.web import (
    get_news, get_weather_forecast, search_supermarket_offers,
    search_goldmall_offers, send_messenger_message, get_navigation_info
)
from astakos_skills.recipe_expert import recipe_expert, log_meal
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
        from config import PHOTOS_DIR
        from memory.vector_store import memory
        
        base_dir = os.getcwd()
        search_dirs = [
            "", PHOTOS_DIR,
            os.path.join(base_dir, "telegram_uploads"),
            os.path.join(base_dir, "telegram_photos"),
            os.path.join(base_dir, "uploads")
        ]
        
        full_path = None
        for d in search_dirs:
            test_path = os.path.join(d, filename) if d else filename
            if os.path.exists(test_path) and os.path.isfile(test_path):
                full_path = test_path
                break
                
        if not full_path:
            return f"❌ Σφάλμα: Το αρχείο {filename} δεν βρέθηκε."
        
        # Καθορίζουμε αν είναι φωτογραφία ή έγγραφο
        ext = os.path.splitext(full_path)[1].lower()
        m_type = "photo" if ext in [".jpg", ".jpeg", ".png", ".webp", ".gif"] else "document"
        
        # Αποθήκευση στην ChromaDB και το JSON
        memory.save(
            memory_type=m_type,
            file_path=full_path,
            analysis=content_summary,
            caption=f"Αρχειοθέτηση ({m_type}): {filename}"
        )
        return f"✅ Έγινε, Μάστορα! Το αρχείο {filename} ({m_type}) αρχειοθετήθηκε μόνιμα με τη σύνοψη που έδωσες."
    except Exception as e:
        return f"❌ Σφάλμα αρχειοθέτησης: {str(e)}"

@tool
def search_memory(query: str, category: str = "") -> str:
    """Αναζήτηση στη μακροπρόθεσμη μνήμη. Κάλεσέ το ΠΑΝΤΑ πριν απαντήσεις σε:
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
def run_terminal_command(command: str) -> str:
    """
    Εκτελεί εντολές PowerShell στο PC του Λάζαρου (Piston-7) και επιστρέφει το αποτέλεσμα.
    Ιδανικό για:
    - Ανάγνωση logs (π.χ. 'Get-Content C:\\path\\to\\mastroapp\\logs\\error.log -Tail 50').
    - Έλεγχο ports (π.χ. 'netstat -ano | findstr 8000').
    - Εκτέλεση tests (π.χ. 'python manage.py test').
    """
    import subprocess
    
    print(f"\033[93m[Terminal Execution]: {command}\033[0m")
    
    try:
        # Εκτελούμε την εντολή μέσω PowerShell. Βάζουμε timeout 30s για να μη "κολλήσει" ο Αστακός.
        result = subprocess.run(
            ["powershell", "-Command", command], 
            capture_output=True, 
            text=True, 
            timeout=30,
            encoding='utf-8', 
            errors='ignore'
        )
        
        # Αν η εντολή πετύχει, παίρνουμε το stdout. Αν σκάσει, παίρνουμε το stderr (το stack trace δηλαδή).
        output = result.stdout if result.returncode == 0 else f"ERROR:\n{result.stderr}"
        
        if not output.strip():
            return "Η εντολή εκτελέστηκε επιτυχώς (δεν επέστρεψε output)."
            
        # Κόβουμε τους χαρακτήρες στους 10.000 για να μην "πνίξουμε" τη μνήμη του Agent
        return f"💻 Terminal Output:\n{output[-10000:]}"
        
    except subprocess.TimeoutExpired:
        return "❌ Error: Το process πήρε πάνω από 30 δευτερόλεπτα και τερματίστηκε."
    except Exception as e:
        return f"❌ Terminal Error: {str(e)}"

@tool
def save_to_memory(fact: str, entities: str = "", category: str = "general") -> str:
    """
    Αποθηκεύει πληροφορίες ΣΗΜΑΣΙΟΛΟΓΙΚΑ.
    fact: Το γεγονός (π.χ. "Ο Αλέξανδρος τρώει μόνο φακές").
    entities: Λέξεις-κλειδιά χωρισμένες με κόμμα (π.χ. "Αλέξανδρος, Φαγητό, Προτίμηση").
    category: Η κατηγορία (π.χ. 'family', 'home', 'lazaros', 'tech', 'work').
    """
    import datetime
    from memory.vector_store import vector_store
    
    try:
        # [MASTRO-GRAPH]: Ενώνουμε το γεγονός με τα tags για να "χτυπάει" τέλεια στο vector search
        semantic_payload = f"{fact} [Tags: {entities}]"
        
        # Καρφώνουμε τη μνήμη στη βάση με τα Metadata της
        vector_store.add_texts(
            texts=[semantic_payload],
            metadatas=[{
                "category": category,
                "entities": entities,
                "timestamp": datetime.datetime.now().timestamp(),
                "type": "semantic_node"
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
            distance = results['distances'][0][0] if 'distances' in results and results['distances'] else 0.0

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
                query_emb = embeddings.embed_query(query)
                best_score = -1.0
                best_entry = None

                for entry in index:
                    candidate = f"{entry.get('caption', '')} {entry.get('analysis', '')}".strip()
                    if not candidate:
                        continue
                    cand_emb = embeddings.embed_query(candidate)
                    dot = sum(a * b for a, b in zip(query_emb, cand_emb))
                    norm_q = sum(a * a for a in query_emb) ** 0.5
                    norm_c = sum(b * b for b in cand_emb) ** 0.5
                    if norm_q and norm_c:
                        sim = dot / (norm_q * norm_c)
                        if sim > best_score:
                            best_score = sim
                            best_entry = entry

                if best_entry:
                    fp = best_entry.get("file_path", "")
                    note = "" if best_score >= 0.5 else " (Δεν βρήκα ακριβή αντιστοιχία — δίνω την πιο πρόσφατη.)"
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
def set_local_reminder(task: str, minutes_from_now: int = 0, exact_time: str = None) -> str:
    """Βάζει τοπική υπενθύμιση. Δώσε minutes_from_now ή exact_time ('YYYY-MM-DD HH:MM')."""
    try:
        rems = []
        if os.path.exists(REMINDERS_FILE):
            with open(REMINDERS_FILE, "r", encoding="utf-8") as f:
                try:
                    rems = json.load(f)
                except:
                    pass

        if minutes_from_now > 0:
            target_time = (datetime.now() + timedelta(minutes=minutes_from_now)).strftime("%Y-%m-%d %H:%M")
        elif exact_time:
            target_time = exact_time
        else:
            return "Σφάλμα: Πρέπει να δώσεις λεπτά ή ακριβή ώρα (YYYY-MM-DD HH:MM)."

        rems.append({"task": task, "time": target_time, "status": "pending"})

        with open(REMINDERS_FILE, "w", encoding="utf-8") as f:
            json.dump(rems, f, ensure_ascii=False, indent=4)

        return f"✅ Η υπενθύμιση ρυθμίστηκε επιτυχώς για τις {target_time}!"
    except Exception as e:
        return f"Σφάλμα υπενθύμισης: {e}"


@tool
def set_reminder(task: str, time_str: str) -> str:
    """Δημιουργεί τοπική υπενθύμιση (format time_str: 'YYYY-MM-DD HH:MM')."""
    rems = []
    if os.path.exists(REMINDERS_FILE):
        with open(REMINDERS_FILE, "r", encoding="utf-8") as f:
            try:
                rems = json.load(f)
            except:
                pass
    rems.append({"task": task, "time": time_str, "status": "pending"})
    with open(REMINDERS_FILE, "w", encoding="utf-8") as f:
        json.dump(rems, f, ensure_ascii=False, indent=4)
    return "System: Η υπενθύμιση ρυθμίστηκε."


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
                except:
                    pass

        if list_name not in lists_db and action != "delete":
            lists_db[list_name] = []

        if action == "read":
            current = lists_db.get(list_name, [])
            if not current:
                return f"Η λίστα '{list_name}' είναι άδεια."
            return f"Περιεχόμενα '{list_name}':\n" + "\n".join([f"- {i}" for i in current])

        to_process = [i.strip() for i in item.split(",")] if item else []

        if action == "add":
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
        token_path = 'credentials/token.json'
        creds = Credentials.from_authorized_user_file(token_path, ['https://www.googleapis.com/auth/calendar'])
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
        token_path = 'credentials/token.json'
        creds = Credentials.from_authorized_user_file(token_path, ['https://www.googleapis.com/auth/tasks'])
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
    
    # Φάκελος εξαγωγής (π.χ. C:\astakos_v2\outputs)
    output_dir = os.path.join(BASE_DIR, "outputs")
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
        
    full_path = os.path.join(output_dir, filename)
    file_type = file_type.lower()

    try:
        if file_type == "docx":
            import docx
            doc = docx.Document()
            doc.add_paragraph(data)
            doc.save(full_path)

        elif file_type == "xlsx":
            import pandas as pd
            # Προσπάθεια μετατροπής του string σε data frame
            try:
                content = json.loads(data)
                df = pd.DataFrame(content)
            except:
                # Αν δεν είναι JSON, το βάζουμε σε μια απλή στήλη
                df = pd.DataFrame([data], columns=["Content"])
            df.to_excel(full_path, index=False)

        elif file_type == "pdf":
            from fpdf import FPDF
            pdf = FPDF()
            pdf.add_page()
            # Χρήση DejaVu ή standard font (για ελληνικά ίσως χρειαστεί .ttf)
            pdf.set_font("Arial", size=12)
            pdf.multi_cell(0, 10, data.encode('latin-1', 'replace').decode('latin-1'))
            pdf.output(full_path)

        # [MASTRO-UPGRADE]: Εδώ βάλαμε και json, csv, html, md
        elif file_type in ["txt", "json", "csv", "html", "md"]:
            with open(full_path, "w", encoding="utf-8") as f:
                f.write(data)

        else:
            return f"❌ Σφάλμα: Ο τύπος '{file_type}' δεν υποστηρίζεται."

        # [MASTRO-FIX]: Η ειδική ταμπέλα για την αναχαίτιση!
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

    # Αποθηκεύουμε στον ΙΔΙΟ φάκελο με τα έγγραφα για να τα βλέπει ο Server
    output_dir = os.path.join(BASE_DIR, "outputs")
    os.makedirs(output_dir, exist_ok=True)

    safe_filename = slugify(prompt[:30]) or "gen_image"
    filename = f"{safe_filename}_{int(time.time())}.jpg"
    full_path = os.path.join(output_dir, filename)

    api_url = f"https://image.pollinations.ai/prompt/{requests.utils.quote(prompt)}?nologo=true"

    try:
        res = requests.get(api_url)
        if res.status_code == 200:
            with open(full_path, 'wb') as f:
                f.write(res.content)
            # Στέλνουμε το SEND_PHOTO tag!
            return f"✅ Έτοιμο! Η εικόνα δημιουργήθηκε.\n[SEND_PHOTO: {full_path}]"
        return "❌ Σφάλμα API. Η μηχανή μπούκωσε."
    except Exception as e:
        return f"❌ Σφάλμα: {str(e)}"
@tool
def drive_manager(action: str = "list_files", file_id: str = None, local_path: str = None,
                  folder_id: str = "12YrIZ3uAQWmmwIlEkIkDf-4gcz2P8Ktv") -> str:
    """Διαχειρίζεται το Google Drive.
    Actions: 'list_files', 'download' (χρειάζεται file_id), 'upload' (χρειάζεται local_path)."""
    try:
        from googleapiclient.http import MediaIoBaseDownload, MediaFileUpload
        import io

        print(f"\033[93m[Drive]: Ενέργεια {action}...\033[0m")
        creds = Credentials.from_authorized_user_file('token.json', SCOPES)
        service = build('drive', 'v3', credentials=creds)

        if action == "list_files":
            results = service.files().list(
                q=f"'{folder_id}' in parents and trashed=false",
                fields="files(id, name, mimeType)"
            ).execute()
            items = results.get('files', [])
            if not items:
                return "Ο φάκελος είναι άδειος."
            output = "📁 Αρχεία στο Drive:\n"
            for i in items:
                output += f"- {i['name']} (ID: {i['id']}) | Type: {i['mimeType']}\n"
            return output

        elif action == "download" and file_id:
            file_metadata = service.files().get(fileId=file_id).execute()
            mime_type = file_metadata.get('mimeType')
            file_name = file_metadata.get('name', 'downloaded_file')

            if "vnd.google-apps" in mime_type:
                request = service.files().export_media(fileId=file_id, mimeType='text/plain')
            else:
                request = service.files().get_media(fileId=file_id)

            fh = io.BytesIO()
            downloader = MediaIoBaseDownload(fh, request)
            done = False
            while not done:
                _, done = downloader.next_chunk()

            if local_path or file_name.lower().endswith('.pdf'):
                save_target = local_path if local_path else file_name
                with open(save_target, "wb") as f:
                    f.write(fh.getvalue())
                return (
                    f"✅ Το αρχείο '{file_name}' κατέβηκε ως '{save_target}'. "
                    f"Χρησιμοποίησε 'read_local_file' για να το διαβάσεις."
                )
            return f"✅ '{file_name}':\n\n{fh.getvalue().decode('utf-8', errors='ignore')[:8000]}"

        elif action == "upload" and local_path:
            if not os.path.exists(local_path):
                return f"Error: Το αρχείο {local_path} δεν υπάρχει τοπικά."
            file_metadata = {'name': os.path.basename(local_path), 'parents': [folder_id]}
            media = MediaFileUpload(local_path, resumable=True)
            file = service.files().create(body=file_metadata, media_body=media, fields='id').execute()
            return f"✅ Το αρχείο ανέβηκε! (Drive ID: {file.get('id')})"

        return "Error: Λείπουν παράμετροι."
    except Exception as e:
        return f"Drive Error: {str(e)}"


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

    # [MASTRO-RADAR]: Λίστα αναζήτησης
    search_dirs = [
        "",  # Απόλυτο path
        PHOTOS_DIR,
        os.path.join(base_dir, "telegram_uploads"),
        os.path.join(base_dir, "telegram_photos"),
        os.path.join(base_dir, "uploads")
    ]

    full_path = None
    print(f"\033[93m[Tool Debug]: Ψάχνω το αρχείο: {filename}\033[0m")
    
    for d in search_dirs:
        test_path = os.path.join(d, filename) if d else file_path
        if os.path.exists(test_path) and os.path.isfile(test_path):
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
def run_code(filename: str) -> str:
    """Εκτελεί ένα αρχείο Python ΜΟΝΟ από τον φάκελο astakos_skills."""
    safe_filename = os.path.basename(filename)
    file_path = os.path.join(WORKSPACE_DIR, safe_filename)

    if not os.path.exists(file_path):
        return f"Error: Το αρχείο {file_path} δεν υπάρχει στο Sandbox."

    try:
        print(f"\033[93m[Dev]: Εκτέλεση του {file_path}...\033[0m")
        venv_python = sys.executable
        res = subprocess.run([venv_python, file_path], capture_output=True, text=True, timeout=20)
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
SCOPES = [
    'https://www.googleapis.com/auth/gmail.modify',
    'https://www.googleapis.com/auth/drive',
    'https://www.googleapis.com/auth/calendar',
    'https://www.googleapis.com/auth/tasks'
]

def get_gmail_service():
    """Δημιουργεί το service του Gmail API χρησιμοποιώντας OAuth."""
    creds = None
    if os.path.exists('token.json'):
        creds = Credentials.from_authorized_user_file('token.json', SCOPES)

    if not creds or not creds.valid:
        if not os.path.exists('credentials.json'):
            raise Exception("Λείπει το αρχείο credentials.json! Κατέβασέ το από το Google Cloud.")
        
        # Αν το token έχει λήξει αλλά έχουμε refresh token
        if creds and creds.expired and creds.refresh_token:
            from google.auth.transport.requests import Request
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file('credentials.json', SCOPES)
            creds = flow.run_local_server(port=0)

        with open('token.json', 'w') as token:
            token.write(creds.to_json())

    return build('gmail', 'v1', credentials=creds)

def decode_base64(data):
    return base64.urlsafe_b64decode(data.encode("UTF-8")).decode("utf-8", errors="replace")

def extract_body(payload):
    if 'parts' in payload:
        for part in payload['parts']:
            if part['mimeType'] == 'text/plain':
                if 'data' in part['body']:
                    return decode_base64(part['body']['data'])
    elif 'body' in payload and 'data' in payload['body']:
        return decode_base64(payload['body']['data'])
    return ""

def clean_text(text):
    return re.sub(r'\s+', ' ', text).strip()

@tool
def mail_manager(action: str, query: str = None, email_id: str = None,
                 to_email: str = None, subject: str = None, body: str = None,
                 limit: int = 10) -> str:
    """
    Διαχείριση Gmail μέσω Google API. 
    Actions: 'search' (θέλει query), 'read_full' (θέλει email_id), 'send', 'delete'.
    """
    try:
        print(f"\033[94m[Mail API]: Εκτέλεση ενέργειας '{action}'...\033[0m")
        service = get_gmail_service()
        action = action.lower()

        # =========================
        # SEND
        # =========================
        if action == "send":
            message = f"To: {to_email}\r\nSubject: {subject}\r\n\r\n{body}"
            raw = base64.urlsafe_b64encode(message.encode("utf-8")).decode("utf-8")
            service.users().messages().send(userId="me", body={"raw": raw}).execute()
            return "✅ Email στάλθηκε κανονικά."

        # =========================
        # SEARCH
        # =========================
        if action in ["search", "check_emails", "check", "read"]:
            results = service.users().messages().list(userId="me", q=query, maxResults=limit).execute()
            messages = results.get("messages", [])

            if not messages:
                return f"Δεν βρέθηκαν email για την αναζήτηση: {query}"

            output = []
            for msg in messages:
                data = service.users().messages().get(userId="me", id=msg['id']).execute()
                headers = data['payload']['headers']
                subject_val = next((h['value'] for h in headers if h['name'] == 'Subject'), "No Subject")
                from_val = next((h['value'] for h in headers if h['name'] == 'From'), "Unknown")
                output.append(f"ID: {msg['id']} | Από: {from_val} | Θέμα: {subject_val}")

            return "\n".join(output)

        # =========================
        # READ FULL
        # =========================
        elif action == "read_full" and email_id:
            data = service.users().messages().get(userId="me", id=email_id, format="full").execute()
            body_text = extract_body(data['payload'])
            return f"📩 Περιεχόμενο:\n{clean_text(body_text)[:5000]}"

        # =========================
        # DELETE
        # =========================
        elif action == "delete" and email_id:
            service.users().messages().trash(userId="me", id=email_id).execute()
            return f"🗑️ Το email {email_id} μεταφέρθηκε στον κάδο."

        return f"❌ Άγνωστη εντολή: {action}"

    except Exception as e:
        return f"Mail API Error: {str(e)}"


# ────────────────────────────────────────────────────────────────
# GITHUB
# ────────────────────────────────────────────────────────────────

@tool
def github_manager(action: str, repo_name: str = "", file_path: str = "",
                   commit_message: str = "", content: str = "") -> str:
    """Διαχειρίζεται το GitHub.
    Actions: 'list_repos', 'read_file', 'create_file', 'update_file'."""
    token = GITHUB_TOKEN
    if not token:
        return "Error: Λείπει το GITHUB_TOKEN."

    try:
        g = Github(token)
        user = g.get_user()

        if action == "list_repos":
            repos = [f"- {r.name} ({'Private' if r.private else 'Public'})" for r in user.get_repos()]
            return f"Βρέθηκαν {len(repos)} Repositories:\n" + "\n".join(repos)

        elif action == "read_file":
            repo = g.get_repo(f"{user.login}/{repo_name}")
            file_content = repo.get_contents(file_path)
            return f"Content of {file_path}:\n{file_content.decoded_content.decode('utf-8')[:10000]}"

        elif action in ["create_file", "update_file"]:
            repo = g.get_repo(f"{user.login}/{repo_name}")
            try:
                file_info = repo.get_contents(file_path)
                repo.update_file(file_path, commit_message, content, file_info.sha)
                return f"System: Το '{file_path}' στο '{repo_name}' ενημερώθηκε!"
            except:
                repo.create_file(file_path, commit_message, content)
                return f"System: Το '{file_path}' δημιουργήθηκε στο '{repo_name}'!"

        else:
            return "Error: Χρησιμοποίησε list_repos, read_file, create_file, ή update_file."

    except Exception as e:
        return f"GitHub Error: {str(e)}"


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
def post_to_linkedin(text: str, image_path: str = None) -> str:
    """
    Δημοσιεύει κείμενο και προαιρετικά μια εικόνα στο LinkedIn του Λάζαρου.
    Αν δοθεί image_path, το εργαλείο ανεβάζει πρώτα την εικόνα και μετά κάνει το post.
    """
    import os
    import requests
    from dotenv import load_dotenv, find_dotenv

    load_dotenv(find_dotenv(), override=True)
    LINKEDIN_TOKEN = os.getenv("LINKEDIN_TOKEN")
    
    if not LINKEDIN_TOKEN:
        return "❌ Σφάλμα: Λείπει το LINKEDIN_TOKEN."

    headers = {
        "Authorization": f"Bearer {LINKEDIN_TOKEN}",
        "X-Restli-Protocol-Version": "2.0.0",
        "Content-Type": "application/json"
    }

    try:
        # 1. Ταυτοποίηση Χρήστη
        user_res = requests.get("https://api.linkedin.com/v2/userinfo", headers=headers)
        if user_res.status_code != 200:
            return f"❌ Σφάλμα Auth: {user_res.text}"
        
        person_urn = f"urn:li:person:{user_res.json().get('sub')}"
        asset_urn = None

        # 2. Αν υπάρχει εικόνα, ξεκινάμε τη διαδικασία Upload
        if image_path and os.path.exists(image_path):
            print(f"[LinkedIn]: Registering image upload...")
            register_url = "https://api.linkedin.com/v2/assets?action=registerUpload"
            register_data = {
                "registerUploadRequest": {
                    "recipes": ["urn:li:digitalmediaRecipe:feedshare-image"],
                    "owner": person_urn,
                    "serviceRelationships": [{
                        "relationshipType": "OWNER",
                        "identifier": "urn:li:userGeneratedContent"
                    }]
                }
            }
            reg_res = requests.post(register_url, headers=headers, json=register_data)
            if reg_res.status_code != 200:
                return f"❌ Σφάλμα Register Image: {reg_res.text}"

            upload_url = reg_res.json()['value']['uploadMechanism']['com.linkedin.digitalmedia.uploading.MediaUploadHttpRequest']['uploadUrl']
            asset_urn = reg_res.json()['value']['asset']

            # Ανέβασμα Binary Αρχείου
            with open(image_path, 'rb') as f:
                binary_data = f.read()
            
            # Εδώ το header θέλει μόνο το Auth, όχι Content-Type JSON
            upload_headers = {"Authorization": f"Bearer {LINKEDIN_TOKEN}"}
            up_res = requests.post(upload_url, headers=upload_headers, data=binary_data)
            if up_res.status_code not in [200, 201]:
                return f"❌ Σφάλμα Binary Upload: {up_res.text}"
            print(f"[LinkedIn]: Image uploaded successfully.")

        # 3. Δημιουργία του Post
        post_url = "https://api.linkedin.com/v2/ugcPosts"
        media_content = {
            "shareCommentary": {"text": text},
            "shareMediaCategory": "IMAGE" if asset_urn else "NONE"
        }
        if asset_urn:
            media_content["media"] = [{
                "status": "READY",
                "media": asset_urn,
                "title": {"text": "Astakos DevLog Image"}
            }]

        payload = {
            "author": person_urn,
            "lifecycleState": "PUBLISHED",
            "specificContent": {"com.linkedin.ugc.ShareContent": media_content},
            "visibility": {"com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"}
        }

        res = requests.post(post_url, headers=headers, json=payload)
        return "✅ Το post ανέβηκε επιτυχώς!" if res.status_code == 201 else f"❌ Αποτυχία: {res.text}"

    except Exception as e:
        return f"❌ Κρίσιμο Σφάλμα: {str(e)}"

@tool
def control_spotify(
    action: str,
    query: str = ""
) -> str:
    """Ελέγχει το Spotify.
    action: 'play', 'pause', 'next', 'top_tracks', 'search'
    query: Τίτλος/Καλλιτέχνης για action='search'"""
    try:
        scope = "user-modify-playback-state user-read-playback-state user-top-read"
        sp = spotipy.Spotify(auth_manager=SpotifyOAuth(scope=scope))

        if action == "top_tracks":
            results = sp.current_user_top_tracks(limit=5, time_range='long_term')
            if not results['items']:
                return "Δεν βρέθηκαν δεδομένα για top tracks."
            tracks = [f"{i+1}. {t['name']} - {t['artists'][0]['name']}" for i, t in enumerate(results['items'])]
            return "🎵 Top 5 τραγούδια σου:\n" + "\n".join(tracks)

        elif action == "pause":
            sp.pause_playback()
            return "Η μουσική σταμάτησε."

        elif action == "next":
            sp.next_track()
            return "Πήγαμε στο επόμενο τραγούδι!"

        elif action == "search" and query:
            res = sp.search(q=query, type='track', limit=1)
            if not res['tracks']['items']:
                return f"Δεν βρήκα το '{query}'."
            track_uri = res['tracks']['items'][0]['uri']
            sp.start_playback(uris=[track_uri])
            return f"Έβαλα να παίζει: {res['tracks']['items'][0]['name']} 🎵"

        elif action == "play":
            sp.start_playback()
            return "Η μουσική ξεκίνησε ξανά!"

        return "Άγνωστη εντολή."
    except Exception as e:
        return f"Spotify Error: {str(e)}. (Μήπως δεν έχεις ανοιχτή την εφαρμογή;)"
all_tools = [
    search_memory, save_to_memory, delete_from_memory, retrieve_photo, update_pending_linkedin_post, process_and_clear_linkedin_post,
    set_local_reminder, set_reminder, manage_list,
    google_calendar_tool, google_tasks_tool, drive_manager,
    read_local_file, write_code, run_code, write_custom_tool,
    mail_manager, github_manager, control_vacuum, control_spotify, recipe_expert, 
    log_meal, create_file_tool,
    get_news, get_weather_forecast, search_supermarket_offers,
    search_goldmall_offers, send_messenger_message, archive_file, get_navigation_info, generate_image_tool, post_to_linkedin,
    DuckDuckGoSearchRun()
]