# ================================================================
# Project: Astakos AI Agent 🦞
# Module:  Reflection Engine — Agent Self-Evaluation
# Runs every night at 03:00 after the analytics engine.
# Analyzes the day's events, writes observations, applies
# automatic changes (confidence > 0.75) or asks (0.5-0.75).
# ================================================================

import os
import json
import sqlite3
import sys
import re
from datetime import datetime, timedelta

# Bootstrap repo root before any project-local imports when this file runs as a script.
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from memory.routine_db import (
    COOLDOWN_DEFAULT_HOURS,
    COOLDOWN_MIN_HOURS,
    COOLDOWN_MAX_HOURS,
    clamp_cooldown_hours,
)

_BASE    = os.path.dirname(os.path.abspath(__file__))
DB_PATH  = os.path.join(_BASE, "..", "astakos_routines.db")
LOG_DIR  = os.path.join(_BASE, "..", "logs", "events")

AUTO_APPLY_THRESHOLD = 0.75   # above this → automatic application
ASK_THRESHOLD        = 0.50   # above this → asks Lazaros
REFLECTION_PENDING   = 0
REFLECTION_APPLIED   = 1
REFLECTION_REJECTED  = -1

# ── DB Setup ─────────────────────────────────────────────────────

def _ensure_table():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS reflections (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at   TEXT NOT NULL,
            source       TEXT,          -- 'routine', 'reminder', 'tool'
            observation  TEXT NOT NULL,
            action       TEXT NOT NULL,
            confidence   REAL NOT NULL,
            lesson       TEXT,
            applied      INTEGER DEFAULT 0,
            applied_at   TEXT,
            routine_id   INTEGER,
            action_value TEXT
        )
    """)
    # Migration for already existing databases (created before routine_id/action_value) —
    # without these, a "yes" in pending reflection with action="increase_cooldown"/"change_time"
    # there was nowhere to apply it (_apply_action sees routine_id=None and falls back
    # in save_to_memory instead of changing the routine).
    cursor = conn.execute("PRAGMA table_info(reflections)")
    existing_cols = {row[1] for row in cursor.fetchall()}
    if "routine_id" not in existing_cols:
        conn.execute("ALTER TABLE reflections ADD COLUMN routine_id INTEGER")
        print("[reflection_engine]: Migration → 'routine_id'")
    if "action_value" not in existing_cols:
        conn.execute("ALTER TABLE reflections ADD COLUMN action_value TEXT")
        print("[reflection_engine]: Migration → 'action_value'")
    conn.commit()
    conn.close()


def _already_reflected(observation: str, action: str, routine_id=None, action_value=None) -> bool:
    """
    Checks if an identical reflection already exists that has either been applied or is awaiting a response.
    This prevents us from rewriting ask-tier duplicates every night.
    """
    try:
        conn = sqlite3.connect(DB_PATH)
        row = conn.execute(
            """
            SELECT id
            FROM reflections
            WHERE observation = ?
              AND action = ?
              AND applied IN (?, ?)
              AND (
                    routine_id = ?
                 OR (routine_id IS NULL AND ? IS NULL)
              )
              AND (
                    action_value = ?
                 OR (action_value IS NULL AND ? IS NULL)
              )
            LIMIT 1
            """,
            (
                observation, action,
                REFLECTION_PENDING, REFLECTION_APPLIED,
                routine_id, routine_id,
                str(action_value) if action_value is not None else None,
                str(action_value) if action_value is not None else None,
            )
        ).fetchone()
        conn.close()
        return row is not None
    except Exception:
        return False


def _normalize_reflection_text(text: str) -> str:
    text = str(text or "").lower().strip()
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"[^\w\s]", "", text)
    return text

def _build_reflection_key(observation: str, action: str, routine_id=None, action_value=None) -> str:
    obs = _normalize_reflection_text(observation)
    act = _normalize_reflection_text(action)
    rid = str(routine_id or "")
    val = _normalize_reflection_text(action_value) if action_value is not None else ""
    return f"{obs}|{act}|{rid}|{val}"

def _build_lesson_key(lesson: str) -> str:
    return _normalize_reflection_text(lesson)

def _save_reflection(source, observation, action, confidence, lesson, applied=False,
                      routine_id=None, action_value=None) -> int:
    """Returns the ID of the record (needed for the Telegram yes/no follow-up)."""
    conn = sqlite3.connect(DB_PATH)
    now  = datetime.now().isoformat(timespec="seconds")
    cursor = conn.execute(
        "INSERT INTO reflections (created_at, source, observation, action, confidence, lesson, applied, applied_at, routine_id, action_value) "
        "VALUES (?,?,?,?,?,?,?,?,?,?)",
        (now, source, observation, action, confidence, lesson, int(applied),
         now if applied else None, routine_id,
         str(action_value) if action_value is not None else None)
    )
    new_id = cursor.lastrowid
    conn.commit()
    conn.close()
    # Audit log
    try:
        from memory.vector_store import _audit_log
        _audit_log(
            "reflection_applied" if applied else "reflection_saved",
            lesson=str(lesson)[:120] if lesson else "",
            observation=str(observation)[:80],
            action=str(action)[:60],
            source=str(source),
        )
    except Exception:
        pass
    return new_id


def load_pending_reflections() -> dict[int, dict]:
    """Loads unapplied ask-tier reflections so that they survive a restart."""
    _ensure_table()
    try:
        conn = sqlite3.connect(DB_PATH)
        rows = conn.execute(
            """
            SELECT id, observation, action, lesson, source, confidence, routine_id, action_value
            FROM reflections
            WHERE applied = ?
            ORDER BY created_at ASC, id ASC
            """,
            (REFLECTION_PENDING,)
        ).fetchall()
        conn.close()
    except Exception as e:
        print(f"⚠️ [Reflection] Load pending failed: {e}")
        return {}

    return {
        row[0]: {
            "id": row[0],
            "observation": row[1],
            "action": row[2],
            "lesson": row[3],
            "source": row[4],
            "confidence": row[5],
            "routine_id": row[6],
            "action_value": row[7],
        }
        for row in rows
    }


def mark_reflection_applied(reflection_id: int) -> None:
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "UPDATE reflections SET applied=?, applied_at=? WHERE id=?",
        (REFLECTION_APPLIED, datetime.now().isoformat(timespec="seconds"), reflection_id)
    )
    conn.commit()
    conn.close()


def mark_reflection_rejected(reflection_id: int) -> None:
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "UPDATE reflections SET applied=?, applied_at=? WHERE id=?",
        (REFLECTION_REJECTED, datetime.now().isoformat(timespec="seconds"), reflection_id)
    )
    conn.commit()
    conn.close()


# ── Data Collection ──────────────────────────────────────────────

def _load_today_events(days_back=1) -> list[dict]:
    """Loads events from the daily log."""
    target = (datetime.now() - timedelta(days=days_back)).strftime("%Y-%m-%d")
    log_file = os.path.join(LOG_DIR, f"{target}.json")
    if not os.path.exists(log_file):
        return []
    try:
        with open(log_file, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def _load_conversation_traces(days_back=1) -> list[dict]:
    """Loads conversation traces from the ExecutionTrace system."""
    try:
        traces_dir = os.path.join(_BASE, "..", "logs", "traces")
        target = (datetime.now() - timedelta(days=days_back)).strftime("%Y-%m-%d")
        trace_file = os.path.join(traces_dir, f"{target}.json")
        if not os.path.exists(trace_file):
            return []
        with open(trace_file, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def _get_routine_stats() -> list[dict]:
    """Routine statistics — ignore_count, mention_count, state, cooldown."""
    try:
        conn   = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, event_name, day_of_week, time_str, state,
                   confidence, ignore_count, mention_count, notify_cooldown_hours
            FROM routines
            WHERE state IN ('active', 'trigger_pending', 'ignored', 'dismissed')
            ORDER BY ignore_count DESC
        """)
        rows = cursor.fetchall()
        conn.close()
        return [
            {
                "id": r[0], "event": r[1], "day": r[2], "time": r[3],
                "state": r[4], "confidence": r[5],
                "ignore_count": r[6] or 0,
                "mention_count": r[7] or 1,
                "cooldown_hours": r[8] or 20,
            }
            for r in rows
        ]
    except Exception:
        return []


# ── LLM Analysis ─────────────────────────────────────────────────

def _analyze_with_llm(events: list, routine_stats: list, traces: list) -> list[dict]:
    """
    Sends data to Gemini and retrieves reflections.
    Returns a list of:
    {observation, action, confidence, lesson, source, routine_id?}
    """
    try:
        import vertexai
        from vertexai.generative_models import GenerativeModel
        from core.brain import HEAVY_MODEL as MAIN_MODEL

        vertexai.init(
            project=os.getenv("PROJECT_ID", "astakos-finall"),
            location=os.getenv("LOCATION", "global")
        )
        model = GenerativeModel(MAIN_MODEL)

        # Summary of traces (conversations)
        trace_summary = []
        for t in traces:  # max 30 traces removed to include all history
            channel  = t.get("channel", "?")
            agent    = t.get("agent", "?")
            user_msg = t.get("user_message", "")
            bot_resp = t.get("response", "").replace("\n", " ")
            tools    = [tc.get("tool", "") for tc in t.get("tool_calls", [])]
            dur      = t.get("duration_ms", 0)
            err      = t.get("error") or any(tc.get("error") for tc in t.get("tool_calls", []))
            loop     = t.get("loop_guard", False)
            line     = f"[{channel}/{agent}] '{user_msg}' -> '{bot_resp}' tools={tools} dur={dur}ms"
            if err:   line += " ❌error"
            if loop:  line += " 🔁loop"
            trace_summary.append(line)

        # Summary of routines
        routine_summary = []
        for r in routine_stats:
            routine_summary.append(
                f"Routine #{r['id']} '{r['event']}' ({r['day']} {r['time']}): "
                f"state={r['state']}, ignores={r['ignore_count']}, "
                f"mentions={r['mention_count']}, cooldown={r['cooldown_hours']}h"
            )

        prompt = f"""Είσαι ο Αστακός, ένας AI agent που κάνει νυχτερινό self-reflection.
Αναλύεις τις συνομιλίες και τις ρουτίνες της χθεσινής μέρας.
Σκοπός: να βρεις patterns, λάθη ή βελτιώσεις — και να τα καταγράψεις ως lessons.

ΣΥΝΟΜΙΛΙΕΣ ΧΘΕΣ ({len(traces)} συνολικά):
{chr(10).join(trace_summary) if trace_summary else "Δεν υπάρχουν."}

ΣΤΑΤΙΣΤΙΚΑ ΡΟΥΤΙΝΩΝ:
{chr(10).join(routine_summary) if routine_summary else "Δεν υπάρχουν ρουτίνες."}

Γράψε ένα JSON array με observations. Κάθε observation:
{{
  "source": "conversation" | "routine" | "general",
  "routine_id": <int or null>,
  "observation": "<1 sentence>",
  "action": "increase_cooldown" | "reduce_frequency" | "change_time" | "save_to_memory",
  "action_value": <number or null>,
  "confidence": <0.0-1.0>,
  "severity": "low" | "medium" | "high",
  "confidence_reason": "<short reason>",
  "source_events": ["<short event 1>", "<short event 2>"],
  "lesson": "<1 sentence>"
}}

ΚΑΝΟΝΕΣ:
- Μην επιστρέφεις 2 observations που λένε ουσιαστικά το ίδιο πράγμα με άλλο wording.
- Για action="save_to_memory", πρότεινέ το μόνο αν το lesson είναι σταθερό και γενικεύσιμο, όχι στιγμιαίο noise.
- Αν 2 observations είναι κοντινά, κράτα μόνο το πιο δυνατό.
- Για ρουτίνες: αν ignore_count >= 2 → πρότεινε αλλαγή
- Για συνομιλίες: αν βλέπεις επαναλαμβανόμενα errors, loops, ή patterns → καταγράψτο ως lesson με action="save_to_memory"
- confidence > 0.75 μόνο αν είσαι σίγουρος
- Μέγιστο 5 observations
- Αν δεν υπάρχει τίποτα αξιοσημείωτο: επέστρεψε []
- Απάντησε ΜΟΝΟ με JSON, χωρίς εξήγηση"""

        response = model.generate_content(prompt)
        text = response.text.strip()

        # Markdown cleaning Regardless of whether you need to translate "Καθαρισμός markdown" to "Markdown cleaning" or "Markdown cleanup", here is the direct translation:

# Markdown cleanup_
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
        text = text.strip().rstrip("```").strip()

        return json.loads(text) if text else []

    except Exception as e:
        print(f"⚠️ [ReflectionEngine] LLM error: {e}")
        return []


# ── Action Executor ───────────────────────────────────────────────

def _apply_action(reflection: dict) -> bool:
    """
    Applies a change to the database based on the action.
    Returns True if it was applied.
    """
    action     = reflection.get("action", "")
    routine_id = reflection.get("routine_id")
    value      = reflection.get("action_value")

    # save_to_memory or actions without routine_id (usually planner/conversations)
    # must be saved as lesson.
    if action == "save_to_memory" or not routine_id:
        lesson = reflection.get("lesson", "")
        if lesson:
            try:
                from memory.vector_store import vector_store
                vector_store.add_texts(
                    [f"[REFLECTION]: {lesson}"],
                    metadatas=[{"category": "reflection", "source": "reflection_engine"}]
                )
                print(f"🧠 [Reflection]: Lesson saved to ChromaDB")
                return True
            except Exception as me:
                print(f"⚠️ [Reflection] ChromaDB save failed: {me}")
                return False
        
        # If the action requires a routine_id but it does not exist, abort.
        if not routine_id:
            return False
        # If the action is save_to_memory but has no lesson, abort.
        if action == "save_to_memory":
            return False

    try:
        conn = sqlite3.connect(DB_PATH)

        if action == "increase_cooldown" and value:
            new_cd = clamp_cooldown_hours(value)
            conn.execute(
                "UPDATE routines SET notify_cooldown_hours=? WHERE id=?",
                (new_cd, routine_id)
            )
            print(f"🔧 [Reflection]: #{routine_id} cooldown → {new_cd}h")

        elif action == "reduce_frequency":
            row = conn.execute(
                "SELECT notify_cooldown_hours FROM routines WHERE id=?",
                (routine_id,)
            ).fetchone()
            current_cd = clamp_cooldown_hours(
                row[0] if row and row[0] is not None else COOLDOWN_DEFAULT_HOURS
            )
            new_cd = clamp_cooldown_hours(current_cd * 2)
            conn.execute(
                "UPDATE routines SET notify_cooldown_hours=? WHERE id=?",
                (new_cd, routine_id)
            )
            print(f"🔧 [Reflection]: #{routine_id} frequency reduced → cooldown {new_cd}h")

        elif action == "change_time" and value:
            # Sanitize: float 14.5 → "14:30", int/str "14" → "14:00"
            try:
                fval = float(str(value))
                hours = int(fval)
                mins  = int(round((fval - hours) * 60))
                time_str = f"{hours:02d}:{mins:02d}"
            except (ValueError, TypeError):
                time_str = str(value)  # if it is already "HH:MM", we keep it as is
            conn.execute(
                "UPDATE routines SET time_str=? WHERE id=?",
                (time_str, routine_id)
            )
            print(f"🔧 [Reflection]: #{routine_id} time → {time_str} (raw: {value})")

        elif action == "save_to_memory":
            # This is a fallback in case it slips through, though the block above handles it.
            return False

        conn.commit()
        conn.close()
        return True

    except Exception as e:
        print(f"⚠️ [Reflection] Apply action failed: {e}")
        return False


# ── Main Entry Point ──────────────────────────────────────────────

def run_reflection() -> dict:
    """
    Main function. Runs after the analytics engine.
    Returns stats: {analyzed, applied, pending, skipped}
    """
    from tools.telegram import send_telegram_msg

    print("[Reflection]: Starting self-evaluation...")
    _ensure_table()

    events        = _load_today_events(days_back=1)
    routine_stats = _get_routine_stats()
    traces        = _load_conversation_traces(days_back=1)

    print(f"[Reflection]: events={len(events)}, routines={len(routine_stats)}, traces={len(traces)}")

    if not events and not routine_stats and not traces:
        print("[Reflection]: No data for analysis.")
        return {"analyzed": 0, "applied": 0, "pending": 0, "skipped": 0}

    reflections = _analyze_with_llm(events, routine_stats, traces)

    if not reflections:
        print("[Reflection]: No observations found.")
        return {"analyzed": 0, "applied": 0, "pending": 0, "skipped": 0}

    applied = pending = skipped = 0
    telegram_lines = []
    pending_items = []   # [{"id":, "observation":, "action":, "routine_id":, "action_value":, "lesson":, "source":}, ...]

    seen_reflection_keys = set()
    seen_lesson_keys = set()

    for r in reflections:
        obs          = r.get("observation", "")
        action       = r.get("action", "")
        confidence   = float(r.get("confidence", 0))
        lesson       = r.get("lesson", "")
        source       = r.get("source", "general")
        routine_id   = r.get("routine_id")
        action_value = r.get("action_value")

        if not obs or not action:
            skipped += 1
            continue

        reflection_key = _build_reflection_key(obs, action, routine_id=routine_id, action_value=action_value)
        lesson_key = _build_lesson_key(lesson)

        if reflection_key in seen_reflection_keys:
            skipped += 1
            continue

        seen_reflection_keys.add(reflection_key)

        # Skip if the same observation+action has already been applied
        if _already_reflected(obs, action, routine_id=routine_id, action_value=action_value):
            print(f"[Reflection]: ⏭ Skip duplicate: '{obs[:40]}...'")
            skipped += 1
            continue

        if action == "save_to_memory" and lesson_key:
            if lesson_key in seen_lesson_keys:
                skipped += 1
                continue
            seen_lesson_keys.add(lesson_key)

        if confidence >= AUTO_APPLY_THRESHOLD:
            # Automatic application
            success = _apply_action(r)
            _save_reflection(source, obs, action, confidence, lesson, applied=success,
                              routine_id=routine_id, action_value=action_value)
            if success:
                applied += 1
                telegram_lines.append(f"✅ *{obs}*\n→ Applied: `{action}`\n💡 _{lesson}_")
            else:
                skipped += 1

        elif confidence >= ASK_THRESHOLD:
            # Asks Lazaros — we keep the id so that a "yes" on Telegram can
            # to apply THIS reflection specifically (see clients/telegram_bot.py)
            new_id = _save_reflection(source, obs, action, confidence, lesson, applied=False,
                                       routine_id=routine_id, action_value=action_value)
            pending += 1
            pending_items.append({
                "id": new_id, "observation": obs, "action": action,
                "routine_id": routine_id, "action_value": action_value,
                "lesson": lesson, "source": source, "confidence": confidence,
            })
            # Note: We DO NOT send the "Should I apply it?" message here.
            # telegram_bot.py builds ONE numbered message for ALL current items
            # pending (old + new) so that numbers #1, #2... correspond correctly
            # for whatever is awaiting a response — see pending_reflection_confirmations.
        else:
            # Low confidence — saving only
            _save_reflection(source, obs, action, confidence, lesson, applied=False,
                              routine_id=routine_id, action_value=action_value)
            skipped += 1

    # Telegram Send
    if telegram_lines:
        header = "🧠 *Astakos Self-Reflection — Nightly Analysis*\n\n"
        msg    = header + "\n\n---\n\n".join(telegram_lines)
        if len(msg) > 4000:
            msg = msg[:3990] + "..."
        send_telegram_msg(msg, disable_notification=True)

    stats = {
        "analyzed": len(reflections), "applied": applied, "pending": pending,
        "skipped": skipped, "pending_items": pending_items,
    }
    print(f"[Reflection]: ✅ {stats}")
    return stats


if __name__ == "__main__":
    print(run_reflection())
