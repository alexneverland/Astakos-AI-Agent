import sqlite3
import os
import hashlib
from difflib import SequenceMatcher
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "astakos_routines.db")

# ────────────────────────────────────────────────────────────────
# CANONICALIZATION LAYER
# ────────────────────────────────────────────────────────────────

_DAY_MAP = {
    "δευτέρα": "Monday",   "δευτερα": "Monday",   "monday": "Monday",
    "τρίτη": "Tuesday",    "τριτη": "Tuesday",     "tuesday": "Tuesday",
    "τετάρτη": "Wednesday","τεταρτη": "Wednesday", "wednesday": "Wednesday",
    "πέμπτη": "Thursday",  "πεμπτη": "Thursday",   "thursday": "Thursday",
    "παρασκευή": "Friday", "παρασκευη": "Friday",  "friday": "Friday",
    "σάββατο": "Saturday", "σαββατο": "Saturday",  "saturday": "Saturday",
    "κυριακή": "Sunday",   "κυριακη": "Sunday",    "sunday": "Sunday",
    "καθημερινά": "Everyday", "καθημερινα": "Everyday", "everyday": "Everyday",
}

def normalize_day(day: str) -> str:
    return _DAY_MAP.get(day.lower().strip(), day.capitalize())

def normalize_time(time_str: str) -> str:
    time_str = time_str.strip()
    if ":" not in time_str:
        return f"{time_str.zfill(2)}:00"
    h, m = time_str.split(":", 1)
    return f"{h.zfill(2)}:{m.zfill(2)}"

def normalize_event(event: str) -> str:
    return event.lower().strip()

def make_fingerprint(day: str, time: str, event: str) -> str:
    key = f"{normalize_day(day)}|{normalize_time(time)}|{normalize_event(event)}"
    return hashlib.md5(key.encode("utf-8")).hexdigest()[:12]

def event_similarity(a: str, b: str) -> float:
    """Stage 2: difflib ratio για minor variations."""
    return SequenceMatcher(None, normalize_event(a), normalize_event(b)).ratio()

# ────────────────────────────────────────────────────────────────
# STAGE 3: EMBEDDING SIMILARITY
# ────────────────────────────────────────────────────────────────

def _cosine_similarity(a: list, b: list) -> float:
    """Cosine similarity χωρίς numpy — pure Python."""
    dot    = sum(x * y for x, y in zip(a, b))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(x * x for x in b) ** 0.5
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)

def _embedding_similarity(text_a: str, text_b: str) -> float:
    """
    Stage 3: Semantic similarity μέσω VertexAI embeddings (με cache).
    Επιστρέφει 0.0 αν τα embeddings δεν είναι διαθέσιμα.
    """
    try:
        from services.embeddings import embeddings as emb_service
        vec_a = emb_service.embed_query(normalize_event(text_a))
        vec_b = emb_service.embed_query(normalize_event(text_b))
        return _cosine_similarity(vec_a, vec_b)
    except Exception:
        return 0.0  # graceful fallback — Stage 3 παραλείπεται

# ────────────────────────────────────────────────────────────────
# DB SETUP & MIGRATION
# ────────────────────────────────────────────────────────────────

def get_connection():
    return sqlite3.connect(DB_PATH)

def setup_db():
    conn   = get_connection()
    cursor = conn.cursor()

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS routines (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            day_of_week TEXT,
            time_str TEXT,
            event_name TEXT,
            event_type TEXT,
            confidence REAL,
            last_triggered TEXT,
            decay_counter INTEGER,
            is_active BOOLEAN DEFAULT 1,
            fingerprint TEXT,
            mention_count INTEGER DEFAULT 1
        )
    ''')

    existing_cols = [r[1] for r in cursor.execute("PRAGMA table_info(routines)").fetchall()]

    if "fingerprint" not in existing_cols:
        cursor.execute("ALTER TABLE routines ADD COLUMN fingerprint TEXT")
        print("[routine_db]: Migration → 'fingerprint'")

    if "mention_count" not in existing_cols:
        cursor.execute("ALTER TABLE routines ADD COLUMN mention_count INTEGER DEFAULT 1")
        print("[routine_db]: Migration → 'mention_count'")

    # Backfill fingerprints
    cursor.execute("SELECT id, day_of_week, time_str, event_name FROM routines WHERE fingerprint IS NULL")
    for r_id, day, time, event in cursor.fetchall():
        fp = make_fingerprint(day or "", time or "", event or "")
        cursor.execute("UPDATE routines SET fingerprint=? WHERE id=?", (fp, r_id))

    conn.commit()
    conn.close()

# ────────────────────────────────────────────────────────────────
# CORE OPERATIONS
# ────────────────────────────────────────────────────────────────

def upsert_routine(day, time, event, ev_type="general", confidence_boost=0.1):
    """
    3-stage dedup πριν αποθηκεύσει:
      Stage 1 — exact fingerprint match
      Stage 2 — difflib fuzzy match (>= 0.72) για ίδιο day/time slot
      Stage 3 — embedding cosine similarity (>= 0.88) για ίδιο day/time slot
    Νέες ρουτίνες ξεκινούν inactive (mention_count=1) — ενεργοποιούνται στη 2η αναφορά.
    """
    c_day   = normalize_day(day)
    c_time  = normalize_time(time)
    c_event = event.strip()
    fp      = make_fingerprint(c_day, c_time, c_event)

    conn   = get_connection()
    cursor = conn.cursor()

    # ── Stage 1: exact fingerprint ───────────────────────────────
    cursor.execute("SELECT id, confidence, mention_count FROM routines WHERE fingerprint=?", (fp,))
    row = cursor.fetchone()
    if row:
        r_id, conf, mentions = row
        new_conf = min(1.0, conf + confidence_boost)
        new_m    = (mentions or 1) + 1
        cursor.execute(
            "UPDATE routines SET confidence=?, decay_counter=0, is_active=?, mention_count=? WHERE id=?",
            (new_conf, 1 if new_m >= 2 else 0, new_m, r_id)
        )
        conn.commit(); conn.close()
        return "updated"

    # Φέρνουμε candidates ίδιου day/time για Stage 2 & 3
    cursor.execute(
        "SELECT id, event_name, confidence, mention_count FROM routines WHERE day_of_week=? AND time_str=?",
        (c_day, c_time)
    )
    candidates = cursor.fetchall()

    # ── Stage 2: difflib fuzzy ───────────────────────────────────
    for r_id, ex_ev, conf, mentions in candidates:
        if event_similarity(c_event, ex_ev) >= 0.72:
            new_conf = min(1.0, conf + confidence_boost)
            new_m    = (mentions or 1) + 1
            new_fp   = make_fingerprint(c_day, c_time, c_event)
            cursor.execute(
                """UPDATE routines
                   SET event_name=?, confidence=?, decay_counter=0,
                       is_active=?, mention_count=?, fingerprint=?
                   WHERE id=?""",
                (c_event, new_conf, 1 if new_m >= 2 else 0, new_m, new_fp, r_id)
            )
            conn.commit(); conn.close()
            print(f"[routine_db S2]: difflib merge '{ex_ev}' → '{c_event}'")
            return "merged"

    # ── Stage 3: embedding cosine similarity ─────────────────────
    for r_id, ex_ev, conf, mentions in candidates:
        sim = _embedding_similarity(c_event, ex_ev)
        if sim >= 0.88:
            new_conf = min(1.0, conf + confidence_boost)
            new_m    = (mentions or 1) + 1
            new_fp   = make_fingerprint(c_day, c_time, c_event)
            cursor.execute(
                """UPDATE routines
                   SET event_name=?, confidence=?, decay_counter=0,
                       is_active=?, mention_count=?, fingerprint=?
                   WHERE id=?""",
                (c_event, new_conf, 1 if new_m >= 2 else 0, new_m, new_fp, r_id)
            )
            conn.commit(); conn.close()
            print(f"[routine_db S3]: embedding merge '{ex_ev}' → '{c_event}' (sim={sim:.2f})")
            return "merged"

    # ── Νέα εγγραφή (inactive μέχρι 2η αναφορά) ─────────────────
    cursor.execute('''
        INSERT INTO routines
            (day_of_week, time_str, event_name, event_type, confidence,
             decay_counter, is_active, fingerprint, mention_count)
        VALUES (?, ?, ?, ?, ?, 0, 0, ?, 1)
    ''', (c_day, c_time, c_event, ev_type, 0.3, fp))

    conn.commit(); conn.close()
    return "created"


def confirm_routine(routine_id):
    conn   = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT confidence, mention_count FROM routines WHERE id=?", (routine_id,))
    row = cursor.fetchone()
    if row:
        new_conf = min(1.0, row[0] + 0.2)
        new_m    = (row[1] or 1) + 1
        cursor.execute(
            "UPDATE routines SET confidence=?, decay_counter=0, is_active=1, mention_count=? WHERE id=?",
            (new_conf, new_m, routine_id)
        )
    conn.commit(); conn.close()


def decay_routine(routine_id):
    conn   = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT confidence, decay_counter FROM routines WHERE id=?", (routine_id,))
    row = cursor.fetchone()
    if row:
        new_conf  = max(0.0, row[0] - 0.2)
        new_decay = row[1] + 1
        is_active = 0 if new_conf < 0.1 else 1
        cursor.execute(
            "UPDATE routines SET confidence=?, decay_counter=?, is_active=? WHERE id=?",
            (new_conf, new_decay, is_active, routine_id)
        )
    conn.commit(); conn.close()


def get_routines_for_day(day: str) -> list:
    conn   = get_connection()
    cursor = conn.cursor()
    c_day  = normalize_day(day)
    cursor.execute('''
        SELECT id, time_str, event_name, event_type, confidence, mention_count
        FROM routines
        WHERE (day_of_week=? OR day_of_week='Everyday' OR day_of_week='Καθημερινά')
        AND is_active=1
        ORDER BY time_str ASC
    ''', (c_day,))
    rows = cursor.fetchall()
    conn.close()
    return [
        {
            "id": r[0], "time": r[1], "event": r[2],
            "type": r[3], "confidence": round(r[4], 2),
            "mentions": r[5]
        }
        for r in rows
    ]

setup_db()

# ────────────────────────────────────────────────────────────────
# PENDING CONFIRMATIONS PERSISTENCE (Recovery After Restart)
# ────────────────────────────────────────────────────────────────

def _setup_pending_table():
    conn   = get_connection()
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS pending_confirmations (
            routine_id INTEGER PRIMARY KEY,
            event_name TEXT,
            sent_at    TEXT
        )
    ''')
    conn.commit()
    conn.close()

def save_pending_confirmation(routine_id: int, event_name: str, sent_at: datetime):
    conn   = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT OR REPLACE INTO pending_confirmations (routine_id, event_name, sent_at) VALUES (?, ?, ?)",
        (routine_id, event_name, sent_at.isoformat())
    )
    conn.commit()
    conn.close()

def remove_pending_confirmation(routine_id: int):
    conn = get_connection()
    conn.execute("DELETE FROM pending_confirmations WHERE routine_id=?", (routine_id,))
    conn.commit()
    conn.close()

def clear_pending_confirmations():
    conn = get_connection()
    conn.execute("DELETE FROM pending_confirmations")
    conn.commit()
    conn.close()

def load_pending_confirmations() -> dict:
    """
    Φορτώνει τα pending confirmations από τη DB κατά την εκκίνηση.
    Επιστρέφει {routine_id: {"event": ..., "sent_at": datetime}}
    """
    conn   = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT routine_id, event_name, sent_at FROM pending_confirmations")
    rows   = cursor.fetchall()
    conn.close()
    result = {}
    for r_id, event_name, sent_at_str in rows:
        try:
            sent_at = datetime.fromisoformat(sent_at_str)
        except Exception:
            sent_at = datetime.now()
        result[r_id] = {"event": event_name, "sent_at": sent_at}
    return result

_setup_pending_table()
