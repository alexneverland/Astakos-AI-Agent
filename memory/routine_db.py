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
    """Μετατρέπει οποιοδήποτε format μέρας στο αγγλικό canonical."""
    return _DAY_MAP.get(day.lower().strip(), day.capitalize())

def normalize_time(time_str: str) -> str:
    """Κανονικοποιεί ώρα: '11' → '11:00', '9:30' → '09:30'."""
    time_str = time_str.strip()
    if ":" not in time_str:
        return f"{time_str.zfill(2)}:00"
    h, m = time_str.split(":", 1)
    return f"{h.zfill(2)}:{m.zfill(2)}"

def normalize_event(event: str) -> str:
    """Lowercase + strip για ομοιόμορφη σύγκριση."""
    return event.lower().strip()

def make_fingerprint(day: str, time: str, event: str) -> str:
    """
    Δημιουργεί ένα MD5 fingerprint από normalized day+time+event.
    Χρησιμοποιείται για exact dedup.
    """
    key = f"{normalize_day(day)}|{normalize_time(time)}|{normalize_event(event)}"
    return hashlib.md5(key.encode("utf-8")).hexdigest()[:12]

def event_similarity(a: str, b: str) -> float:
    """Επιστρέφει ομοιότητα 0.0-1.0 μεταξύ δύο event names."""
    return SequenceMatcher(None, normalize_event(a), normalize_event(b)).ratio()

# ────────────────────────────────────────────────────────────────
# DB SETUP & MIGRATION
# ────────────────────────────────────────────────────────────────

def get_connection():
    return sqlite3.connect(DB_PATH)

def setup_db():
    conn = get_connection()
    cursor = conn.cursor()

    # Δημιουργία πίνακα αν δεν υπάρχει (νέο schema)
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

    # Migration: προσθέτουμε τις νέες στήλες αν λείπουν (existing DB)
    existing_cols = [row[1] for row in cursor.execute("PRAGMA table_info(routines)").fetchall()]

    if "fingerprint" not in existing_cols:
        cursor.execute("ALTER TABLE routines ADD COLUMN fingerprint TEXT")
        print("[routine_db]: Migration → προστέθηκε 'fingerprint'")

    if "mention_count" not in existing_cols:
        cursor.execute("ALTER TABLE routines ADD COLUMN mention_count INTEGER DEFAULT 1")
        print("[routine_db]: Migration → προστέθηκε 'mention_count'")

    # Backfill fingerprints για υπάρχουσες εγγραφές
    cursor.execute("SELECT id, day_of_week, time_str, event_name FROM routines WHERE fingerprint IS NULL")
    rows = cursor.fetchall()
    for r_id, day, time, event in rows:
        fp = make_fingerprint(day or "", time or "", event or "")
        cursor.execute("UPDATE routines SET fingerprint=? WHERE id=?", (fp, r_id))

    conn.commit()
    conn.close()

# ────────────────────────────────────────────────────────────────
# CORE OPERATIONS
# ────────────────────────────────────────────────────────────────

def upsert_routine(day, time, event, ev_type="general", confidence_boost=0.1):
    """
    Αποθηκεύει ρουτίνα με:
    1. Canonicalization (normalize day/time/event)
    2. Exact dedup μέσω fingerprint
    3. Fuzzy semantic dedup για παρόμοια events στο ίδιο timeslot
    4. mention_count tracking (ρουτίνα ενεργοποιείται μόνο μετά από 2+ αναφορές)
    """
    # 1. Canonicalize
    c_day   = normalize_day(day)
    c_time  = normalize_time(time)
    c_event = event.strip()
    fp      = make_fingerprint(c_day, c_time, c_event)

    conn   = get_connection()
    cursor = conn.cursor()

    # 2. Exact match μέσω fingerprint
    cursor.execute("SELECT id, confidence, mention_count FROM routines WHERE fingerprint=?", (fp,))
    row = cursor.fetchone()

    if row:
        r_id, current_conf, mentions = row
        new_conf     = min(1.0, current_conf + confidence_boost)
        new_mentions = (mentions or 1) + 1
        new_active   = 1 if new_mentions >= 2 else 0
        cursor.execute(
            "UPDATE routines SET confidence=?, decay_counter=0, is_active=?, mention_count=? WHERE id=?",
            (new_conf, new_active, new_mentions, r_id)
        )
        conn.commit()
        conn.close()
        return "updated"

    # 3. Fuzzy semantic dedup: ψάχνουμε παρόμοια events στο ίδιο day/time
    cursor.execute(
        "SELECT id, event_name, confidence, mention_count FROM routines WHERE day_of_week=? AND time_str=?",
        (c_day, c_time)
    )
    candidates = cursor.fetchall()

    for r_id, existing_event, current_conf, mentions in candidates:
        if event_similarity(c_event, existing_event) >= 0.72:
            # Semantic duplicate → merge (boost confidence, update event_name με νεότερο)
            new_conf     = min(1.0, current_conf + confidence_boost)
            new_mentions = (mentions or 1) + 1
            new_active   = 1 if new_mentions >= 2 else 0
            new_fp       = make_fingerprint(c_day, c_time, c_event)
            cursor.execute(
                """UPDATE routines
                   SET event_name=?, confidence=?, decay_counter=0,
                       is_active=?, mention_count=?, fingerprint=?
                   WHERE id=?""",
                (c_event, new_conf, new_active, new_mentions, new_fp, r_id)
            )
            conn.commit()
            conn.close()
            print(f"[routine_db]: Semantic merge '{existing_event}' → '{c_event}'")
            return "merged"

    # 4. Νέα εγγραφή — starts inactive (mention_count=1, is_active=0)
    cursor.execute('''
        INSERT INTO routines
            (day_of_week, time_str, event_name, event_type, confidence, decay_counter, is_active, fingerprint, mention_count)
        VALUES (?, ?, ?, ?, ?, 0, 0, ?, 1)
    ''', (c_day, c_time, c_event, ev_type, 0.3, fp))

    conn.commit()
    conn.close()
    return "created"


def confirm_routine(routine_id):
    conn   = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT confidence, mention_count FROM routines WHERE id=?", (routine_id,))
    row = cursor.fetchone()
    if row:
        new_conf     = min(1.0, row[0] + 0.2)
        new_mentions = (row[1] or 1) + 1
        cursor.execute(
            "UPDATE routines SET confidence=?, decay_counter=0, is_active=1, mention_count=? WHERE id=?",
            (new_conf, new_mentions, routine_id)
        )
    conn.commit()
    conn.close()


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
    conn.commit()
    conn.close()


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
