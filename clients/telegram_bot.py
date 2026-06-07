# ================================================================
# Project: Astakos AI Agent 🦞
# Developer: Lazaros (Piston-7)
# Description: Modular LLM-agnostic multi-agent framework
# Copyright (c) 2026 - All Rights Reserved
# ================================================================

"""
clients/telegram_bot.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Ο Telegram Bot του Αστακού.
Δέχεται μηνύματα/φωτογραφίες από τον Λάζαρο και
απαντάει μέσω του graph (LangGraph pipeline).
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

import os
import json
import time
import queue
import threading
import requests
from datetime import datetime
from zoneinfo import ZoneInfo
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from langchain_core.messages import HumanMessage, AIMessage

from config import TELEGRAM_TOKEN, TELEGRAM_CHAT_ID, PHOTOS_DIR, PHOTOS_INDEX_FILE, TELEGRAM_HISTORY_FILE

def _normalize_gr(text: str) -> str:
    """Αφαιρεί τόνους από ελληνικό κείμενο για accent-insensitive σύγκριση."""
    import unicodedata
    return unicodedata.normalize("NFD", text).encode("ascii", "ignore").decode("ascii").lower()

from memory.event_log import log_event, is_duplicate_notification, is_duplicate_routine
from core.exceptions import SchedulerCrashError, PendingTimeoutError, DBWriteError
from core.brain import llm
from core.graph import graph
from core.agents import clean_message, filter_messages
from memory.vector_store import memory
from memory.working_memory import update_working_memory, update_capabilities_from_exchange
from memory.session_memory import trigger_memory_sifter, log_exchange, _run_session_summary
from tools.telegram import send_telegram_msg, send_telegram_voice
from services.gemini import safe_gemini_call
from services.embeddings import embeddings
from core.event_bus import bus
# ────────────────────────────────────────────────────────────────
# GLOBALS
# ────────────────────────────────────────────────────────────────
shutdown_event        = threading.Event()
astakos_queue         = queue.Queue()
memory_lock           = threading.Lock()
last_interaction_time = time.time()
# Pending routine confirmations: {routine_id: {"event": ..., "sent_at": ...}}
pending_routine_confirmations = {}
pending_exec_command = None
# Pending photo: αποθηκεύει ανάλυση φωτογραφίας που έφτασε χωρίς caption, για να συνδυαστεί με το επόμενο μήνυμα
pending_photo_lock = threading.Lock()
pending_photo      = None   # {analysis, filename, path, timestamp}
# Voice mode toggle: όταν True, ΟΛΕΣ οι απαντήσεις είναι φωνητικές ακόμα και αν γράφεις
voice_mode_enabled = False
# Scheduler reference (set in __main__, used by /status command)
astakos_scheduler = None
# ── Rate Limiting ─────────────────────────────────────────────
QUIET_HOURS          = (23, 8)   # 23:00 → 08:00 χωρίς proactive
MAX_PROACTIVE_PER_HOUR = 3       # max proactive μηνύματα/ώρα
PROACTIVE_RECENT_ACTIVITY_GRACE_SECONDS = 15 * 60

_proactive_count = {"hour": -1, "count": 0}
_proactive_lock  = threading.Lock()

def is_quiet_hours() -> bool:
    """True αν είμαστε εντός quiet window (π.χ. 23:00–08:00)."""
    h = datetime.now().hour
    start, end = QUIET_HOURS
    return h >= start or h < end  # wraps midnight

def can_send_proactive() -> bool:
    """Rate-limit: max MAX_PROACTIVE_PER_HOUR proactive μηνύματα/ώρα."""
    with _proactive_lock:
        h = datetime.now().hour
        if _proactive_count["hour"] != h:
            _proactive_count["hour"]  = h
            _proactive_count["count"] = 0
        if _proactive_count["count"] >= MAX_PROACTIVE_PER_HOUR:
            return False
        _proactive_count["count"] += 1
        return True


def _seconds_since_user_activity() -> float:
    """Shared last-user-activity across web/Telegram, with local fallback."""
    try:
        from memory.conversation_history import seconds_since_last_user_activity
        elapsed = seconds_since_last_user_activity()
        if elapsed is not None:
            return elapsed
    except Exception as e:
        print(f"[Proactive]: Shared activity read failed, using local timer: {e}")

    with memory_lock:
        return time.time() - last_interaction_time


def should_skip_proactive_for_recent_activity(
    max_age_seconds: int = PROACTIVE_RECENT_ACTIVITY_GRACE_SECONDS,
) -> bool:
    elapsed = _seconds_since_user_activity()
    if elapsed < max_age_seconds:
        print(f"⏸️ [Proactive]: Recent user activity ({int(elapsed)}s ago) — παραλείπεται.")
        log_event("proactive", "skipped", reason="recent_activity", elapsed_s=int(elapsed))
        return True
    return False

def enqueue_task(func, *args):
    astakos_queue.put((func, args))


# ── Human Override State ──────────────────────────────────────
import time as _time

_OVERRIDE_FILE = os.path.join(os.path.dirname(__file__), "..", "scheduler_state.json")
_override_state = {"pause_reminders": False, "mute_proactive": False, "sleep_until": None}
_override_lock  = threading.Lock()

def _load_override_state():
    global _override_state
    try:
        if os.path.exists(_OVERRIDE_FILE):
            with open(_OVERRIDE_FILE, "r", encoding="utf-8") as f:
                _override_state.update(json.load(f))
    except Exception:
        pass

def _save_override_state():
    try:
        with open(_OVERRIDE_FILE, "w", encoding="utf-8") as f:
            json.dump(_override_state, f, ensure_ascii=False)
    except Exception:
        pass

def is_reminders_paused() -> bool:
    with _override_lock:
        if _override_state.get("sleep_until") and _time.time() < _override_state["sleep_until"]:
            return True
        return bool(_override_state.get("pause_reminders"))

def is_proactive_muted() -> bool:
    with _override_lock:
        if _override_state.get("sleep_until") and _time.time() < _override_state["sleep_until"]:
            return True
        return bool(_override_state.get("mute_proactive"))


# ────────────────────────────────────────────────────────────────
# QUEUE WORKER
# ────────────────────────────────────────────────────────────────

def queue_worker():
    print("\033[90m[TelegramBot]: Queue Worker Ξεκίνησε!\033[0m")
    while not shutdown_event.is_set():
        try:
            task_func, args = astakos_queue.get(timeout=2)
            try:
                task_func(*args)
            except Exception as e:
                print(f"\033[91m[Queue Task Error στο {task_func.__name__}]: {e}\033[0m")
            finally:
                astakos_queue.task_done()
        except queue.Empty:
            continue
# ────────────────────────────────────────────────────────────────
# DOCUMENT HANDLER (ΝΕΟ)
# ────────────────────────────────────────────────────────────────

def handle_document(doc_obj: dict, caption: str, chat_id: str):
    """Κατεβάζει έγγραφα (PDF, Excel κλπ) από το Telegram στον σωστό φάκελο."""
    try:
        from config import BASE_DIR
        file_id = doc_obj["file_id"]
        # Αν δεν έχει όνομα, του δίνουμε ένα τυχαίο
        file_name = doc_obj.get("file_name", f"doc_{int(time.time())}.pdf")

        # Τα έγγραφα πάνε στον telegram_uploads (όπως στο Web UI)
        target_dir = os.path.join(BASE_DIR, "telegram_uploads")
        os.makedirs(target_dir, exist_ok=True)
        local_path = os.path.join(target_dir, file_name)

        # Get file path από Telegram API
        file_resp = requests.get(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getFile",
            params={"file_id": file_id}, timeout=10
        ).json()
        file_path_remote = file_resp["result"]["file_path"]

        # Download
        file_url = f"https://api.telegram.org/file/bot{TELEGRAM_TOKEN}/{file_path_remote}"
        doc_data = requests.get(file_url, timeout=30).content

        with open(local_path, "wb") as f:
            f.write(doc_data)
        print(f"\033[94m[Document]: Αποθηκεύτηκε στο Telegram: {local_path}\033[0m")

        # Στέλνουμε μήνυμα στον χρήστη ότι το λάβαμε
        send_telegram_msg(f"📄 Έγγραφο ελήφθη: `{file_name}`\nΠερίμενε, το κοιτάζω...")

        # Συνθέτουμε το "αόρατο" μήνυμα για να το πιάσει το Graph (Tech_Agent)
        user_text = f"[USER_UPLOADED_FILE]: {file_name}\n[FILE PATH]: {local_path}"
        if caption:
            user_text += f"\nΟδηγία: {caption}"
        else:
            user_text += "\nΤι θέλεις να κάνω με αυτό; Να το διαβάσω ή να το αρχειοθετήσω;"

        # Το περνάμε στον κανονικό handler μηνυμάτων για να αναλάβει ο Αστακός
        handle_message(user_text, chat_id)

    except Exception as e:
        print(f"\033[91m[Document Error]: {e}\033[0m")
        send_telegram_msg(f"❌ Σφάλμα λήψης εγγράφου: {str(e)}")
# ────────────────────────────────────────────────────────────────
# VOICE HANDLER (CONSOLIDATED)
# ────────────────────────────────────────────────────────────────
def handle_voice(voice_obj: dict, chat_id: str):
    """Λαμβάνει ηχητικό, το κάνει κείμενο και απαντάει φωνητικά."""
    from config import TELEGRAM_TOKEN
    from services.gemini import safe_gemini_call
    from tools.telegram import send_telegram_msg

    local_path = None
    try:
        file_id = voice_obj["file_id"]
        local_path = os.path.join(os.getcwd(), "telegram_uploads", f"voice_{int(time.time())}.ogg")
        os.makedirs(os.path.dirname(local_path), exist_ok=True)

        file_resp = requests.get(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getFile",
            params={"file_id": file_id}, timeout=10
        ).json()
        
        file_path_remote = file_resp["result"]["file_path"]
        file_url = f"https://api.telegram.org/file/bot{TELEGRAM_TOKEN}/{file_path_remote}"
        audio_data = requests.get(file_url, timeout=30).content
        
        with open(local_path, "wb") as f:
            f.write(audio_data)

        print(f"\033[96m[Voice]: Ανάλυση ήχου...\033[0m")

        import base64 as _b64
        import vertexai
        from vertexai.generative_models import GenerativeModel, Part
        from core.brain import FAST_MODEL
        vertexai.init(project=os.getenv("PROJECT_ID", "astakos-finall"), location=os.getenv("LOCATION", "global"))
        stt_model = GenerativeModel(FAST_MODEL)
        prompt = "Είσαι ΑΠΟΚΛΕΙΣΤΙΚΑ εργαλείο Speech-to-Text. Μετέγραψε ΜΟΝΟ αυτό που ακούς, λέξη προς λέξη, χωρίς σχόλια ή απαντήσεις. Αν δεν ακούς τίποτα, γράψε: [ΣΙΩΠΗ]."
        audio_part = Part.from_data(data=audio_data, mime_type="audio/ogg")
        stt_response = stt_model.generate_content([prompt, audio_part])
        ai_reply = stt_response.text.strip() if stt_response and stt_response.text else "Δεν έβγαλα άκρη."

        print(f"\033[92m[Voice AI]: {ai_reply}\033[0m")
        # Στέλνουμε το flag [ΦΩΝΗΤΙΚΟ] + [VOICE_INPUT] για να ξέρει η handle_message να απαντήσει με ήχο
        # και ο Αστακός ότι το μήνυμα ήρθε από φωνή (να απαντά πιο σύντομα και καθομιλούμενα)
        handle_message(f"[ΦΩΝΗΤΙΚΟ]: [VOICE_INPUT] {ai_reply}", chat_id)

    except Exception as e:
        print(f"\033[91m[Voice Error]: {e}\033[0m")
        # [FIX]: ΕΔΩ ΗΤΑΝ ΤΟ ΛΑΘΟΣ - Μόνο ένα όρισμα
        send_telegram_msg("🚨 Μάστορα, σκάλωσε το voice processing.") 
    finally:
        if local_path and os.path.exists(local_path):
            os.remove(local_path)
def send_telegram_document(file_path, chat_id=None):
    if not chat_id: chat_id = TELEGRAM_CHAT_ID
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendDocument"
        with open(file_path, 'rb') as f:
            requests.post(url, data={'chat_id': chat_id}, files={'document': f})
        print(f"\033[92m[Telegram]: Το αρχείο {os.path.basename(file_path)} στάλθηκε!\033[0m")
    except Exception as e:
        print(f"❌ Telegram File Error: {e}")         
def handle_end_session(chat_id: str):
    """Κλείνει τη συνεδρία, σώζει το summary και καθαρίζει το working memory."""
    try:
        from memory.session_memory import _run_session_summary
        from config import WORKING_MEMORY_FILE
        
        send_telegram_msg("⌛ **Αρχειοθέτηση...** Μαζεύω τις μνήμες της ημέρας και καθαρίζω τον πάγκο.")
        
        # 1. Τρέχουμε το κεντρικό summary (όπως στο server.py)
        _run_session_summary(channel="telegram")
        
        # 2. Καθαρίζουμε το Post-it (Working Memory)
        with open(WORKING_MEMORY_FILE, "w", encoding="utf-8") as f:
            f.write("ΚΕΝΟ")
            
        print("\033[92m[Telegram]: Η συνεδρία έκλεισε και αρχειοθετήθηκε επιτυχώς.\033[0m")
        send_telegram_msg("✅ **Έγινε!** Η συνεδρία αρχειοθετήθηκε. Τα λέμε στην επόμενη βάρδια, Μάστορα! 🦞")

    except Exception as e:
        print(f"\033[91m[End Session Error]: {e}\033[0m")
        send_telegram_msg(f"❌ Κάτι στράβωσε στο κλείσιμο: {str(e)}")       
# ────────────────────────────────────────────────────────────────
# PHOTO HANDLER
# ────────────────────────────────────────────────────────────────

def handle_photo(photo_list: list, caption: str, chat_id: str):
    """
    [MASTRO-PARITY]: Αναλύει φωτογραφία μέσω Vision LLM.
    - Με caption: επεξεργάζεται αμέσως με το caption ως ερώτηση.
    - Χωρίς caption: αποθηκεύει ανάλυση ως pending και περιμένει το επόμενο μήνυμα (30s).
    """
    global pending_photo
    try:
        import base64
        from langchain_core.messages import HumanMessage, AIMessage
        from core.brain import llm
        from core.agents import clean_message

        # 1. Λήψη αρχείου από Telegram
        best_photo = max(photo_list, key=lambda p: p.get("file_size", 0))
        file_id = best_photo["file_id"]
        file_resp = requests.get(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getFile", params={"file_id": file_id}).json()
        file_path_remote = file_resp["result"]["file_path"]
        img_data = requests.get(f"https://api.telegram.org/file/bot{TELEGRAM_TOKEN}/{file_path_remote}").content

        # 2. Αποθήκευση τοπικά
        timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename  = f"photo_{timestamp_str}.jpg"
        local_path = os.path.join(PHOTOS_DIR, filename)
        with open(local_path, "wb") as f:
            f.write(img_data)
        print(f"\033[92m[Photo]: Κατέβηκε: {filename}\033[0m")

        # 3. Vision LLM — αντικειμενική ανάλυση pixels
        img_b64 = base64.b64encode(img_data).decode("utf-8")
        vision_prompt = "Περίγραψε αναλυτικά τι δείχνει η φωτογραφία (αντικείμενα, κείμενο, χρώματα, πλαίσιο). Απάντησε στα Ελληνικά, 3-5 προτάσεις."
        vision_msg = HumanMessage(content=[
            {"type": "text",      "text": vision_prompt},
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"}}
        ])
        print(f"\033[94m[Vision]: Οπτική ανάλυση...\033[0m")
        analysis_raw  = llm.invoke([vision_msg])
        memory_analysis = clean_message(analysis_raw.content)
        print(f"\033[94m[Vision]: {memory_analysis[:120]}...\033[0m")

        # 4α. ΜΕ caption → έλεγχος για /nutrition, /receipt ή κανονική ερώτηση
        if caption:
            caption_cmd = caption.strip().lower()
            if caption_cmd == "/nutrition":
                send_telegram_msg("🔍 Αναλύω τη διατροφική αξία...")
                threading.Thread(target=_run_nutrition, args=(local_path, chat_id), daemon=True).start()
            elif caption_cmd == "/receipt":
                send_telegram_msg("🧾 Σκανάρω την απόδειξη...")
                threading.Thread(target=_run_receipt, args=(local_path, chat_id), daemon=True).start()
            else:
                _process_photo_with_question(filename, local_path, memory_analysis, caption, chat_id)

        # 4β. ΧΩΡΙΣ caption → αποθηκεύουμε pending, ειδοποιούμε
        else:
            with pending_photo_lock:
                pending_photo = {
                    "analysis":  memory_analysis,
                    "filename":  filename,
                    "path":      local_path,
                    "timestamp": time.time()
                }
            send_telegram_msg("📷 Φωτό ελήφθη! Τι θέλεις να κάνω με αυτή;")

    except Exception as e:
        import traceback
        traceback.print_exc()
        send_telegram_msg(f"Μάστορα, σκάλωσε η φωτό. Σφάλμα: {e}")


def _process_photo_with_question(filename: str, local_path: str, analysis: str, question: str, chat_id: str):
    """Περνάει φωτογραφία + ερώτηση στο graph και στέλνει ΜΙΑ απάντηση (σωστό streaming pattern)."""
    import re
    from langchain_core.messages import HumanMessage, AIMessage
    from core.agents import clean_message

    # Φόρτωση history (shared mixed πρώτα, legacy Telegram ως fallback)
    context_msgs = _load_shared_context_messages("telegram")
    if not context_msgs:
        try:
            if os.path.exists(TELEGRAM_HISTORY_FILE):
                with open(TELEGRAM_HISTORY_FILE, "r", encoding="utf-8") as f:
                    raw_hist = json.load(f)
                for entry in raw_hist[-21:-1]:
                    ts     = entry.get("time", "")
                    prefix = f"[{ts}] " if ts else ""
                    if entry["role"] == "human":
                        context_msgs.append(HumanMessage(content=f"{prefix}{entry['content']}"))
                    else:
                        context_msgs.append(AIMessage(content=f"{prefix}{entry['content']}"))
        except Exception:
            pass

    now_ts = datetime.now().strftime("%H:%M")
    user_log_msg = (
        f"[{now_ts}] "
        f"[USER_UPLOADED_PHOTO]: {filename}\n"
        f"[PHOTO PATH]: {local_path}\n"
        f"[ΟΠΤΙΚΗ ΑΝΑΛΥΣΗ]: {analysis}\n"
        f"Ερώτηση: {question}"
    )
    print(f"\033[94m[Photo->Graph]: {user_log_msg[:200]}\033[0m")

    # Streaming — collect, send once (ίδιο pattern με handle_message)
    final_response = ""
    try:
        for event in graph.stream({"messages": context_msgs + [HumanMessage(content=user_log_msg)]}, {"recursion_limit": 50}):
            for node, data in event.items():
                if node not in ["supervisor", "tools"]:
                    msgs = data.get("messages", [])
                    if msgs and hasattr(msgs[-1], "content"):
                        candidate = clean_message(msgs[-1].content).strip()
                        if candidate:
                            final_response = candidate
    except Exception as e:
        send_telegram_msg(f"❌ Σφάλμα επεξεργασίας φωτό: {e}")
        return

    if not final_response:
        send_telegram_msg("⚠️ Δεν πήρα σαφή απάντηση για τη φωτογραφία.")
        return

    # Interceptor για CREATED_FILE
    file_match = re.search(r"\[CREATED_FILE:\s*(.*?)\]", final_response)
    if file_match:
        file_path = file_match.group(1).strip()
        final_response = re.sub(r"\[CREATED_FILE:\s*(.*?)\]", "", final_response).strip()
        if final_response:
            send_telegram_msg(final_response)
        try:
            from tools.telegram import send_telegram_document
            send_telegram_document(file_path)
        except Exception:
            pass
    else:
        send_telegram_msg(final_response)
def _run_nutrition(image_path: str, chat_id: str):
    """Τρέχει τον nutrition analyzer και στέλνει αποτέλεσμα."""
    try:
        from astakos_skills.nutrition_analyzer import analyze_nutrition
        result = analyze_nutrition(image_path)
        send_telegram_msg(result)
    except Exception as e:
        send_telegram_msg(f"❌ Σφάλμα nutrition analysis: {e}")


def _run_receipt(image_path: str, chat_id: str):
    """Τρέχει το receipt scanner και στέλνει αποτέλεσμα."""
    try:
        from astakos_skills.scan_receipt import scan_receipt
        result = scan_receipt.invoke({"image_path": image_path})
        send_telegram_msg(result)
    except Exception as e:
        send_telegram_msg(f"❌ Σφάλμα receipt scan: {e}")


def _run_story_maker(theme: str, characters: str, chat_id: str):
    """Δημιουργεί παραμύθι + εικόνες και τα στέλνει στο Telegram."""
    try:
        from astakos_skills.story_maker import make_story
        from tools.telegram import send_telegram_photo
        result = make_story(theme, characters)

        if result.get("error") or not result.get("story"):
            send_telegram_msg(f"❌ {result.get('error', 'Αποτυχία δημιουργίας παραμυθιού')}")
            return

        # Στέλνουμε πρώτα το κείμενο (σε κομμάτια αν είναι μεγάλο)
        story_text = f"📖 *Παραμύθι: {theme}*\n\n{result['story']}"
        # Telegram limit: 4096 chars
        max_len = 4000
        chunks = [story_text[i:i+max_len] for i in range(0, len(story_text), max_len)]
        for chunk in chunks:
            send_telegram_msg(chunk)
            time.sleep(0.5)

        # Στέλνουμε τις εικόνες
        images = result.get("images", [])
        if images:
            send_telegram_msg(f"🎨 *{len(images)} εικόνες από το παραμύθι:*")
            for img_path in images:
                if os.path.exists(img_path):
                    try:
                        import asyncio
                        asyncio.run(send_telegram_photo(img_path))
                        time.sleep(1)
                    except Exception as img_e:
                        print(f"⚠️ [StoryMaker] Αποτυχία αποστολής εικόνας: {img_e}")
        else:
            send_telegram_msg("⚠️ Οι εικόνες δεν δημιουργήθηκαν (Pollinations timeout).")

        print(f"✅ [StoryMaker] Παραμύθι '{theme}' ολοκληρώθηκε.")

        # Ενημερώνουμε τον agent με ΣΥΝΤΟΜΟ note — ώστε να ξέρει ότι έγραψε παραμύθι
        # και να μη καλέσει search_memory αν ρωτήσει ο Λάζαρος για αυτό
        char_note = f" με χαρακτήρες: {characters}" if characters else ""
        img_note = f"{len(images)} εικόνες στάλθηκαν" if images else "εικόνες δεν δημιουργήθηκαν"
        agent_note = (
            f"[SYSTEM]: Μόλις έγραψα και έστειλα παραμύθι με θέμα '{theme}'{char_note}. "
            f"{img_note}. Ο Λάζαρος το έχει ήδη στο Telegram."
        )
        threading.Thread(
            target=handle_message,
            args=(agent_note, chat_id),
            daemon=True
        ).start()
    except Exception as e:
        send_telegram_msg(f"❌ Σφάλμα story maker: {e}")
        print(f"❌ [StoryMaker] {e}")


def send_voice_reply(text, chat_id):
    """Μετατρέπει το κείμενο σε ομιλία και το στέλνει ως voice message."""
    try:
        from tools.telegram import send_telegram_voice # Σιγουρέψου ότι υπάρχει στο tools/telegram.py
        
        voice_path = os.path.join(os.getcwd(), "telegram_uploads", f"reply_{int(time.time())}.mp3")
        os.makedirs(os.path.dirname(voice_path), exist_ok=True)

        # Δημιουργία του ήχου (στα ελληνικά)
        tts = gTTS(text=text, lang='el')
        tts.save(voice_path)

        # Αποστολή του αρχείου
        send_telegram_voice(voice_path, chat_id)

        # Καθάρισμα
        if os.path.exists(voice_path):
            os.remove(voice_path)
            
    except Exception as e:
        print(f"❌ TTS Error: {e}")
        send_telegram_msg(f"Μάστορα, μου κόπηκε η φωνή... (Error: {e})", chat_id)
def _append_to_analytics_log(role: str, content: str):
    """Append-only log για analytics engine — με date/time."""
    try:
        now = datetime.now()
        entry = {
            "role": role,
            "content": content,
            "date": now.strftime("%Y-%m-%d"),
            "time": now.strftime("%H:%M")
        }
        history = []
        if os.path.exists(TELEGRAM_HISTORY_FILE):
            with open(TELEGRAM_HISTORY_FILE, "r", encoding="utf-8") as f:
                history = json.load(f)
        history.append(entry)
        with open(TELEGRAM_HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(history, f, ensure_ascii=False, indent=2)
        try:
            shared_role = "assistant" if role in ("ai", "assistant") else role
            # notify_telegram_message: αποθηκεύει στη shared SQLite + WebSocket broadcast στο Web UI
            try:
                from api.server import notify_telegram_message
                notify_telegram_message(role=shared_role, content=content)
            except Exception:
                # Fallback: άμεσο append χωρίς broadcast (αν ο server δεν τρέχει)
                from memory.conversation_history import append_message
                append_message(
                    role=shared_role,
                    content=content,
                    channel="telegram",
                    timestamp=now,
                )
        except Exception as shared_error:
            print(f"[ConversationHistory/telegram]: Σφάλμα shared write: {shared_error}")
    except Exception as e:
        print(f"[TelegramAnalytics]: Σφάλμα: {e}")


def _load_shared_context_messages(channel: str) -> list:
    """Φορτώνει μικτό shared context. Αν αποτύχει, ο caller κάνει fallback στο legacy history."""
    try:
        from memory.conversation_history import load_recent_context
        entries = load_recent_context(channel=channel, global_limit=12, channel_limit=10, total_limit=20)
    except Exception as e:
        print(f"[ConversationHistory/{channel}]: Σφάλμα shared read: {e}")
        return []

    context_msgs = []
    for entry in entries:
        content = entry.get("content", "")
        if not content:
            continue
        prefix = f"[{entry.get('date', '')} {entry.get('time', '')} / {entry.get('channel', '')}] "
        if entry.get("role") in ("user", "human", "Human"):
            context_msgs.append(HumanMessage(content=f"{prefix}{content}"))
        else:
            context_msgs.append(AIMessage(content=f"{prefix}{content}"))
    return context_msgs


# ────────────────────────────────────────────────────────────────
# MESSAGE HANDLER
# ────────────────────────────────────────────────────────────────

def handle_message(user_text: str, chat_id: str):
    """Στέλνει το μήνυμα στον Αστακό και απαντάει (Κείμενο ή Ήχο)."""
    global last_interaction_time
    from tools.telegram import send_telegram_voice, send_telegram_msg
    import re

    # 1. Ελέγχουμε αν ζητήθηκε φωνή (από ηχητικό, /voice εντολή, ή global toggle)
    is_voice_mode = "[ΦΩΝΗΤΙΚΟ]" in user_text or "[VOICE_MESSAGE]" in user_text or voice_mode_enabled
    is_voice_input = "[VOICE_INPUT]" in user_text  # το μήνυμα ήρθε από φωνή

    # 2. Καθαρίζουμε τα tags πριν πάνε στον εγκέφαλο
    clean_user_text = user_text.replace("/voice", "").replace("[ΦΩΝΗΤΙΚΟ]:", "").replace("[VOICE_MESSAGE]:", "").strip()
    # /plan διατηρείται ώστε ο graph router να το αναγνωρίσει
    # Αν είναι voice input, κρατάμε το hint για τον Αστακό αλλά αφαιρούμε το tag
    if is_voice_input:
        clean_user_text = clean_user_text.replace("[VOICE_INPUT]", "").strip()
        clean_user_text = f"[Φωνητικό μήνυμα — απάντησε σύντομα και καθομιλούμενα]: {clean_user_text}"
    if not clean_user_text: 
        clean_user_text = "Γεια σου Αστακέ"
    # ── ROUTINE FEEDBACK LOOP ──
    if pending_routine_confirmations:
        text_check = _normalize_gr(clean_user_text)
        text_words = text_check.replace(",", "").replace(".", "").replace("!", "").split()

        yes_words = [_normalize_gr(w) for w in ["ναι", "yes", "οκ", "ok", "ισχύει", "σωστά", "σωστα"]]
        no_words  = [_normalize_gr(w) for w in ["όχι", "οχι", "no", "σταμάτα", "σταματα", "διέγραψε", "βγάλτο", "βγαλτο"]]
        question_words = [_normalize_gr(w) for w in [
            "δείξε", "δειξε", "πες", "γιατί", "γιατι", "τι", "πως", "πώς",
            "έλεγξε", "ελεγξε", "δες", "δωσε", "δώσε", "show", "check", "why"
        ]]

        action_words = [_normalize_gr(w) for w in [
            "πάμε", "πηγαίνουμε", "φεύγουμε", "ξεκινάμε", "πάω", "θα πάμε",
            "θα πάω", "πήγαμε", "ήρθαμε", "φτάσαμε", "είμαστε", "ξεκίνησα",
            "ξεκίνησε", "αρχίζω", "έγινε", "έτοιμος", "τελειώσαμε", "went",
            "going", "done", "finished", "started"
        ]]
        is_question_like = any(w in text_words for w in question_words) or "?" in clean_user_text
        explicit_yes = (
            not is_question_like
            and len(text_words) <= 4
            and any(w in text_words for w in yes_words)
        )
        implicit_confirmed = False
        if not is_question_like and any(w in text_check for w in action_words):
            for rid, rdata in pending_routine_confirmations.items():
                event_name = rdata.get("event", "") if isinstance(rdata, dict) else str(rdata)
                event_words = [_normalize_gr(w) for w in event_name.split() if len(w) > 3]
                if any(ew in text_check for ew in event_words):
                    implicit_confirmed = True
                    print(f"🔍 [Routine Implicit Confirm]: '{text_check[:40]}' → '{event_name}'")
                    break

        if explicit_yes or implicit_confirmed:
            from memory.routine_db import confirm_routine, mark_routine_responded, clear_pending_confirmations
            for rid in list(pending_routine_confirmations.keys()):
                confirm_routine(rid)
                mark_routine_responded(rid)
                from memory.event_log import log_event
                log_event("routines", "confirmed", routine_id=rid, event=pending_routine_confirmations[rid])
                print(f"✅ [Routine Confirmed]: {pending_routine_confirmations[rid]}")
                bus.emit("routine_confirmed", routine_id=rid, event=pending_routine_confirmations[rid], channel="telegram")
            pending_routine_confirmations.clear()
            clear_pending_confirmations()
        elif any(w in text_check for w in no_words):
            from memory.routine_db import decay_routine, clear_pending_confirmations
            for rid in list(pending_routine_confirmations.keys()):
                decay_routine(rid)
                from memory.event_log import log_event
                log_event("routines", "dismissed", routine_id=rid, event=pending_routine_confirmations[rid])
                print(f"📉 [Routine Dismissed]: {pending_routine_confirmations[rid]}")
                bus.emit("routine_dismissed", routine_id=rid, event=pending_routine_confirmations[rid], channel="telegram")
            pending_routine_confirmations.clear()
            clear_pending_confirmations()
    # ── SAFE EXECUTOR CONFIRMATION LOOP ──────────────────────────
    global pending_exec_command
    if pending_exec_command:
        text_check = _normalize_gr(clean_user_text)
        if any(w in text_check for w in [_normalize_gr(w) for w in ["ναι", "yes", "ok", "οκ"]]):
            cmd = pending_exec_command
            pending_exec_command = None
            from memory.event_log import log_event
            log_event("safe_executor", "confirmed_and_executed", cmd=cmd[:80])
            try:
                import subprocess
                result = subprocess.run(
                    ["powershell", "-Command", cmd],
                    capture_output=True, text=True, timeout=30,
                    encoding='utf-8', errors='ignore'
                )
                output = result.stdout if result.returncode == 0 else f"ERROR:\n{result.stderr}"
                send_telegram_msg(
                    f"✅ Εκτελέστηκε:\n💻 {output[:2000]}" if output.strip()
                    else "✅ Εκτελέστηκε (χωρίς output)."
                )
            except Exception as e:
                send_telegram_msg(f"❌ Σφάλμα εκτέλεσης: {e}")
            return
        elif any(w in text_check for w in [_normalize_gr(w) for w in ["όχι", "οχι", "no", "cancel"]]):
            pending_exec_command = None
            send_telegram_msg("❌ Ακυρώθηκε.")
            return

    with memory_lock:
        last_interaction_time = time.time()

    # ── Pending photo: αν ήρθε φωτό χωρίς caption πρόσφατα, συνδύασέ το ──
    global pending_photo
    photo_prefix = ""
    with pending_photo_lock:
        if pending_photo and (time.time() - pending_photo["timestamp"]) < 30:
            p = pending_photo
            pending_photo = None
            print(f"\033[94m[Photo+Msg]: Συνδυασμός pending φωτό + μήνυμα\033[0m")
            _process_photo_with_question(p["filename"], p["path"], p["analysis"], clean_user_text, chat_id)
            return  # Η _process_photo_with_question έστειλε την απάντηση

    final_ai_response = ""
    handling_agent = "Chat_Agent"

    # ── Typing indicator — δείχνει "ο Αστακός πληκτρολογεί..." ──
    _typing_active = {"on": True}
    def _typing_loop():
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendChatAction"
        while _typing_active["on"]:
            try:
                requests.post(url, json={"chat_id": chat_id, "action": "typing"}, timeout=5)
            except Exception:
                pass
            time.sleep(4)  # Telegram δείχνει typing για 5s — ανανεώνουμε κάθε 4s
    typing_thread = threading.Thread(target=_typing_loop, daemon=True)
    typing_thread.start()

    try:
        # ── Context: shared mixed history πρώτα, legacy Telegram history ως fallback ────────────
        now_ts = datetime.now().strftime("%H:%M")
        context_msgs = _load_shared_context_messages("telegram")
        if not context_msgs:
            try:
                if os.path.exists(TELEGRAM_HISTORY_FILE):
                    with open(TELEGRAM_HISTORY_FILE, "r", encoding="utf-8") as f:
                        raw_hist = json.load(f)
                    for entry in raw_hist[-21:-1]:
                        ts = entry.get("time", "")
                        prefix = f"[{ts}] " if ts else ""
                        if entry["role"] == "human":
                            context_msgs.append(HumanMessage(content=f"{prefix}{entry['content']}"))
                        else:
                            context_msgs.append(AIMessage(content=f"{prefix}{entry['content']}"))
            except:
                pass
        current_msg  = HumanMessage(content=f"[{now_ts}] {clean_user_text}")
        # ── Ροή μέσω LangGraph ───────────────────────────────────
        import tools.system as _ts; _ts._CURRENT_CHANNEL = "telegram"
        for event in graph.stream({"messages": context_msgs + [current_msg], "channel": "telegram"}, {"recursion_limit": 50}):
            for node, data in event.items():
                if node not in ["supervisor", "tools"]:
                    handling_agent = node
                    msgs = data.get("messages", [])
                    if msgs and hasattr(msgs[-1], "content"):
                        candidate = clean_message(msgs[-1].content).strip()
                        if candidate:
                            final_ai_response = candidate

        if not final_ai_response:
            # [MASTRO-FIX]: Fallback όταν ο agent δεν παρήγαγε κείμενο (π.χ. loop/recursion)
            send_telegram_msg("⚠️ Κάτι μπλόκαρε — δεν πήρα σαφή απάντηση. Ξαναστείλε μου.")
            return

        if final_ai_response:
            # --- MASTRO INTERCEPTOR ΓΙΑ ΕΓΓΡΑΦΑ ---
            file_match = re.search(r"\[CREATED_FILE:\s*(.*?)\]", final_ai_response)
            if file_match:
                file_path = file_match.group(1).strip()
                final_ai_response = re.sub(r"\[CREATED_FILE:\s*(.*?)\]", "", final_ai_response).strip()
                
                if final_ai_response:
                    if is_voice_mode:
                        import asyncio
                        asyncio.run(send_telegram_voice(final_ai_response))
                    else:
                        send_telegram_msg(final_ai_response) # [FIX]: Μόνο ένα όρισμα!
                
                try:
                    from tools.telegram import send_telegram_document
                    send_telegram_document(file_path) # [FIX]: Μόνο ένα όρισμα
                except:
                    pass
            else:
                # Κανονική Ροή (Χωρίς Έγγραφα)
                if is_voice_mode:
                    import asyncio
                    asyncio.run(send_telegram_voice(final_ai_response))
                else:
                    send_telegram_msg(final_ai_response) # [FIX]: Μόνο ένα όρισμα!
            # Κρατάμε context για επόμενο μήνυμα
            _typing_active["on"] = False  # Σταματάμε το typing
            _append_to_analytics_log("user", clean_user_text)
            _append_to_analytics_log("ai", final_ai_response)
            # Φωτογραφίες
            if "[SEND_PHOTO:" in final_ai_response:
                match = re.search(r"\[SEND_PHOTO:\s*(.+?)\]", final_ai_response)
                if match:
                    photo_path = match.group(1).strip()
                    try:
                        _send_photo_to_telegram(photo_path, chat_id)
                    except:
                        pass

            # Background Tasks
            enqueue_task(update_working_memory,             user_text, final_ai_response)
            enqueue_task(trigger_memory_sifter,             user_text, final_ai_response, handling_agent, "telegram")
            enqueue_task(log_exchange,                       user_text, final_ai_response, handling_agent, "telegram")
            enqueue_task(update_capabilities_from_exchange, user_text, final_ai_response, handling_agent)

    except Exception as e:
        _typing_active["on"] = False  # Σταματάμε το typing και σε error
        import traceback
        traceback.print_exc()
        send_telegram_msg(f"❌ Σφάλμα: {str(e)}")

def _send_photo_to_telegram(photo_path: str, chat_id: str):
    """Στέλνει αρχείο φωτογραφίας στο Telegram chat."""
    if not os.path.exists(photo_path):
        send_telegram_msg(f"⚠️ Η φωτογραφία δεν βρέθηκε στο δίσκο: `{photo_path}`")
        return
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendPhoto"
        with open(photo_path, "rb") as photo_file:
            requests.post(
                url,
                data={"chat_id": chat_id},
                files={"photo": photo_file},
                timeout=30
            )
        print(f"\033[92m[TelegramBot]: Φωτογραφία στάλθηκε: {photo_path}\033[0m")
    except Exception as e:
        print(f"\033[91m[TelegramBot Photo Send Error]: {e}\033[0m")
        send_telegram_msg(f"❌ Αδύνατη η αποστολή φωτογραφίας: {str(e)}")
def handle_location(msg, live_update=False):
    """Λαμβάνει live location και ελέγχει για location-based reminders."""
    import math

    chat_id = str(msg.get("chat", {}).get("id", ""))
    loc     = msg.get("location", {})
    lat     = loc.get("latitude")
    lon     = loc.get("longitude")
    if not lat or not lon:
        return
    # Αποθήκευση location στο JSON
    try:
        from config import GPS_STORAGE_FILE
        import time
        with open(GPS_STORAGE_FILE, "w", encoding="utf-8") as f:
            json.dump({"lat": lat, "lon": lon, "timestamp": time.time()}, f)
    except Exception:
        pass
    #print(f"\033[94m[Location]: {lat}, {lon}\033[0m")

    # ── Location Reminders ──────────────────────────────────────
    try:
        from config import HOME_COORDS, HOME_RADIUS_M, REMINDERS_FILE

        def haversine(lat1, lon1, lat2, lon2):
            R = 6371000
            p = math.pi / 180
            a = (math.sin((lat2-lat1)*p/2)**2 +
                 math.cos(lat1*p) * math.cos(lat2*p) *
                 math.sin((lon2-lon1)*p/2)**2)
            return 2 * R * math.asin(math.sqrt(a))

        if os.path.exists(REMINDERS_FILE):
            with open(REMINDERS_FILE, "r", encoding="utf-8") as f:
                rems = json.load(f)

            changed = False
            for r in rems:
                if r.get("status") != "pending" or r.get("type") != "location":
                    continue
                target = r.get("location", "home")
                if target == "home":
                    dist = haversine(lat, lon, HOME_COORDS[0], HOME_COORDS[1])
                    if dist <= HOME_RADIUS_M:
                        send_telegram_msg(f"📍 ΥΠΕΝΘΥΜΙΣΗ (Έφτασες σπίτι!): {r['task']}")
                        print(f"\033[93m[Location Reminder]: {r['task']} fired ({dist:.0f}m)\033[0m")
                        r["status"] = "done"
                        changed = True

            if changed:
                with open(REMINDERS_FILE, "w", encoding="utf-8") as f:
                    json.dump(rems, f, ensure_ascii=False, indent=4)
    except Exception as e:
        print(f"\033[91m[Location Reminder Error]: {e}\033[0m")

    # ── Web Agent μόνο για manual location (όχι live updates) ──
    if live_update:
        return  # Live location update → μόνο reminders, όχι μήνυμα

    from core.graph import graph
    from langchain_core.messages import HumanMessage
    location_prompt = (
        f"[GPS_UPDATE] Ο Λάζαρος μοιράστηκε τοποθεσία: lat={lat}, lon={lon}. "
        "Χρησιμοποίησε το web tool για reverse geocoding και απάντησε σύντομα στα Ελληνικά "
        "πού βρίσκεται, με Google Maps link και οδηγίες από Piston 7."
    )
    try:
        final = ""
        for event in graph.stream({"messages": [HumanMessage(content=location_prompt)]}):
            for node, data in event.items():
                msgs = data.get("messages", [])
                if msgs and hasattr(msgs[-1], "content"):
                    content = msgs[-1].content
                    if isinstance(content, list):
                        content = " ".join(p.get("text","") for p in content if isinstance(p, dict))
                    if content.strip():
                        final = content.strip()
        if final:
            from core.agents import clean_message
            send_telegram_msg(clean_message(final))
    except Exception as e:
        print(f"\033[91m[Location Handler Error]: {e}\033[0m")
        send_telegram_msg(f"📍 Τοποθεσία: {lat}, {lon}")

# ────────────────────────────────────────────────────────────────
# POLLING LOOP
# ────────────────────────────────────────────────────────────────

def _handle_approval_callback(cq: dict):
    """Χειρίζεται τα ✅/❌ approval callbacks από inline keyboard."""
    try:
        from core.approval import execute_approved_pending, get_pending, pop_pending
        from tools.system import all_tools

        cq_id   = cq["id"]
        data    = cq.get("data", "")
        chat_id = str(cq["message"]["chat"]["id"])
        msg_id  = cq["message"]["message_id"]

        # Answer the callback (αφαίρεση loading spinner)
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/answerCallbackQuery",
            json={"callback_query_id": cq_id},
            timeout=5,
        )

        if ":" not in data:
            return

        action, tool_call_id = data.split(":", 1)

        if action == "approve":
            item = get_pending(tool_call_id)  # get πρωτα, OXI pop
            if not item:
                # Duplicate/stale callback after a reload or an already executed action.
                # Keep the chat quiet and just remove the old inline keyboard if possible.
                requests.post(
                    f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/editMessageReplyMarkup",
                    json={"chat_id": chat_id, "message_id": msg_id, "reply_markup": {"inline_keyboard": []}},
                    timeout=5,
                )
                print(f"\033[93m[ApprovalCallback]: stale approve callback ignored ({tool_call_id})\033[0m")
                return

            tool_name = item["tool_name"]

            # Ενημέρωση keyboard → "✅ Εγκρίθηκε"
            requests.post(
                f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/editMessageReplyMarkup",
                json={"chat_id": chat_id, "message_id": msg_id, "reply_markup": {"inline_keyboard": []}},
                timeout=5,
            )

            send_telegram_msg(f"⚙️ Εκτελώ `{tool_name}`...")

            execution = execute_approved_pending(tool_call_id, all_tools)
            if execution["ok"]:
                send_telegram_msg("✅ `" + tool_name + "` ολοκληρώθηκε:\n\n" + str(execution["result"])[:800])
            elif execution["status"] == "tool_not_found":
                send_telegram_msg(f"❌ Tool `{tool_name}` δεν βρέθηκε.")
            else:
                send_telegram_msg(f"❌ `{tool_name}` απέτυχε: {execution['error']}")

        elif action == "reject":
            pop_pending(tool_call_id)
            requests.post(
                f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/editMessageReplyMarkup",
                json={"chat_id": chat_id, "message_id": msg_id, "reply_markup": {"inline_keyboard": []}},
                timeout=5,
            )
            send_telegram_msg("❌ Action ακυρώθηκε.")

    except Exception as e:
        print(f"\033[91m[ApprovalCallback]: {e}\033[0m")


def run_polling():
    """Long-polling loop — διαβάζει updates από το Telegram API."""
    global voice_mode_enabled
    if not TELEGRAM_TOKEN:
        print("\033[91m[TelegramBot]: Λείπει το TELEGRAM_TOKEN!\033[0m")
        return

    if not TELEGRAM_CHAT_ID:
        print("\033[91m[TelegramBot]: Λείπει το TELEGRAM_CHAT_ID!\033[0m")
        return

    offset = 0
    print(f"\033[92m[TelegramBot]: Polling ξεκίνησε (allowed chat: {TELEGRAM_CHAT_ID})\033[0m")

    while not shutdown_event.is_set():
        try:
            resp = requests.get(
                f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates",
                params={"offset": offset, "timeout": 30},
                timeout=35
            )

            if resp.status_code != 200:
                print(f"\033[91m[TelegramBot]: API Error {resp.status_code}\033[0m")
                time.sleep(5)
                continue

            updates = resp.json().get("result", [])

            for update in updates:
                offset = update["update_id"] + 1

                # ── Approval callbacks (inline keyboard ✅/❌) ──────────
                cq = update.get("callback_query")
                if cq:
                    _handle_approval_callback(cq)
                    continue

                # [MASTRO-FIX]: Πιάνουμε και τα Live Locations που έρχονται ως edited_message
                msg = update.get("message") or update.get("edited_message")
                if not msg:
                    continue
                
                chat_id = str(msg["chat"]["id"])

                # Security: μόνο ο Λάζαρος
                if chat_id != str(TELEGRAM_CHAT_ID):
                    print(f"\033[93m[TelegramBot]: Μη εξουσιοδοτημένο chat: {chat_id}\033[0m")
                    continue

                # 1. Τοποθεσία (GPS) - Μόνο μία φορά, σε thread, περνώντας όλο το msg
                if "location" in msg:
                    is_live_update = "edited_message" in update
                    threading.Thread(
                        target=handle_location,
                        args=(msg,),
                        kwargs={"live_update": is_live_update},
                        daemon=True
                    ).start()
                    continue

                # 2. Φωτογραφία
                if "photo" in msg:
                    caption = msg.get("caption", "")
                    threading.Thread(
                        target=handle_photo,
                        args=(msg["photo"], caption, chat_id),
                        daemon=True
                    ).start()
                    continue

                # 3. Φωνητικό (Voice)
                if "voice" in msg:
                    threading.Thread(
                        target=handle_voice,
                        args=(msg["voice"], chat_id),
                        daemon=True
                    ).start()
                    continue

                # 4. Έγγραφα (PDF, κλπ)
                if "document" in msg:
                    caption = msg.get("caption", "")
                    threading.Thread(
                        target=handle_document,
                        args=(msg["document"], caption, chat_id),
                        daemon=True
                    ).start()
                    continue
                
                # 5. Κείμενο & Εντολές
                user_text = msg.get("text", "").strip()
                if not user_text:
                    continue

                # --- [MASTRO-COMMANDS] ---
                cmd = user_text.lower().strip()

                if cmd == "/pause":
                    with _override_lock:
                        _override_state["pause_reminders"] = True
                    _save_override_state()
                    send_telegram_msg("⏸️ Reminders παγωμένα. `/resume` για επαναφορά.")
                    continue

                if cmd == "/mute":
                    with _override_lock:
                        _override_state["mute_proactive"] = True
                    _save_override_state()
                    send_telegram_msg("🔇 Proactive notifications σιωπηλά. `/resume` για επαναφορά.")
                    continue

                if cmd.startswith("/sleep"):
                    parts = cmd.split()
                    hours = float(parts[1]) if len(parts) > 1 else 8.0
                    with _override_lock:
                        _override_state["sleep_until"] = _time.time() + hours * 3600
                    _save_override_state()
                    send_telegram_msg(f"😴 Sleep mode για {hours:.0f} ώρες. Ησυχία!")
                    continue

                if cmd == "/resume":
                    with _override_lock:
                        _override_state.update({"pause_reminders": False, "mute_proactive": False, "sleep_until": None})
                    _save_override_state()
                    send_telegram_msg("✅ Όλα ξανά ενεργά!")
                    continue
                if user_text.lower().startswith("/confirm"):
                    cmd_to_confirm = user_text[len("/confirm"):].strip()
                    if not cmd_to_confirm:
                        send_telegram_msg("⚠️ Χρήση: `/confirm <εντολή>`")
                        continue
                    pending_exec_command = cmd_to_confirm
                    send_telegram_msg(
                        f"⚠️ *Επιβεβαίωση απαιτείται:*\n`{cmd_to_confirm}`\n\nΘέλεις να εκτελεστεί; (ναι/όχι)"
                    )
                    continue
                if cmd == "/help":
                    voice_status = "🔊 ON" if voice_mode_enabled else "✍️ OFF"
                    send_telegram_msg(
                        "🦞 *Αστακός — Εντολές*\n\n"
                        "/status — Κατάσταση scheduler & ενεργών jobs\n"
                        "/nutrition — Ανάλυση προϊόντος \\(στείλε φωτό πρώτα\\)\n"
                        "/receipt — Σκανάρισμα απόδειξης \\(στείλε φωτό πρώτα\\)\n"
                        "/story \\[θέμα\\] — Παραμύθι για τον Αλέξανδρο \\+ εικόνες\n"
                        "             π\\.χ\\. /story δεινόσαυροι \\| Αλέξανδρος και Rex\n"
                        f"/voice — Toggle φωνητικές απαντήσεις \\(τώρα: {voice_status}\\)\n"
                        "/pause — Παύση υπενθυμίσεων\n"
                        "/mute — Σίγαση proactive μηνυμάτων\n"
                        "/resume — Επαναφορά όλων \\(pause/mute/sleep\\)\n"
                        "/sleep \\[ώρες\\] — Ησυχία για Χ ώρες \\(π\\.χ\\. /sleep 8\\)\n"
                        "/confirm \\[εντολή\\] — Εκτέλεση εντολής με επιβεβαίωση\n"
                        "/plan [goal] — Multi-step εκτέλεση (π.χ. /plan κάνε release v1.2)\n"
                        "/end — Τέλος session & περίληψη"
                    )
                    continue

                if cmd == "/status":
                    if astakos_scheduler:
                        send_telegram_msg(astakos_scheduler.status())
                    else:
                        send_telegram_msg("⚠️ Scheduler δεν έχει εκκινήσει ακόμα.")
                    continue

                if cmd == "/voice":
                    voice_mode_enabled = not voice_mode_enabled
                    if voice_mode_enabled:
                        send_telegram_msg("🔊 *Voice mode ON* — Θα απαντάω με φωνητικά ακόμα και αν γράφεις.")
                    else:
                        send_telegram_msg("✍️ *Voice mode OFF* — Πίσω σε γραπτά μηνύματα.")
                    continue

                if user_text.lower() == "/nutrition":
                    global pending_photo
                    with pending_photo_lock:
                        p = pending_photo if (pending_photo and (time.time() - pending_photo["timestamp"]) < 30) else None
                        if p:
                            pending_photo = None
                    if p:
                        send_telegram_msg("🔍 Αναλύω τη διατροφική αξία...")
                        threading.Thread(
                            target=_run_nutrition,
                            args=(p["path"], chat_id),
                            daemon=True
                        ).start()
                    else:
                        send_telegram_msg("📷 Στείλε φωτογραφία της ετικέτας/συσκευασίας και μετά /nutrition (εντός 30\").")
                    continue

                if user_text.lower() == "/receipt":
                    with pending_photo_lock:
                        p = pending_photo if (pending_photo and (time.time() - pending_photo["timestamp"]) < 30) else None
                        if p:
                            pending_photo = None
                    if p:
                        send_telegram_msg("🧾 Σκανάρω την απόδειξη...")
                        threading.Thread(
                            target=_run_receipt,
                            args=(p["path"], chat_id),
                            daemon=True
                        ).start()
                    else:
                        send_telegram_msg("📷 Στείλε φωτογραφία απόδειξης και μετά /receipt (εντός 30\").")
                    continue

                if user_text.lower() == "/end":
                    print(f"\033[94m[Telegram]: Εντολή τερματισμού συνεδρίας από Λάζαρο.\033[0m")
                    threading.Thread(
                        target=handle_end_session,
                        args=(chat_id,),
                        daemon=True
                    ).start()
                    continue

                if cmd.startswith("/story"):
                    # /story [θέμα]  ή  /story [θέμα] | [χαρακτήρες]
                    rest = user_text[len("/story"):].strip()
                    if "|" in rest:
                        theme_part, chars_part = rest.split("|", 1)
                        story_theme = theme_part.strip()
                        story_chars = chars_part.strip()
                    else:
                        story_theme = rest or "μαγική περιπέτεια"
                        story_chars = ""
                    send_telegram_msg(f"📖 Φτιάχνω παραμύθι για *{story_theme}*\\.\\.\\. \\(30\\-60\"\\)")
                    threading.Thread(
                        target=_run_story_maker,
                        args=(story_theme, story_chars, chat_id),
                        daemon=True
                    ).start()
                    continue

                # Κανονικό μήνυμα προς τον Αστακό
                print(f"\n\033[96m[Telegram] Λάζαρος: {user_text}\033[0m")
                threading.Thread(
                    target=handle_message,
                    args=(user_text, chat_id),
                    daemon=True
                ).start()

        except requests.exceptions.Timeout:
            continue
        except Exception as e:
            print(f"\033[91m[TelegramBot Polling Error]: {e}\033[0m")
            time.sleep(5)

# ────────────────────────────────────────────────────────────────
# SCHEDULER JOBS (χωρίς while loop — ο scheduler τα καλεί)
# ────────────────────────────────────────────────────────────────

def job_check_reminders():
    """Ελέγχει για υπενθυμίσεις και τις στέλνει στο Telegram."""
    if is_reminders_paused():
        return
    from config import REMINDERS_FILE
    if not os.path.exists(REMINDERS_FILE):
        return
    try:
        with open(REMINDERS_FILE, "r", encoding="utf-8") as f:
            rems = json.load(f)
    except Exception:
        return
    now, changed = datetime.now().strftime("%Y-%m-%d %H:%M"), False
    for r in rems:
        if r.get("status") == "pending" and r.get("type") != "location" and now >= r.get("time", ""):
            msg = f"🔔 ΥΠΕΝΘΥΜΙΣΗ: {r['task']}"
            if is_duplicate_notification(msg, cooldown_seconds=60):
                continue
            send_telegram_msg(msg)
            log_event("reminders", "sent", task=r["task"])
            r["status"], changed = "done", True
    if changed:
        with open(REMINDERS_FILE, "w", encoding="utf-8") as f:
            json.dump(rems, f, ensure_ascii=False, indent=4)

def _load_recent_proactive_context(limit: int = 10) -> str:
    """Return a compact mixed-channel conversation snippet for proactive messages."""
    try:
        from memory.conversation_history import load_recent_context

        entries = load_recent_context(
            channel="telegram",
            global_limit=limit,
            channel_limit=limit,
            total_limit=limit,
        )
    except Exception as exc:
        print(f"\033[93m[ProactiveContext]: failed to load recent context: {exc}\033[0m")
        return ""

    lines = []
    for entry in entries[-limit:]:
        role = entry.get("role", "unknown")
        channel = entry.get("channel", "?")
        time_label = entry.get("time") or str(entry.get("timestamp", ""))[11:16]
        content = clean_message(str(entry.get("content", ""))).strip()
        if not content:
            continue
        content = " ".join(content.split())
        if len(content) > 220:
            content = content[:217].rstrip() + "..."
        speaker = "Λάζαρος" if role == "user" else "Αστακός"
        lines.append(f"- [{channel} {time_label}] {speaker}: {content}")

    return "\n".join(lines[-limit:])


def _craft_proactive_msg(event_name: str, confidence: float, count: int = 1) -> str:
    """LLM φτιάχνει φυσικό proactive μήνυμα αντί για template."""
    from langchain_core.messages import HumanMessage
    from core.brain import llm

    if count > 1:
        context = f"Ο Λάζαρος έχει {count} ρουτίνες σε ~30 λεπτά: {event_name}."
    elif confidence >= 0.8:
        context = f"Ο Λάζαρος κάνει σχεδόν πάντα '{event_name}' αυτή την ώρα (υψηλή βεβαιότητα)."
    elif confidence >= 0.5:
        context = f"Ο Λάζαρος συνήθως κάνει '{event_name}' αυτή την ώρα."
    else:
        context = f"Παλιότερα ο Λάζαρος έκανε '{event_name}' αυτή την ώρα, δεν είμαστε σίγουροι πια."

    recent_context = _load_recent_proactive_context()
    recent_block = (
        f"\n\n[ΠΡΟΣΦΑΤΟ ΙΣΤΟΡΙΚΟ WEB+TELEGRAM]\n{recent_context}\n"
        if recent_context
        else ""
    )

    prompt = (
        f"{context}\n\n"
        f"{recent_block}"
        "Είσαι ο Αστακός, ο προσωπικός AI του Λάζαρου (42 χρονών, μάστορας, "
        "γιος Αλέξανδρος 6 ετών, κόρη Μαρία 15 ετών, γυναίκα Σοφία). "
        "Στείλε ΕΝΑ φυσικό μήνυμα κολλημένο στην καθημερινότητα — με χιούμορ, σαν παλιός φίλος.\n"
        "Πριν γράψεις, διάβασε το πρόσφατο ιστορικό. Αν υπάρχει ζωντανό context "
        "(π.χ. παίζουν επιτραπέζιο, είναι σε ποδόσφαιρο, δουλεύει, είναι έξω), "
        "δέσε την ατάκα φυσικά με αυτό. Αν το ιστορικό δεν σχετίζεται, αγνόησέ το.\n"
        "ΚΡΙΣΙΜΟ: Το μήνυμα ΠΡΕΠΕΙ να αφορά ΜΟΝΟ τη συγκεκριμένη ρουτίνα/event. "
        "Το πρόσφατο ιστορικό είναι μόνο φόντο για ύφος, όχι αφορμή να αλλάξεις θέμα. "
        "Μην κάνεις status για tools, υγεία, Google Fit, debug ή άλλο θέμα αν δεν είναι το event.\n"
        "Αν το event αφορά σύνταξη/αποστολή μηνύματος στη Σοφία, μίλα μόνο για αυτό "
        "και ρώτα διακριτικά αν θέλει να ετοιμάσετε/στείλετε το μήνυμα.\n"
        "Χρησιμοποίησε τις ώρες στα πρόσφατα μηνύματα: μην παρουσιάζεις σαν τελειωμένο "
        "κάτι που ξεκίνησε πριν λίγα λεπτά ή δεν δηλώθηκε ότι ολοκληρώθηκε. "
        "Αν ο Λάζαρος είπε μόλις 'μαγειρεύω', 'παίζουμε', 'φεύγουμε' ή 'πάμε', "
        "μίλα σαν να είναι σε εξέλιξη, όχι σαν να έγινε ήδη.\n"
        "ΑΠΑΓΟΡΕΥΕΤΑΙ: 'δεν είναι η ώρα για', 'υπενθύμιση', 'θυμίζω', το event name κυριολεκτικά.\n"
        "Παραδείγματα:\n"
        "- 'Μάστορα, ο μικρός θα σε κυνηγάει αν δεν τον πας για ύπνο σε λίγο 😄'\n"
        "- 'Ε, καλά, δουλειά δουλειά — αλλά ο Αλέξανδρος σε θέλει για ύπνο!'\n"
        "Μέχρι 1-2 προτάσεις. Ελληνικά."
    )

    try:
        response = llm.invoke([HumanMessage(content=prompt)])
        content = response.content
        if isinstance(content, list):
            content = "".join(
                part.get("text", "") if isinstance(part, dict) else str(part)
                for part in content
            )
        return content.strip()
    except Exception as e:
        print(f"[Proactive Craft Error]: {e}")
        return f"Μάστορα, δεν είναι η ώρα για '{event_name}';"
def job_check_routines():
    """
    Ελέγχει για επερχόμενες ρουτίνες (30' νωρίτερα) και κάνει timeout decay
    σε εκκρεμείς επιβεβαιώσεις που δεν απαντήθηκαν.
    """
    import sqlite3
    from datetime import timedelta
    from config import BASE_DIR

    DB_PATH = os.path.join(BASE_DIR, "astakos_routines.db")
    DAYS_MAP = {
        "Monday":    ["Monday", "Δευτέρα"],
        "Tuesday":   ["Tuesday", "Τρίτη"],
        "Wednesday": ["Wednesday", "Τετάρτη"],
        "Thursday":  ["Thursday", "Πέμπτη"],
        "Friday":    ["Friday", "Παρασκευή"],
        "Saturday":  ["Saturday", "Σάββατο"],
        "Sunday":    ["Sunday", "Κυριακή"],
    }

    # Quiet hours ή proactive muted
    if is_proactive_muted():
        return
    if is_quiet_hours():
        if pending_routine_confirmations:
            from memory.routine_db import decay_routine, remove_pending_confirmation
            now_check = datetime.now()
            for rid in list(pending_routine_confirmations.keys()):
                if (now_check - pending_routine_confirmations[rid]["sent_at"]).total_seconds() > 1800:
                    decay_routine(rid)
                    log_event("routines", "timeout_decay", routine_id=rid,
                              event=pending_routine_confirmations[rid]["event"],
                              elapsed_s=1800)
                    del pending_routine_confirmations[rid]
                    remove_pending_confirmation(rid)
        return
    # 1. Upcoming routine notifications
    try:
        if os.path.exists(DB_PATH):
            conn   = sqlite3.connect(DB_PATH)
            cursor = conn.cursor()
            now          = datetime.now()
            target_time  = now + timedelta(minutes=30)
            day_en       = target_time.strftime("%A")
            possible_days = DAYS_MAP.get(day_en, [day_en])
            target_time_str = target_time.strftime("%H:%M")
            today_str       = now.strftime("%Y-%m-%d")

            placeholders = ",".join("?" * len(possible_days))
            cursor.execute(f"""
                SELECT id, event_name, confidence FROM routines
                WHERE (day_of_week IN ({placeholders}) OR day_of_week='Everyday' OR day_of_week='Καθημερινά')
                AND time_str=? AND state='active'
                AND (last_triggered IS NULL OR last_triggered != ?)
            """, (*possible_days, target_time_str, today_str))

            # ── Anti-Spam: φιλτράρισμα με per-routine cooldown ──────────
            from memory.routine_db import (
                get_routine_notify_info, mark_routine_notified,
                save_pending_confirmation
            )
            due_routines = []
            for r_id, event_name, confidence in cursor.fetchall():
                info = get_routine_notify_info(r_id)
                cd_hours = info["cooldown_hours"]
                if is_duplicate_routine(r_id, cd_hours):
                    log_event("routines", "skipped", reason="cooldown",
                              routine_id=r_id, event=event_name,
                              cooldown_hours=cd_hours)
                    continue
                due_routines.append((r_id, event_name, confidence))

            if not due_routines:
                conn.close()
                return

            if not can_send_proactive():
                log_event("routines", "skipped", reason="rate_limit",
                          count=len(due_routines))
                print(f"⏸️ [job_check_routines]: Rate limit, {len(due_routines)} routine(s) skipped")
                conn.close()
                return

            # ── Batching: πολλές ρουτίνες → ένα μήνυμα ──────────────────
            if len(due_routines) > 1:
                names = ", ".join(f"'{e}'" for _, e, _ in due_routines)
                msg = _craft_proactive_msg(names, 0.9, count=len(due_routines))
                send_telegram_msg(msg)
                sent_at = datetime.now()
                for r_id, event_name, confidence in due_routines:
                    cursor.execute("UPDATE routines SET last_triggered=? WHERE id=?", (today_str, r_id))
                    mark_routine_notified(r_id)
                    log_event("routines", "triggered", routine_id=r_id,
                              event=event_name, confidence=confidence,
                              batch=len(due_routines), preview=msg[:160])
                    pending_routine_confirmations[r_id] = {"event": event_name, "sent_at": sent_at}
                    save_pending_confirmation(r_id, event_name, sent_at)
                    bus.emit("routine_triggered", routine_id=r_id, event=event_name, confidence=confidence, batch=True, channel="telegram")
                conn.commit()
            else:
                # Μία ρουτίνα → εξατομικευμένο μήνυμα
                r_id, event_name, confidence = due_routines[0]
                msg = _craft_proactive_msg(event_name, confidence)
                cursor.execute("UPDATE routines SET last_triggered=? WHERE id=?", (today_str, r_id))
                conn.commit()
                mark_routine_notified(r_id)
                send_telegram_msg(msg)
                log_event("routines", "triggered", routine_id=r_id,
                          event=event_name, confidence=confidence,
                          preview=msg[:160])
                sent_at = datetime.now()
                pending_routine_confirmations[r_id] = {"event": event_name, "sent_at": sent_at}
                save_pending_confirmation(r_id, event_name, sent_at)
                bus.emit("routine_triggered", routine_id=r_id, event=event_name, confidence=confidence, batch=False, channel="telegram")

            conn.close()
    except Exception as e:
        print(f"❌ [job_check_routines]: {e}")

    # 2. Timeout decay για εκκρεμείς επιβεβαιώσεις (>30')
    # TRIGGER_PENDING → IGNORED → ACTIVE (cooldown doubled, confidence ανέπαφο)
    if pending_routine_confirmations:
        from memory.routine_db import mark_routine_ignored, remove_pending_confirmation
        now_check = datetime.now()
        for rid in list(pending_routine_confirmations.keys()):
            elapsed = (now_check - pending_routine_confirmations[rid]["sent_at"]).total_seconds()
            if elapsed > 1800:
                ev = pending_routine_confirmations[rid]["event"]
                try:
                    mark_routine_ignored(rid)  # TRIGGER_PENDING → IGNORED → ACTIVE + doubled cooldown
                except DBWriteError as e:
                    print(f"\033[91m[Timeout Decay DBWriteError]: {e}\033[0m")
                timeout_err = PendingTimeoutError(rid, ev, elapsed)
                log_event("routines", "timeout_decay",
                          routine_id=rid, event=ev,
                          elapsed_s=int(elapsed))
                print(f"⏰ {timeout_err}")
                bus.emit("routine_timeout", routine_id=rid, event=ev, elapsed_s=int(elapsed), channel="telegram")
                del pending_routine_confirmations[rid]
                remove_pending_confirmation(rid)


def job_proactive_scan():
    """
    Ο 'Νυχτοφύλακας' — σκανάρει το watch_folder και αν βρει θέμα, στέλνει alert.
    """
    from tools.system import read_local_file
    WATCH_DIR = "C:\\astakos_v2\\watch_folder"

    if is_proactive_muted():
        return
    if is_quiet_hours():
        print("🌙 [job_proactive_scan]: Quiet hours — παραλείπεται.")
        return
    if should_skip_proactive_for_recent_activity():
        return
    if not can_send_proactive():
        print("⏸️ [job_proactive_scan]: Rate limit reached — παραλείπεται.")
        return

    print("🦞 [Proactive]: Ξεκινάω αθόρυβο σκανάρισμα συστήματος...")
    try:
        os.makedirs(WATCH_DIR, exist_ok=True)
        files_to_scan = os.listdir(WATCH_DIR)
        if not files_to_scan:
            return

        collected_data = ""
        for file in files_to_scan:
            filepath = os.path.join(WATCH_DIR, file)
            try:
                content = read_local_file.invoke(filepath)
            except TypeError:
                content = read_local_file.invoke({"file_path": filepath})
            collected_data += f"\n--- ΑΡΧΕΙΟ: {file} ---\n{str(content)[:2000]}\n"

        prompt = (
            "Είσαι ο Αστακός. Λειτουργείς ως σύστημα προληπτικής συντήρησης.\n"
            "1. Ψάξε για ΗΜΕΡΟΜΗΝΙΕΣ ΛΗΞΗΣ κοντά στο σήμερα.\n"
            "2. Ψάξε για ERRORS ή προβλήματα.\n"
            "3. ΑΝ ΥΠΑΡΧΕΙ ΘΕΜΑ: ξεκίνα με '🚨 Μάστορα, ρίξε μια ματιά:'.\n"
            "4. ΑΝ ΟΛΑ ΕΙΝΑΙ ΚΑΛΑ: γράψε ΜΟΝΟ 'ΟΛΑ ΚΑΛΑ'."
        )
        response = safe_gemini_call(f"{prompt}\n\n[ΔΕΔΟΜΕΝΑ]:\n{collected_data}")
        reply = response.text.strip()

        if reply and "ΟΛΑ ΚΑΛΑ" not in reply:
            if not is_duplicate_notification(reply, cooldown_seconds=3600):
                send_telegram_msg(reply)
                log_event("proactive", "alert_sent", preview=reply[:80])
                print(f"⚠️ [Proactive Alert Sent]: {reply[:50]}...")
        else:
            log_event("proactive", "all_clear")
            print("✔️ [Proactive]: Όλα καθαρά.")
    except Exception as e:
        print(f"⚠️ [job_proactive_scan]: {e}")

def job_analytics_engine():
    """Nightly passive routine detection — τρέχει μόνο 03:00–04:00."""
    now_hour = datetime.now().hour
    if now_hour != 3:
        return
    try:
        from services.analytics_engine import run_analytics
        stats = run_analytics()
        if stats.get("created", 0) + stats.get("merged", 0) > 0:
            send_telegram_msg(
                f"🧠 [Analytics]: Εντόπισα νέες ρουτίνες!\n"
                f"✅ Νέες: {stats['created']} | 🔗 Merged: {stats['merged']} | "
                f"📊 Ανιχνεύθηκαν: {stats['detected']}"
            )
    except Exception as e:
        print(f"[Analytics Job Error]: {e}")

    # Reflection engine — τρέχει αμέσως μετά τα analytics
    try:
        from services.reflection_engine import run_reflection
        r_stats = run_reflection()
        print(f"[Reflection Job]: applied={r_stats.get('applied',0)}, pending={r_stats.get('pending',0)}")
    except Exception as re:
        print(f"[Reflection Job Error]: {re}")

def job_morning_fit_briefing():
    """Πρωινό Google Fit briefing — τρέχει μόνο 08:00–09:00, μία φορά."""
    now_hour = datetime.now().hour
    if now_hour != 8:
        return
    # Αποφυγή διπλής αποστολής — ελέγχουμε αν το στείλαμε ήδη σήμερα
    flag_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".fit_briefing_sent")
    today_str = datetime.now().strftime("%Y-%m-%d")
    if os.path.exists(flag_file):
        with open(flag_file, "r") as f:
            if f.read().strip() == today_str:
                return
    try:
        from astakos_skills.google_fit import get_morning_summary
        summary = get_morning_summary()
        send_telegram_msg(f"🌅 *Καλημέρα Μάστορα!*\n\n{summary}")
        with open(flag_file, "w") as f:
            f.write(today_str)
        print(f"✅ [FitBriefing]: Πρωινό briefing στάλθηκε.")
    except Exception as e:
        print(f"⚠️ [FitBriefing]: {e}")

def job_goal_followup():
    """
    Ελέγχει active goals που δεν αναφέρθηκαν τις τελευταίες 7 μέρες.
    Τρέχει μία φορά την ημέρα στις 10:00.
    """
    now_hour = datetime.now().hour
    if now_hour != 10:
        return

    flag_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".goal_followup_sent")
    today_str = datetime.now().strftime("%Y-%m-%d")
    if os.path.exists(flag_file):
        with open(flag_file, "r") as f:
            if f.read().strip() == today_str:
                return

    try:
        from memory.vector_store import get_active_goals
        from config import BASE_DIR
        import json as _json

        goals = get_active_goals()
        if not goals:
            return

        # Semantic search: ψάχνουμε αν υπάρχουν πρόσφατες μνήμες για κάθε goal
        from datetime import timedelta
        from memory.vector_store import vector_store, vector_lock
        cutoff_ts = (datetime.now() - timedelta(days=7)).timestamp()

        stale_goals = []
        for g in goals:
            try:
                with vector_lock:
                    results = vector_store._collection.query(
                        query_texts=[g["project"] + " " + g["description"]],
                        n_results=3,
                        where={"timestamp": {"$gte": cutoff_ts}},
                    )
                # Αν δεν βρήκε τίποτα πρόσφατο → stale
                if not results["ids"] or not results["ids"][0]:
                    stale_goals.append(g)
                    print(f"[GoalFollowup]: '{g['project']}' → stale (0 recent memories)")
                else:
                    print(f"[GoalFollowup]: '{g['project']}' → active ({len(results['ids'][0])} recent memories)")
            except Exception as _e:
                print(f"[GoalFollowup]: semantic check error for '{g['project']}': {_e}")
                stale_goals.append(g)

        if not stale_goals:
            return

        # LLM crafts natural follow-up message
        from services.gemini import safe_gemini_call
        goals_text = "\n".join(f"- {g['project']}: {g['description']}" for g in stale_goals[:3])
        prompt = f"""Είσαι ο Αστακός, ο AI βοηθός του Λάζαρου. 
Ο Λάζαρος έχει τους εξής ανοιχτούς στόχους που δεν αναφέρθηκαν τις τελευταίες 7 μέρες:

{goals_text}

Γράψε ένα σύντομο, φιλικό και φυσικό μήνυμα (2-3 προτάσεις) που τον υπενθυμίζει για αυτούς.
ΜΗΝ ακούγεσαι σαν bot. Μίλα σαν συνεργάτης που θυμάται."""

        response = safe_gemini_call(prompt)
        msg = response.text.strip() if hasattr(response, "text") else str(response).strip()

        if msg:
            send_telegram_msg(f"🎯 {msg}")
            with open(flag_file, "w") as f:
                f.write(today_str)
            print(f"✅ [GoalFollowup]: Στάλθηκε για {len(stale_goals)} goals.")

    except Exception as e:
        print(f"⚠️ [GoalFollowup]: {e}")


# ────────────────────────────────────────────────────────────────
# ASTAKOS SCHEDULER (Central Event Bus)
# ────────────────────────────────────────────────────────────────

class AstakosScheduler:
    """
    Ένας thread, όλα τα background jobs.
    - Heartbeat 10s
    - Watchdog: fail_count + disabled_after_N_failures
    - Duration tracking
    - status() για /status command
    """

    MAX_FAILURES = 5  # απενεργοποίηση μετά από τόσα διαδοχικά failures

    def __init__(self):
        self._jobs = []

    def register(self, func, interval_seconds: int, name: str = None):
        self._jobs.append({
            "name":          name or func.__name__,
            "func":          func,
            "interval":      interval_seconds,
            "last_run":      0,
            "last_duration": 0.0,
            "fail_count":    0,
            "last_error":    None,
            "disabled":      False,
        })
        print(f"\033[90m[Scheduler]: Registered '{name or func.__name__}' every {interval_seconds}s\033[0m")

    def _write_snapshot(self):
        """Γράφει runtime_snapshot.json κάθε heartbeat — διαβάζεται από /debug/runtime."""
        try:
            from config import BASE_DIR
            import json as _json
            now = time.time()
            snapshot = {
                "written_at":  datetime.now().isoformat(timespec="seconds"),
                "jobs": [
                    {
                        "name":          j["name"],
                        "interval":      j["interval"],
                        "last_run":      datetime.fromtimestamp(j["last_run"]).strftime("%H:%M:%S") if j["last_run"] > 0 else None,
                        "next_in_secs":  max(0, int(j["interval"] - (now - j["last_run"]))) if j["last_run"] > 0 else 0,
                        "last_duration": round(j["last_duration"], 3),
                        "fail_count":    j["fail_count"],
                        "last_error":    j["last_error"],
                        "disabled":      j["disabled"],
                    }
                    for j in self._jobs
                ],
                "pending_confirmations": len(pending_routine_confirmations),
                "queue_size":            astakos_queue.qsize(),
                "quiet_hours":           is_quiet_hours(),
                "proactive_muted":       is_proactive_muted(),
                "reminders_paused":      is_reminders_paused(),
            }
            with _proactive_lock:
                snapshot["proactive_this_hour"] = _proactive_count["count"]
            path = os.path.join(BASE_DIR, "runtime_snapshot.json")
            with open(path, "w", encoding="utf-8") as f:
                _json.dump(snapshot, f, ensure_ascii=False)
        except Exception as e:
            print(f"[Scheduler]: snapshot write error: {e}")

    def run(self):
        print("\033[90m[Scheduler]: Central Event Bus ξεκίνησε!\033[0m")
        while not shutdown_event.is_set():
            now = time.time()
            for job in self._jobs:
                if job["disabled"]:
                    continue
                if now - job["last_run"] < job["interval"]:
                    continue

                t_start = time.time()
                log_event(job["name"], "start")
                try:
                    job["func"]()
                    job["fail_count"] = 0
                    job["last_error"] = None
                    log_event(job["name"], "complete", duration=round(time.time()-t_start, 2))
                except DBWriteError as e:
                    job["fail_count"] += 1
                    job["last_error"] = str(e)
                    log_event(job["name"], "db_error", error=str(e), fail_count=job["fail_count"])
                    print(f"\033[91m💾 [Scheduler/{job['name']}]: DBWriteError: {e}\033[0m")
                    if job["fail_count"] >= self.MAX_FAILURES:
                        crash = SchedulerCrashError(job["name"], job["fail_count"], str(e))
                        job["disabled"] = True
                        log_event(job["name"], "disabled", reason="db_crash", error=str(crash))
                        print(f"\033[91m\U0001f6ab [Scheduler]: {crash}\033[0m")
                        send_telegram_msg(f"\u26a0\ufe0f Watchdog: Job `{job['name']}` \u03b1\u03c0\u03b5\u03bd\u03b5\u03c1\u03b3\u03bf\u03c0\u03bf\u03b9\u03ae\u03b8\u03b7\u03ba\u03b5 (DB errors).\n\u03a4\u03b5\u03bb\u03b5\u03c5\u03c4\u03b1\u03af\u03bf: {str(e)[:200]}")
                except Exception as e:
                    job["fail_count"] += 1
                    job["last_error"] = str(e)
                    log_event(job["name"], "error", error=str(e), fail_count=job["fail_count"])
                    print(f"\033[91m\u274c [Scheduler/{job['name']}]: {e} (fail {job['fail_count']}/{self.MAX_FAILURES})\033[0m")
                    if job["fail_count"] >= self.MAX_FAILURES:
                        crash = SchedulerCrashError(job["name"], job["fail_count"], str(e))
                        job["disabled"] = True
                        log_event(job["name"], "disabled", reason="max_failures", error=str(crash))
                        print(f"\033[91m\U0001f6ab [Scheduler]: {crash}\033[0m")
                        send_telegram_msg(f"\u26a0\ufe0f Watchdog: Job `{job['name']}` \u03b1\u03c0\u03b5\u03bd\u03b5\u03c1\u03b3\u03bf\u03c0\u03bf\u03b9\u03ae\u03b8\u03b7\u03ba\u03b5 \u03bc\u03b5\u03c4\u03ac \u03b1\u03c0\u03cc {self.MAX_FAILURES} \u03c3\u03c6\u03ac\u03bb\u03bc\u03b1\u03c4\u03b1.\n\u03a4\u03b5\u03bb\u03b5\u03c5\u03c4\u03b1\u03af\u03bf: {str(e)[:200]}")
                job["last_run"]      = time.time()
                job["last_duration"] = time.time() - t_start

            self._write_snapshot()
            shutdown_event.wait(timeout=10)

    def status(self) -> str:
        now   = time.time()
        lines = ["\U0001f4ca *Scheduler Status:*"]
        for job in self._jobs:
            icon = "\U0001f6ab" if job["disabled"] else "\u2705"
            if job["last_run"] > 0:
                last_str  = datetime.fromtimestamp(job["last_run"]).strftime("%H:%M:%S")
                next_secs = max(0, int(job["interval"] - (now - job["last_run"])))
                next_str  = f"{next_secs}s"
            else:
                last_str = "\u2014"
                next_str = "\u03b1\u03bc\u03ad\u03c3\u03c9\u03c2"
            lines.append(
                f"{icon} `{job['name']}` | last: {last_str} | next: {next_str} "
                f"| {job['last_duration']:.1f}s | fails: {job['fail_count']}"
            )
            if job["last_error"]:
                lines.append(f"   \u2514\u2500 \u26a0\ufe0f _{job['last_error'][:100]}_")

        lines.append("")
        lines.append(f"\u23f3 Pending confirmations: {len(pending_routine_confirmations)}")
        lines.append(f"\U0001f4ec Queue size: {astakos_queue.qsize()}")
        quiet = is_quiet_hours()
        quiet_label = "\u039d\u0391\u0399" if quiet else "\u039f\u03a7\u0399"
        lines.append(f"\U0001f319 Quiet hours: {quiet_label} ({QUIET_HOURS[0]:02d}:00\u2013{QUIET_HOURS[1]:02d}:00)")
        with _proactive_lock:
            lines.append(f"\U0001f4e3 Proactive this hour: {_proactive_count['count']}/{MAX_PROACTIVE_PER_HOUR}")
        with _override_lock:
            paused  = _override_state.get("pause_reminders")
            muted   = _override_state.get("mute_proactive")
            sleep_u = _override_state.get("sleep_until")
            sleeping = sleep_u and _time.time() < sleep_u
        if paused or muted or sleeping:
            ovr = []
            if paused:   ovr.append("reminders paused")
            if muted:    ovr.append("proactive muted")
            if sleeping: ovr.append(f"sleep until {datetime.fromtimestamp(sleep_u).strftime('%H:%M')}")
            lines.append(f"\U0001f6d1 Override: {', '.join(ovr)}")
        return "\n".join(lines)


# ────────────────────────────────────────────────────────────────
# ENTRY POINT
# ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import signal as _signal

    def _handle_exit(*args):
        print("\n[TelegramBot]: \u03a4\u03b5\u03c1\u03bc\u03b1\u03c4\u03b9\u03c3\u03bc\u03cc\u03c2...")
        shutdown_event.set()

    _signal.signal(_signal.SIGTERM, _handle_exit)
    _signal.signal(_signal.SIGINT,  _handle_exit)

    threading.Thread(target=queue_worker, daemon=True).start()

    _load_override_state()
    from memory.routine_db import load_pending_confirmations
    pending_routine_confirmations.update(load_pending_confirmations())
    if pending_routine_confirmations:
        print(f"\033[93m[Recovery]: \u03a6\u03bf\u03c1\u03c4\u03ce\u03b8\u03b7\u03ba\u03b1\u03bd {len(pending_routine_confirmations)} pending confirmations.\033[0m")

    astakos_scheduler = AstakosScheduler()
    astakos_scheduler.register(job_check_reminders, interval_seconds=20,    name="reminders")
    astakos_scheduler.register(job_check_routines,  interval_seconds=60,    name="routines")
    astakos_scheduler.register(job_proactive_scan,  interval_seconds=43200, name="proactive")
    astakos_scheduler.register(job_analytics_engine, interval_seconds=3600, name="analytics")
    astakos_scheduler.register(job_morning_fit_briefing, interval_seconds=3600, name="fit_briefing")
    astakos_scheduler.register(job_goal_followup,       interval_seconds=3600, name="goal_followup")
    threading.Thread(target=astakos_scheduler.run, daemon=True).start()
    # Φόρτωσε το ιστορικό από τον δίσκο


    print("\u2501" * 50)
    print("  \U0001f99e  \u0391\u03c3\u03c4\u03b1\u03ba\u03cc\u03c2 Telegram Bot \u2014 \u0395\u03ba\u03ba\u03af\u03bd\u03b7\u03c3\u03b7")
    print("\u2501" * 50)
    
    send_telegram_msg("🦞 Αστακός Ξεκίνησα! Πώς μπορώ να βοηθήσω Λάζαρε;")
    try:
        run_polling()
    except KeyboardInterrupt:
        _handle_exit()
    finally:
        shutdown_event.set()
        # Drain queue before summary (max 5s)
        try:
            import threading as _th
            _done = _th.Event()
            def _drain(): astakos_queue.join(); _done.set()
            _th.Thread(target=_drain, daemon=True).start()
            _done.wait(timeout=5)
        except Exception:
            pass
        try:
            _run_session_summary(channel='telegram')
        except Exception:
            pass
        print('[TelegramBot]: Τερματίστηκε.')
