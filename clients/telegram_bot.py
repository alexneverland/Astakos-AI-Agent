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

from langchain_core.messages import HumanMessage, AIMessage

from config import TELEGRAM_TOKEN, TELEGRAM_CHAT_ID, PHOTOS_DIR, PHOTOS_INDEX_FILE
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
# Scheduler reference (set in __main__, used by /status command)
astakos_scheduler = None

# ── Rate Limiting ─────────────────────────────────────────────
QUIET_HOURS          = (23, 8)   # 23:00 → 08:00 χωρίς proactive
MAX_PROACTIVE_PER_HOUR = 3       # max proactive μηνύματα/ώρα

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

        audio_part = {
            "inline_data": {
                "mime_type": "audio/ogg",
                "data": audio_data
            }
        }
        
        prompt = "Άκουσε αυτό το μήνυμα και απάντησε σύντομα και μαστορικά."
        response = safe_gemini_call([prompt, audio_part])
        ai_reply = response.text if response and response.text else "Δεν έβγαλα άκρη."

        print(f"\033[92m[Voice AI]: {ai_reply}\033[0m")
        # Στέλνουμε το flag [ΦΩΝΗΤΙΚΟ] για να ξέρει η handle_message να απαντήσει με ήχο
        handle_message(f"[ΦΩΝΗΤΙΚΟ]: {ai_reply}", chat_id)

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
        _run_session_summary()
        
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
    [MASTRO-PARITY]: Στέλνει τα PIXELS στο LLM για ανάλυση και μετατρέπει 
    το αποτέλεσμα σε ασφαλές κείμενο για το Telegram.
    """
    try:
        import base64
        from langchain_core.messages import HumanMessage
        from core.brain import llm  # Χρησιμοποιούμε τον "βαρύ" εγκέφαλο για σιγουριά
        from core.agents import clean_message  # Προστασία από list errors

        # 1. Λήψη αρχείου από Telegram
        best_photo = max(photo_list, key=lambda p: p.get("file_size", 0))
        file_id = best_photo["file_id"]
        file_resp = requests.get(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getFile", params={"file_id": file_id}).json()
        file_path_remote = file_resp["result"]["file_path"]
        img_data = requests.get(f"https://api.telegram.org/file/bot{TELEGRAM_TOKEN}/{file_path_remote}").content

        # 2. Αποθήκευση τοπικά
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"photo_{timestamp}.jpg"
        local_path = os.path.join(PHOTOS_DIR, filename)

        with open(local_path, "wb") as f:
            f.write(img_data)
        print(f"\033[92m[Photo]: Κατέβηκε επιτυχώς: {filename}\033[0m")
        
        # 3. Mastro-Fix: Σωστή φόρτωση των pixels στο Vision LLM
        img_b64 = base64.b64encode(img_data).decode("utf-8")
        vision_prompt = f"Ανάλυσε τι δείχνει η φωτογραφία. Το σχόλιο του χρήστη είναι: '{caption or 'Κανένα σχόλιο'}'. Απάντησε σε 2-3 προτάσεις στα Ελληνικά."
        
        # Φτιάχνουμε το "Multimodal" πακέτο
        vision_msg = HumanMessage(content=[
            {"type": "text", "text": vision_prompt},
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"}}
        ])
        
        print(f"\033[94m[Vision]: Ξεκινάει η οπτική ανάλυση...\033[0m")
        analysis_response = llm.invoke([vision_msg])
        memory_analysis = clean_message(analysis_response.content)

        # 4. Σύνθεση του Μηνύματος (Έτοιμο για τον Agent)
        user_log_msg = (
            f"[USER_UPLOADED_FILE]: {filename}\n"
            f"[FILE PATH]: {local_path}\n"
            f"[ΟΠΤΙΚΗ ΑΝΑΛΥΣΗ]: {memory_analysis}\n"
            f"Σχόλιο: {caption if caption else 'Δες τη φωτογραφία.'}"
        )

        print(f"\033[94m[Telegram->Graph]: {user_log_msg}\033[0m")

# 5. Τροφοδοσία του LangGraph
        for event in graph.stream({"messages": [HumanMessage(content=user_log_msg)]}):
            for node_name, output in event.items():
                if "messages" in output:
                    last_msg = output["messages"][-1]
                    safe_text = clean_message(last_msg.content)
                    if safe_text:                                      # ← check στο καθαρό string
                        import re
                        
                        # --- MASTRO INTERCEPTOR ΓΙΑ TELEGRAM ---
                        file_match = re.search(r"\[CREATED_FILE:\s*(.*?)\]", safe_text)
                        if file_match:
                            file_path = file_match.group(1).strip()
                            # Καθαρίζουμε την ταμπέλα από το κείμενο για να μη φαίνεται άσχημα
                            safe_text = re.sub(r"\[CREATED_FILE:\s*(.*?)\]", "", safe_text).strip()
                            
                            # Στέλνουμε το κείμενο (π.χ. "Έτοιμο το έγγραφο!")
                            if safe_text:
                                send_telegram_msg(safe_text)
                            
                            # ΣΤΕΛΝΟΥΜΕ ΤΟ ΙΔΙΟ ΤΟ ΑΡΧΕΙΟ ΣΤΟ ΚΙΝΗΤΟ
                            send_telegram_document(file_path)
                        else:
                            # Κανονική αποστολή αν δεν υπάρχει αρχείο
                            if safe_text:
                                send_telegram_msg(safe_text)

    except Exception as e:
        import traceback
        print(f"❌ Telegram Photo Error: {e}")
        send_telegram_msg(f"Μάστορα, σκάλωσε η φωτό. Έλεγξε την κονσόλα. Σφάλμα: {e}")
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
# ────────────────────────────────────────────────────────────────
# MESSAGE HANDLER
# ────────────────────────────────────────────────────────────────

def handle_message(user_text: str, chat_id: str):
    """Στέλνει το μήνυμα στον Αστακό και απαντάει (Κείμενο ή Ήχο)."""
    global last_interaction_time
    from tools.telegram import send_telegram_voice, send_telegram_msg
    import re

    # 1. Ελέγχουμε αν ζητήθηκε φωνή (από ηχητικό ή /voice)
    is_voice_mode = "[ΦΩΝΗΤΙΚΟ]" in user_text or "[VOICE_MESSAGE]" in user_text or user_text.lower().startswith("/voice")
    
    # 2. Καθαρίζουμε τα tags πριν πάνε στον εγκέφαλο
    clean_user_text = user_text.replace("/voice", "").replace("[ΦΩΝΗΤΙΚΟ]:", "").replace("[VOICE_MESSAGE]:", "").strip()
    if not clean_user_text: 
        clean_user_text = "Γεια σου Αστακέ"
    # ── ROUTINE FEEDBACK LOOP ──
    if pending_routine_confirmations:
        text_check = clean_user_text.lower()
        # Βγάζουμε τα σημεία στίξης και κόβουμε την πρόταση σε λίστα λέξεων
        text_words = text_check.replace(",", "").replace(".", "").replace("!", "").split()
        
        yes_words = ["ναι", "yes", "οκ", "ok", "ισχύει", "ισχυει", "σωστά", "σωστα"]
        no_words  = ["όχι", "οχι", "no", "σταμάτα", "σταματα", "διέγραψε", "διεγραψε", "βγάλτο", "βγαλτο"]

        if any(w in text_words for w in yes_words):
            from memory.routine_db import confirm_routine, mark_routine_responded, clear_pending_confirmations
            for rid in list(pending_routine_confirmations.keys()):
                confirm_routine(rid)
                mark_routine_responded(rid)
                from memory.event_log import log_event
                log_event("routines", "confirmed", routine_id=rid, event=pending_routine_confirmations[rid])
                print(f"✅ [Routine Confirmed]: {pending_routine_confirmations[rid]}")
            pending_routine_confirmations.clear()
            clear_pending_confirmations()
        elif any(w in text_check for w in no_words):
            from memory.routine_db import decay_routine, clear_pending_confirmations
            for rid in list(pending_routine_confirmations.keys()):
                decay_routine(rid)
                from memory.event_log import log_event
                log_event("routines", "dismissed", routine_id=rid, event=pending_routine_confirmations[rid])
                print(f"📉 [Routine Dismissed]: {pending_routine_confirmations[rid]}")
            pending_routine_confirmations.clear()
            clear_pending_confirmations()
    # ── SAFE EXECUTOR CONFIRMATION LOOP ──────────────────────────
    global pending_exec_command
    if pending_exec_command:
        text_check = clean_user_text.lower().strip()
        if any(w in text_check for w in ["ναι", "yes", "ok", "οκ"]):
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
        elif any(w in text_check for w in ["όχι", "οχι", "no", "cancel"]):
            pending_exec_command = None
            send_telegram_msg("❌ Ακυρώθηκε.")
            return

    with memory_lock:
        last_interaction_time = time.time()

    final_ai_response = ""
    handling_agent = "Chat_Agent"

    try:
        # Ροή μέσω LangGraph
        for event in graph.stream({"messages": [HumanMessage(content=clean_user_text)]}):
            for node, data in event.items():
                if node not in ["supervisor", "tools"]:
                    handling_agent = node
                    msgs = data.get("messages", [])
                    if msgs and hasattr(msgs[-1], "content"):
                        candidate = clean_message(msgs[-1].content).strip()
                        if candidate:
                            final_ai_response = candidate

        if final_ai_response:
            # --- MASTRO INTERCEPTOR ΓΙΑ ΕΓΓΡΑΦΑ ---
            file_match = re.search(r"\[CREATED_FILE:\s*(.*?)\]", final_ai_response)
            if file_match:
                file_path = file_match.group(1).strip()
                final_ai_response = re.sub(r"\[CREATED_FILE:\s*(.*?)\]", "", final_ai_response).strip()
                
                if final_ai_response:
                    if is_voice_mode:
                        send_telegram_voice(final_ai_response) # [FIX]: Κάνει TTS εσωτερικά το εργαλείο σου!
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
                    send_telegram_voice(final_ai_response) # [FIX]: Μόνο ένα όρισμα!
                else:
                    send_telegram_msg(final_ai_response) # [FIX]: Μόνο ένα όρισμα!

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
            enqueue_task(trigger_memory_sifter,             user_text, final_ai_response, handling_agent)
            enqueue_task(log_exchange,                       user_text, final_ai_response, handling_agent)
            enqueue_task(update_capabilities_from_exchange, user_text, final_ai_response, handling_agent)

    except Exception as e:
        import traceback
        traceback.print_exc()
        # [FIX]: ΕΔΩ ΗΤΑΝ ΤΟ ΛΑΘΟΣ - Αφαιρέθηκε το chat_id
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

    print(f"\033[94m[Location]: {lat}, {lon}\033[0m")

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

def run_polling():
    """Long-polling loop — διαβάζει updates από το Telegram API."""
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
                if cmd == "/status":
                    if astakos_scheduler:
                        send_telegram_msg(astakos_scheduler.status())
                    else:
                        send_telegram_msg("⚠️ Scheduler δεν έχει εκκινήσει ακόμα.")
                    continue

                if user_text.lower() == "/end":
                    print(f"\033[94m[Telegram]: Εντολή τερματισμού συνεδρίας από Λάζαρο.\033[0m")
                    threading.Thread(
                        target=handle_end_session,
                        args=(chat_id,),
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
                msg   = f"🧠 **Proactive:** Μάστορα, έχεις {len(due_routines)} ρουτίνες σε ~30': {names}. Όλα έτοιμα;"
                send_telegram_msg(msg)
                sent_at = datetime.now()
                for r_id, event_name, confidence in due_routines:
                    cursor.execute("UPDATE routines SET last_triggered=? WHERE id=?", (today_str, r_id))
                    mark_routine_notified(r_id)
                    log_event("routines", "triggered", routine_id=r_id,
                              event=event_name, confidence=confidence, batch=len(due_routines))
                    pending_routine_confirmations[r_id] = {"event": event_name, "sent_at": sent_at}
                    save_pending_confirmation(r_id, event_name, sent_at)
                conn.commit()
            else:
                # Μία ρουτίνα → εξατομικευμένο μήνυμα
                r_id, event_name, confidence = due_routines[0]
                if confidence >= 0.8:
                    msg = f"🧠 **Proactive:** Μάστορα, πλησιάζει η ώρα για '{event_name}' (σε 30'). Όλα έτοιμα;"
                elif confidence >= 0.5:
                    msg = f"🧠 **Proactive:** Συνήθως τέτοια ώρα έχεις '{event_name}'. Ισχύει και σήμερα;"
                else:
                    msg = f"🧠 **Proactive:** Παλιά είχαμε '{event_name}' τέτοια ώρα, να το βγάλω αν δεν παίζει πια;"
                cursor.execute("UPDATE routines SET last_triggered=? WHERE id=?", (today_str, r_id))
                conn.commit()
                mark_routine_notified(r_id)
                send_telegram_msg(msg)
                log_event("routines", "triggered", routine_id=r_id,
                          event=event_name, confidence=confidence)
                sent_at = datetime.now()
                pending_routine_confirmations[r_id] = {"event": event_name, "sent_at": sent_at}
                save_pending_confirmation(r_id, event_name, sent_at)

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
    threading.Thread(target=astakos_scheduler.run, daemon=True).start()

    print("\u2501" * 50)
    print("  \U0001f99e  \u0391\u03c3\u03c4\u03b1\u03ba\u03cc\u03c2 Telegram Bot \u2014 \u0395\u03ba\u03ba\u03af\u03bd\u03b7\u03c3\u03b7")
    print("\u2501" * 50)
    send_telegram_msg("\U0001f99e \u0391\u03c3\u03c4\u03b1\u03ba\u03cc\u03c2 Bot: \u039e\u03b5\u03ba\u03af\u03bd\u03b1\u03c3\u03b1! \u03a0\u03ce\u03c2 \u03bc\u03c0\u03bf\u03c1\u03ce \u03bd\u03b1 \u03b2\u03bf\u03b7\u03b8\u03ae\u03c3\u03c9, \u039c\u03ac\u03c3\u03c4\u03bf\u03c1\u03b7;")

    try:
        run_polling()
    except KeyboardInterrupt:
        _handle_exit()
    finally:
        shutdown_event.set()
        try:
            _run_session_summary()
        except Exception:
            pass
        print("[TelegramBot]: \u03a4\u03b5\u03c1\u03bc\u03b1\u03c4\u03af\u03c3\u03c4\u03b7\u03ba\u03b5.")
