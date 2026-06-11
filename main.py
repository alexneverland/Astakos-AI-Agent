# ================================================================
# Project: Astakos AI Agent 🦞
# Developer: Lazaros (Piston-7)
# Description: Modular LLM-agnostic multi-agent framework
# Copyright (c) 2026 - All Rights Reserved
# ================================================================

"""
main.py — CLI Entry Point του Αστακού
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Τρέξε: python main.py

Εναλλακτικά:
  API Server  → uvicorn api.server:server --reload
  Telegram Bot → python clients/telegram_bot.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

import os
import sys
import json
import time
import queue
import signal
import asyncio
import threading
from datetime import datetime
from zoneinfo import ZoneInfo

from langchain_core.messages import HumanMessage, AIMessage
from rich.console import Console

from config import REMINDERS_FILE
from core.brain import llm, safe_llm_invoke
from core.graph import graph
from core.agents import clean_message
from memory.working_memory import update_working_memory, update_capabilities_from_exchange
from memory.session_memory import trigger_memory_sifter, log_exchange, _run_session_summary
from tools.telegram import send_telegram_msg

console = Console()

# ────────────────────────────────────────────────────────────────
# GLOBALS
# ────────────────────────────────────────────────────────────────
shutdown_event        = threading.Event()
astakos_queue         = queue.Queue()
memory_lock           = threading.Lock()
last_interaction_time = time.time()
_summary_done        = threading.Event()


def enqueue_task(func, *args):
    astakos_queue.put((func, args))


# ────────────────────────────────────────────────────────────────
# WORKERS
# ────────────────────────────────────────────────────────────────

def queue_worker():
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


def reminder_worker():
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
                    print(f"\n\033[93m[🔔 ΥΠΕΝΘΥΜΙΣΗ]: {r['task']}\033[0m\nΛάζαρος: ", end="", flush=True)
                    send_telegram_msg(f"🔔 ΥΠΕΝΘΥΜΙΣΗ: {r['task']}")
                    r["status"], changed = "done", True
            if changed:
                with open(REMINDERS_FILE, "w", encoding="utf-8") as f:
                    json.dump(rems, f, ensure_ascii=False, indent=4)
        shutdown_event.wait(timeout=20)


def proactive_worker():
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
                    f"ΚΑΝΟΝΕΣ: ΜΟΝΟ Ελληνικά, 1-2 προτάσεις, Mastro-style χιούμορ, κλείσε με ερώτηση."
                )

                if shutdown_event.is_set():
                    break

                try:
                    response = safe_llm_invoke(llm, [HumanMessage(content=poke_prompt)])
                    if shutdown_event.is_set():
                        break

                    ai_msg = clean_message(response.content).strip()
                    print(f"\n🤖 [Proactive]: {ai_msg}")
                    send_telegram_msg(f"🤖 {ai_msg}")

                    with memory_lock:
                        enqueue_task(log_exchange, "POKE_EVENT", ai_msg, "Proactive_Worker", "terminal")

                except Exception as e:
                    print(f"\n[Proactive Worker Error]: {e}")


# ────────────────────────────────────────────────────────────────
# GRACEFUL SHUTDOWN
# ────────────────────────────────────────────────────────────────

def _graceful_exit(*args):
    shutdown_event.set()
    raise KeyboardInterrupt


signal.signal(signal.SIGTERM, _graceful_exit)
signal.signal(signal.SIGINT,  _graceful_exit)


def _drain_queue(timeout: float = 5.0) -> None:
    try:
        done = threading.Event()

        def _drain():
            astakos_queue.join()
            done.set()

        threading.Thread(target=_drain, daemon=True).start()
        done.wait(timeout=timeout)
    except Exception:
        pass


def _do_session_summary():
    """Τρέχει session summary με timeout 5s."""
    if _summary_done.is_set():
        return
    _summary_done.set()
    _drain_queue(timeout=5.0)
    try:
        loop = asyncio.new_event_loop()
        loop.run_until_complete(asyncio.wait_for(
            loop.run_in_executor(None, lambda: _run_session_summary("terminal")),
            timeout=5.0
        ))
    except (asyncio.TimeoutError, Exception):
        print("\033[93m[System]: Summary timeout — παράκαμψη.\033[0m")


# ────────────────────────────────────────────────────────────────
# MAIN LOOP
# ────────────────────────────────────────────────────────────────

def main():
    global last_interaction_time

    # Εκκίνηση workers
    threading.Thread(target=reminder_worker,  daemon=True).start()
    threading.Thread(target=proactive_worker, daemon=True).start()
    threading.Thread(target=queue_worker,     daemon=True).start()

    print("\n" + "━" * 52)
    print("  🦞  Αστακός — CLI Mode")
    print("  Γράψε 'exit' ή πάτα Ctrl+C για έξοδο.")
    print("━" * 52 + "\n")

    try:
        while not shutdown_event.is_set():
            try:
                inp = input("Λάζαρος: ")
            except EOFError:
                break

            if inp.strip().lower() in ("exit", "quit"):
                print("\n[System]: Τερματισμός και αρχειοθέτηση...")
                shutdown_event.set()
                break

            if not inp.strip():
                continue

            with memory_lock:
                last_interaction_time = time.time()

            final_ai_response = ""
            handling_agent    = "Chat_Agent"

            try:
                for event in graph.stream({"messages": [HumanMessage(content=inp)]}):
                    for node, data in event.items():
                        if data is None:
                            continue
                        if node not in ["supervisor", "tools"]:
                            handling_agent = node
                            msgs = data.get("messages", [])
                            if msgs and hasattr(msgs[-1], "content"):
                                candidate = clean_message(msgs[-1].content).strip()
                                if candidate:
                                    final_ai_response = candidate
                                    console.print(
                                        f"\n[bold green][Αστακός ({handling_agent})]:[/bold green] "
                                        f"{final_ai_response}"
                                    )

                if final_ai_response:
                    enqueue_task(update_working_memory,             inp, final_ai_response)
                    enqueue_task(trigger_memory_sifter,             inp, final_ai_response, handling_agent, "terminal")
                    enqueue_task(log_exchange,                      inp, final_ai_response, handling_agent, "terminal")
                    enqueue_task(update_capabilities_from_exchange, inp, final_ai_response, handling_agent)

            except Exception as e:
                import traceback
                traceback.print_exc()
                print(f"\033[91m[Graph Error]: {e}\033[0m")

    except KeyboardInterrupt:
        print("\n[System]: Ctrl+C — Τερματισμός...")
        shutdown_event.set()
    finally:
        shutdown_event.set()
        _do_session_summary()

    print("[System]: Αντίο, Μάστορη! 🦞")


if __name__ == "__main__":
    main()
