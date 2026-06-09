# ================================================================
# Project: Astakos AI Agent 🦞
# Module:  Reflection Engine — Agent Self-Evaluation
# Τρέχει κάθε βράδυ 03:00 μετά το analytics engine.
# Αναλύει events της μέρας, γράφει observations, εφαρμόζει
# αλλαγές αυτόματα (confidence > 0.75) ή ρωτάει (0.5-0.75).
# ================================================================

import os
import json
import sqlite3
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime, timedelta

_BASE    = os.path.dirname(os.path.abspath(__file__))
DB_PATH  = os.path.join(_BASE, "..", "astakos_routines.db")
LOG_DIR  = os.path.join(_BASE, "..", "logs", "events")

AUTO_APPLY_THRESHOLD = 0.75   # πάνω από αυτό → αυτόματη εφαρμογή
ASK_THRESHOLD        = 0.50   # πάνω από αυτό → ρωτάει τον Λάζαρο
COOLDOWN_MAX         = 168    # max cooldown ώρες (7 μέρες)

# ── DB Setup ─────────────────────────────────────────────────────

def _ensure_table():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS reflections (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at  TEXT NOT NULL,
            source      TEXT,          -- 'routine', 'reminder', 'tool'
            observation TEXT NOT NULL,
            action      TEXT NOT NULL,
            confidence  REAL NOT NULL,
            lesson      TEXT,
            applied     INTEGER DEFAULT 0,
            applied_at  TEXT
        )
    """)
    conn.commit()
    conn.close()


def _save_reflection(source, observation, action, confidence, lesson, applied=False):
    conn = sqlite3.connect(DB_PATH)
    now  = datetime.now().isoformat(timespec="seconds")
    conn.execute(
        "INSERT INTO reflections (created_at, source, observation, action, confidence, lesson, applied, applied_at) VALUES (?,?,?,?,?,?,?,?)",
        (now, source, observation, action, confidence, lesson, int(applied), now if applied else None)
    )
    conn.commit()
    conn.close()


# ── Data Collection ──────────────────────────────────────────────

def _load_today_events(days_back=1) -> list[dict]:
    """Φορτώνει events από το daily log."""
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
    """Φορτώνει conversation traces από το ExecutionTrace σύστημα."""
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
    """Στατιστικά ρουτινών — ignore_count, mention_count, state, cooldown."""
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
    Στέλνει δεδομένα στο Gemini και παίρνει reflections.
    Επιστρέφει λίστα από:
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

        # Σύνοψη traces (conversations)
        trace_summary = []
        for t in traces[-30:]:  # max 30 traces
            channel  = t.get("channel", "?")
            agent    = t.get("agent", "?")
            user_msg = t.get("user_message", "")[:60]
            tools    = [tc.get("tool", "") for tc in t.get("tool_calls", [])]
            dur      = t.get("duration_ms", 0)
            err      = t.get("error") or any(tc.get("error") for tc in t.get("tool_calls", []))
            loop     = t.get("loop_guard", False)
            line     = f"[{channel}/{agent}] '{user_msg}' tools={tools} dur={dur}ms"
            if err:   line += " ❌error"
            if loop:  line += " 🔁loop"
            trace_summary.append(line)

        # Σύνοψη routines
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
  "routine_id": <int ή null — μόνο για routine observations>,
  "observation": "<τι παρατήρησες σε 1 πρόταση>",
  "action": "increase_cooldown" | "reduce_frequency" | "change_time" | "save_to_memory",
  "action_value": <αριθμός ή null>,
  "confidence": <0.0-1.0>,
  "lesson": "<τι έμαθες για τον Λάζαρο ή την κατάσταση σε 1 πρόταση>"
}}

ΚΑΝΟΝΕΣ:
- Για ρουτίνες: αν ignore_count >= 2 → πρότεινε αλλαγή
- Για συνομιλίες: αν βλέπεις επαναλαμβανόμενα errors, loops, ή patterns → καταγράψτο ως lesson με action="save_to_memory"
- confidence > 0.75 μόνο αν είσαι σίγουρος
- Μέγιστο 5 observations
- Αν δεν υπάρχει τίποτα αξιοσημείωτο: επέστρεψε []
- Απάντησε ΜΟΝΟ με JSON, χωρίς εξήγηση"""

        response = model.generate_content(prompt)
        text = response.text.strip()

        # Καθαρισμός markdown
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
    Εφαρμόζει αλλαγή στη βάση βάσει action.
    Επιστρέφει True αν εφαρμόστηκε.
    """
    action     = reflection.get("action", "")
    routine_id = reflection.get("routine_id")
    value      = reflection.get("action_value")

    if not routine_id:
        return False

    try:
        conn = sqlite3.connect(DB_PATH)

        if action == "increase_cooldown" and value:
            new_cd = min(COOLDOWN_MAX, int(value))
            conn.execute(
                "UPDATE routines SET notify_cooldown_hours=? WHERE id=?",
                (new_cd, routine_id)
            )
            print(f"🔧 [Reflection]: #{routine_id} cooldown → {new_cd}h")

        elif action == "reduce_frequency":
            conn.execute(
                "UPDATE routines SET notify_cooldown_hours=MIN(notify_cooldown_hours*2, ?) WHERE id=?",
                (COOLDOWN_MAX, routine_id)
            )
            print(f"🔧 [Reflection]: #{routine_id} frequency reduced")

        elif action == "change_time" and value:
            conn.execute(
                "UPDATE routines SET time_str=? WHERE id=?",
                (str(value), routine_id)
            )
            print(f"🔧 [Reflection]: #{routine_id} time → {value}")

        elif action == "save_to_memory":
            lesson = reflection.get("lesson", "")
            if lesson:
                try:
                    from memory.vector_store import save_memory
                    save_memory(f"[REFLECTION]: {lesson}", source="reflection_engine")
                    print(f"🧠 [Reflection]: Lesson saved to ChromaDB")
                except Exception as me:
                    print(f"⚠️ [Reflection] ChromaDB save failed: {me}")
            conn.close()
            return True

        conn.commit()
        conn.close()
        return True

    except Exception as e:
        print(f"⚠️ [Reflection] Apply action failed: {e}")
        return False


# ── Main Entry Point ──────────────────────────────────────────────

def run_reflection() -> dict:
    """
    Κύρια συνάρτηση. Τρέχει μετά το analytics engine.
    Επιστρέφει stats: {analyzed, applied, pending, skipped}
    """
    from tools.telegram import send_telegram_msg

    print("[Reflection]: Ξεκινάω self-evaluation...")
    _ensure_table()

    events        = _load_today_events(days_back=1)
    routine_stats = _get_routine_stats()
    traces        = _load_conversation_traces(days_back=1)

    print(f"[Reflection]: events={len(events)}, routines={len(routine_stats)}, traces={len(traces)}")

    if not events and not routine_stats and not traces:
        print("[Reflection]: Δεν υπάρχουν δεδομένα για ανάλυση.")
        return {"analyzed": 0, "applied": 0, "pending": 0, "skipped": 0}

    reflections = _analyze_with_llm(events, routine_stats, traces)

    if not reflections:
        print("[Reflection]: Δεν βρέθηκαν observations.")
        return {"analyzed": 0, "applied": 0, "pending": 0, "skipped": 0}

    applied = pending = skipped = 0
    telegram_lines = []

    for r in reflections:
        obs        = r.get("observation", "")
        action     = r.get("action", "")
        confidence = float(r.get("confidence", 0))
        lesson     = r.get("lesson", "")
        source     = r.get("source", "general")

        if not obs or not action:
            skipped += 1
            continue

        if confidence >= AUTO_APPLY_THRESHOLD:
            # Αυτόματη εφαρμογή
            success = _apply_action(r)
            _save_reflection(source, obs, action, confidence, lesson, applied=success)
            if success:
                applied += 1
                telegram_lines.append(f"✅ *{obs}*\n→ Εφαρμόστηκε: `{action}`\n💡 _{lesson}_")
            else:
                # Αποτυχία εφαρμογής — αποθηκεύουμε χωρίς apply
                _save_reflection(source, obs, action, confidence, lesson, applied=False)
                skipped += 1

        elif confidence >= ASK_THRESHOLD:
            # Ρωτάει τον Λάζαρο
            _save_reflection(source, obs, action, confidence, lesson, applied=False)
            pending += 1
            telegram_lines.append(
                f"🤔 *Παρατήρηση:* {obs}\n"
                f"→ Προτείνω: `{action}` (confidence: {confidence:.0%})\n"
                f"Να το εφαρμόσω; (ναι/όχι)"
            )
        else:
            # Χαμηλή confidence — αποθηκεύω μόνο
            _save_reflection(source, obs, action, confidence, lesson, applied=False)
            skipped += 1

    # Αποστολή Telegram
    if telegram_lines:
        header = "🧠 *Astakos Self-Reflection — Νυχτερινή Ανάλυση*\n\n"
        msg    = header + "\n\n---\n\n".join(telegram_lines)
        if len(msg) > 4000:
            msg = msg[:3990] + "..."
        send_telegram_msg(msg)

    stats = {"analyzed": len(reflections), "applied": applied, "pending": pending, "skipped": skipped}
    print(f"[Reflection]: ✅ {stats}")
    return stats


if __name__ == "__main__":
    print(run_reflection())
 apply
                _save_reflection(source, obs, action, confidence, lesson, applied=False)
                skipped += 1

        elif confidence >= ASK_THRESHOLD:
            # Ρωτάει τον Λάζαρο
            _save_reflection(source, obs, action, confidence, lesson, applied=False)
            pending += 1
            telegram_lines.append(
                f"🤔 *Παρατήρηση:* {obs}\n"
                f"→ Προτείνω: `{action}` (confidence: {confidence:.0%})\n"
                f"Να το εφαρμόσω; (ναι/όχι)"
            )
        else:
            # Χαμηλή confidence — αποθηκεύω μόνο
            _save_reflection(source, obs, action, confidence, lesson, applied=False)
            skipped += 1

    # Αποστολή Telegram
    if telegram_lines:
        header = "🧠 *Astakos Self-Reflection — Νυχτερινή Ανάλυση*\n\n"
        msg    = header + "\n\n---\n\n".join(telegram_lines)
        if len(msg) > 4000:
            msg = msg[:3990] + "..."
        send_telegram_msg(msg)

    stats = {"analyzed": len(reflections), "applied": applied, "pending": pending, "skipped": skipped}
    print(f"[Reflection]: ✅ {stats}")
    return stats


if __name__ == "__main__":
    print(run_reflection())
