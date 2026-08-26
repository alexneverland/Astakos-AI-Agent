# ================================================================
# Project: Astakos AI Agent 🦞
# Developer: User
# Description: Modular LLM-agnostic multi-agent framework
# Copyright (c) 2026 - All Rights Reserved
# ================================================================

"""
main.py — Astakos CLI Entry Point
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Run: python main.py

Alternatively:
  API Server  → uvicorn api.server:server --reload
  Telegram Bot → python clients/telegram_bot.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

import os
import sys
import sqlite3
import time
import queue
import signal
import asyncio
import threading
from datetime import datetime
from zoneinfo import ZoneInfo

from langchain_core.messages import HumanMessage, AIMessage
from rich.console import Console

from config import STATE_DB, USER_NAME, KID1_NAME
from core.brain import llm, safe_llm_invoke
from core.graph import graph
from core.agents import clean_message
from memory.working_memory import update_working_memory, update_capabilities_from_exchange
from core.utils import load_agent_prompt
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
    print("\033[90m[System]: Queue Worker Started!\033[0m")
    while not shutdown_event.is_set():
        try:
            task_func, args = astakos_queue.get(timeout=2)
            try:
                task_func(*args)
            except Exception as e:
                print(f"\033[91m[Queue Task Error in {task_func.__name__}]: {e}\033[0m")
            finally:
                astakos_queue.task_done()
        except queue.Empty:
            continue


def reminder_worker():
    while not shutdown_event.is_set():
        if os.path.exists(STATE_DB):
            now = datetime.now().strftime("%Y-%m-%d %H:%M")
            conn = None
            try:
                conn = sqlite3.connect(STATE_DB)
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT id, task FROM reminders WHERE status='pending' AND time NOT LIKE 'loc:%' AND time <= ?",
                    (now,),
                )
                due = cursor.fetchall()
                for rid, task in due:
                    print(f"\n\033[93m[🔔 REMINDER]: {task}\033[0m\n{USER_NAME}: ", end="", flush=True)
                    send_telegram_msg(f"🔔 REMINDER: {task}")
                    cursor.execute("UPDATE reminders SET status='done' WHERE id=?", (rid,))
                conn.commit()
            except Exception as e:
                print(f"\033[91m[ReminderWorker Error]: {e}\033[0m")
            finally:
                if conn:
                    conn.close()
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
                    time_context = "Morning: Good morning Master, coding for Mastroapp/Astakos?"
                elif current_hour < 17:
                    time_context = f"Noon: Joking about {KID1_NAME}/LEGO/lentils."
                else:
                    time_context = "Evening: Relaxation, Netflix or the rabbit."

                base_poke_prompt = load_agent_prompt("main_poke", f"You are Astakos. 2.5 hours of silence have passed. Poke {USER_NAME} briefly.")
                poke_prompt = f"{base_poke_prompt}\nCONTEXT: {time_context}"

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
    """Runs session summary with a 5s timeout."""
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
        print("\033[93m[System]: Summary timeout — skipping.\033[0m")


# ────────────────────────────────────────────────────────────────
# MAIN LOOP
# ────────────────────────────────────────────────────────────────

def main():
    global last_interaction_time

    from memory.list_store import init_list_store
    from memory.reminder_store import init_reminder_store
    init_list_store()
    init_reminder_store()

    # Start workers
    threading.Thread(target=reminder_worker,  daemon=True).start()
    threading.Thread(target=proactive_worker, daemon=True).start()
    threading.Thread(target=queue_worker,     daemon=True).start()

    try:
        from core.diagnostics import format_boot_diagnostics_text
        print("\n" + format_boot_diagnostics_text())
    except Exception:
        pass

    print("\n" + "━" * 52)
    print("  🦞  Astakos — CLI Mode")
    print("  Type 'exit' or press Ctrl+C to quit.")
    print("━" * 52 + "\n")


    try:
        while not shutdown_event.is_set():
            try:
                inp = input(f"{USER_NAME}: ")
            except EOFError:
                break

            if inp.strip().lower() in ("exit", "quit"):
                print("\n[System]: Terminating and archiving...")
                shutdown_event.set()
                break

            if not inp.strip():
                continue

            with memory_lock:
                last_interaction_time = time.time()

            final_ai_response = ""
            handling_agent    = "Chat_Agent"

            try:
                events = list(graph.stream({"messages": [HumanMessage(content=inp)]}))
                for event in events:
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
                                        f"\n[bold green][Astakos ({handling_agent})]:[/bold green] "
                                        f"{final_ai_response}"
                                    )

                if final_ai_response:
                    from core.untrusted_content import external_tool_names_from_events
                    external_content_sources = external_tool_names_from_events(events)
                    if external_content_sources:
                        print("[Security]: external-derived reply - use trusted user text only for background state")
                        enqueue_task(update_working_memory, inp, "")
                        enqueue_task(trigger_memory_sifter, inp, "", handling_agent, "terminal", False)
                        enqueue_task(log_exchange, inp, "", handling_agent, "terminal")
                    else:
                        enqueue_task(update_working_memory,             inp, final_ai_response)
                        enqueue_task(trigger_memory_sifter,             inp, final_ai_response, handling_agent, "terminal")
                        enqueue_task(log_exchange,                      inp, final_ai_response, handling_agent, "terminal")
                        enqueue_task(update_capabilities_from_exchange, inp, final_ai_response, handling_agent)

            except Exception as e:
                import traceback
                traceback.print_exc()
                print(f"\033[91m[Graph Error]: {e}\033[0m")

    except KeyboardInterrupt:
        print("\n[System]: Ctrl+C — Terminating...")
        shutdown_event.set()
    finally:
        shutdown_event.set()
        
        try:
            from memory.vector_store import close_vector_store
            close_vector_store()
        except Exception:
            pass
            
        _do_session_summary()

    print("[System]: Goodbye! 🦞")


if __name__ == "__main__":
    main()
