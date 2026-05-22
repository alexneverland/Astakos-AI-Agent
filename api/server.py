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
        },
    })


@server.get("/debug")
async def debug_panel():
    """Observability HTML dashboard — auto-refresh κάθε 5 δευτερόλεπτα."""
    from fastapi.responses import HTMLResponse
    html = """<!DOCTYPE html>
<html lang="el">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>🦞 Astakos Runtime Dashboard</title>
<style>
  :root {
    --bg:      #0d1117; --card:  #161b22; --border: #30363d;
    --text:    #e6edf3; --muted: #8b949e; --green:  #3fb950;
    --red:     #f85149; --yellow:#d29922; --blue:   #58a6ff;
    --purple:  #bc8cff; --orange:#f0883e;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { background: var(--bg); color: var(--text); font-family: 'Segoe UI', monospace; font-size: 13px; padding: 16px; }
  h1   { font-size: 20px; margin-bottom: 4px; }
  .ts  { color: var(--muted); font-size: 11px; margin-bottom: 16px; }
  .grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(340px, 1fr)); gap: 12px; }
  .card { background: var(--card); border: 1px solid var(--border); border-radius: 8px; padding: 14px; }
  .card h2 { font-size: 13px; color: var(--muted); text-transform: uppercase; letter-spacing: .05em; margin-bottom: 10px; }
  table { width: 100%; border-collapse: collapse; }
  th    { color: var(--muted); font-weight: 600; font-size: 11px; text-transform: uppercase; padding: 4px 6px; text-align: left; border-bottom: 1px solid var(--border); }
  td    { padding: 5px 6px; border-bottom: 1px solid #21262d; vertical-align: top; }
  tr:last-child td { border-bottom: none; }
  .ok   { color: var(--green); }
  .warn { color: var(--yellow); }
  .err  { color: var(--red); }
  .off  { color: var(--muted); }
  .badge { display: inline-block; padding: 1px 7px; border-radius: 10px; font-size: 11px; font-weight: 600; }
  .b-green  { background: #1a3a1f; color: var(--green); }
  .b-yellow { background: #3a2d0a; color: var(--yellow); }
  .b-red    { background: #3a0d0d; color: var(--red); }
  .b-blue   { background: #0d2240; color: var(--blue); }
  .b-purple { background: #220d3a; color: var(--purple); }
  .b-orange { background: #3a1e0a; color: var(--orange); }
  .b-muted  { background: #1c2128; color: var(--muted); }
  .kv   { display: flex; justify-content: space-between; padding: 4px 0; border-bottom: 1px solid #21262d; }
  .kv:last-child { border-bottom: none; }
  .kv .k { color: var(--muted); }
  .kv .v { font-weight: 600; }
  .bar-wrap { background: #21262d; border-radius: 4px; height: 6px; width: 100%; margin-top: 3px; }
  .bar-fill { height: 6px; border-radius: 4px; background: var(--green); transition: width .4s; }
  #refresh-bar { height: 2px; background: var(--blue); transition: width .1s linear; position: fixed; top:0; left:0; z-index:99; }
  .stale { color: var(--red); font-size: 11px; }
</style>
</head>
<body>
<div id="refresh-bar" style="width:0%"></div>
<h1>🦞 Astakos Runtime Dashboard</h1>
<div class="ts" id="ts">Φόρτωση...</div>
<div class="grid" id="grid"></div>

<script>
const REFRESH = 5000;
let countdown = REFRESH;
let rafId;

function stateBadge(state) {
  const m = {
    'active':          ['b-green',  'ACTIVE'],
    'trigger_pending': ['b-yellow', 'TRIGGER_PENDING'],
    'confirmed':       ['b-blue',   'CONFIRMED'],
    'ignored':         ['b-orange', 'IGNORED'],
    'dismissed':       ['b-purple', 'DISMISSED'],
    'decayed':         ['b-red',    'DECAYED'],
    'archived':        ['b-muted',  'ARCHIVED'],
    'learned':         ['b-muted',  'LEARNED'],
  };
  const [cls, label] = m[state] || ['b-muted', state];
  return `<span class="badge ${cls}">${label}</span>`;
}

function jobRow(j) {
  const icon = j.disabled ? '🚫' : j.fail_count > 0 ? '⚠️' : '✅';
  const nextLabel = j.disabled ? '—' : `${j.next_in_secs}s`;
  const dur  = j.last_duration != null ? `${j.last_duration.toFixed(2)}s` : '—';
  const failCls = j.fail_count > 0 ? 'warn' : 'ok';
  return `<tr>
    <td>${icon} <b>${j.name}</b></td>
    <td class="off">${j.last_run || '—'}</td>
    <td class="${j.disabled?'err':'ok'}">${nextLabel}</td>
    <td>${dur}</td>
    <td class="${failCls}">${j.fail_count}</td>
  </tr>${j.last_error ? `<tr><td colspan="5" class="err" style="font-size:11px;padding:2px 6px 6px">↳ ${j.last_error}</td></tr>` : ''}\`;
}

function confBar(val) {
  const pct = Math.round(val * 100);
  const col = val >= 0.8 ? 'var(--green)' : val >= 0.5 ? 'var(--yellow)' : 'var(--red)';
  return `${pct}% <div class="bar-wrap"><div class="bar-fill" style="width:${pct}%;background:${col}"></div></div>`;
}

function stateBadge(state) {
  const m = {
    'active':          ['b-green',  'ACTIVE'],
    'trigger_pending': ['b-yellow', 'TRIGGER_PENDING'],
    'confirmed':       ['b-blue',   'CONFIRMED'],
    'ignored':         ['b-orange', 'IGNORED'],
    'dismissed':       ['b-purple', 'DISMISSED'],
    'decayed':         ['b-red',    'DECAYED'],
    'archived':        ['b-muted',  'ARCHIVED'],
    'learned':         ['b-muted',  'LEARNED'],
  };
  const [cls, label] = m[state] || ['b-muted', state];
  return `<span class="badge ${cls}">${label}</span>`;
}

function render(d) {
  const s     = d.scheduler || {};
  const ovr   = d.overrides || {};
  const rout  = d.routines  || {};
  const evts  = d.events_1h || {};
  const pend  = d.pending_confirmations || [];

  const stale = d.snapshot_age_s != null && d.snapshot_age_s > 30;
  const ageStr = d.snapshot_age_s != null ? `(snapshot ${d.snapshot_age_s}s ago${stale ? ' ⚠️ STALE' : ''})` : '(telegram_bot offline?)';

  document.getElementById('ts').innerHTML =
    `Τελευταία ανανέωση: <b>${new Date().toLocaleTimeString('el-GR')}</b> &nbsp;${ageStr}`;

  const flags = [];
  if (ovr.sleeping)        flags.push(`<span class="badge b-red">😴 Sleep until ${ovr.sleep_until}</span>`);
  if (ovr.pause_reminders) flags.push('<span class="badge b-yellow">⏸ Reminders Paused</span>');
  if (ovr.mute_proactive)  flags.push('<span class="badge b-yellow">🔇 Proactive Muted</span>');
  if (s.quiet_hours)       flags.push('<span class="badge b-muted">🌙 Quiet Hours</span>');

  let html = '';

  html += `<div class="card"><h2>⚙️ Scheduler Jobs</h2>
    ${flags.length ? '<div style="margin-bottom:8px">' + flags.join(' ') + '</div>' : ''}
    <table>
      <tr><th>Job</th><th>Last Run</th><th>Next</th><th>Dur</th><th>Fails</th></tr>
      ${(s.jobs||[]).map(jobRow).join('')}
    </table></div>`;

  html += `<div class="card"><h2>📊 Queue & Rate</h2>
    <div class="kv"><span class="k">Queue size</span><span class="v ${s.queue_size>5?'warn':''}">${ s.queue_size ?? '?'}</span></div>
    <div class="kv"><span class="k">Proactive this hour</span><span class="v">${s.proactive_this_hour ?? 0} / 3</span></div>
    <div class="kv"><span class="k">Pending confirmations</span><span class="v ${s.pending_count>0?'warn':''}">${ s.pending_count ?? 0}</span></div>
    <div class="kv"><span class="k">Total events today</span><span class="v">${evts.total_today ?? 0}</span></div>
  </div>`;

  if (pend.length > 0) {
    html += `<div class="card"><h2>⏳ Pending Confirmations</h2>
      <table><tr><th>ID</th><th>Event</th><th>Elapsed</th><th>Timeout in</th></tr>
      ${pend.map(p => `<tr>
          <td class="off">#${p.routine_id}</td><td>${p.event}</td>
          <td class="${p.elapsed_min>25?'warn':''}">${ p.elapsed_min}m</td>
          <td class="${p.timeout_in_min<5?'err':'ok'}">${p.timeout_in_min}m</td>
        </tr>`).join('')}
      </table></div>`;
  }

  if ((rout.active||[]).length > 0) {
    html += `<div class="card" style="grid-column: span 2"><h2>🗓️ Active Routines (${rout.active.length})</h2>
      <table><tr><th>ID</th><th>Day</th><th>Time</th><th>Event</th><th>Confidence</th><th>Cooldown left</th><th>State</th></tr>
      ${rout.active.map(r => `<tr>
          <td class="off">#${r.id}</td><td>${r.day}</td><td><b>${r.time}</b></td>
          <td>${r.event}</td>
          <td style="min-width:80px">${confBar(r.confidence)}</td>
          <td class="${r.cooldown_remaining_h===0?'ok':r.cooldown_remaining_h>10?'err':'warn'}">${r.cooldown_remaining_h!=null ? r.cooldown_remaining_h+'h' : '\u2014'}</td>
          <td>${stateBadge(r.state)}</td>
        </tr>`).join('')}
      </table></div>`;
  }

  const sc = rout.state_counts || {};
  if (Object.keys(sc).length > 0) {
    html += `<div class="card"><h2>\ud83d\udcc8 Routine State Counts</h2>
      ${Object.entries(sc).map(([st,c]) => `<div class="kv"><span class="k">${stateBadge(st)}</span><span class="v">${c}</span></div>`).join('')}
    </div>`;
  }

  if ((rout.non_active||[]).length > 0) {
    html += `<div class="card"><h2>\ud83d\udd04 Non-Active Routines</h2>
      <table><tr><th>ID</th><th>Event</th><th>State</th><th>Conf</th></tr>
      ${rout.non_active.map(r => `<tr>
          <td class="off">#${r.id}</td><td>${r.event}</td>
          <td>${stateBadge(r.state)}</td>
          <td class="${r.confidence<0.1?'err':r.confidence<0.5?'warn':'ok'}">${r.confidence}</td>
        </tr>`).join('')}
      </table></div>`;
  }

  const tp = evts.throughput || {};
  if (Object.keys(tp).length > 0) {
    const max_tp = Math.max(...Object.values(tp), 1);
    html += `<div class="card"><h2>\u26a1 Event Throughput (last 1h)</h2>
      ${Object.entries(tp).sort((a,b)=>b[1]-a[1]).map(([k,v]) => {
        const pct = Math.round(v/max_tp*100);
        return `<div style="margin-bottom:5px">
          <div style="display:flex;justify-content:space-between"><span class="off">${k}</span><b>${v}</b></div>
          <div class="bar-wrap"><div class="bar-fill" style="width:${pct}%;background:var(--blue)"></div></div>
        </div>`;
      }).join('')}
    </div>`;
  }

  if ((evts.last_errors||[]).length > 0) {
    html += `<div class="card"><h2>\u274c Last Errors (1h)</h2>
      ${evts.last_errors.map(e => `<div style="margin-bottom:6px;font-size:12px">
        <span class="off">${e.time}</span> <span class="warn">[${e.job}]</span><br>
        <span class="err">${e.error}</span>
      </div>`).join('')}
    </div>`;
  }

  document.getElementById('grid').innerHTML = html;
}

async function fetchData() {
  try {
    const r = await fetch('/debug/runtime');
    const d = await r.json();
    render(d);
  } catch(e) {
    document.getElementById('ts').innerHTML = `<span class="err">\u03a3\u03c6\u03ac\u03bb\u03bc\u03b1 \u03c6\u03cc\u03c1\u03c4\u03c9\u03c3\u03b7\u03c2: ${e}</span>`;
  }
}

function startCountdown() {
  cancelAnimationFrame(rafId);
  const bar = document.getElementById('refresh-bar');
  const start = performance.now();
  function tick(now) {
    const elapsed = now - start;
    const pct = Math.min(100, (elapsed / REFRESH) * 100);
    bar.style.width = pct + '%';
    if (elapsed < REFRESH) { rafId = requestAnimationFrame(tick); }
    else { fetchData(); startCountdown(); }
  }
  rafId = requestAnimationFrame(tick);
}

fetchData();
startCountdown();
</script>
</body>
</html>"""
    return HTMLResponse(content=html)
