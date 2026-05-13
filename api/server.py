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
import sqlite3
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
from langgraph.checkpoint.sqlite import SqliteSaver
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
console = Console()

# ────────────────────────────────────────────────────────────────
# GLOBALS
# ────────────────────────────────────────────────────────────────
shutdown_event  = threading.Event()
astakos_queue   = queue.Queue()
memory_lock     = threading.Lock()
last_interaction_time = time.time()

THREAD_ID = "lazaros_stable_v41"
checkpointer = SqliteSaver(sqlite3.connect("checkpoints.db", check_same_thread=False))

# Graph με checkpointer (για REST endpoint)
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

                    ai_msg = response.content.strip()
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
    global server_loop                               # <--- ΠΡΟΣΘΗΚΗ ΑΥΤΗ ΤΗ ΓΡΑΜΜΗ
    server_loop = asyncio.get_running_loop()
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
# Επίτρεψε στο Web UI (frontend) να μιλάει ελεύθερα με τον server
server.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

config = {"configurable": {"thread_id": THREAD_ID}}

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

    with memory_lock:
        last_interaction_time = time.time()

    # ── Αποθήκευση user message στο history ────────────────────
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
            
            enhanced_user_input = f"[USER_UPLOADED_FILE]: {filename}\n{user_input}"
            
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
        else:
            human_msg = HumanMessage(content=user_input)

        # ── Τρέξιμο του LangGraph ────────────────────────────────
        for event in graph.stream({"messages": [human_msg]}):
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
            
            # Φτιάχνουμε ένα ωραίο HTML img tag για να εμφανιστεί η εικόνα στο chat
            img_html = f'<br><br><img src="{base_url}/outputs/{filename}" alt="Generated Image" style="max-width: 100%; border-radius: 8px; box-shadow: 0 4px 8px rgba(0,0,0,0.2);">'
            
            # Αντικαθιστούμε την ταμπέλα με την εικόνα!
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


@server.get("/health")
async def health():
    return {"status": "ok", "time": datetime.now().isoformat()}


# ────────────────────────────────────────────────────────────────
# WEB UI SYNC (Ιστορικό & Ζωντανά Logs)
# ────────────────────────────────────────────────────────────────


active_websockets = []
server_loop = None

class WsLogger:
    """Κλέβει τα print() του τερματικού και τα στέλνει και στο Web UI!"""
    def __init__(self, orig):
        self.orig = orig
        
    def write(self, msg):
        self.orig.write(msg)
        self.orig.flush()
        if msg.strip() and server_loop and active_websockets:
            clean_msg = re.sub(r'\x1b\[[0-9;]*m', '', msg) # Αφαιρεί τα χρώματα ANSI
            for ws in active_websockets:
                try:
                    asyncio.run_coroutine_threadsafe(ws.send_text(clean_msg), server_loop)
                except:
                    pass
                    
    def flush(self):
        self.orig.flush()
@server.post("/voice")
async def process_web_voice(file: UploadFile = File(...)):
    """Δέχεται ηχητικό από το Web UI, το κάνει κείμενο με Gemini και το επιστρέφει."""
    try:
        from google import genai
        from config import GEMINI_API_KEY
        
        # Διαβάζουμε τα bytes του ηχητικού
        audio_data = await file.read()
        
        print(f"\033[96m[Web Voice]: Αποκωδικοποίηση ηχητικού από τον browser...\033[0m")
        client = genai.Client(api_key=GEMINI_API_KEY)
        
        # Ο browser στέλνει τον ήχο σε μορφή audio/webm
        response = client.models.generate_content(
            model='gemini-3.1-flash-lite-preview',
            contents=[
                {"inline_data": {"mime_type": "audio/webm", "data": audio_data}},
                "Άκουσε το ηχητικό και γράψε μου ΑΚΡΙΒΩΣ τι λέει στα Ελληνικά, χωρίς δικά σου σχόλια."
            ]
        )
        
        transcription = response.text.strip() if response.text else ""
        if not transcription:
            return JSONResponse({"error": "Δεν έβγαλα άκρη με τον ήχο."})
            
        print(f"\033[92m[Web Voice]: Ο Λάζαρος είπε -> {transcription}\033[0m")
        
        # Επιστρέφουμε το κείμενο στο Web UI για να το βάλει στο chat
        return JSONResponse({"transcription": transcription})
        
    except Exception as e:
        import traceback
        print(f"\033[91m[Web Voice Error]: {traceback.format_exc()}\033[0m")
        return JSONResponse({"error": str(e)}, status_code=500)
# Ενεργοποίηση του "κλέφτη" των logs
sys.stdout = WsLogger(sys.stdout)
@server.post("/upload")
async def upload_file(file: UploadFile = File(...)):
    """
    Endpoint για το ανέβασμα αρχείων (φωτογραφίες & έγγραφα).
    Ροή: Διαχωρισμός Φακέλου → Αποθήκευση → (Ανάλυση Vision ΜΟΝΟ για εικόνες) → Επιστροφή & Ερώτηση.
    """
    try:
        # 1. Βρίσκουμε την κατάληξη και φτιάχνουμε το όνομα
        file_ext = os.path.splitext(file.filename or "")[1].lower() or ".jpg"
        filename  = f"web_{uuid.uuid4().hex}{file_ext}"

        # 2. [MASTRO-ROUTER]: Πού θα αποθηκευτεί το αρχείο;
        image_exts = [".jpg", ".jpeg", ".png", ".webp", ".gif"]
        doc_exts = [".pdf", ".docx", ".xlsx", ".xls", ".txt", ".csv", ".json"]
        is_image = file_ext in image_exts

        if is_image:
            # Οι εικόνες πάνε στον φάκελο PHOTOS_DIR
            target_dir = PHOTOS_DIR
        else:
            # Τα έγγραφα πάνε στον telegram_uploads
            target_dir = "telegram_uploads"
            if not os.path.exists(target_dir):
                os.makedirs(target_dir)

        file_path = os.path.join(target_dir, filename)

        # 3. Αποθήκευση του αρχείου στον ΣΩΣΤΟ φάκελο
        content = await file.read()
        with open(file_path, "wb") as buffer:
            buffer.write(content)
        print(f"\033[92m[Upload]: Αποθηκεύτηκε στο {target_dir} → {filename}\033[0m")

        memory_analysis = ""
        detailed_analysis = ""

        # 4. Ανάλυση (Μόνο αν είναι εικόνα)
        if is_image:
            from PIL import Image
            client = genai.Client(api_key=GEMINI_API_KEY)
            img = Image.open(file_path)
            img.thumbnail((1024, 1024))

            mem_resp = client.models.generate_content(
                model="gemini-3.1-flash-lite-preview",
                contents=[img, "Περίγραψε τι βλέπεις στα Ελληνικά, κοφτά, 1-2 προτάσεις."]
            )
            memory_analysis = mem_resp.text.strip() if mem_resp.text else "No analysis available."

            chat_resp = client.models.generate_content(
                model="gemini-3.1-flash-lite-preview",
                contents=[img, "Ανάλυσε τη φωτό λεπτομερώς στα Ελληνικά, με χιούμορ και ζωντάνια."]
            )
            detailed_analysis = chat_resp.text.strip() if chat_resp.text else memory_analysis
            print(f"📸 [Vision]: Ανάλυση εικόνας ολοκληρώθηκε.")

            chat_ai_msg = (
                f"📸 **Φωτογραφία ελήφθη:** `{filename}`\n\n"
                f"{detailed_analysis}\n\n"
                "**Λάζαρε, να την αρχειοθετήσω μόνιμα στη μνήμη μου;**"
            )
            user_log_msg = f"[USER_UPLOADED_PHOTO]: {filename}\n[PHOTO PATH]: {file_path}\n[ANALYSIS]: {memory_analysis}"

        elif file_ext in doc_exts:
            # Έγγραφα (Δεν καλούμε Vision, τα σώσαμε στο telegram_uploads)
            memory_analysis = f"Έγγραφο τύπου {file_ext} με όνομα {file.filename}."
            detailed_analysis = f"Έλαβα το αρχείο **{file.filename}** (αποθηκεύτηκε ως `{filename}`). Είναι έγγραφο ({file_ext}) και μπορώ να το διαβάσω αν μου το ζητήσεις."
            print(f"📄 [Docs]: Το έγγραφο {filename} καταγράφηκε.")
            
            chat_ai_msg = (
                f"📄 **Έγγραφο ελήφθη:** `{filename}` (Αρχικό όνομα: {file.filename})\n\n"
                f"{detailed_analysis}\n\n"
                "**Λάζαρε, θέλεις να το διαβάσω ή να το αρχειοθετήσω;**"
            )
            user_log_msg = f"[USER_UPLOADED_FILE]: {filename}\n[FILE PATH]: {file_path}\n[ANALYSIS]: {memory_analysis}"

        else:
            # Άλλα αρχεία (Zip, exe κλπ.)
            memory_analysis = f"Αρχείο {file_ext} με όνομα {file.filename}."
            detailed_analysis = f"Ανέβηκε ένα αρχείο με κατάληξη {file_ext} στον φάκελο {target_dir}."
            print(f"📁 [File]: Άλλο αρχείο καταγράφηκε.")
            
            chat_ai_msg = (
                f"📁 **Αρχείο ελήφθη:** `{filename}`\n\n"
                f"{detailed_analysis}\n\n"
                "**Λάζαρε, τι θέλεις να κάνω με αυτό;**"
            )
            user_log_msg = f"[USER_UPLOADED_FILE]: {filename}\n[FILE PATH]: {file_path}\n[ANALYSIS]: {memory_analysis}"

        # 5. Ενημέρωση Chat History & Session Log
        append_to_chat_history("user", f"📎 *Ανέβασα αρχείο:* `{filename}`")
        append_to_chat_history("assistant", chat_ai_msg)
        
        log_exchange(user_log_msg, chat_ai_msg, "Chat_Agent")

        return JSONResponse({
            "status": "success",
            "filename": filename,
            "file_path": file_path,
            "url": f"/photos/{filename}" if is_image else None, 
            "ai_message": chat_ai_msg,
            "analysis": memory_analysis,
        })

    except Exception as e:
        import traceback
        print(f"\033[91m[Upload Error]: {traceback.format_exc()}\033[0m")
        return JSONResponse({"status": "error", "message": str(e)}, status_code=500)
@server.get("/history")
async def get_history():
    """Δίνει το ιστορικό στο Web UI — διαβάζει από το JSON για να επιβιώνει το F5/restart."""
    with chat_history_lock:
        history = _load_chat_history()
    return {"history": history}


@server.websocket("/ws/logs")
async def websocket_logs(websocket: WebSocket):
    """Κρατάει το κανάλι ανοιχτό για να δέχεται τα logs"""
    await websocket.accept()
    active_websockets.append(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        active_websockets.remove(websocket)