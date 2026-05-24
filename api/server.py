# ================================================================
# Project: Astakos AI Agent 🦞
# Developer: Lazaros (Piston-7)
# Description: Modular LLM-agnostic multi-agent framework
# Copyright (c) 2026 - All Rights Reserved
# ================================================================

import os
import json
import time
import queue
import signal
import asyncio
import threading
import sys
import re
from contextlib import asynccontextmanager
from datetime import datetime
from fastapi.staticfiles import StaticFiles
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect, File, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from langchain_core.messages import HumanMessage, AIMessage
from rich.console import Console
from zoneinfo import ZoneInfo

from config import REMINDERS_FILE
from core.brain import llm
from core.graph import graph, AgentState
from core.agents import clean_message
from memory.working_memory import update_working_memory, update_capabilities_from_exchange
from memory.session_memory import trigger_memory_sifter, log_exchange, _run_session_summary
from tools.telegram import send_telegram_msg
import uuid
from PIL import Image
from google import genai
from fastapi.staticfiles import StaticFiles
from config import PHOTOS_DIR, GEMINI_API_KEY
from core.utils import detect_prompt_injection
console = Console()
from core.brain import FAST_MODEL
# ────────────────────────────────────────────────────────────────
# GLOBALS
# ────────────────────────────────────────────────────────────────
shutdown_event  = threading.Event()
astakos_queue   = queue.Queue()
memory_lock     = threading.Lock()
last_interaction_time = time.time()

# ── WebSocket log streaming ────────────────────────────────────
active_websockets: list = []
server_loop = None

class WsLogger:
    """Intercepts print() output and streams it live to Web UI via WebSocket."""
    def __init__(self, orig):
        self.orig = orig
    def write(self, msg):
        self.orig.write(msg)
        self.orig.flush()
        if msg.strip() and server_loop and active_websockets:
            clean_msg = re.sub(r'\x1b\[[0-9;]*m', '', msg)
            for ws in active_websockets:
                try:
                    asyncio.run_coroutine_threadsafe(ws.send_text(clean_msg), server_loop)
                except Exception:
                    pass
    def flush(self):
        self.orig.flush()

from core.graph import build_graph as _build_graph
app_graph = _build_graph()

# ── Κεντρικό chat history (επιβιώνει restarts μέσω JSON) ──────
CHAT_HISTORY_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "astakos_chat_history.json")
chat_history_lock = threading.Lock()

def _load_chat_history() -> list:
    """Φορτώνει το chat history από δίσκο."""
    if not os.path.exists(CHAT_HISTORY_FILE):
        return []
    try:
        with open(CHAT_HISTORY_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return []

def _save_chat_history(history: list):
    """Αποθηκεύει το chat history στο δίσκο (τελευταία 200 μηνύματα)."""
    try:
        with open(CHAT_HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(history[-200:], f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[ChatHistory]: Σφάλμα αποθήκευσης: {e}")

def append_to_chat_history(role: str, content: str):
    """Thread-safe προσθήκη μηνύματος στο history."""
    with chat_history_lock:
        history = _load_chat_history()
        history.append({
            "role": role,
            "content": content,
            "time": datetime.now().strftime("%H:%M")
        })
        _save_chat_history(history)

# ────────────────────────────────────────────────────────────────
# QUEUE SYSTEM
# ────────────────────────────────────────────────────────────────

def queue_worker():
    """Εκτελεί background tasks (memory sifter, working memory, κλπ) ένα-ένα."""
    print("\033[90m[System]: Queue Worker Ξεκίνησε!\033[0m")
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

def enqueue_task(func, *args):
    astakos_queue.put((func, args))

# ────────────────────────────────────────────────────────────────
# REMINDER WORKER
# ────────────────────────────────────────────────────────────────

def reminder_worker():
    """Ελέγχει για τοπικές υπενθυμίσεις κάθε 20 δευτερόλεπτα."""
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
                    print(f"\n\033[93m[🔔 ΥΠΕΝΘΥΜΙΣΗ]: {r['task']}\033[0m")
                    send_telegram_msg(f"🔔 ΥΠΕΝΘΥΜΙΣΗ: {r['task']}")
                    r["status"], changed = "done", True
            if changed:
                with open(REMINDERS_FILE, "w", encoding="utf-8") as f:
                    json.dump(rems, f, ensure_ascii=False, indent=4)
        shutdown_event.wait(timeout=20)

# ────────────────────────────────────────────────────────────────
# PROACTIVE WORKER
# ────────────────────────────────────────────────────────────────

def proactive_worker():
    """Κάνει poke στον Λάζαρο αν υπάρχει σιωπή 2.5 ωρών (09:00–23:00)."""
    global last_interaction_time
    CHECK_INTERVAL = 9000
    greece_tz = ZoneInfo("Europe/Athens")

    while not shutdown_event.is_set():
        if shutdown_event.wait(timeout=5):
            break

        now_gr = datetime.now(greece_tz)
        current_hour = now_gr.hour

        if 9 <= current_hour <= 23:
            with memory_lock:
                elapsed = time.time() - last_interaction_time

            if elapsed >= CHECK_INTERVAL:
                with memory_lock:
                    last_interaction_time = time.time()

                if current_hour < 12:
                    time_context = "Πρωινό: Μάστορη καλημέρα, κώδικας για Mastroapp/Αστακό;"
                elif current_hour < 17:
                    time_context = "Μεσημέρι: Πλάκα για Αλέξανδρο/LEGO/φακές."
                else:
                    time_context = "Βράδυ: Χαλάρωση, Netflix ή το κουνέλι."

                poke_prompt = (
                    f"Είσαι ο Αστακός. Πέρασαν 2.5 ώρες σιωπής. Κάνε ένα σύντομο poke στον Λάζαρο. "
                    f"CONTEXT: {time_context} "
                    f"ΚΑΝΟΝΕΣ: ΜΟΝΟ Ελληνικά, 1-2 προτάσεις, Mastro-style χιούμορ, χωρίς τυπικότητες, κλείσε με ερώτηση."
                )

                if shutdown_event.is_set():
                    break

                try:
                    response = llm.invoke([HumanMessage(content=poke_prompt)])
                    if shutdown_event.is_set():
                        break

                    ai_msg = clean_message(response.content).strip()
                    print(f"\n🤖 [Proactive]: {ai_msg}")
                    send_telegram_msg(f"🤖 {ai_msg}")

                    with memory_lock:
                        enqueue_task(log_exchange, "POKE_EVENT", ai_msg, "Proactive_Worker")

                except Exception as e:
                    print(f"\n[Proactive Worker Error]: {e}")

# ────────────────────────────────────────────────────────────────
# FASTAPI LIFESPAN
# ────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Ξεκινάει workers, περιμένει, τερματίζει καθαρά."""
    global server_loop
    server_loop = asyncio.get_running_loop()
    sys.stdout = WsLogger(sys.stdout)
    threads = [
        # reminder_worker και proactive_worker τρέχουν ΜΟΝΟ στο telegram_bot.py
        # Εδώ κρατάμε μόνο τον queue_worker για τα background memory tasks
        threading.Thread(target=queue_worker, daemon=True),
    ]
    for t in threads:
        t.start()

    print("\n--- Αστακός API Server: Ξεκίνησε ---")
    yield  # Server τρέχει εδώ

    print("\n[Server]: Τερματισμός...")
    shutdown_event.set()

    loop = asyncio.get_event_loop()
    try:
        await asyncio.wait_for(
            loop.run_in_executor(None, _run_session_summary),
            timeout=5.0
        )
    except (asyncio.TimeoutError, Exception):
        print("\033[93m[System]: Summary timeout — παράκαμψη.\033[0m")

# ────────────────────────────────────────────────────────────────
# FASTAPI APP & MIDDLEWARE
# ────────────────────────────────────────────────────────────────

server = FastAPI(lifespan=lifespan)
server.mount("/photos", StaticFiles(directory=PHOTOS_DIR), name="photos")

# --- [MASTRO-ROUTE]: Επιτρέπουμε το download από τον φάκελο outputs ---
from config import BASE_DIR
outputs_dir = os.path.join(BASE_DIR, "outputs")
os.makedirs(outputs_dir, exist_ok=True)
server.mount("/outputs", StaticFiles(directory=outputs_dir), name="outputs")

# --- [MASTRO-FIX]: Ξεχωριστός φάκελος για τις φάτσες του UI ---
avatars_dir = os.path.join(BASE_DIR, "avatars")
os.makedirs(avatars_dir, exist_ok=True)
server.mount("/avatars", StaticFiles(directory=avatars_dir), name="avatars")

# Επίτρεψε στο Web UI (frontend) να μιλάει ελεύθερα με τον server
server.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)



# ────────────────────────────────────────────────────────────────
# ENDPOINTS
# ────────────────────────────────────────────────────────────────
# [MASTRO-FIX]: Προσθήκη του endpoint για το κουμπί του Web UI
@server.post("/end_session")
async def manual_session_save():
    """Επιτρέπει στο Web UI να ζητάει χειροκίνητη αρχειοθέτηση (Κουμπί)"""
    from memory.session_memory import _run_session_summary
    import threading
    
    # Εκτέλεση σε ξεχωριστό thread για να μην κολλήσει το API
    threading.Thread(target=_run_session_summary, daemon=True).start()
    return JSONResponse({"status": "Η αρχειοθέτηση ξεκίνησε!"})
@server.post("/chat")
async def chat_endpoint(request: Request):
    global last_interaction_time

    body       = await request.json()
    user_input = body.get("message", "").strip()

    # (Mastro-Shield): Αποφυγή null ή περίεργων paths
    photo_path = body.get("photo_path")
    if photo_path is None:
        photo_path = ""
    else:
        photo_path = str(photo_path).strip()

    if not user_input:
        return JSONResponse({"error": "Κενό μήνυμα."}, status_code=400)

    # 1. --- PROMPT INJECTION FIREWALL ---
    # We catch malicious intents before they ever touch the LLM or cost API tokens.
    if detect_prompt_injection(user_input):
        print(f"\033[91m🛡️ [SECURITY INTERCEPT]: Blocked malicious input -> {user_input}\033[0m")
        return JSONResponse({
            "agent": "Security_Firewall",
            "response": "🛡️ [SECURITY OVERRIDE]: Prohibited command detected."
        })

    # 2. --- XML CONTEXT ISOLATION ---
    # We wrap the user's prompt so Astakos knows it is strictly raw data.
    isolated_user_input = f"<isolated_data>\n{user_input}\n</isolated_data>"

    with memory_lock:
        last_interaction_time = time.time()

    # ── Αποθήκευση user message στο history ────────────────────
    # Note: We save the original `user_input` to the UI chat history, 
    # not the XML-wrapped version, to keep the frontend looking clean.
    append_to_chat_history("user", user_input)

    final_ai_response = ""
    handling_agent    = "Chat_Agent"

    try:
        # ── Multimodal message αν υπάρχει αρχείο ───────────
        if photo_path and os.path.exists(photo_path):
            import base64
            filename = os.path.basename(photo_path)
            ext = os.path.splitext(filename)[1].lower()
            image_exts = [".jpg", ".jpeg", ".png", ".webp", ".gif"]
            
            # We inject the isolated input into the enhanced string
            enhanced_user_input = f"[USER_UPLOADED_FILE]: {filename}\n{isolated_user_input}"
            
            # Αν είναι ΕΙΚΟΝΑ, το κάνουμε Base64 και το στέλνουμε ως image_url
            if ext in image_exts:
                with open(photo_path, "rb") as f:
                    img_b64 = base64.b64encode(f.read()).decode("utf-8")
                
                mime = {"png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                        ".gif": "image/gif", ".webp": "image/webp"}.get(ext, "image/jpeg")
                
                human_msg = HumanMessage(content=[
                    {"type": "text", "text": enhanced_user_input},
                    {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{img_b64}"}}
                ])
                print(f"\033[92m[Chat]: Multimodal message (Εικόνα): {filename}\033[0m")
            
            # Αν είναι ΕΓΓΡΑΦΟ (PDF, Word, Excel), το στέλνουμε μόνο ως κείμενο/όνομα
            else:
                human_msg = HumanMessage(content=enhanced_user_input)
                print(f"\033[94m[Chat]: Text message με αναφορά εγγράφου: {filename}\033[0m")
        
        # ── Standard text message ────────────────────────────────
        else:
            # We feed the LangGraph state the isolated XML payload
            human_msg = HumanMessage(content=isolated_user_input)

        # ── Context: τελευταία 10 μηνύματα με timestamps ─────────
        with chat_history_lock:
            raw_hist = _load_chat_history()
        context_msgs = []
        for entry in raw_hist[-11:-1]:
            role    = entry.get("role", "")
            content = entry.get("content", "")
            ts      = entry.get("time", "")
            prefix  = f"[{ts}] " if ts else ""
            if role in ("user", "Human"):
                context_msgs.append(HumanMessage(content=f"{prefix}{content}"))
            else:
                context_msgs.append(AIMessage(content=f"{prefix}{content}"))
        # Timestamp στο τρέχον μήνυμα
        now_ts = datetime.now().strftime("%H:%M")
        if isinstance(human_msg.content, str):
            human_msg = HumanMessage(content=f"[{now_ts}] {human_msg.content}")
        elif isinstance(human_msg.content, list):
            parts = list(human_msg.content)
            for i, p in enumerate(parts):
                if isinstance(p, dict) and p.get("type") == "text":
                    parts[i] = {"type": "text", "text": f"[{now_ts}] {p['text']}"}
                    break
            human_msg = HumanMessage(content=parts)
        # ── Τρέξιμο του LangGraph ────────────────────────────────
        for event in graph.stream({"messages": context_msgs + [human_msg]}, {"recursion_limit": 20}):
            for node, data in event.items():
                if node not in ["supervisor", "tools"]:
                    handling_agent = node
                    msgs = data.get("messages", [])
                    if msgs and hasattr(msgs[-1], "content"):
                        # Εδώ "τσιμπάμε" την απάντηση μέσα από το loop
                        candidate = clean_message(msgs[-1].content).strip()
                        if candidate:
                            final_ai_response = candidate

        # --- [MASTRO-FIX]: Επιπλέον καθάρισμα ΠΡΙΝ την αποθήκευση ---
        # We use the raw user_input for memory extraction so Astakos 
        # doesn't memorize the XML tags as part of your data.
        clean_user = clean_message(user_input)
        clean_ai   = clean_message(final_ai_response)

        # 1. --- MASTRO INTERCEPTOR ΓΙΑ LINKS ΕΓΓΡΑΦΩΝ (Web UI) ---
        file_match = re.search(r"\[CREATED_FILE:\s*(.*?)\]", clean_ai)
        if file_match:
            file_path = file_match.group(1).strip()
            filename = os.path.basename(file_path)
            
            base_url = str(request.base_url).rstrip("/")
            
            download_link = f'<br><br><a href="{base_url}/outputs/{filename}" target="_blank" download style="color: #4CAF50; font-weight: bold; text-decoration: none;">📥 Κάνε κλικ εδώ για λήψη: {filename}</a>'
            
            clean_ai = re.sub(r"\[CREATED_FILE:\s*(.*?)\]", download_link, clean_ai)

        # 2. --- MASTRO INTERCEPTOR ΓΙΑ ΕΙΚΟΝΕΣ (Web UI) ---
        photo_match = re.search(r"\[SEND_PHOTO:\s*(.*?)\]", clean_ai)
        if photo_match:
            file_path = photo_match.group(1).strip()
            filename = os.path.basename(file_path)
            base_url = str(request.base_url).rstrip("/")
            
            # Ελέγχουμε έξυπνα πού βρίσκεται η φωτογραφία
            if "outputs" in file_path.lower():
                img_url = f"{base_url}/outputs/{filename}"
            else:
                img_url = f"{base_url}/photos/{filename}"
                
            img_html = f'<br><br><img src="{img_url}" alt="Astakos Image" style="max-width: 100%; border-radius: 8px; box-shadow: 0 4px 8px rgba(0,0,0,0.2);">'
            
            # Αντικαθιστούμε την ταμπέλα με την εικόνα
            clean_ai = re.sub(r"\[SEND_PHOTO:\s*(.*?)\]", img_html, clean_ai)

        if final_ai_response:
            # Αποθηκεύουμε παντού τα ΚΑΘΑΡΑ strings (με το Link/Img αν υπάρχει)
            append_to_chat_history("assistant", clean_ai)
            enqueue_task(update_working_memory,             clean_user, clean_ai)
            enqueue_task(trigger_memory_sifter,             clean_user, clean_ai, handling_agent)
            enqueue_task(log_exchange,                      clean_user, clean_ai, handling_agent)
            enqueue_task(update_capabilities_from_exchange, clean_user, clean_ai, handling_agent)

        return JSONResponse({
            "agent":    handling_agent,
            "response": clean_ai,  # Επιστρέφουμε την απάντηση στο Frontend
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return JSONResponse({"error": str(e)}, status_code=500)

@server.post("/voice")
async def process_web_voice(file: UploadFile = File(...)):
    """Δέχεται ηχητικό από το Web UI, το κάνει κείμενο με Gemini και το επιστρέφει."""
    try:
        audio_data = await file.read()
        debug_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "debug_voice.webm")
        with open(debug_path, "wb") as f:
            f.write(audio_data)
        print(f"\033[96m[Web Voice]: Αποκωδικοποίηση ηχητικού ({len(audio_data)} bytes)...\033[0m")
        client = genai.Client(api_key=GEMINI_API_KEY)
        response = client.models.generate_content(
            model=FAST_MODEL,
            contents=[
                {"inline_data": {"mime_type": "audio/webm", "data": audio_data}},
                "Είσαι ΑΠΟΚΛΕΙΣΤΙΚΑ ένα εργαλείο Speech-to-Text. Δουλειά σου είναι ΜΟΝΟ να μεταγράψεις τον ήχο σε κείμενο. ΑΠΑΓΟΡΕΥΕΤΑΙ να απαντήσεις, να σχολιάσεις ή να πεις ότι 'δεν έχεις τη δυνατότητα'. Αν δεν ακούς τίποτα ή ο ήχος είναι κενός, επέστρεψε μόνο τη λέξη: [ΣΙΩΠΗ]."
            ]
        )
        transcription = response.text.strip() if response.text else ""
        if not transcription or "[ΣΙΩΠΗ]" in transcription:
            return JSONResponse({"error": "Δεν ακούστηκε τίποτα. Έλεγξε το μικρόφωνό σου!"})
        print(f"\033[92m[Web Voice]: Ο Λάζαρος είπε -> {transcription}\033[0m")
        return JSONResponse({"transcription": transcription})
    except Exception as e:
        import traceback
        print(f"\033[91m[Web Voice Error]: {traceback.format_exc()}\033[0m")
        return JSONResponse({"error": str(e)}, status_code=500)


import edge_tts
import io

@server.post("/tts")
async def text_to_speech(request: Request):
    try:
        body = await request.json()
        text = body.get("text", "").strip()
        if not text:
            return JSONResponse({"error": "Κενό κείμενο"}, status_code=400)
        text = re.sub(r'[*#`]', '', text)
        text = re.sub(r'\[.*?\]\(.*?\)', '', text)
        text = re.sub(r'\[SEND_PHOTO:.*?\]', '', text)
        text = text.strip()
        voice = "el-GR-NestorasNeural"
        communicate = edge_tts.Communicate(text, voice, rate="-10%", volume="+10%")
        audio_buffer = io.BytesIO()
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                audio_buffer.write(chunk["data"])
        audio_buffer.seek(0)
        audio_bytes = audio_buffer.read()
        if not audio_bytes:
            return JSONResponse({"error": "Αποτυχία δημιουργίας ήχου"}, status_code=500)
        print(f"\033[95m[TTS]: Φωνή δημιουργήθηκε ({len(audio_bytes)} bytes)\033[0m")
        from fastapi.responses import Response
        return Response(
            content=audio_bytes,
            media_type="audio/mpeg",
            headers={"Content-Disposition": "inline; filename=response.mp3"}
        )
    except Exception as e:
        import traceback
        print(f"\033[91m[TTS Error]: {traceback.format_exc()}\033[0m")
        return JSONResponse({"error": str(e)}, status_code=500)


@server.post("/upload")
async def upload_file(file: UploadFile = File(...)):
    """Endpoint για ανέβασμα αρχείων (φωτογραφίες & έγγραφα) από το Web UI."""
    try:
        file_ext  = os.path.splitext(file.filename or "")[1].lower() or ".jpg"
        filename  = f"web_{uuid.uuid4().hex}{file_ext}"
        image_exts = [".jpg", ".jpeg", ".png", ".webp", ".gif"]
        doc_exts   = [".pdf", ".docx", ".xlsx", ".xls", ".txt", ".csv", ".json"]
        is_image   = file_ext in image_exts
        if is_image:
            target_dir = PHOTOS_DIR
        else:
            from config import UPLOADS_DIR
            target_dir = UPLOADS_DIR
        file_path = os.path.join(target_dir, filename)
        content = await file.read()
        with open(file_path, "wb") as buffer:
            buffer.write(content)
        print(f"\033[92m[Upload]: Αποθηκεύτηκε → {filename}\033[0m")
        memory_analysis = ""
        detailed_analysis = ""
        if is_image:
            client = genai.Client(api_key=GEMINI_API_KEY)
            img = Image.open(file_path)
            img.thumbnail((1024, 1024))
            mem_resp = client.models.generate_content(
                model=FAST_MODEL,
                contents=[img, "Περίγραψε τι βλέπεις στα Ελληνικά, κοφτά, 1-2 προτάσεις."]
            )
            memory_analysis = mem_resp.text.strip() if mem_resp.text else "No analysis available."
            chat_resp = client.models.generate_content(
                model=FAST_MODEL,
                contents=[img, "Ανάλυσε τη φωτό λεπτομερώς στα Ελληνικά, με χιούμορ και ζωντάνια."]
            )
            detailed_analysis = chat_resp.text.strip() if chat_resp.text else memory_analysis
            chat_ai_msg = (
                f"📸 **Φωτογραφία ελήφθη:** `{filename}`\n\n"
                f"{detailed_analysis}\n\n"
                "**Λάζαρε, να την αρχειοθετήσω μόνιμα στη μνήμη μου;**"
            )
            user_log_msg = f"[USER_UPLOADED_PHOTO]: {filename}\n[PHOTO PATH]: {file_path}\n[ANALYSIS]: {memory_analysis}"
        elif file_ext in doc_exts:
            memory_analysis = f"Έγγραφο τύπου {file_ext} με όνομα {file.filename}."
            detailed_analysis = f"Έλαβα το αρχείο **{file.filename}** (αποθηκεύτηκε ως `{filename}`). Είναι έγγραφο ({file_ext}) και μπορώ να το διαβάσω αν μου το ζητήσεις."
            chat_ai_msg = (
                f"📄 **Έγγραφο ελήφθη:** `{filename}` (Αρχικό όνομα: {file.filename})\n\n"
                f"{detailed_analysis}\n\n"
                "**Λάζαρε, θέλεις να το διαβάσω ή να το αρχειοθετήσω;**"
            )
            user_log_msg = f"[USER_UPLOADED_FILE]: {filename}\n[FILE PATH]: {file_path}\n[ANALYSIS]: {memory_analysis}"
        else:
            memory_analysis = f"Αρχείο {file_ext} με όνομα {file.filename}."
            detailed_analysis = f"Ανέβηκε ένα αρχείο με κατάληξη {file_ext}."
            chat_ai_msg = (
                f"📁 **Αρχείο ελήφθη:** `{filename}`\n\n"
                f"{detailed_analysis}\n\n"
                "**Λάζαρε, τι θέλεις να κάνω με αυτό;**"
            )
            user_log_msg = f"[USER_UPLOADED_FILE]: {filename}\n[FILE PATH]: {file_path}\n[ANALYSIS]: {memory_analysis}"
        append_to_chat_history("user", f"📎 *Ανέβασα αρχείο:* `{filename}`")
        append_to_chat_history("assistant", chat_ai_msg)
        log_exchange(user_log_msg, chat_ai_msg, "Chat_Agent")
        return JSONResponse({
            "status":    "success",
            "filename":  filename,
            "file_path": file_path,
            "url":       f"/photos/{filename}" if is_image else None,
            "ai_message": chat_ai_msg,
            "analysis":  memory_analysis,
        })
    except Exception as e:
        import traceback
        print(f"\033[91m[Upload Error]: {traceback.format_exc()}\033[0m")
        return JSONResponse({"status": "error", "message": str(e)}, status_code=500)


@server.get("/")
async def read_index():
    """Σερβίρει το Web UI (index.html)."""
    from fastapi.responses import FileResponse
    return FileResponse('index.html')


@server.get("/health")
async def health():
    return {"status": "ok", "time": datetime.now().isoformat()}


@server.get("/history")
async def get_history():
    """Δίνει το ιστορικό στο Web UI — διαβάζει από JSON για να επιβιώνει το F5/restart."""
    with chat_history_lock:
        history = _load_chat_history()
    return {"history": history}


@server.websocket("/ws/logs")
async def websocket_logs(websocket: WebSocket):
    """Κρατάει το κανάλι ανοιχτό — στέλνει live print() output στο Web UI."""
    await websocket.accept()
    active_websockets.append(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        if websocket in active_websockets:
            active_websockets.remove(websocket)


# ────────────────────────────────────────────────────────────────
# OBSERVABILITY: /debug/runtime + /debug
# ────────────────────────────────────────────────────────────────

def _read_json_file(path: str, default):
    try:
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return default


@server.get("/debug/runtime")
async def debug_runtime():
    """
    Live runtime snapshot — διαβάζει από:
      • runtime_snapshot.json   (scheduler jobs — γράφεται κάθε 10s από telegram_bot)
      • scheduler_state.json    (override state)
      • astakos_routines.db     (active routines, pending confirmations, cooldowns)
      • logs/events/YYYY-MM-DD.json  (event throughput, last errors)
    """
    base = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")

    # ── 1. Scheduler snapshot ────────────────────────────────────
    snapshot     = _read_json_file(os.path.join(base, "runtime_snapshot.json"), {})
    override     = _read_json_file(os.path.join(base, "scheduler_state.json"), {})

    # ── 2. DB: routines + pending confirmations ──────────────────
    import sqlite3 as _sqlite3
    db_path      = os.path.join(base, "astakos_routines.db")
    active_routines   = []
    pending_from_db   = []
    cooldown_info     = []

    try:
        conn   = _sqlite3.connect(db_path, check_same_thread=False)
        cursor = conn.cursor()

        # Active routines
        cursor.execute("""
            SELECT id, day_of_week, time_str, event_name, confidence,
                   mention_count, notify_cooldown_hours, last_notified_ts, state
            FROM routines
            WHERE state='active'
            ORDER BY day_of_week, time_str
        """)
        for row in cursor.fetchall():
            r_id, day, tstr, ev, conf, mentions, cd_h, last_ts, state = row
            now_dt = datetime.now()
            cooldown_remaining = None
            if last_ts:
                try:
                    last_dt = datetime.fromisoformat(last_ts)
                    elapsed = (now_dt - last_dt).total_seconds()
                    cd_secs = (cd_h or 20.0) * 3600
                    remaining_secs = cd_secs - elapsed
                    cooldown_remaining = max(0, round(remaining_secs / 3600, 1))
                except Exception:
                    pass
            active_routines.append({
                "id":                r_id,
                "day":               day,
                "time":              tstr,
                "event":             ev,
                "confidence":        round(conf or 0, 2),
                "mentions":          mentions or 1,
                "cooldown_hours":    cd_h or 20.0,
                "last_notified":     last_ts,
                "cooldown_remaining_h": cooldown_remaining,
                "state":             state,
            })

        # Pending confirmations
        cursor.execute("SELECT routine_id, event_name, sent_at FROM pending_confirmations")
        for row in cursor.fetchall():
            rid, ev, sent_at_str = row
            try:
                sent_dt  = datetime.fromisoformat(sent_at_str)
                elapsed  = round((datetime.now() - sent_dt).total_seconds() / 60, 1)
            except Exception:
                elapsed  = None
            pending_from_db.append({
                "routine_id": rid,
                "event":      ev,
                "sent_at":    sent_at_str,
                "elapsed_min": elapsed,
                "timeout_in_min": round(max(0, 30 - (elapsed or 0)), 1),
            })

        # Routines in non-active states (TRIGGER_PENDING, DISMISSED, DECAYED, etc.)
        cursor.execute("""
            SELECT id, event_name, state, confidence, last_notified_ts, notify_cooldown_hours
            FROM routines
            WHERE state != 'active' AND state != 'archived' AND state != 'learned'
            ORDER BY state
        """)
        for row in cursor.fetchall():
            r_id, ev, state, conf, last_ts, cd_h = row
            cooldown_info.append({
                "id": r_id, "event": ev, "state": state,
                "confidence": round(conf or 0, 2),
                "last_notified": last_ts,
                "cooldown_hours": cd_h or 20.0,
            })

        # Stats
        cursor.execute("SELECT state, COUNT(*) FROM routines GROUP BY state")
        state_counts = dict(cursor.fetchall())

        conn.close()
    except Exception as e:
        state_counts = {}
        active_routines.append({"error": str(e)})

    # ── 3. Today's event log: throughput + last errors ───────────
    today      = datetime.now().strftime("%Y-%m-%d")
    log_file   = os.path.join(base, "logs", "events", f"{today}.json")
    events     = _read_json_file(log_file, [])

    # Throughput: count per (job, action) in last 1h
    from datetime import timedelta
    one_hour_ago = datetime.now() - timedelta(hours=1)
    throughput = {}
    last_errors = []
    for ev in events:
        try:
            ts  = datetime.fromisoformat(ev.get("timestamp", ""))
            job = ev.get("job", "?")
            act = ev.get("action", "?")
            key = f"{job}/{act}"
            if ts >= one_hour_ago:
                throughput[key] = throughput.get(key, 0) + 1
            if act in ("error", "db_error", "disabled") and ts >= one_hour_ago:
                last_errors.append({
                    "time":  ev.get("timestamp", "")[-8:],
                    "job":   job,
                    "error": str(ev.get("error", ""))[:120],
                })
        except Exception:
            pass
    last_errors = last_errors[-10:]  # max 10

    # ── 4. Assemble response ─────────────────────────────────────
    sleep_until = override.get("sleep_until")
    sleeping    = sleep_until and time.time() < sleep_until
    sleep_until_str = datetime.fromtimestamp(sleep_until).strftime("%H:%M") if sleeping else None

    return JSONResponse({
        "snapshot_age_s": round(time.time() - datetime.fromisoformat(snapshot["written_at"]).timestamp(), 0)
                          if snapshot.get("written_at") else None,
        "scheduler": {
            "written_at":         snapshot.get("written_at"),
            "jobs":               snapshot.get("jobs", []),
            "queue_size":         snapshot.get("queue_size", "?"),
            "quiet_hours":        snapshot.get("quiet_hours"),
            "proactive_muted":    snapshot.get("proactive_muted"),
            "reminders_paused":   snapshot.get("reminders_paused"),
            "proactive_this_hour": snapshot.get("proactive_this_hour", 0),
            "pending_count":      snapshot.get("pending_confirmations", 0),
        },
        "overrides": {
            "pause_reminders": bool(override.get("pause_reminders")),
            "mute_proactive":  bool(override.get("mute_proactive")),
            "sleeping":        bool(sleeping),
            "sleep_until":     sleep_until_str,
        },
        "routines": {
            "state_counts":    state_counts,
            "active":          active_routines,
            "non_active":      cooldown_info,
        },
        "pending_confirmations": pending_from_db,
        "events_1h": {
            "throughput":  throughput,
            "last_errors": last_errors,
            "total_today": len(events),
            "recent_logs": events[-100:],
        },
    })

@server.get("/debug/replay")
async def debug_replay(days: int = 2):
    from memory.event_log import get_routine_timeline
    try:
        events = get_routine_timeline(routine_id=None, days=days)
        return {"events": events, "count": len(events), "days": days}
    except Exception as e:
        return {"events": [], "error": str(e)}

@server.get("/debug")
async def debug_panel():
    """Observability HTML dashboard — auto-refresh every 5s."""
    from fastapi.responses import HTMLResponse
    _dir = os.path.dirname(os.path.abspath(__file__))
    html_path = os.path.join(_dir, "debug_dashboard.html")
    try:
        with open(html_path, "r", encoding="utf-8") as f:
            html = f.read()
    except FileNotFoundError:
        html = "<h1>debug_dashboard.html not found</h1>"
    return HTMLResponse(content=html)
