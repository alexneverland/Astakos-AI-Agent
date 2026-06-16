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

from config import TELEGRAM_TOKEN, TELEGRAM_CHAT_ID, PHOTOS_DIR, PHOTOS_INDEX_FILE

def _normalize_gr(text: str) -> str:
    """Αφαιρεί τόνους από ελληνικό κείμενο για accent-insensitive σύγκριση."""
    import unicodedata
    normalized = unicodedata.normalize("NFD", str(text))
    return "".join(ch for ch in normalized if not unicodedata.combining(ch)).lower()

from memory.event_log import log_event, is_duplicate_notification, is_duplicate_routine
from core.exceptions import SchedulerCrashError, PendingTimeoutError, DBWriteError
from core.brain import llm, safe_llm_invoke
from core.graph import graph
from core.agents import clean_message, filter_messages
from memory.vector_store import memory
from memory.working_memory import update_working_memory, update_capabilities_from_exchange
from memory.session_memory import trigger_memory_sifter, log_exchange, _run_session_summary, startup_stale_cleanup
from tools.telegram import send_telegram_msg, send_telegram_voice, send_telegram_msg_full
from services.gemini import safe_gemini_call
from services.embeddings import embeddings
from core.event_bus import bus
# ────────────────────────────────────────────────────────────────
# GLOBALS
# ────────────────────────────────────────────────────────────────
shutdown_event        = threading.Event()
astakos_queue         = queue.Queue()
memory_lock           = threading.Lock()

# Cache: telegram message_id → full text (τελευταία 50 bot μηνύματα)
# Χρησιμοποιείται από _handle_message_reaction για exact match
_bot_message_cache: dict[int, str] = {}
_bot_message_cache_lock = threading.Lock()
_BOT_CACHE_MAX = 50

def _cache_bot_message(message_id: int | None, text: str) -> None:
    if not message_id:
        return
    with _bot_message_cache_lock:
        _bot_message_cache[message_id] = text
        # Κράτα μόνο τα τελευταία N
        if len(_bot_message_cache) > _BOT_CACHE_MAX:
            oldest = sorted(_bot_message_cache.keys())[0]
            del _bot_message_cache[oldest]
last_interaction_time = time.time()
# Pending routine confirmations: {routine_id: {"event": ..., "sent_at": ...}}
pending_routine_confirmations = {}
pending_exec_command = None
# Pending reflection confirmations (ask-tier, 50-75% confidence): {reflection_id: {full reflection dict}}
pending_reflection_confirmations = {}
# Pending photo: αποθηκεύει ανάλυση φωτογραφίας που έφτασε χωρίς caption, για να συνδυαστεί με το επόμενο μήνυμα
pending_photo_lock = threading.Lock()
pending_photo      = None   # {analysis, filename, path, timestamp}
pending_georgian_lock = threading.Lock()
pending_georgian_until = 0.0
PENDING_GEORGIAN_TTL_SECONDS = 120
pending_sofia_lock = threading.Lock()
pending_sofia_until = 0.0   # ka→el mode (Σοφία γράφει Γεωργιανά)
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
        analysis_raw  = safe_llm_invoke(llm, [vision_msg])
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

    # Φόρτωση history από shared SQLite
    context_msgs = _load_shared_context_messages("telegram")

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
        from memory.execution_trace import ExecutionTrace
        _ptrace = ExecutionTrace(channel="telegram", user_message=user_log_msg)
        for event in graph.stream({"messages": context_msgs + [HumanMessage(content=user_log_msg)], "channel": "telegram"}, {"recursion_limit": 50}):
            _ptrace.process_event(event)
            for node, data in event.items():
                if data is None:
                    continue
                if node not in ["supervisor", "tools"]:
                    msgs = data.get("messages", [])
                    if msgs and hasattr(msgs[-1], "content"):
                        candidate = clean_message(msgs[-1].content).strip()
                        if candidate:
                            final_response = candidate
        _ptrace.finalize(response=final_response or None)
        _ptrace.save()
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
        _send_and_record_assistant(result, chat_id)
    except Exception as e:
        _send_and_record_assistant(f"❌ Σφάλμα nutrition analysis: {e}", chat_id)


def _run_receipt(image_path: str, chat_id: str):
    """Τρέχει το receipt scanner και στέλνει αποτέλεσμα."""
    try:
        from astakos_skills.scan_receipt import scan_receipt
        result = scan_receipt.invoke({"image_path": image_path})
        _send_and_record_assistant(result, chat_id)
    except Exception as e:
        _send_and_record_assistant(f"❌ Σφάλμα receipt scan: {e}", chat_id)


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
        send_telegram_msg(f"Μάστορα, μου κόπηκε η φωνή... (Error: {e})")
def _append_to_analytics_log(role: str, content: str):
    """Καταγραφή μηνύματος στο shared SQLite conversation history (telegram channel)."""
    try:
        now = datetime.now()
        shared_role = "assistant" if role in ("ai", "assistant") else role
        try:
            # notify_telegram_message: αποθηκεύει στη shared SQLite + WebSocket broadcast στο Web UI
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
    except Exception as e:
        print(f"[ConversationHistory/telegram]: Σφάλμα shared write: {e}")


def _send_and_record_assistant(content: str, chat_id: str | None = None):
    """Στέλνει assistant reply στο Telegram και το γράφει στο shared history."""
    message_id = send_telegram_msg(content)
    _append_to_analytics_log("ai", content)
    return message_id


def _arm_pending_georgian():
    global pending_georgian_until
    with pending_georgian_lock:
        pending_georgian_until = time.time() + PENDING_GEORGIAN_TTL_SECONDS


def _clear_pending_georgian():
    global pending_georgian_until
    with pending_georgian_lock:
        pending_georgian_until = 0.0


def _consume_pending_georgian() -> bool:
    global pending_georgian_until
    with pending_georgian_lock:
        if pending_georgian_until and time.time() <= pending_georgian_until:
            pending_georgian_until = 0.0
            return True
        pending_georgian_until = 0.0
        return False


def _arm_pending_sofia():
    global pending_sofia_until
    with pending_sofia_lock:
        pending_sofia_until = time.time() + PENDING_GEORGIAN_TTL_SECONDS


def _clear_pending_sofia():
    global pending_sofia_until
    with pending_sofia_lock:
        pending_sofia_until = 0.0


def _consume_pending_sofia() -> bool:
    global pending_sofia_until
    with pending_sofia_lock:
        if pending_sofia_until and time.time() <= pending_sofia_until:
            pending_sofia_until = 0.0
            return True
        pending_sofia_until = 0.0
        return False


def _send_georgian_translation(text: str, *, force_src: str = "auto"):
    from tools.georgian import translate, tts_audio

    try:
        result = translate(text, src=force_src)
    except Exception as e:
        send_telegram_msg(f"❌ Σφάλμα μετάφρασης: {e}")
        return

    flag = "🇬🇪" if result["tgt"] == "ka" else "🇬🇷"
    direction = "el→ka" if result["tgt"] == "ka" else "ka→el"

    reply = f"{flag} <code>{result['translated']}</code>"
    if result["phonetic"]:
        reply += f"\n📢 <i>{result['phonetic']}</i>"
    send_telegram_msg(reply)

    try:
        audio_bytes = tts_audio(result["translated"], lang=result["tgt"])
        tg_url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendAudio"
        requests.post(
            tg_url,
            data={"chat_id": TELEGRAM_CHAT_ID},
            files={"audio": ("georgian.mp3", audio_bytes, "audio/mpeg")},
            timeout=20,
        )
        print(f"\033[92m[Georgian]: {direction} '{text}' → '{result['translated']}' + audio\033[0m")
    except Exception as e_audio:
        print(f"\033[93m[Georgian]: audio skip — {e_audio}\033[0m")


def _tool_results_fallback_response(user_text: str, tool_results: list[str]) -> str:
    """Συνθέτει τελική απάντηση όταν το graph γύρισε μόνο tool results."""
    clean_results = [clean_message(r).strip() for r in tool_results if clean_message(r).strip()]
    if not clean_results:
        return ""

    joined_results = "\n\n---\n\n".join(clean_results[-5:])[:6000]
    prompt = (
        "Σύνθεσε σύντομη, καθαρή απάντηση στα Ελληνικά για τον χρήστη με βάση ΜΟΝΟ "
        "τα παρακάτω αποτελέσματα εργαλείων. Μην καλέσεις εργαλεία. "
        "Αν τα στοιχεία δεν επαρκούν για ακριβή απάντηση, πες τι λείπει και δώσε "
        "προσεκτική σύνοψη.\n\n"
        f"Ερώτηση χρήστη:\n{user_text}\n\n"
        f"Αποτελέσματα εργαλείων:\n{joined_results}"
    )
    try:
        response = safe_llm_invoke(llm, [HumanMessage(content=prompt)])
        content = clean_message(getattr(response, "content", "")).strip()
        if content and not content.startswith("[Κλήση Εργαλείου:"):
            return content
    except Exception as e:
        print(f"\033[93m[ToolFallback]: synthesis failed — {e}\033[0m")

    return "Βρήκα αυτά τα σχετικά στοιχεία, αλλά δεν μπόρεσα να τα συνθέσω καθαρά:\n\n" + joined_results[:1800]


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


def _llm_routine_judge(user_msg: str, events: list) -> str:
    """
    Κρίνει αν το μήνυμα του χρήστη επιβεβαιώνει ή απορρίπτει pending routine events.
    Επιστρέφει: "YES" / "NO" / "UNCLEAR"
    Χρησιμοποιεί safe_gemini_call με fallback σε UNCLEAR αν αποτύχει.
    """
    try:
        from services.gemini import safe_gemini_call
        events_str = chr(10).join(f"- {e}" for e in events)
        prompt = (
            "You are a routine tracking assistant. A user has a pending activity check."
            + chr(10) + chr(10)
            + "Pending events:" + chr(10) + events_str
            + chr(10) + chr(10)
            + f'User message: "{user_msg}"'
            + chr(10) + chr(10)
            + "Does this message indicate the user confirmed they did (or will do) one of the above events? "
            + "Or does it clearly refuse/cancel? "
            + "Reply with exactly one word: YES (confirmed), NO (refused/cancelled), or UNCLEAR (unrelated or ambiguous)."
        )
        result = safe_gemini_call(prompt, retries=2, base_delay=1.0)
        verdict = result.text.strip().upper().split()[0] if result and result.text.strip() else "UNCLEAR"
        if verdict not in ("YES", "NO", "UNCLEAR"):
            verdict = "UNCLEAR"
        print(f"\033[96m🤖 [Routine LLM Judge]: '{user_msg[:50]}' \u2192 {verdict}\033[0m")
        return verdict
    except Exception as e:
        print(f"\033[93m[Routine LLM Judge]: Σφάλμα, fallback σε UNCLEAR: {e}\033[0m")
        return "UNCLEAR"


# ────────────────────────────────────────────────────────────────
# MESSAGE HANDLER
# ────────────────────────────────────────────────────────────────

def _send_pending_reflections_summary() -> None:
    """Στέλνει ένα ενιαίο αριθμημένο μήνυμα για όλα τα pending reflections."""
    if not pending_reflection_confirmations:
        return

    blocks = []
    for i, (rid, rdata) in enumerate(pending_reflection_confirmations.items(), start=1):
        conf = rdata.get("confidence")
        conf_txt = f" (confidence: {conf:.0%})" if isinstance(conf, (int, float)) else ""
        blocks.append(
            f"🤔 *#{i} Παρατήρηση:* {rdata.get('observation','')}\n"
            f"→ Προτείνω: `{rdata.get('action','')}`{conf_txt}"
        )
    msg = (
        "🧠 *Astakos — Εκκρεμή reflections*\n\n"
        + "\n\n---\n\n".join(blocks)
        + "\n\n_Απάντησε:_ `ναι Ν` / `όχι Ν` για συγκεκριμένο, ή απλά `ναι`/`όχι` για όλα μαζί."
    )
    if len(msg) > 4000:
        msg = msg[:3990] + "..."
    send_telegram_msg(msg)


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
        llm_dismissed = False
        if not explicit_yes and not is_question_like and not any(w in text_check for w in no_words):
            # LLM κρίνει αν το μήνυμα είναι implicit confirmation/dismissal
            event_names = [
                (rdata.get("event", "") if isinstance(rdata, dict) else str(rdata))
                for rdata in pending_routine_confirmations.values()
            ]
            verdict = _llm_routine_judge(clean_user_text, event_names)
            if verdict == "YES":
                implicit_confirmed = True
            elif verdict == "NO":
                llm_dismissed = True

        if explicit_yes or implicit_confirmed:
            from memory.routine_db import confirm_routine, mark_routine_responded, clear_pending_confirmations
            for rid in list(pending_routine_confirmations.keys()):
                confirm_routine(rid)
                mark_routine_responded(rid)
                from memory.event_log import log_event
                log_event("routines", "confirmed", routine_id=rid, event=pending_routine_confirmations[rid].get("event","?"))
                print(f"✅ [Routine Confirmed]: {pending_routine_confirmations[rid]}")
                bus.emit("routine_confirmed", routine_id=rid, event=pending_routine_confirmations[rid].get("event","?"), channel="telegram")
            pending_routine_confirmations.clear()
            clear_pending_confirmations()
        elif any(w in text_check for w in no_words) or llm_dismissed:
            from memory.routine_db import decay_routine, clear_pending_confirmations
            for rid in list(pending_routine_confirmations.keys()):
                decay_routine(rid)
                from memory.event_log import log_event
                log_event("routines", "dismissed", routine_id=rid, event=pending_routine_confirmations[rid].get("event","?"))
                print(f"📉 [Routine Dismissed]: {pending_routine_confirmations[rid]}")
                bus.emit("routine_dismissed", routine_id=rid, event=pending_routine_confirmations[rid].get("event","?"), channel="telegram")
            pending_routine_confirmations.clear()
            clear_pending_confirmations()

    # ── REFLECTION CONFIRMATION LOOP (ask-tier, 50-75% confidence) ──
    global pending_reflection_confirmations
    if pending_reflection_confirmations:
        text_check = _normalize_gr(clean_user_text)
        text_words = text_check.replace(",", "").replace(".", "").replace("!", "").split()
        yes_words = [_normalize_gr(w) for w in ["ναι", "yes", "ok", "οκ"]]
        no_words  = [_normalize_gr(w) for w in ["όχι", "οχι", "no", "cancel", "άκυρο", "ακυρο"]]
        is_yes = any(w in text_words for w in yes_words)
        is_no  = any(w in text_words for w in no_words)

        if is_yes or is_no:
            import re as _re
            numbers = [int(n) for n in _re.findall(r"\d+", text_check)]
            # Αντιστοίχιση αριθμού -> reflection_id, με βάση τη σειρά εμφάνισης
            # στο τελευταίο αριθμημένο μήνυμα (= σειρά εισαγωγής στο dict).
            ordered_ids = list(pending_reflection_confirmations.keys())
            if numbers:
                targets = [ordered_ids[n - 1] for n in numbers if 1 <= n <= len(ordered_ids)]
            else:
                targets = ordered_ids  # χωρίς αριθμό → όλα μαζί (παλιά συμπεριφορά)

            if not targets:
                send_telegram_msg("⚠️ Δεν βρήκα reflection με αυτόν τον αριθμό.")
                return

            if is_yes:
                from services.reflection_engine import _apply_action, mark_reflection_applied
                lines = []
                for rid in targets:
                    rdata = pending_reflection_confirmations[rid]
                    success = _apply_action(rdata)
                    if success:
                        try:
                            mark_reflection_applied(rid)
                        except Exception as e:
                            print(f"⚠️ [Reflection Confirm] DB update failed: {e}")
                        lines.append(f"✅ Εφαρμόστηκε: {rdata.get('observation','')[:80]}")
                        del pending_reflection_confirmations[rid]
                    else:
                        lines.append(f"⚠️ Αποτυχία εφαρμογής, μένει εκκρεμές: {rdata.get('observation','')[:80]}")
                send_telegram_msg("\n".join(lines) if lines else "✅ Έγινε.")
                if pending_reflection_confirmations:
                    _send_pending_reflections_summary()
                return
            else:
                from services.reflection_engine import mark_reflection_rejected
                for rid in targets:
                    try:
                        mark_reflection_rejected(rid)
                    except Exception as e:
                        print(f"⚠️ [Reflection Reject] DB update failed: {e}")
                    del pending_reflection_confirmations[rid]
                send_telegram_msg("❌ Ακυρώθηκε, δεν εφαρμόστηκε.")
                if pending_reflection_confirmations:
                    _send_pending_reflections_summary()
                return

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
                if output.strip():
                    send_telegram_msg_full(output, prefix="✅ Εκτελέστηκε:\n💻 ")
                else:
                    send_telegram_msg("✅ Εκτελέστηκε (χωρίς output).")
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
        # ── Context: shared mixed history από τη SQLite ────────────
        now_ts = datetime.now().strftime("%H:%M")
        context_msgs = _load_shared_context_messages("telegram")
        current_msg  = HumanMessage(content=f"[{now_ts}] {clean_user_text}")
        # ── Ροή μέσω LangGraph ───────────────────────────────────
        import tools.system as _ts; _ts._CURRENT_CHANNEL = "telegram"
        from memory.execution_trace import ExecutionTrace
        _trace = ExecutionTrace(channel="telegram", user_message=clean_user_text)
        tool_result_fallbacks = []
        for event in graph.stream({"messages": context_msgs + [current_msg], "channel": "telegram"}, {"recursion_limit": 50}):
            _trace.process_event(event)
            for node, data in event.items():
                if data is None:
                    continue
                if node == "tools":
                    for msg in data.get("messages", []):
                        if getattr(msg, "type", "") == "tool":
                            tool_content = clean_message(getattr(msg, "content", "")).strip()
                            if tool_content:
                                tool_result_fallbacks.append(tool_content)
                if node not in ["supervisor", "tools"]:
                    handling_agent = node
                    msgs = data.get("messages", [])
                    if msgs and hasattr(msgs[-1], "content"):
                        last_msg = msgs[-1]
                        # [MASTRO-FIX]: Skip intermediate tool-call steps
                        if getattr(last_msg, "tool_calls", None):
                            continue
                        candidate = clean_message(last_msg.content).strip()
                        # Skip tool-call announcement strings (internal debug output)
                        if candidate and not candidate.startswith("[Κλήση Εργαλείου:"):
                            final_ai_response = candidate

        if not final_ai_response:
            final_ai_response = _tool_results_fallback_response(clean_user_text, tool_result_fallbacks)

        if not final_ai_response:
            # [MASTRO-FIX]: Fallback όταν ο agent δεν παρήγαγε κείμενο (π.χ. loop/recursion)
            send_telegram_msg("⚠️ Κάτι μπλόκαρε — δεν πήρα σαφή απάντηση. Ξαναστείλε μου.")
            return

        _trace.finalize(response=final_ai_response or None)
        _trace.save()
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
                        _mid = send_telegram_msg(final_ai_response)
                        _cache_bot_message(_mid, final_ai_response)

                # Στείλε το αρχείο στο Telegram ως document
                try:
                    from tools.telegram import send_telegram_document
                    import os as _os
                    _fname = _os.path.basename(file_path)
                    send_telegram_document(file_path, caption=f"📎 <b>{_fname}</b>")
                except Exception as _de:
                    print(f"❌ [Doc send error]: {_de}")
                    send_telegram_msg(f"📎 Αρχείο: <code>{file_path}</code>")
            else:
                # Κανονική Ροή (Χωρίς Έγγραφα)
                if is_voice_mode:
                    import asyncio
                    asyncio.run(send_telegram_voice(final_ai_response))
                else:
                    _mid = send_telegram_msg(final_ai_response)
                    _cache_bot_message(_mid, final_ai_response)
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
                if data is None:
                    continue
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
                send_telegram_msg_full(str(execution["result"]), prefix="✅ `" + tool_name + "` ολοκληρώθηκε:\n\n")
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


def _handle_message_reaction(reaction: dict) -> None:
    """
    Όταν ο Λάζαρος κάνει ❤️ react σε μήνυμα του Αστακού,
    αποθηκεύει το περιεχόμενο του μηνύματος στη long-term memory.
    """
    try:
        chat_id = str(reaction.get("chat", {}).get("id", ""))
        if chat_id != str(TELEGRAM_CHAT_ID):
            return

        # Μόνο νέα reactions (όχι αφαίρεση)
        new_reactions = reaction.get("new_reaction", [])
        emojis = [r.get("emoji", "") for r in new_reactions if r.get("type") == "emoji"]
        if "❤" not in emojis and "❤️" not in emojis:
            return

        # Βρες το περιεχόμενο του μηνύματος που έγινε react
        msg_id = reaction.get("message_id")
        bot_text = None

        # 1. Πρώτα ψάξε στο in-memory cache (exact match)
        with _bot_message_cache_lock:
            bot_text = _bot_message_cache.get(msg_id)

        # 2. Fallback: τελευταίο assistant μήνυμα από SQLite
        if not bot_text:
            try:
                from memory.conversation_history import load_messages
                recent = load_messages(channel="telegram", limit=20)
                for entry in reversed(recent):
                    if entry.get("role") in ("assistant", "ai", "bot"):
                        bot_text = entry.get("content", "")
                        break
            except Exception as e:
                print(f"⚠️ [Reaction]: history lookup failed: {e}")

        if not bot_text:
            send_telegram_msg("❤️ Έπιασα το react αλλά δεν βρήκα το μήνυμα στη μνήμη μου.")
            return

        # Αποθήκευσε στη long-term memory
        preview = bot_text[:80].replace("\n", " ")
        print(f"\033[92m[Reaction ❤️]: Αποθήκευση: {preview}...\033[0m")
        threading.Thread(
            target=_save_reaction_to_memory,
            args=(bot_text,),
            daemon=True
        ).start()

    except Exception as e:
        print(f"⚠️ [Reaction Handler]: {e}")


def _save_reaction_to_memory(text: str) -> None:
    """Background: αποθηκεύει το κείμενο στη ChromaDB και ειδοποιεί."""
    try:
        from tools.system import save_to_memory
        preview = text[:60].replace("\n", " ")
        result = save_to_memory.invoke({
            "fact": text,
            "entities": "Αστακός, απάντηση",
            "category": "saved_by_user",
        })
        send_telegram_msg(f"❤️ Αποθηκεύτηκε στη μνήμη μου:\n_\"{preview}…\"_")
    except Exception as e:
        print(f"⚠️ [Reaction Save]: {e}")


def run_polling():
    """Long-polling loop — διαβάζει updates από το Telegram API."""
    global voice_mode_enabled
    if not TELEGRAM_TOKEN:
        print("\033[91m[TelegramBot]: Λείπει το TELEGRAM_TOKEN!\033[0m")
        return

    if not TELEGRAM_CHAT_ID:
        print("\033[91m[TelegramBot]: Λείπει το TELEGRAM_CHAT_ID!\033[0m")
        return

    # ── Ορισμός εντολών στο Telegram menu (το "/" autocomplete) ──────────────
    _bot_commands = [
        {"command": "g",                "description": "Ελληνικά → Γεωργιανά (+ ήχος)"},
        {"command": "gr",               "description": "Γεωργιανά → Ελληνικά (μετάφραση σε Greek)"},
        {"command": "g_phrases",        "description": "Γρήγορες γεωργιανές φράσεις"},
        {"command": "nutrition",        "description": "Ανάλυση διατροφικής αξίας (στείλε φωτό)"},
        {"command": "receipt",          "description": "Ανάλυση απόδειξης (στείλε φωτό)"},
        {"command": "story",            "description": "Παραμύθι για τον Αλέξανδρο"},
        {"command": "voice",            "description": "Φωνητικές απαντήσεις ON/OFF"},
        {"command": "status",           "description": "Κατάσταση scheduler & jobs"},
        {"command": "doctor",           "description": "Health status Αστακού"},
        {"command": "mute",             "description": "Σίγαση proactive μηνυμάτων"},
        {"command": "pause",            "description": "Παύση υπενθυμίσεων"},
        {"command": "resume",           "description": "Επαναφορά όλων"},
        {"command": "end",              "description": "Τέλος session & περίληψη"},
        {"command": "help",             "description": "Λίστα εντολών"},
    ]
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/setMyCommands",
            json={"commands": _bot_commands},
            timeout=10,
        )
        print("\033[92m[TelegramBot]: Bot commands menu ενημερώθηκε ✓\033[0m")
    except Exception as _e:
        print(f"\033[93m[TelegramBot]: setMyCommands απέτυχε: {_e}\033[0m")

    offset = 0
    print(f"\033[92m[TelegramBot]: Polling ξεκίνησε (allowed chat: {TELEGRAM_CHAT_ID})\033[0m")

    while not shutdown_event.is_set():
        try:
            resp = requests.get(
                f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates",
                params={"offset": offset, "timeout": 30, "allowed_updates": '["message","callback_query","message_reaction","edited_message"]'},
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

                # ── ❤️ Reaction → save bot message to memory ──────────
                reaction = update.get("message_reaction")
                if reaction:
                    _handle_message_reaction(reaction)
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

                if not cmd.startswith("/") and _consume_pending_georgian():
                    _send_georgian_translation(user_text)
                    continue
                if not cmd.startswith("/") and _consume_pending_sofia():
                    _send_georgian_translation(user_text, force_src="ka")
                    continue
                if cmd.startswith("/") and cmd not in ("/georgian", "/geo", "/g", "/georgian_phrases", "/gr", "/greek"):
                    _clear_pending_georgian()
                    _clear_pending_sofia()

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
                        "🦞 <b>Αστακός — Εντολές</b>\n\n"
                        "<b>Καθημερινά</b>\n"
                        "<code>/nutrition</code> — Ανάλυση προϊόντος (στείλε φωτό πρώτα)\n"
                        "<code>/receipt</code> — Ανάλυση απόδειξης (στείλε φωτό πρώτα)\n"
                        "<code>/g κείμενο</code> — Μετάφραση + ήχος Ελληνικά→Γεωργιανά\n"
                        "<code>/gr κείμενο</code> — Γεωργιανά→Ελληνικά (translate to Greek)\n"
                        "<code>/g phrases</code> — Γρήγορες γεωργιανές φράσεις\n"
                        "<code>/story θέμα</code> — Παραμύθι για Αλέξανδρο + εικόνες\n\n"
                        "<b>Έλεγχος</b>\n"
                        "<code>/doctor</code> — Health status Αστακού\n"
                        "<code>/status</code> — Scheduler & ενεργά jobs\n"
                        f"<code>/voice</code> — Φωνητικές απαντήσεις ON/OFF (τώρα: {voice_status})\n"
                        "<code>/help</code> — Λίστα εντολών\n\n"
                        "<b>Ησυχία / session</b>\n"
                        "<code>/mute</code> — Σίγαση proactive μηνυμάτων\n"
                        "<code>/pause</code> — Παύση υπενθυμίσεων\n"
                        "<code>/sleep 8</code> — Ησυχία για Χ ώρες\n"
                        "<code>/resume</code> — Επαναφορά όλων\n"
                        "<code>/end</code> — Τέλος session & περίληψη\n\n"
                        "<b>Προχωρημένα</b>\n"
                        "<code>/confirm εντολή</code> — Εκτέλεση με επιβεβαίωση\n"
                        "<code>/plan στόχος</code> — Multi-step εκτέλεση"
                    )
                    continue

                if cmd == "/doctor":
                    try:
                        from tools.system import system_doctor
                        send_telegram_msg(system_doctor(days=1))
                    except Exception as e:
                        send_telegram_msg(f"❌ Σφάλμα doctor: {e}")
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

                if cmd in ("/georgian", "/geo", "/g", "/georgian_phrases"):
                    from tools.georgian import phrases_message
                    rest = user_text[len(cmd):].strip()

                    # /georgian_phrases → γρήγορη λίστα
                    if cmd == "/georgian_phrases" or rest.lower() == "phrases":
                        send_telegram_msg(phrases_message())
                        continue

                    # /georgian χωρίς κείμενο → οδηγίες
                    if not rest:
                        _arm_pending_georgian()
                        send_telegram_msg(
                            "🇬🇪 Στείλε τώρα το κείμενο που θέλεις να μεταφράσω."
                        )
                        continue

                    _send_georgian_translation(rest)
                    continue

                if cmd in ("/gr", "/greek"):
                    rest = user_text[len(cmd):].strip()
                    if rest:
                        # Άμεση μετάφραση ka→el
                        _send_georgian_translation(rest, force_src="ka")
                    else:
                        # Pending mode: επόμενο μήνυμα θεωρείται Γεωργιανό
                        _arm_pending_sofia()
                        send_telegram_msg("🇬🇪 Στείλε το γεωργιανό κείμενο για μετάφραση σε Ελληνικά.")
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
        from memory.context_builder import build_memory_context

        context = build_memory_context(
            "",
            channel="telegram",
            recent_limit=limit,
            semantic_k=0,
        )
        return "\n".join(context.recent_lines)
    except Exception as exc:
        print(f"\033[93m[ProactiveContext]: failed to load recent context: {exc}\033[0m")
        return ""


def _build_proactive_memory_context(event_name: str) -> str:
    """Build richer context for routine nudges, including recent cancellation clues."""
    try:
        from memory.context_builder import build_memory_context

        recall_query = (
            f"θυμάσαι {event_name}; πρόσφατο context για το αν ισχύει ακόμα η ρουτίνα. "
            "Αλέξανδρος κατασκήνωση λείπει γύρισε πάρκο κοιμήθηκε βάρδια Σοφία "
            "ήδη έγινε ακυρώθηκε"
        )
        context = build_memory_context(
            recall_query,
            channel="telegram",
            recent_limit=18,
            temporal_limit=12,
            semantic_k=6,
        )
        return context.render()
    except Exception as exc:
        print(f"\033[93m[ProactiveContext]: rich context builder failed: {exc}\033[0m")
        return ""


def _clear_routine_pending_confirmation(routine_id: int) -> None:
    """Best-effort cleanup for stale pending confirmations on context-driven skips."""
    pending_routine_confirmations.pop(routine_id, None)
    try:
        from memory.routine_db import remove_pending_confirmation

        remove_pending_confirmation(routine_id)
    except Exception as exc:
        print(f"\033[93m[RoutinePendingCleanup]: #{routine_id} failed: {exc}\033[0m")


def _apply_context_mute(routine_id: int, event_name: str, memory_context: str) -> str | None:
    """Infer mute window from context and pre-classify sentimental family routines."""
    if not memory_context:
        return None
    try:
        until = _infer_muted_until(event_name, memory_context)
    except Exception as exc:
        print(f"\033[93m[RoutineMute]: #{routine_id} infer failed: {exc}\033[0m")
        return None
    if not until:
        return None

    try:
        from memory.routine_db import (
            get_sentimental_info,
            set_routine_muted_until,
            set_routine_sentimental,
        )

        info = get_sentimental_info(routine_id)
        if info.get("sentimental") is None:
            is_sentimental = _infer_sentimental(event_name, memory_context)
            set_routine_sentimental(routine_id, is_sentimental)

        set_routine_muted_until(routine_id, until)
        return until
    except Exception as exc:
        print(f"\033[93m[RoutineMute]: #{routine_id} apply failed: {exc}\033[0m")
        return None


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

    memory_context = _build_proactive_memory_context(event_name)
    memory_block = f"\n\n{memory_context}\n" if memory_context else ""

    prompt = (
        f"{context}\n\n"
        f"{memory_block}"
        "Είσαι ο Αστακός, ο προσωπικός AI του Λάζαρου (42 χρονών, μάστορας, "
        "γιος Αλέξανδρος 6 ετών, κόρη Μαρία 15 ετών, γυναίκα Σοφία). "
        "Στείλε ΕΝΑ φυσικό μήνυμα κολλημένο στην καθημερινότητα — με χιούμορ, σαν παλιός φίλος.\n"
        "Πριν γράψεις, διάβασε το πρόσφατο ιστορικό. Αν υπάρχει ζωντανό context "
        "(π.χ. παίζουν επιτραπέζιο, είναι σε ποδόσφαιρο, δουλεύει, είναι έξω), "
        "δέσε την ατάκα φυσικά με αυτό. Αν το ιστορικό δεν σχετίζεται, αγνόησέ το.\n"
        "ΚΡΙΣΙΜΟ: Το μήνυμα ΠΡΕΠΕΙ να υπηρετεί τη συγκεκριμένη ρουτίνα/event. "
        "Μπορείς και πρέπει να το δένεις με το πρόσφατο ιστορικό όταν ταιριάζει "
        "(π.χ. ποδόσφαιρο, επιτραπέζιο, δουλειά, χαλάρωση με τον Αλέξανδρο), "
        "αλλά μην αλλάζεις αποστολή και μην κάνεις status για άσχετα tools/debug/Google Fit.\n"
        "Αν το event αφορά σύνταξη/αποστολή μηνύματος στη Σοφία, φτιάξε ατάκα για τη Σοφία "
        "χρησιμοποιώντας φυσικά το πρόσφατο context, και ρώτα διακριτικά αν θέλει να ετοιμάσετε/στείλετε το μήνυμα.\n"
        "Χρησιμοποίησε τις ώρες στα πρόσφατα μηνύματα: μην παρουσιάζεις σαν τελειωμένο "
        "κάτι που ξεκίνησε πριν λίγα λεπτά ή δεν δηλώθηκε ότι ολοκληρώθηκε. "
        "Αν ο Λάζαρος είπε μόλις 'μαγειρεύω', 'παίζουμε', 'φεύγουμε' ή 'πάμε', "
        "μίλα σαν να είναι σε εξέλιξη, όχι σαν να έγινε ήδη.\n"
        "Αν το context λέει ότι ο Αλέξανδρος λείπει/είναι κατασκήνωση, ΜΗΝ προτείνεις "
        "δραστηριότητα μαζί του (πάρκο, παιχνίδι, ύπνο). Χρησιμοποίησε [CONTEXT_SKIP] "
        "ή στείλε μόνο τρυφερό σχόλιο για την απουσία αν ταιριάζει.\n"
        "ΑΠΑΓΟΡΕΥΕΤΑΙ: 'δεν είναι η ώρα για', 'υπενθύμιση', 'θυμίζω', το event name κυριολεκτικά.\n"
        "ΣΗΜΑΝΤΙΚΟ — ΕΠΙΛΕΞΕ ΑΚΡΙΒΩΣ ΕΝΑ ΑΠΟ ΤΑ ΤΡΙΑ:\n"
        "1. ΚΑΝΟΝΙΚΟ ΜΗΝΥΜΑ: 1-2 προτάσεις χωρίς tag.\n"
        "2. [CONTEXT_SKIP]: ΑΝ η ρουτίνα ακυρώνεται λόγω context "
        "(π.χ. παιδί κατασκήνωση, χρήστης σε βάρδια) "
        "— ξεκίνα ΤΟ ΜΗΝΥΜΑ ΣΟΥ με [CONTEXT_SKIP] "
        "(στέλνεται μήνυμα, ΔΕΝ μαρκάρεται ως pending).\n"
        "3. [SILENT_SKIP]: ΑΝ η ρουτίνα είναι ΑΔΥΝΑΤΗ ή ΗΔΗ ΕΓΙΝΕ ξεκάθαρα "
        "(π.χ. ο χρήστης μόλις είπε 'πήγαμε πάρκο', 'κοιμήθηκε ο Αλέξανδρος') "
        "— γράψε ΜΟΝΟ [SILENT_SKIP] χωρίς τίποτε άλλο "
        "(κανένα μήνυμα δεν στέλνεται, μόνο ενημερώνεται το last_triggered).\n"
        "Παραδείγματα:\n"
        "- 'Μάστορα, ο μικρός θα σε κυνηγάει αν δεν τον πας για ύπνο σε λίγο 😄'\n"
        "- '[CONTEXT_SKIP] Κανονικά τέτοια ώρα θα πάλευες να κοιμίσεις τον μικρό, αλλά απόψε σε βλέπω να ξεραίνεσαι εσύ!'\n"
        "- '[SILENT_SKIP]'  ← μόνο αυτό, όταν το event δηλώθηκε ότι ήδη έγινε\n"
        "Ελληνικά."
    )

    try:
        response = safe_llm_invoke(llm, [HumanMessage(content=prompt)])
        content = response.content
        if isinstance(content, list):
            content = "".join(
                part.get("text", "") if isinstance(part, dict) else str(part)
                for part in content
            )
        return content.strip()
    except Exception as e:
        print(f"[Proactive Craft Error]: {e}")
        return f"Μάστορα, ώρα για '{event_name}' (μου κόλλησε λίγο ο εγκέφαλος 😅)"


def _infer_muted_until(event_name: str, memory_context: str) -> str | None:
    """
    Μικρό LLM call: βάσει context, επιστρέφει μέχρι πότε να σιγαστεί η ρουτίνα.
    Επιστρέφει YYYY-MM-DD string ή None αν δεν μπορεί να εκτιμήσει.
    Καλείται ΜΟΝΟ αφού έχει εντοπιστεί [SILENT_SKIP] για πρώτη φορά.
    """
    from langchain_core.messages import HumanMessage
    from core.brain import llm
    from datetime import date

    today = date.today().isoformat()
    prompt = (
        f"Σήμερα είναι {today}.\n"
        f"Η ρουτίνα '{event_name}' κρίθηκε ότι δεν ισχύει αυτή τη στιγμή λόγω context.\n\n"
        f"Context:\n{memory_context}\n\n"
        "Βάσει του context, μέχρι ποια ημερομηνία (YYYY-MM-DD) πρέπει να σιγαστεί αυτή η ρουτίνα; "
        "Αν μπορείς να εκτιμήσεις, απάντησε ΜΟΝΟ με την ημερομηνία σε μορφή YYYY-MM-DD. "
        "Αν δεν μπορείς να εκτιμήσεις, απάντησε ΜΟΝΟ με NULL. "
        "Καμία άλλη λέξη."
    )
    try:
        response = safe_llm_invoke(llm, [HumanMessage(content=prompt)])
        content = response.content
        if isinstance(content, list):
            content = "".join(
                p.get("text", "") if isinstance(p, dict) else str(p) for p in content
            )
        content = content.strip()
        if content.upper() == "NULL" or not content:
            return None
        # Validate format YYYY-MM-DD
        import re as _re
        if _re.match(r"^\d{4}-\d{2}-\d{2}$", content):
            # Ensure it's in the future
            if content > today:
                return content
        return None
    except Exception as e:
        print(f"[_infer_muted_until Error]: {e}")
        return None



def _infer_sentimental(event_name: str, memory_context: str) -> bool:
    """
    One-time LLM assessment: κρίνει αν η ρουτίνα έχει συναισθηματική αξία.
    Sentimental = αφορά παιδί, οικογένεια, κοινές εμπειρίες, συνήθειες με φορτίο.
    Καλείται μία φορά και αποθηκεύεται μόνιμα στο DB.
    """
    from langchain_core.messages import HumanMessage
    from core.brain import llm

    prompt = (
        f"Η ρουτίνα: '{event_name}'.\n\n"
        f"Context:\n{memory_context}\n\n"
        "Αυτή η ρουτίνα αφορά οικογένεια, παιδί, κοινές εμπειρίες ή έχει "
        "συναισθηματική αξία (π.χ. βόλτα με παιδί, παιχνίδι, ύπνος παιδιού); "
        "Απάντησε ΜΟΝΟ: YES ή NO."
    )
    try:
        response = safe_llm_invoke(llm, [HumanMessage(content=prompt)])
        content = response.content
        if isinstance(content, list):
            content = "".join(
                p.get("text", "") if isinstance(p, dict) else str(p) for p in content
            )
        return content.strip().upper().startswith("YES")
    except Exception as e:
        print(f"[_infer_sentimental Error]: {e}")
        return False


def _craft_sentimental_absent_msg(
    event_name: str, muted_from: str, muted_until: str, memory_context: str
) -> str:
    """
    Φτιάχνει συναισθηματικό μήνυμα για ρουτίνα που δεν μπορεί να γίνει τώρα.
    ΔΕΝ υπενθυμίζει την ρουτίνα — αναγνωρίζει με ζεστασιά/χιούμορ.
    """
    from langchain_core.messages import HumanMessage
    from core.brain import llm
    from datetime import date

    today = date.today().isoformat()
    prompt = (
        f"Σήμερα: {today}. Η ρουτίνα '{event_name}' δεν μπορεί να γίνει "
        f"από {muted_from} έως {muted_until}.\n\n"
        f"Context:\n{memory_context}\n\n"
        "Γράψε ΕΝΑ σύντομο μήνυμα (1-2 προτάσεις) που:\n"
        "- ΔΕΝ λέει 'θυμήσου να...' ή 'ώρα για...' — δεν υπενθυμίζει\n"
        "- Αναγνωρίζει συναισθηματικά (νοσταλγία, αντίστροφη μέτρηση, χιούμορ)\n"
        "- Είναι σαν μήνυμα από φίλο που ξέρει την κατάσταση\n"
        "Ελληνικά. Χωρίς tag. Χωρίς εισαγωγικά."
    )
    try:
        response = safe_llm_invoke(llm, [HumanMessage(content=prompt)])
        content = response.content
        if isinstance(content, list):
            content = "".join(
                p.get("text", "") if isinstance(p, dict) else str(p) for p in content
            )
        return content.strip()
    except Exception as e:
        print(f"[_craft_sentimental_absent_msg Error]: {e}")
        return ""


def _craft_deferred_msg(event_name: str, confidence: float, missed_minutes: int) -> str:

    """
    LLM φτιάχνει deferred follow-up: ξέρει ότι ήταν offline και η ώρα πέρασε.
    Αντί για reminder, ρωτάει/σχολιάζει αν έγινε το event — σαν φίλος που ήρθε αργά.
    Ίδιο full pipeline (memory context, personality) με το κανονικό proactive.
    """
    from langchain_core.messages import HumanMessage
    from core.brain import llm

    if confidence >= 0.8:
        certainty = f"Ο Λάζαρος κάνει σχεδόν πάντα '{event_name}' αυτή την ώρα."
    else:
        certainty = f"Συνήθως αυτή την ώρα ο Λάζαρος κάνει '{event_name}'."

    try:
        from memory.context_builder import build_memory_context
        memory_context = build_memory_context(
            event_name,
            channel="telegram",
            recent_limit=8,
            semantic_k=4,
        ).render()
    except Exception as exc:
        print(f"\033[93m[DeferredMsg]: context builder failed: {exc}\033[0m")
        memory_context = ""
    memory_block = f"\n\n{memory_context}\n" if memory_context else ""

    prompt = (
        f"{certainty}\n\n"
        f"Ο Αστακός ήταν offline/εκτός λειτουργίας και η ώρα της ρουτίνας πέρασε "
        f"πριν από {missed_minutes} λεπτά.\n"
        f"{memory_block}"
        "Είσαι ο Αστακός, ο προσωπικός AI του Λάζαρου (42 χρονών, μάστορας, "
        "γιος Αλέξανδρος 6 ετών, κόρη Μαρία 15 ετών, γυναίκα Σοφία). "
        "Δεν στέλνεις υπενθύμιση — η ώρα πέρασε. Στέλνεις φυσικό follow-up: "
        "ρωτάς/σχολιάζεις αν το event έγινε, πώς πήγε, κάτι ανάλογο. "
        "Σαν να ήρθες αργά και ρωτάς τι έγινε — χωρίς να εξηγείς γιατί έλειπες.\n"
        "Χρησιμοποίησε το πρόσφατο ιστορικό αν ταιριάζει φυσικά. "
        "Αν το context λέει ότι ο Αλέξανδρος λείπει/είναι κατασκήνωση, ΜΗΝ προτείνεις "
        "δραστηριότητα μαζί του (πάρκο, παιχνίδι, ύπνο). Χρησιμοποίησε [CONTEXT_SKIP] "
        "ή στείλε μόνο τρυφερό σχόλιο για την απουσία αν ταιριάζει. "
        "ΑΠΑΓΟΡΕΥΕΤΑΙ: 'υπενθύμιση', 'reminder', 'έχασα', 'δεν ήμουν', το event name κυριολεκτικά.\n"
        "ΣΗΜΑΝΤΙΚΟ — ΕΠΙΛΕΞΕ ΑΚΡΙΒΩΣ ΕΝΑ ΑΠΟ ΤΑ ΤΡΙΑ:\n"
        "1. ΚΑΝΟΝΙΚΟ ΜΗΝΥΜΑ: 1-2 προτάσεις χωρίς tag.\n"
        "2. [CONTEXT_SKIP]: ΑΝ η ρουτίνα ακυρώνεται λόγω context "
        "(π.χ. παιδί κατασκήνωση, χρήστης σε βάρδια) "
        "— ξεκίνα ΤΟ ΜΗΝΥΜΑ ΣΟΥ με [CONTEXT_SKIP] "
        "(στέλνεται μήνυμα, ΔΕΝ μαρκάρεται ως pending).\n"
        "3. [SILENT_SKIP]: ΑΝ η ρουτίνα είναι ΑΔΥΝΑΤΗ ή ΗΔΗ ΕΓΙΝΕ ξεκάθαρα "
        "(π.χ. ο χρήστης μόλις είπε 'πήγαμε πάρκο', 'κοιμήθηκε ο Αλέξανδρος') "
        "— γράψε ΜΟΝΟ [SILENT_SKIP] χωρίς τίποτε άλλο "
        "(κανένα μήνυμα δεν στέλνεται, μόνο ενημερώνεται το last_triggered).\n"
        "Παραδείγματα:\n"
        "- 'Μάστορα, ο μικρός θα σε κυνηγάει αν δεν τον πας για ύπνο σε λίγο 😄'\n"
        "- '[CONTEXT_SKIP] Κανονικά τέτοια ώρα θα πάλευες να κοιμίσεις τον μικρό, αλλά απόψε σε βλέπω να ξεραίνεσαι εσύ!'\n"
        "- '[SILENT_SKIP]'  ← μόνο αυτό, όταν το event δηλώθηκε ότι ήδη έγινε\n"
        "Ελληνικά."
    )

    try:
        response = safe_llm_invoke(llm, [HumanMessage(content=prompt)])
        content = response.content
        if isinstance(content, list):
            content = "".join(
                part.get("text", "") if isinstance(part, dict) else str(part)
                for part in content
            )
        return content.strip()
    except Exception as e:
        print(f"[Deferred Craft Error]: {e}")
        return "Ε, πήγε καλά; 😊"


def startup_check_missed_routines():
    """
    Εκτελείται ΜΙΑ φορά στην εκκίνηση (με μικρή καθυστέρηση αρχικοποίησης).
    Ψάχνει active ρουτίνες που έπρεπε να πυροδοτηθούν ενώ ο bot ήταν offline,
    εντός ROUTINE_MISS_GRACE_MINUTES, και στέλνει deferred follow-up με full memory context.
    """
    import sqlite3
    import time as _time
    from datetime import timedelta
    from config import BASE_DIR, ROUTINE_MISS_GRACE_MINUTES

    if is_quiet_hours() or is_proactive_muted():
        print("\033[90m[MissedRoutines]: Quiet hours / muted — skip startup check.\033[0m")
        return

    DB_PATH = os.path.join(BASE_DIR, "astakos_routines.db")
    if not os.path.exists(DB_PATH):
        return

    DAYS_MAP = {
        "Monday":    ["Monday", "Δευτέρα"],
        "Tuesday":   ["Tuesday", "Τρίτη"],
        "Wednesday": ["Wednesday", "Τετάρτη"],
        "Thursday":  ["Thursday", "Πέμπτη"],
        "Friday":    ["Friday", "Παρασκευή"],
        "Saturday":  ["Saturday", "Σάββατο"],
        "Sunday":    ["Sunday", "Κυριακή"],
    }

    try:
        now           = datetime.now()
        today_str     = now.strftime("%Y-%m-%d")
        now_str       = now.strftime("%H:%M")
        grace_start   = (now - timedelta(minutes=ROUTINE_MISS_GRACE_MINUTES)).strftime("%H:%M")
        day_en        = now.strftime("%A")
        possible_days = DAYS_MAP.get(day_en, [day_en])
        placeholders  = ",".join("?" * len(possible_days))

        conn   = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute(f"""
            SELECT id, event_name, confidence, time_str FROM routines
            WHERE (day_of_week IN ({placeholders}) OR day_of_week='Everyday' OR day_of_week='Καθημερινά')
              AND state='active'
              AND (last_triggered IS NULL OR last_triggered != ?)
              AND time_str <  ?
              AND time_str >= ?
        """, (*possible_days, today_str, now_str, grace_start))
        missed = cursor.fetchall()
        conn.close()

        if not missed:
            print("\033[90m[MissedRoutines]: Καμία χαμένη ρουτίνα εντός grace window.\033[0m")
            return

        print(f"\033[93m[MissedRoutines]: {len(missed)} χαμένη/ες ρουτίνα/ες — deferred follow-up.\033[0m")

        from memory.routine_db import get_routine_notify_info, mark_routine_notified, save_pending_confirmation

        for r_id, event_name, confidence, time_str in missed:
            # Cooldown check — αποφεύγουμε spam αν ειδοποιήθηκε πρόσφατα
            info = get_routine_notify_info(r_id)
            if is_duplicate_routine(r_id, info["cooldown_hours"]):
                print(f"\033[90m[MissedRoutines]: #{r_id} '{event_name}' — cooldown, skip.\033[0m")
                continue

            try:
                h, m       = map(int, time_str.split(":"))
                routine_dt = now.replace(hour=h, minute=m, second=0, microsecond=0)
                missed_min = max(1, int((now - routine_dt).total_seconds() / 60))
            except Exception:
                missed_min = ROUTINE_MISS_GRACE_MINUTES // 2

            msg = _craft_deferred_msg(event_name, confidence, missed_min)
            ctx = ""
            if msg.strip() == "[SILENT_SKIP]" or "[CONTEXT_SKIP]" in msg:
                try:
                    ctx = _build_proactive_memory_context(event_name)
                except Exception:
                    ctx = ""

            # Μάρκαρε ως triggered ώστε το κανονικό job να μην το ξαναστείλει σήμερα
            conn2   = sqlite3.connect(DB_PATH)
            cursor2 = conn2.cursor()
            cursor2.execute("UPDATE routines SET last_triggered=? WHERE id=?", (today_str, r_id))
            conn2.commit()
            conn2.close()

            if msg.strip() == "[SILENT_SKIP]":
                _clear_routine_pending_confirmation(r_id)
                muted_until = _apply_context_mute(r_id, event_name, ctx)
                log_event("routines", "silent_skip", routine_id=r_id, event=event_name,
                          deferred=True, muted_until=muted_until)
                bus.emit("routine_skipped_context", routine_id=r_id, event=event_name,
                         deferred=True, channel="telegram")
                print(f"\033[90m[MissedRoutines]: SILENT_SKIP '{event_name}' ({missed_min} λεπτά αργά)\033[0m")
                continue

            is_context_skip = "[CONTEXT_SKIP]" in msg
            if is_context_skip:
                msg = msg.replace("[CONTEXT_SKIP]", "").strip()

            send_telegram_msg(msg)

            if is_context_skip:
                _clear_routine_pending_confirmation(r_id)
                muted_until = _apply_context_mute(r_id, event_name, ctx)
                log_event("routines", "context_skip", routine_id=r_id, event=event_name,
                          deferred=True, missed_minutes=missed_min,
                          muted_until=muted_until, preview=msg[:160])
                bus.emit("routine_skipped_context", routine_id=r_id, event=event_name,
                         deferred=True, channel="telegram")
                print(f"\033[90m[MissedRoutines]: CONTEXT_SKIP '{event_name}' ({missed_min} λεπτά αργά) → '{msg[:80]}'\033[0m")
                continue

            mark_routine_notified(r_id)
            sent_at = datetime.now()
            pending_routine_confirmations[r_id] = {"event": event_name, "sent_at": sent_at}
            save_pending_confirmation(r_id, event_name, sent_at)
            log_event("routines", "deferred_followup",
                      routine_id=r_id, event=event_name,
                      missed_minutes=missed_min, preview=msg[:160])
            bus.emit("routine_triggered", routine_id=r_id, event=event_name,
                     confidence=confidence, deferred=True, channel="telegram")
            print(f"\033[92m[MissedRoutines]: ✅ Deferred '{event_name}' ({missed_min} λεπτά αργά) → '{msg[:80]}'\033[0m")

            if len(missed) > 1:
                _time.sleep(300)  # 5 λεπτά παύση — ώστε να απαντήσει στο πρώτο

    except Exception as e:
        print(f"\033[91m[MissedRoutines]: {e}\033[0m")


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

    if pending_routine_confirmations:
        from memory.routine_db import get_routine_muted_until, remove_pending_confirmation
        for rid in list(pending_routine_confirmations.keys()):
            try:
                muted_until = get_routine_muted_until(rid)
            except Exception:
                muted_until = None
            if muted_until:
                ev = pending_routine_confirmations[rid]["event"]
                del pending_routine_confirmations[rid]
                remove_pending_confirmation(rid)
                log_event("routines", "pending_cleared_muted", routine_id=rid, event=ev, muted_until=muted_until)
                print(f"\033[90m[RoutinePendingCleanup]: #{rid} '{ev}' cleared because muted until {muted_until}\033[0m")

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
                save_pending_confirmation, get_routine_muted_until,
            )
            due_routines = []
            for r_id, event_name, confidence in cursor.fetchall():
                # ── muted_until check ────────────────────────────────────
                muted_until = get_routine_muted_until(r_id)
                if muted_until:
                    cursor.execute("UPDATE routines SET last_triggered=? WHERE id=?", (today_str, r_id))
                    conn.commit()

                    # Όταν η ρουτίνα είναι ήδη muted, το proactive για αυτό το slot τελειώνει εδώ.
                    # ΔΕΝ στέλνουμε δεύτερο sentimental message από το polling loop· τα
                    # συναισθηματικά/contextual messages παράγονται μόνο στη στιγμή που
                    # ανιχνεύθηκε το context skip / mute, όχι ξανά σε κάθε επόμενο poll.
                    log_event("routines", "silent_skip", routine_id=r_id, event=event_name,
                              reason="muted_until", muted_until=muted_until)
                    print(f"\U0001f507 [job_check_routines]: #{r_id} '{event_name}' muted until {muted_until} — skipped")
                    continue
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

                if msg.strip() == "[SILENT_SKIP]":
                    # Πρώτη φορά SILENT_SKIP — εκτίμα muted_until για κάθε ρουτίνα
                    try:
                        ctx = _build_proactive_memory_context(names)
                    except Exception:
                        ctx = ""
                    for r_id, event_name, confidence in due_routines:
                        cursor.execute("UPDATE routines SET last_triggered=? WHERE id=?", (today_str, r_id))
                        log_event("routines", "silent_skip", routine_id=r_id, event=event_name, batch=True)
                        bus.emit("routine_skipped_context", routine_id=r_id, event=event_name, batch=True, channel="telegram")
                        _clear_routine_pending_confirmation(r_id)
                        _apply_context_mute(r_id, event_name, ctx)
                    conn.commit()
                else:
                    is_context_skip = False
                    if "[CONTEXT_SKIP]" in msg:
                        is_context_skip = True
                        msg = msg.replace("[CONTEXT_SKIP]", "").strip()

                    send_telegram_msg(msg)
                    sent_at = datetime.now()
                    context_skip_ctx = ""
                    if is_context_skip:
                        try:
                            context_skip_ctx = _build_proactive_memory_context(names)
                        except Exception:
                            context_skip_ctx = ""
                    for r_id, event_name, confidence in due_routines:
                        cursor.execute("UPDATE routines SET last_triggered=? WHERE id=?", (today_str, r_id))
                        if is_context_skip:
                            _clear_routine_pending_confirmation(r_id)
                            muted_until = _apply_context_mute(r_id, event_name, context_skip_ctx)
                            log_event("routines", "context_skip", routine_id=r_id, event=event_name,
                                      batch=True, muted_until=muted_until, preview=msg[:160])
                            bus.emit("routine_skipped_context", routine_id=r_id, event=event_name, batch=True, channel="telegram")
                        else:
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

                if msg.strip() == "[SILENT_SKIP]":
                    # Πρώτη φορά SILENT_SKIP — εκτίμα muted_until
                    try:
                        ctx = _build_proactive_memory_context(event_name)
                    except Exception:
                        ctx = ""
                    cursor.execute("UPDATE routines SET last_triggered=? WHERE id=?", (today_str, r_id))
                    conn.commit()
                    log_event("routines", "silent_skip", routine_id=r_id, event=event_name)
                    bus.emit("routine_skipped_context", routine_id=r_id, event=event_name, channel="telegram")
                    _clear_routine_pending_confirmation(r_id)
                    _apply_context_mute(r_id, event_name, ctx)
                else:
                    is_context_skip = False
                    if "[CONTEXT_SKIP]" in msg:
                        is_context_skip = True
                        msg = msg.replace("[CONTEXT_SKIP]", "").strip()

                    cursor.execute("UPDATE routines SET last_triggered=? WHERE id=?", (today_str, r_id))
                    conn.commit()

                    send_telegram_msg(msg)

                    if is_context_skip:
                        try:
                            context_skip_ctx = _build_proactive_memory_context(event_name)
                        except Exception:
                            context_skip_ctx = ""
                        _clear_routine_pending_confirmation(r_id)
                        muted_until = _apply_context_mute(r_id, event_name, context_skip_ctx)
                        log_event("routines", "context_skip", routine_id=r_id, event=event_name,
                                  muted_until=muted_until, preview=msg[:160])
                        # DO NOT mark as pending, just keep it active.
                        bus.emit("routine_skipped_context", routine_id=r_id, event=event_name, channel="telegram")
                    else:
                        mark_routine_notified(r_id)
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
        global pending_reflection_confirmations
        r_stats = run_reflection()
        for item in r_stats.get("pending_items", []):
            pending_reflection_confirmations[item["id"]] = item

        if pending_reflection_confirmations:
            _send_pending_reflections_summary()

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

def job_morning_calendar_briefing():
    """Πρωινό Google Calendar briefing — τρέχει μόνο 08:00–09:00, μία φορά."""
    now_hour = datetime.now().hour
    if now_hour != 8:
        return

    flag_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".calendar_briefing_sent")
    today_str = datetime.now().strftime("%Y-%m-%d")
    if os.path.exists(flag_file):
        with open(flag_file, "r") as f:
            if f.read().strip() == today_str:
                return

    try:
        from astakos_skills.gcalendar import google_calendar_tool

        today_events = google_calendar_tool.invoke({"action": "today"})
        week_events  = google_calendar_tool.invoke({"action": "week"})

        # Αν δεν υπάρχουν events σήμερα, στέλνουμε μόνο σύνοψη εβδομάδας
        if "Δεν υπάρχουν events" in today_events:
            msg = (
                f"🌅 *Καλημέρα Λάζαρε!*\n\n"
                f"📅 Σήμερα δεν έχεις τίποτα προγραμματισμένο.\n\n"
                f"*Επόμενες 7 μέρες:*\n{week_events}"
            )
        else:
            msg = (
                f"🌅 *Καλημέρα Λάζαρε!*\n\n"
                f"*Σημερινό πρόγραμμα:*\n{today_events}"
            )

        send_telegram_msg(msg)
        with open(flag_file, "w") as f:
            f.write(today_str)
        print("✅ [CalendarBriefing]: Πρωινό briefing στάλθηκε.")
    except Exception as e:
        print(f"⚠️ [CalendarBriefing]: {e}")


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

    def register(self, func, interval_seconds: int, name: str = None, verbose: bool = True):
        """
        verbose=True  → log start/complete κάθε run (για σπάνια/σημαντικά jobs)
        verbose=False → log μόνο errors (για frequent jobs: reminders, routines)
        """
        self._jobs.append({
            "name":          name or func.__name__,
            "func":          func,
            "interval":      interval_seconds,
            "last_run":      0,
            "last_duration": 0.0,
            "fail_count":    0,
            "last_error":    None,
            "disabled":      False,
            "verbose":       verbose,
        })
        print(f"\033[90m[Scheduler]: Registered '{name or func.__name__}' every {interval_seconds}s (verbose={verbose})\033[0m")

    def _write_snapshot(self):
        """Γράφει runtime_snapshot.json κάθε heartbeat — διαβάζεται από /debug/runtime."""
        try:
            from config import BASE_DIR
            import json as _json
            now = time.time()
            memory_context_path = os.path.join(BASE_DIR, "runtime_memory_context.json")
            try:
                with open(memory_context_path, "r", encoding="utf-8") as f:
                    memory_context_debug = _json.load(f)
            except Exception:
                memory_context_debug = {}
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
                "memory_context":        memory_context_debug,
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
                if job.get("verbose", True):
                    log_event(job["name"], "start")
                try:
                    job["func"]()
                    job["fail_count"] = 0
                    job["last_error"] = None
                    if job.get("verbose", True):
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
    from services.reflection_engine import load_pending_reflections
    pending_routine_confirmations.update(load_pending_confirmations())
    pending_reflection_confirmations.update(load_pending_reflections())
    if pending_routine_confirmations:
        print(f"\033[93m[Recovery]: \u03a6\u03bf\u03c1\u03c4\u03ce\u03b8\u03b7\u03ba\u03b1\u03bd {len(pending_routine_confirmations)} pending confirmations.\033[0m")
    if pending_reflection_confirmations:
        print(f"\033[93m[Recovery]: Loaded {len(pending_reflection_confirmations)} pending reflections.\033[0m")

    astakos_scheduler = AstakosScheduler()
    astakos_scheduler.register(job_check_reminders, interval_seconds=20,    name="reminders",   verbose=False)
    astakos_scheduler.register(job_check_routines,  interval_seconds=60,    name="routines",    verbose=False)
    astakos_scheduler.register(job_proactive_scan,  interval_seconds=43200, name="proactive",   verbose=True)
    astakos_scheduler.register(job_analytics_engine, interval_seconds=3600, name="analytics",   verbose=True)
    astakos_scheduler.register(job_morning_fit_briefing,       interval_seconds=3600, name="fit_briefing",      verbose=True)
    astakos_scheduler.register(job_morning_calendar_briefing,  interval_seconds=3600, name="cal_briefing",      verbose=True)
    astakos_scheduler.register(job_goal_followup,              interval_seconds=3600, name="goal_followup",     verbose=True)
    threading.Thread(target=astakos_scheduler.run, daemon=True).start()

    # Startup check για χαμένες ρουτίνες (10s καθυστέρηση για πλήρη αρχικοποίηση)
    def _delayed_missed_check():
        import time as _t
        _t.sleep(10)
        startup_check_missed_routines()
    threading.Thread(target=_delayed_missed_check, daemon=True).start()

    # Stale working memory cleanup (hard restart recovery)
    startup_stale_cleanup(channel="telegram")


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
        # Graceful ChromaDB shutdown — περίμενε να τελειώσει τυχόν write
        try:
            from memory.vector_store import vector_lock
            acquired = vector_lock.acquire(timeout=3)
            if acquired:
                vector_lock.release()
        except Exception:
            pass
        try:
            handle_end_session(TELEGRAM_CHAT_ID)
        except Exception:
            pass
        print('[TelegramBot]: Τερματίστηκε.')
