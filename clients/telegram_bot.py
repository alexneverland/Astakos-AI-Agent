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
# Pending routine confirmations: {routine_id: event_name}
pending_routine_confirmations = {}
def enqueue_task(func, *args):
    astakos_queue.put((func, args))


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
        
        prompt = "Άκουσε αυτό το μήνυμα και απάντησε σύντομα και μάστορικα."
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
    if not chat_id: chat_id = ALLOWED_CHAT_ID
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
            from memory.routine_db import confirm_routine
            for rid in list(pending_routine_confirmations.keys()):
                confirm_routine(rid)
                print(f"✅ [Routine Confirmed]: {pending_routine_confirmations[rid]}")
            pending_routine_confirmations.clear()
        elif any(w in text_check for w in no_words):
            from memory.routine_db import decay_routine
            for rid in list(pending_routine_confirmations.keys()):
                decay_routine(rid)
                print(f"📉 [Routine Decayed]: {pending_routine_confirmations[rid]}")
            pending_routine_confirmations.clear()
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
def handle_location(msg):
    """Πιάνει το στίγμα και το γράφει στο last_location.json."""
    from config import GPS_STORAGE_FILE
    import json
    import time
    
    if "location" in msg:
        lat = msg["location"]["latitude"]
        lon = msg["location"]["longitude"]
        data = {
            "lat": lat,
            "lon": lon,
            "timestamp": time.time()
        }
        try:
            with open(GPS_STORAGE_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f)
            print(f"📍 [GPS]: Το στίγμα ενημερώθηκε: {lat}, {lon}")
        except Exception as e:
            print(f"❌ Σφάλμα GPS: {e}")

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
                    threading.Thread(
                        target=handle_location,
                        args=(msg,), 
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

                # --- [MASTRO-COMMANDS]: Έλεγχος για /end ---
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
# REMINDER WORKER (standalone για τον bot)
# ────────────────────────────────────────────────────────────────

def reminder_worker():
    """Ελέγχει για υπενθυμίσεις και τις στέλνει στο Telegram."""
    from config import REMINDERS_FILE
    while not shutdown_event.is_set():
        if os.path.exists(REMINDERS_FILE):
            with open(REMINDERS_FILE, "r", encoding="utf-8") as f:
                try:
                    rems = json.load(f)
                except:
                    rems = []
            now, changed = datetime.now().strftime("%Y-%m-%d %H:%M"), False
            for r in rems:
                if r["status"] == "pending" and now >= r["time"]:
                    send_telegram_msg(f"🔔 ΥΠΕΝΘΥΜΙΣΗ: {r['task']}")
                    r["status"], changed = "done", True
            if changed:
                with open(REMINDERS_FILE, "w", encoding="utf-8") as f:
                    json.dump(rems, f, ensure_ascii=False, indent=4)
        shutdown_event.wait(timeout=20)
# ────────────────────────────────────────────────────────────────
# ROUTINE WORKER (BEHAVIOR PREDICTION ENGINE)
# ────────────────────────────────────────────────────────────────
def routine_worker():
    """
    Διαβάζει την SQLite (astakos_routines.db) κάθε 1 λεπτό.
    Ειδοποιεί αν έρχεται κάποια ρουτίνα με μεγάλο confidence στα επόμενα 30 λεπτά.
    """
    import os
    import sqlite3
    from datetime import datetime, timedelta
    from tools.telegram import send_telegram_msg
    from config import BASE_DIR

    DB_PATH = os.path.join(BASE_DIR, "astakos_routines.db")

    DAYS_MAP = {
        "Monday":    ["Monday", "Δευτέρα"],
        "Tuesday":   ["Tuesday", "Τρίτη"],
        "Wednesday": ["Wednesday", "Τετάρτη"],
        "Thursday":  ["Thursday", "Πέμπτη"],
        "Friday":    ["Friday", "Παρασκευή"],
        "Saturday":  ["Saturday", "Σάββατο"],
        "Sunday":    ["Sunday", "Κυριακή"]
    }

    while not shutdown_event.is_set():
        try:
            if os.path.exists(DB_PATH):
                conn = sqlite3.connect(DB_PATH)
                cursor = conn.cursor()

                now = datetime.now()
                target_time = now + timedelta(minutes=30)

                day_en = target_time.strftime("%A")
                possible_days = DAYS_MAP.get(day_en, [day_en])

                target_time_str = target_time.strftime("%H:%M")
                today_str = now.strftime("%Y-%m-%d")

                placeholders = ','.join('?' * len(possible_days))
                query = f'''
                    SELECT id, event_name, confidence FROM routines 
                    WHERE (day_of_week IN ({placeholders}) OR day_of_week = 'Everyday' OR day_of_week = 'Καθημερινά')
                    AND time_str=? AND is_active=1
                    AND (last_triggered IS NULL OR last_triggered != ?)
                '''
                params = (*possible_days, target_time_str, today_str)
                cursor.execute(query, params)

                upcoming_routines = cursor.fetchall()

                for r_id, event_name, confidence in upcoming_routines:
                    if confidence >= 0.8:
                        msg = f"🧠 **Proactive:** Μάστορα, πλησιάζει η ώρα για '{event_name}' (σε 30'). Όλα έτοιμα;"
                    elif confidence >= 0.5:
                        msg = f"🧠 **Proactive:** Συνήθως τέτοια ώρα έχεις '{event_name}'. Ισχύει και σήμερα;"
                    else:
                        msg = f"🧠 **Proactive:** Παλιά είχαμε '{event_name}' τέτοια ώρα, να το βγάλω απ' το πρόγραμμα αν δεν παίζει πια;"

                    cursor.execute('UPDATE routines SET last_triggered=? WHERE id=?', (today_str, r_id))
                    conn.commit()

                    send_telegram_msg(msg)
                    pending_routine_confirmations[r_id] = {"event": event_name, "sent_at": datetime.now()}

                conn.close()

        except Exception as e:
            print(f"❌ Routine Worker Error: {e}")

        # Timeout decay: αν έχουν περάσει >30' χωρίς απάντηση, decay
        if pending_routine_confirmations:
            from memory.routine_db import decay_routine
            now_check = datetime.now()
            for rid in list(pending_routine_confirmations.keys()):
                sent_at = pending_routine_confirmations[rid]["sent_at"]
                if (now_check - sent_at).total_seconds() > 1800:
                    decay_routine(rid)
                    print(f"⏰ [Routine Timeout Decay]: {pending_routine_confirmations[rid]['event']}")
                    del pending_routine_confirmations[rid]

        # Ελέγχει κάθε 60 δευτερόλεπτα
        shutdown_event.wait(timeout=60)
def proactive_worker():
    """
    Ο 'Νυχτοφύλακας' του Αστακού.
    Ξυπνάει κάθε 12 ώρες, διαβάζει αρχεία/logs και αν βρει κάτι επείγον, στέλνει μήνυμα.
    """
    import os
    from tools.system import read_local_file # Χρησιμοποιούμε το δικό σου tool για διάβασμα
    
    # Φάκελοι που θέλουμε να "κατασκοπεύει" (Βάλε τα δικά σου paths)
    WATCH_DIR = "C:\\astakos_v2\\watch_folder" 
    
    while not shutdown_event.is_set():
        # Ξυπνάει κάθε 12 ώρες (43200 δευτερόλεπτα). Για δοκιμή βάλτο στα 60 (1 λεπτό).
        shutdown_event.wait(timeout=43200) 
        if shutdown_event.is_set():
            break
            
        print("🦞 [Proactive]: Ξεκινάω αθόρυβο σκανάρισμα συστήματος...")
        
        try:
            # 1. Μαζεύουμε τα δεδομένα (π.χ. βρίσκουμε τα αρχεία στον φάκελο)
            if not os.path.exists(WATCH_DIR):
                os.makedirs(WATCH_DIR)
                
            files_to_scan = os.listdir(WATCH_DIR)
            if not files_to_scan:
                continue # Αν δεν έχει τίποτα, ξανακοιμάται
                
            collected_data = ""
            for file in files_to_scan:
                filepath = os.path.join(WATCH_DIR, file)
                
                # [MASTRO-FIX]: Επειδή είναι AI Tool, το καλούμε με .invoke() αντί για απλές παρενθέσεις
                try:
                    content = read_local_file.invoke(filepath)
                except TypeError:
                    # Fallback αν το εργαλείο ζητάει το όνομα της παραμέτρου
                    content = read_local_file.invoke({"file_path": filepath})
                    
                # Σιγουρευόμαστε ότι είναι string πριν το κόψουμε
                collected_data += f"\n--- ΑΡΧΕΙΟ: {file} ---\n{str(content)[:2000]}\n"

            # 2. Στέλνουμε τα δεδομένα στον Εγκέφαλο (Gemini) με αυστηρή οδηγία
            prompt = """
            Είσαι ο Αστακός. Λειτουργείς στο background ως σύστημα προληπτικής συντήρησης (Proactive Scan).
            Έχεις μπροστά σου κάποια αρχεία/logs από το σύστημα του Λάζαρου (Piston-7).
            
            ΟΔΗΓΙΕΣ:
            1. Ψάξε για ΗΜΕΡΟΜΗΝΙΕΣ ΛΗΞΗΣ (π.χ. λογαριασμοί, συνδρομές) που είναι κοντά στο σήμερα.
            2. Ψάξε για ERRORS, ελλείψεις ή προβλήματα (π.χ. στο PraxisERP).
            3. ΑΝ ΥΠΑΡΧΕΙ ΘΕΜΑ: Γράψε ένα σταράτο, μάστορικο μήνυμα προς τον Λάζαρο ξεκινώντας με "🚨 Μάστορα, ρίξε μια ματιά:".
            4. ΑΝ ΟΛΑ ΕΙΝΑΙ ΚΑΛΑ: Γράψε ΑΚΡΙΒΩΣ και ΜΟΝΟ τη φράση "ΟΛΑ ΚΑΛΑ".
            """
            
            response = safe_gemini_call(f"{prompt}\n\n[ΔΕΔΟΜΕΝΑ]:\n{collected_data}")
            reply = response.text.strip()
            
            # 3. Αν δεν απάντησε "ΟΛΑ ΚΑΛΑ", χτυπάει συναγερμός στο Telegram!
            if reply and "ΟΛΑ ΚΑΛΑ" not in reply:
                send_telegram_msg(reply)
                print(f"⚠️ [Proactive Alert Sent]: {reply[:50]}...")
            else:
                print("✔️ [Proactive]: Όλα καθαρά, πάω για ύπνο.")
                
        except Exception as e:
            print(f"⚠️ Proactive Scan Error: {e}")

# ────────────────────────────────────────────────────────────────
# ENTRY POINT
# ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import signal as _signal

    def _handle_exit(*args):
        print("\n[TelegramBot]: Τερματισμός...")
        shutdown_event.set()

    _signal.signal(_signal.SIGTERM, _handle_exit)
    _signal.signal(_signal.SIGINT,  _handle_exit)

    # Εκκίνηση workers
    threading.Thread(target=queue_worker,   daemon=True).start()
    threading.Thread(target=reminder_worker, daemon=True).start()
    threading.Thread(target=proactive_worker, daemon=True).start()
    threading.Thread(target=routine_worker, daemon=True).start()

    print("━" * 50)
    print("  🦞  Αστακός Telegram Bot — Εκκίνηση")
    print("━" * 50)
    send_telegram_msg("🦞 Αστακός Bot: Ξεκίνησα! Πώς μπορώ να βοηθήσω, Μάστορη;")

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
        print("[TelegramBot]: Τερματίστηκε.")
