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
from datetime import datetime, timedelta

# Bootstrap repo root before any project-local imports when this file runs as a script.
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

_BASE    = os.path.dirname(os.path.abspath(__file__))
DB_PATH  = os.path.join(_BASE, "..", "astakos_routines.db")
LOG_DIR  = os.path.join(_BASE, "..", "logs", "events")

AUTO_APPLY_THRESHOLD = 0.75   # πάνω από αυτό → αυτόματη εφαρμογή
ASK_THRESHOLD        = 0.50   # πάνω από αυτό → ρωτάει τον Λάζαρο
COOLDOWN_MAX         = 168    # max cooldown ώρες (7 μέρες)
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
    # Migration για ήδη υπάρχουσες βάσεις (δημιουργήθηκαν πριν τα routine_id/action_value) —
    # χωρίς αυτά, ένα "ναι" σε pending reflection με action="increase_cooldown"/"change_time"
    # δεν είχε πού να εφαρμοστεί (ο _apply_action βλέπει routine_id=None και κάνει fallback
    # σε save_to_memory αντί να αλλάξει τη ρουτίνα).
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
    Ελέγχει αν υπάρχει ήδη ίδιο reflection που είτε εφαρμόστηκε είτε περιμένει απάντηση.
    Έτσι αποφεύγουμε να ξαναγράφουμε ask-tier duplicates κάθε νύχτα.
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


def _save_reflection(source, observation, action, confidence, lesson, applied=False,
                      routine_id=None, action_value=None) -> int:
    """Επιστρέφει το id της εγγραφής (χρειάζεται για το Telegram ναι/όχι follow-up)."""
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
    """Φορτώνει unapplied ask-tier reflections ώστε να επιβιώνουν σε restart."""
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

    # save_to_memory δεν χρειάζεται routine_id — handle πρώτα
    if action == "save_to_memory":
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
        return False

    # Planner/conversation reflections δεν έχουν routine_id —
    # fallback: αποθήκευση lesson στο ChromaDB ως γνώση.
    if not routine_id:
        lesson = reflection.get("lesson", "")
        if lesson:
            try:
                from memory.vector_store import vector_store
                vector_store.add_texts(
                    [f"[REFLECTION]: {lesson}"],
                    metadatas=[{"category": "reflection", "source": "reflection_engine"}]
                )
                print(f"🧠 [Reflection]: Lesson saved to ChromaDB (no routine_id)")
                return True
            except Exception as me:
                print(f"⚠️ [Reflection] ChromaDB save failed: {me}")
                return False
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
            # Sanitize: float 14.5 → "14:30", int/str "14" → "14:00"
            try:
                fval = float(str(value))
                hours = int(fval)
                mins  = int(round((fval - hours) * 60))
                time_str = f"{hours:02d}:{mins:02d}"
            except (ValueError, TypeError):
                time_str = str(value)  # αν είναι ήδη "HH:MM", κρατάμε ως έχει
            conn.execute(
                "UPDATE routines SET time_str=? WHERE id=?",
                (time_str, routine_id)
            )
            print(f"🔧 [Reflection]: #{routine_id} time → {time_str} (raw: {value})")

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
    pending_items = []   # [{"id":, "observation":, "action":, "routine_id":, "action_value":, "lesson":, "source":}, ...]

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

        # Skip αν έχει ήδη εφαρμοστεί το ίδιο observation+action
        if _already_reflected(obs, action, routine_id=routine_id, action_value=action_value):
            print(f"[Reflection]: ⏭ Skip duplicate: '{obs[:40]}...'")
            skipped += 1
            continue

        if confidence >= AUTO_APPLY_THRESHOLD:
            # Αυτόματη εφαρμογή
            success = _apply_action(r)
            _save_reflection(source, obs, action, confidence, lesson, applied=success,
                              routine_id=routine_id, action_value=action_value)
            if success:
                applied += 1
                telegram_lines.append(f"✅ *{obs}*\n→ Εφαρμόστηκε: `{action}`\n💡 _{lesson}_")
            else:
                skipped += 1

        elif confidence >= ASK_THRESHOLD:
            # Ρωτάει τον Λάζαρο — κρατάμε το id ώστε ένα "ναι" στο Telegram να μπορεί
            # να εφαρμόσει ΑΥΤΟ ΤΟ reflection συγκεκριμένα (βλ. clients/telegram_bot.py)
            new_id = _save_reflection(source, obs, action, confidence, lesson, applied=False,
                                       routine_id=routine_id, action_value=action_value)
            pending += 1
            pending_items.append({
                "id": new_id, "observation": obs, "action": action,
                "routine_id": routine_id, "action_value": action_value,
                "lesson": lesson, "source": source, "confidence": confidence,
            })
            # Σημείωση: ΔΕΝ στέλνουμε εδώ το "Να το εφαρμόσω;" μήνυμα.
            # Το telegram_bot.py χτίζει ΕΝΑ αριθμημένο μήνυμα για ΟΛΑ τα τρέχοντα
            # pending (παλιά + νέα) ώστε οι αριθμοί #1, #2... να αντιστοιχούν σωστά
            # σε ό,τι περιμένει απάντηση — βλ. pending_reflection_confirmations.
        else:
            # Χαμηλή confidence — αποθηκεύω μόνο
            _save_reflection(source, obs, action, confidence, lesson, applied=False,
                              routine_id=routine_id, action_value=action_value)
            skipped += 1

    # Αποστολή Telegram
    if telegram_lines:
        header = "🧠 *Astakos Self-Reflection — Νυχτερινή Ανάλυση*\n\n"
        msg    = header + "\n\n---\n\n".join(telegram_lines)
        if len(msg) > 4000:
            msg = msg[:3990] + "..."
        send_telegram_msg(msg)

    stats = {
        "analyzed": len(reflections), "applied": applied, "pending": pending,
        "skipped": skipped, "pending_items": pending_items,
    }
    print(f"[Reflection]: ✅ {stats}")
    return stats


if __name__ == "__main__":
    print(run_reflection())
