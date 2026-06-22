import sqlite3
import os
import hashlib
import threading
from difflib import SequenceMatcher
from datetime import datetime

from core.exceptions import RoutineConflictError, DBWriteError
from core.routine_state import RoutineState, validate_transition, is_notifiable, state_from_str

DB_PATH      = os.path.join(os.path.dirname(__file__), "..", "astakos_routines.db")
db_write_lock = threading.Lock()  # Serializes writes — reads χωρίς lock (WAL mode)

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


def normalize_search_text(text: str) -> str:
    """Accent-insensitive normalizer για lightweight routine matching."""
    import unicodedata

    raw = str(text or "").strip().lower()
    normalized = unicodedata.normalize("NFD", raw)
    return "".join(ch for ch in normalized if not unicodedata.combining(ch))

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

def get_connection(write: bool = False):
    """
    Επιστρέφει SQLite connection με WAL mode (graceful fallback αν δεν υποστηρίζεται).
    check_same_thread=False για multi-thread safety.
    """
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=3000")
    except sqlite3.Error:
        pass  # Fallback: default journal mode (π.χ. network drive, read-only fs)
    return conn

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
            mention_count INTEGER DEFAULT 1,
            ignore_count INTEGER DEFAULT 0,
            notify_cooldown_hours REAL DEFAULT 20.0,
            last_notified_ts TEXT,
            state TEXT DEFAULT 'learned'
        )
    ''')

    existing_cols = [r[1] for r in cursor.execute("PRAGMA table_info(routines)").fetchall()]

    if "fingerprint" not in existing_cols:
        cursor.execute("ALTER TABLE routines ADD COLUMN fingerprint TEXT")
        print("[routine_db]: Migration → 'fingerprint'")

    if "mention_count" not in existing_cols:
        cursor.execute("ALTER TABLE routines ADD COLUMN mention_count INTEGER DEFAULT 1")
        print("[routine_db]: Migration → 'mention_count'")

    if "ignore_count" not in existing_cols:
        cursor.execute("ALTER TABLE routines ADD COLUMN ignore_count INTEGER DEFAULT 0")
        print("[routine_db]: Migration → 'ignore_count'")

    if "notify_cooldown_hours" not in existing_cols:
        cursor.execute("ALTER TABLE routines ADD COLUMN notify_cooldown_hours REAL DEFAULT 20.0")
        print("[routine_db]: Migration → 'notify_cooldown_hours'")

    if "last_notified_ts" not in existing_cols:
        cursor.execute("ALTER TABLE routines ADD COLUMN last_notified_ts TEXT")
        print("[routine_db]: Migration → 'last_notified_ts'")

    if "state" not in existing_cols:
        cursor.execute("ALTER TABLE routines ADD COLUMN state TEXT DEFAULT 'learned'")
        print("[routine_db]: Migration → 'state'")
        # Backfill: derive state from existing is_active + mention_count + confidence
        cursor.execute("""
            UPDATE routines SET state = CASE
                WHEN is_active = 1                                  THEN 'active'
                WHEN is_active = 0 AND confidence < 0.1            THEN 'decayed'
                WHEN is_active = 0 AND (mention_count IS NULL OR mention_count < 2) THEN 'learned'
                ELSE 'active'
            END
        """)
        print("[routine_db]: Backfill → state column από is_active/confidence")

    if "muted_until" not in existing_cols:
        cursor.execute("ALTER TABLE routines ADD COLUMN muted_until TEXT DEFAULT NULL")
        print("[routine_db]: Migration → 'muted_until'")

    if "muted_from" not in existing_cols:
        cursor.execute("ALTER TABLE routines ADD COLUMN muted_from TEXT DEFAULT NULL")
        print("[routine_db]: Migration → 'muted_from'")

    if "sentimental" not in existing_cols:
        cursor.execute("ALTER TABLE routines ADD COLUMN sentimental INTEGER DEFAULT NULL")
        print("[routine_db]: Migration → 'sentimental'")

    if "sentimental_send_every" not in existing_cols:
        cursor.execute("ALTER TABLE routines ADD COLUMN sentimental_send_every INTEGER DEFAULT 2")
        print("[routine_db]: Migration → 'sentimental_send_every'")

    if "sentimental_last_sent" not in existing_cols:
        cursor.execute("ALTER TABLE routines ADD COLUMN sentimental_last_sent TEXT DEFAULT NULL")
        print("[routine_db]: Migration → 'sentimental_last_sent'")

    if "sentimental_silenced" not in existing_cols:
        cursor.execute("ALTER TABLE routines ADD COLUMN sentimental_silenced INTEGER DEFAULT 0")
        print("[routine_db]: Migration → 'sentimental_silenced'")

    # Phase 3C: Conditions
    if "condition_type" not in existing_cols:
        cursor.execute("ALTER TABLE routines ADD COLUMN condition_type TEXT")
        print("[routine_db]: Migration → 'condition_type'")

    if "condition_payload" not in existing_cols:
        cursor.execute("ALTER TABLE routines ADD COLUMN condition_payload TEXT")
        print("[routine_db]: Migration → 'condition_payload'")

    if "condition_mode" not in existing_cols:
        cursor.execute("ALTER TABLE routines ADD COLUMN condition_mode TEXT")
        print("[routine_db]: Migration → 'condition_mode'")

    if "conditions_json" not in existing_cols:
        cursor.execute("ALTER TABLE routines ADD COLUMN conditions_json TEXT")
        print("[routine_db]: Migration → 'conditions_json'")

    if "priority" not in existing_cols:
        cursor.execute("ALTER TABLE routines ADD COLUMN priority INTEGER DEFAULT 0")
        print("[routine_db]: Migration → 'priority'")

    if "conflict_group" not in existing_cols:
        cursor.execute("ALTER TABLE routines ADD COLUMN conflict_group TEXT")
        print("[routine_db]: Migration → 'conflict_group'")

    if "source_memory_ref" not in existing_cols:
        cursor.execute("ALTER TABLE routines ADD COLUMN source_memory_ref TEXT")
        print("[routine_db]: Migration → 'source_memory_ref'")

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS context_state (
            key TEXT PRIMARY KEY,
            value TEXT,
            expires_at TEXT,
            updated_at TEXT
        )
    ''')

    # Backfill fingerprints
    cursor.execute("SELECT id, day_of_week, time_str, event_name FROM routines WHERE fingerprint IS NULL")
    for r_id, day, time, event in cursor.fetchall():
        fp = make_fingerprint(day or "", time or "", event or "")
        cursor.execute("UPDATE routines SET fingerprint=? WHERE id=?", (fp, r_id))

    conn.commit()
    conn.close()

# ────────────────────────────────────────────────────────────────
# STATE MACHINE LAYER
# ────────────────────────────────────────────────────────────────

def get_routine_state(routine_id: int) -> RoutineState:
    """Επιστρέφει το τρέχον state μιας ρουτίνας. Άγνωστο → LEARNED."""
    conn   = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT state FROM routines WHERE id=?", (routine_id,))
    row = cursor.fetchone()
    conn.close()
    if not row:
        return RoutineState.LEARNED
    return state_from_str(row[0])


def transition_routine(routine_id: int, to_state: RoutineState) -> None:
    """
    Validated state transition. Raises RoutineConflictError αν δεν επιτρέπεται.
    Ενημερώνει και το is_active για backward compatibility.
    """
    current = get_routine_state(routine_id)
    validate_transition(current, to_state)  # raises RoutineConflictError αν invalid

    # is_active: True μόνο για ACTIVE (backward compat με παλιό κώδικα)
    active_flag = 1 if to_state == RoutineState.ACTIVE else 0

    conn   = get_connection()
    cursor = conn.cursor()
    try:
        with db_write_lock:
            cursor.execute(
                "UPDATE routines SET state=?, is_active=? WHERE id=?",
                (to_state.value, active_flag, routine_id)
            )
            conn.commit()
    except sqlite3.Error as e:
        raise DBWriteError(f"transition_routine/{current.value}→{to_state.value}", e) from e
    finally:
        conn.close()

    print(f"[routine_db]: #{routine_id} {current.value} → {to_state.value}")
    from memory.event_log import log_event
    log_event("routines", "state_change", routine_id=routine_id, from_state=current.value, to_state=to_state.value)

# ────────────────────────────────────────────────────────────────
# CORE OPERATIONS
# ────────────────────────────────────────────────────────────────

def upsert_routine(day, time, event, ev_type="general", confidence_boost=0.1):
    """
    3-stage dedup πριν αποθηκεύσει:
      Stage 1 — exact fingerprint match
      Stage 2 — difflib fuzzy match (>= 0.72) για ίδιο day/time slot
      Stage 3 — embedding cosine similarity (>= 0.88) για ίδιο day/time slot

    State transitions:
      - Νέα ρουτίνα → LEARNED
      - 2η+ αναφορά  → ACTIVE (αν ήταν LEARNED/DECAYED)
    Raises: DBWriteError αν η εγγραφή αποτύχει.
    """
    c_day   = normalize_day(day)
    c_time  = normalize_time(time)
    c_event = event.strip()
    fp      = make_fingerprint(c_day, c_time, c_event)

    # Reads χωρίς lock (WAL mode επιτρέπει concurrent reads)
    conn   = get_connection()
    cursor = conn.cursor()

    # ── Stage 1: exact fingerprint ───────────────────────────────
    cursor.execute("SELECT id, confidence, mention_count, state FROM routines WHERE fingerprint=?", (fp,))
    row = cursor.fetchone()
    if row:
        r_id, conf, mentions, cur_state_str = row
        new_conf = min(1.0, conf + confidence_boost)
        new_m    = (mentions or 1) + 1
        new_state = RoutineState.ACTIVE if new_m >= 2 else RoutineState.LEARNED
        # Αν ήταν DECAYED και ξαναναφέρθηκε → ACTIVE (re-teach)
        cur_state = state_from_str(cur_state_str)
        if cur_state == RoutineState.DECAYED:
            new_state = RoutineState.ACTIVE
        active_flag = 1 if new_state == RoutineState.ACTIVE else 0
        try:
            with db_write_lock:
                cursor.execute(
                    "UPDATE routines SET confidence=?, decay_counter=0, is_active=?, mention_count=?, state=? WHERE id=?",
                    (new_conf, active_flag, new_m, new_state.value, r_id)
                )
                conn.commit()
        except sqlite3.Error as e:
            raise DBWriteError("upsert_routine/stage1_update", e) from e
        finally:
            conn.close()
        if cur_state != new_state:
            print(f"[routine_db S1]: #{r_id} {cur_state.value} → {new_state.value} (mention #{new_m})")
        return "updated"

    # Φέρνουμε candidates ίδιου day/time για Stage 2 & 3
    cursor.execute(
        "SELECT id, event_name, confidence, mention_count, state FROM routines WHERE day_of_week=? AND time_str=?",
        (c_day, c_time)
    )
    candidates = cursor.fetchall()

    # ── Stage 2: difflib fuzzy ───────────────────────────────────
    for r_id, ex_ev, conf, mentions, cur_state_str in candidates:
        if event_similarity(c_event, ex_ev) >= 0.72:
            new_conf = min(1.0, conf + confidence_boost)
            new_m    = (mentions or 1) + 1
            new_fp   = make_fingerprint(c_day, c_time, c_event)
            cur_state = state_from_str(cur_state_str)
            new_state = RoutineState.ACTIVE if new_m >= 2 else RoutineState.LEARNED
            if cur_state == RoutineState.DECAYED:
                new_state = RoutineState.ACTIVE
            active_flag = 1 if new_state == RoutineState.ACTIVE else 0
            try:
                with db_write_lock:
                    cursor.execute(
                        """UPDATE routines
                           SET event_name=?, confidence=?, decay_counter=0,
                               is_active=?, mention_count=?, fingerprint=?, state=?
                           WHERE id=?""",
                        (c_event, new_conf, active_flag, new_m, new_fp, new_state.value, r_id)
                    )
                    conn.commit()
            except sqlite3.Error as e:
                raise DBWriteError("upsert_routine/stage2_merge", e) from e
            finally:
                conn.close()
            print(f"[routine_db S2]: difflib merge '{ex_ev}' → '{c_event}' ({cur_state.value}→{new_state.value})")
            return "merged"

    # ── Stage 3: embedding cosine similarity ─────────────────────
    for r_id, ex_ev, conf, mentions, cur_state_str in candidates:
        # Sanity check: αν τα texts είναι πολύ διαφορετικά σε μήκος, skip
        len_ratio = min(len(c_event), len(ex_ev)) / max(len(c_event), len(ex_ev)) if max(len(c_event), len(ex_ev)) > 0 else 0
        if len_ratio < 0.4:
            continue  # π.χ. "πάρκο" vs "μαγείρεμα σνίτσελ" — πολύ διαφορετικά
        sim = _embedding_similarity(c_event, ex_ev)
        if sim >= 0.92:  # αυξήθηκε από 0.88 για λιγότερα false positives
            new_conf = min(1.0, conf + confidence_boost)
            new_m    = (mentions or 1) + 1
            new_fp   = make_fingerprint(c_day, c_time, c_event)
            cur_state = state_from_str(cur_state_str)
            new_state = RoutineState.ACTIVE if new_m >= 2 else RoutineState.LEARNED
            if cur_state == RoutineState.DECAYED:
                new_state = RoutineState.ACTIVE
            active_flag = 1 if new_state == RoutineState.ACTIVE else 0
            try:
                with db_write_lock:
                    cursor.execute(
                        """UPDATE routines
                           SET event_name=?, confidence=?, decay_counter=0,
                               is_active=?, mention_count=?, fingerprint=?, state=?
                           WHERE id=?""",
                        (c_event, new_conf, active_flag, new_m, new_fp, new_state.value, r_id)
                    )
                    conn.commit()
            except sqlite3.Error as e:
                raise DBWriteError("upsert_routine/stage3_merge", e) from e
            finally:
                conn.close()
            print(f"[routine_db S3]: embedding merge '{ex_ev}' → '{c_event}' (sim={sim:.2f}, {cur_state.value}→{new_state.value})")
            return "merged"

    # ── Νέα εγγραφή → state=LEARNED (inactive μέχρι 2η αναφορά) ─
    try:
        with db_write_lock:
            cursor.execute('''
                INSERT INTO routines
                    (day_of_week, time_str, event_name, event_type, confidence,
                     decay_counter, is_active, fingerprint, mention_count, state)
                VALUES (?, ?, ?, ?, ?, 0, 0, ?, 1, 'learned')
            ''', (c_day, c_time, c_event, ev_type, 0.3, fp))
            conn.commit()
    except sqlite3.IntegrityError as e:
        raise RoutineConflictError(
            f"Fingerprint conflict για '{c_event}' @ {c_day} {c_time}",
            context={"fingerprint": fp, "error": str(e)}
        ) from e
    except sqlite3.Error as e:
        raise DBWriteError("upsert_routine/insert", e) from e
    finally:
        conn.close()
    return "created"


def delete_routine_db(routine_id: int) -> bool:
    """Διαγράφει οριστικά μια ρουτίνα από τη βάση."""
    conn = get_connection()
    cursor = conn.cursor()
    try:
        with db_write_lock:
            cursor.execute("DELETE FROM routines WHERE id=?", (routine_id,))
            conn.commit()
            return cursor.rowcount > 0
    except sqlite3.Error as e:
        raise DBWriteError("delete_routine_db", e) from e
    finally:
        conn.close()


def update_routine_db(routine_id: int, new_time: str = None, new_day: str = None) -> bool:
    """Ενημερώνει ώρα/ημέρα υπάρχουσας ρουτίνας και κάνει re-fingerprint."""
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT day_of_week, time_str, event_name FROM routines WHERE id=?", (routine_id,))
        row = cursor.fetchone()
        if not row:
            return False
        
        day = normalize_day(new_day) if new_day else row[0]
        time_s = normalize_time(new_time) if new_time else row[1]
        ev_name = row[2]
        
        fp = make_fingerprint(day, time_s, ev_name)
        
        with db_write_lock:
            cursor.execute(
                "UPDATE routines SET day_of_week=?, time_str=?, fingerprint=? WHERE id=?",
                (day, time_s, fp, routine_id)
            )
            conn.commit()
            return True
    except sqlite3.Error as e:
        raise DBWriteError("update_routine_db", e) from e
    finally:
        conn.close()


def confirm_routine(routine_id: int):
    """
    TRIGGER_PENDING → CONFIRMED → ACTIVE (double transition, auto-immediate).
    Αυξάνει confidence + mention_count.
    """
    current_state = get_routine_state(routine_id)
    # Idempotent: ήδη active από προηγούμενη session (pending δεν καθαρίστηκε λόγω crash)
    if current_state == RoutineState.ACTIVE:
        remove_pending_confirmation(routine_id)
        return
    validate_transition(current_state, RoutineState.CONFIRMED)
    validate_transition(RoutineState.CONFIRMED, RoutineState.ACTIVE)
    conn   = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT confidence, mention_count FROM routines WHERE id=?", (routine_id,))
    row = cursor.fetchone()
    if row:
        new_conf = min(1.0, row[0] + 0.2)
        new_m    = (row[1] or 1) + 1
        try:
            with db_write_lock:
                # CONFIRMED → ACTIVE αμέσως (single write, valid shortcut)
                cursor.execute(
                    "UPDATE routines SET confidence=?, decay_counter=0, is_active=1, mention_count=?, state='active' WHERE id=?",
                    (new_conf, new_m, routine_id)
                )
                conn.commit()
        except sqlite3.Error as e:
            raise DBWriteError("confirm_routine", e) from e
        finally:
            conn.close()
        print(f"[routine_db]: #{routine_id} confirmed → active (conf={new_conf:.2f})")


def decay_routine(routine_id: int):
    """
    Decay confidence. State transitions:
      - Everyday + confidence >= 0.1 → ACTIVE (skip today, επιστροφή αύριο)
      - Non-everyday + confidence >= 0.1 → DISMISSED (user said no, αλλά ρουτίνα επιβιώνει)
      - confidence < 0.1  → DECAYED (προς archived)
    """
    conn   = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT confidence, decay_counter, day_of_week FROM routines WHERE id=?", (routine_id,))
    row = cursor.fetchone()
    if row:
        new_conf    = max(0.0, row[0] - 0.2)
        new_decay   = row[1] + 1
        everyday_like_days = {
            "everyday",
            "weekdays",
            "εργάσιμες",
            "καθημερινές",
        }
        day_value = (row[2] or "").strip().lower()
        is_everyday_like = day_value in everyday_like_days

        if new_conf < 0.1:
            new_state   = RoutineState.DECAYED
            active_flag = 0
        elif is_everyday_like:
            new_state   = RoutineState.ACTIVE
            active_flag = 1
        else:
            new_state   = RoutineState.DISMISSED
            active_flag = 0

        validate_transition(get_routine_state(routine_id), new_state)
        try:
            with db_write_lock:
                cursor.execute(
                    "UPDATE routines SET confidence=?, decay_counter=?, is_active=?, state=? WHERE id=?",
                    (new_conf, new_decay, active_flag, new_state.value, routine_id)
                )
                conn.commit()
        except sqlite3.Error as e:
            raise DBWriteError("decay_routine", e) from e
        finally:
            conn.close()
        print(f"[routine_db]: #{routine_id} decayed → {new_state.value} (conf={new_conf:.2f})")
        from memory.event_log import log_event
        log_event("routines", "decay", routine_id=routine_id, new_confidence=new_conf, new_state=new_state.value)

def get_routines_for_day(day: str) -> list:
    """Επιστρέφει active ρουτίνες για την ημέρα. Φιλτράρει με state='active'."""
    conn   = get_connection()
    cursor = conn.cursor()
    c_day  = normalize_day(day)
    cursor.execute("""
        SELECT id, time_str, event_name, event_type, confidence, mention_count, state
        FROM routines
        WHERE (
            day_of_week=?
            OR day_of_week='Everyday'
            OR (day_of_week IN ('Weekdays','Εργάσιμες','καθημερινές') AND ? IN ('Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Weekdays','Εργάσιμες','καθημερινές'))
            OR (day_of_week IN ('Weekends','Σαββατοκύριακο','σκ') AND ? IN ('Saturday', 'Sunday', 'Weekends','Σαββατοκύριακο','σκ'))
        )
        AND state='active'
        ORDER BY time_str ASC
    """, (c_day, c_day, c_day))
    rows = cursor.fetchall()
    conn.close()
    return [
        {
            "id": r[0], "time": r[1], "event": r[2],
            "type": r[3], "confidence": round(r[4], 2),
            "mentions": r[5], "state": r[6],
        }
        for r in rows
    ]


setup_db()

# ────────────────────────────────────────────────────────────────
# ANTI-SPAM: Adaptive Cooldown
# ────────────────────────────────────────────────────────────────

COOLDOWN_DEFAULT_HOURS = 20.0
COOLDOWN_MIN_HOURS     = 4.0
COOLDOWN_MAX_HOURS     = 72.0


def mark_routine_notified(routine_id: int):
    """TRIGGER_PENDING: routine ειδοποιήθηκε — αναμένει επιβεβαίωση."""
    validate_transition(get_routine_state(routine_id), RoutineState.TRIGGER_PENDING)
    conn   = get_connection()
    cursor = conn.cursor()
    with db_write_lock:
        cursor.execute(
            "UPDATE routines SET last_notified_ts=?, state='trigger_pending', is_active=0 WHERE id=?",
            (datetime.now().isoformat(timespec="seconds"), routine_id)
        )
        conn.commit()
    conn.close()


def mark_routine_ignored(routine_id: int):
    """Timeout (όχι απόρριψη): TRIGGER_PENDING → IGNORED → ACTIVE + διπλασιασμός cooldown."""
    current = get_routine_state(routine_id)
    if current == RoutineState.ACTIVE:
        # Ήδη confirmed από τον χρήστη — δεν χρειάζεται ignore
        remove_pending_confirmation(routine_id)
        return
    validate_transition(current, RoutineState.IGNORED)
    validate_transition(RoutineState.IGNORED, RoutineState.ACTIVE)
    conn   = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT ignore_count, notify_cooldown_hours FROM routines WHERE id=?",
        (routine_id,)
    )
    row = cursor.fetchone()
    if row:
        ignore_count = (row[0] or 0) + 1
        new_cd       = min(COOLDOWN_MAX_HOURS, (row[1] or COOLDOWN_DEFAULT_HOURS) * 2)
        with db_write_lock:
            cursor.execute(
                "UPDATE routines SET ignore_count=?, notify_cooldown_hours=?, state='active', is_active=1 WHERE id=?",
                (ignore_count, new_cd, routine_id)
            )
            conn.commit()
        print(f"[routine_db]: timeout ignore#{ignore_count} -> cooldown {new_cd:.0f}h (id={routine_id})")
        from memory.event_log import log_event
        log_event("routines", "cooldown_extended", routine_id=routine_id, new_cooldown_hours=new_cd, ignore_count=ignore_count)
    conn.close()


def mark_routine_responded(routine_id: int):
    """Χρήστης ανταποκρίθηκε — reset cooldown."""
    conn   = get_connection()
    cursor = conn.cursor()
    with db_write_lock:
        cursor.execute(
            """
            UPDATE routines
            SET ignore_count=0,
                notify_cooldown_hours=?,
                state='active',
                is_active=1
            WHERE id=?
            """,
            (COOLDOWN_DEFAULT_HOURS, routine_id)
        )
        conn.commit()
    conn.close()


def get_routine_notify_info(routine_id: int) -> dict:
    conn   = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT notify_cooldown_hours, last_notified_ts FROM routines WHERE id=?",
        (routine_id,)
    )
    row = cursor.fetchone()
    conn.close()
    if not row:
        return {"cooldown_hours": COOLDOWN_DEFAULT_HOURS, "last_notified_ts": None}
    return {
        "cooldown_hours":   row[0] if row[0] is not None else COOLDOWN_DEFAULT_HOURS,
        "last_notified_ts": row[1],
    }


# ────────────────────────────────────────────────────────────────
# MUTED UNTIL: Ρουτίνα σε σίγαση μέχρι ημερομηνία
# ────────────────────────────────────────────────────────────────

def set_routine_muted_until(routine_id: int, until_date_str: str) -> None:
    """
    Βάζει τη ρουτίνα σε σίγαση μέχρι until_date_str (YYYY-MM-DD).
    Αποθηκεύει και muted_from (σήμερα). ΔΕΝ αγγίζει sentimental_silenced — αν ο χρήστης
    είχε ζητήσει ρητά silence_emotional παλιότερα, αυτό ΔΕΝ πρέπει να σβήνεται σιωπηλά σε
    κάθε νέο/extended mute (πριν: reset σε 0 κάθε φορά — bug). sentimental_last_sent
    γίνεται σήμερα (όχι NULL) ώστε το cooldown (sentimental_send_every) να ξεκινά ΤΩΡΑ,
    όχι instant sentimental msg στο επόμενο poll (60s μετά το mute — bug).
    """
    today = datetime.now().strftime("%Y-%m-%d")
    conn   = get_connection()
    cursor = conn.cursor()
    with db_write_lock:
        cursor.execute(
            """UPDATE routines
               SET muted_until=?, muted_from=?, sentimental_last_sent=?
               WHERE id=?""",
            (until_date_str, today, today, routine_id)
        )
        conn.commit()
    conn.close()
    print(f"[routine_db]: #{routine_id} muted {today} → {until_date_str}")
    from memory.event_log import log_event
    log_event("routines", "muted", routine_id=routine_id, muted_from=today, until=until_date_str)


def clear_routine_muted_until(routine_id: int) -> None:
    """
    Αφαιρεί τη σίγαση — reset muted_from, sentimental_last_sent, sentimental_silenced.
    Καλείται αυτόματα όταν λήξει η muted_until, ή manual unmute.
    """
    conn   = get_connection()
    cursor = conn.cursor()
    with db_write_lock:
        cursor.execute(
            """UPDATE routines
               SET muted_until=NULL, muted_from=NULL,
                   sentimental_last_sent=NULL, sentimental_silenced=0
               WHERE id=?""",
            (routine_id,)
        )
        conn.commit()
    conn.close()
    print(f"[routine_db]: #{routine_id} unmuted — sentimental state reset")
    from memory.event_log import log_event
    log_event("routines", "unmuted", routine_id=routine_id)


def get_routine_muted_until(routine_id: int) -> str | None:
    """
    Επιστρέφει muted_until (YYYY-MM-DD) ή None αν δεν είναι σε σίγαση.
    Αν η ημερομηνία έχει περάσει, καθαρίζει αυτόματα και επιστρέφει None.
    """
    conn   = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT muted_until FROM routines WHERE id=?", (routine_id,))
    row = cursor.fetchone()
    conn.close()
    if not row or not row[0]:
        return None
    muted_until = row[0]
    today = datetime.now().strftime("%Y-%m-%d")
    if muted_until < today:
        # Ημερομηνία πέρασε — αυτόματο unmute
        clear_routine_muted_until(routine_id)
        return None
    return muted_until



# ────────────────────────────────────────────────────────────────
# SENTIMENTAL ROUTINES: Συναισθηματικά μηνύματα κατά τη σίγαση
# ────────────────────────────────────────────────────────────────

def set_routine_sentimental(routine_id: int, sentimental: bool, send_every: int = 2) -> None:
    """
    Ορίζει αν μια ρουτίνα έχει συναισθηματική αξία (μόνιμο flag).
    send_every: στείλε emotional msg κάθε N μέρες κατά τη σίγαση.
    """
    conn   = get_connection()
    cursor = conn.cursor()
    with db_write_lock:
        cursor.execute(
            "UPDATE routines SET sentimental=?, sentimental_send_every=? WHERE id=?",
            (1 if sentimental else 0, send_every, routine_id)
        )
        conn.commit()
    conn.close()
    print(f"[routine_db]: #{routine_id} sentimental={sentimental}, send_every={send_every}d")


def get_sentimental_info(routine_id: int) -> dict:
    """
    Επιστρέφει όλες τις sentimental πληροφορίες για μια ρουτίνα:
      sentimental, muted_from, muted_until, sentimental_send_every,
      sentimental_last_sent, sentimental_silenced
    """
    conn   = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """SELECT sentimental, muted_from, muted_until,
                  sentimental_send_every, sentimental_last_sent, sentimental_silenced
           FROM routines WHERE id=?""",
        (routine_id,)
    )
    row = cursor.fetchone()
    conn.close()
    if not row:
        return {
            "sentimental": None, "muted_from": None, "muted_until": None,
            "sentimental_send_every": 2, "sentimental_last_sent": None, "sentimental_silenced": False
        }
    return {
        "sentimental":           row[0],   # None=not assessed, 0=no, 1=yes
        "muted_from":            row[1],
        "muted_until":           row[2],
        "sentimental_send_every": row[3] or 2,
        "sentimental_last_sent": row[4],
        "sentimental_silenced":  bool(row[5]),
    }


def update_sentimental_last_sent(routine_id: int, date_str: str) -> None:
    """Καταγράφει πότε στάλθηκε το τελευταίο sentimental μήνυμα."""
    conn   = get_connection()
    cursor = conn.cursor()
    with db_write_lock:
        cursor.execute(
            "UPDATE routines SET sentimental_last_sent=? WHERE id=?",
            (date_str, routine_id)
        )
        conn.commit()
    conn.close()


def set_sentimental_silenced(routine_id: int, silenced: bool) -> None:
    """
    User override: αν silenced=True, δεν στέλνεται κανένα sentimental μήνυμα
    για την τρέχουσα muted περίοδο. Επαναφέρεται αυτόματα στο unmute.
    """
    conn   = get_connection()
    cursor = conn.cursor()
    with db_write_lock:
        cursor.execute(
            "UPDATE routines SET sentimental_silenced=? WHERE id=?",
            (1 if silenced else 0, routine_id)
        )
        conn.commit()
    conn.close()
    state = "silenced" if silenced else "unsilenced"
    print(f"[routine_db]: #{routine_id} sentimental {state}")
    from memory.event_log import log_event
    log_event("routines", f"sentimental_{state}", routine_id=routine_id)


def find_routines_by_name(event_name: str, min_similarity: float = 0.75) -> list[dict]:
    """
    Βρίσκει τις πιο πιθανές ρουτίνες (state='active' ή 'learned') από ένα όνομα
    που είπε ο χρήστης σε φυσική κουβέντα (όχι απαραίτητα το exact canonical event_name).

    3-stage match, ίδια λογική με το upsert_routine αλλά ΧΩΡΙΣ φιλτράρισμα day/time
    (ψάχνει σε ΟΛΕΣ τις ρουτίνες):
      Stage 1 — exact normalized match (επιστρέφει ΟΛΕΣ τις exact matches)
      Stage 2 — difflib fuzzy ratio (>= min_similarity· πριν ήταν 0.55 — θόρυβος σε
                κοντά strings προκαλούσε false matches όπως "μαγείρεμα" αντί άσχετου
                event_name. 0.75 μειώνει τα false positives, χωρίς να σκοτώνει genuine
                paraphrases.)
      Stage 3 — embedding cosine similarity (>= 0.80) αν το difflib αποτύχει
 
    Επιστρέφει λίστα από dicts με id/day/time/event/type/state/confidence.
    """
    conn   = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """SELECT id, day_of_week, time_str, event_name, event_type, confidence, state
           FROM routines WHERE state IN ('active', 'learned')"""
    )
    rows = cursor.fetchall()
    conn.close()

    if not rows:
        return []

    def _row_to_dict(r) -> dict:
        return {
            "id": r[0], "day": r[1], "time": r[2], "event": r[3],
            "type": r[4], "confidence": round(r[5], 2), "state": r[6],
        }

    target = normalize_event(event_name)

    # ── Stage 1: exact normalized match ──────────────────────────
    exact_matches = [_row_to_dict(r) for r in rows if normalize_event(r[3]) == target]
    if exact_matches:
        return exact_matches

    # ── Stage 2: difflib fuzzy ────────────────────────────────────
    best_row, best_score = None, 0.0
    for r in rows:
        score = event_similarity(event_name, r[3])
        if score > best_score:
            best_row, best_score = r, score
    if best_row is not None and best_score >= min_similarity:
        return [_row_to_dict(best_row)]

    # ── Stage 3: embedding cosine similarity ──────────────────────
    best_row, best_score = None, 0.0
    for r in rows:
        sim = _embedding_similarity(event_name, r[3])
        if sim > best_score:
            best_row, best_score = r, sim
    if best_row is not None and best_score >= 0.80:
        return [_row_to_dict(best_row)]

    return []


def find_routine_by_name(event_name: str, min_similarity: float = 0.75) -> dict | None:
    """Backward-compatible wrapper που επιστρέφει μόνο την πρώτη match."""
    matches = find_routines_by_name(event_name, min_similarity=min_similarity)
    return matches[0] if matches else None


def _token_overlap(a: str, b: str) -> set[str]:
    a_tokens = set(normalize_event(a).split())
    b_tokens = set(normalize_event(b).split())
    return a_tokens & b_tokens


def find_routines_for_schedule_control(
    event_name: str, 
    *, 
    min_similarity: float = 0.82,
    day_of_week: str | None = None,
    time_str: str | None = None
) -> list[dict]:
    """
    Very strict matching for the schedule control tool.
    Does not use embeddings. Requires either exact match or high string similarity
    WITH lexical overlap to prevent tool hallucination on irrelevant routines.
    """
    conn   = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """SELECT id, day_of_week, time_str, event_name, event_type, confidence, state
           FROM routines WHERE state IN ('active', 'learned')"""
    )
    rows = cursor.fetchall()
    conn.close()

    if not rows:
        return []
        
    filtered_rows = []
    for r in rows:
        if day_of_week and day_of_week.lower() != str(r[1]).lower():
            continue
        if time_str and time_str != r[2]:
            continue
        filtered_rows.append(r)
    rows = filtered_rows

    def _row_to_dict(r) -> dict:
        return {
            "id": r[0], "day": r[1], "time": r[2], "event": r[3],
            "type": r[4], "confidence": round(r[5], 2), "state": r[6],
        }

    target = normalize_event(event_name)

    # Stage 1: Exact
    exact_matches = [_row_to_dict(r) for r in rows if normalize_event(r[3]) == target]
    if exact_matches:
        return exact_matches

    # Stage 1.5: Substring match (for short queries matching long db names)
    substring_matches = []
    for r in rows:
        norm_r = normalize_event(r[3])
        if target in norm_r.split() or target in norm_r:
            substring_matches.append(r)
            
    if substring_matches:
        # Return ALL substring matches so a generic rule applies to all related routines
        return [_row_to_dict(r) for r in substring_matches]

    # Stage 2: Strict Fuzzy with Overlap
    best_row, best_score = None, 0.0
    for r in rows:
        score = event_similarity(event_name, r[3])
        if score > best_score:
            best_row, best_score = r, score
            
    if best_row is not None and best_score >= min_similarity:
        # Enforce lexical overlap
        if _token_overlap(event_name, best_row[3]):
            return [_row_to_dict(best_row)]

    return []



def find_routines_for_reconciliation(
    *,
    subject_tokens: list[str],
    include_tokens: list[str] | None = None,
    exclude_tokens: list[str] | None = None,
) -> list[dict]:
    """
    Conservative matcher για automatic fact→routine reconciliation.

    Σε αντίθεση με το find_routines_by_name(), εδώ ΔΕΝ θέλουμε fuzzy/embedding guesswork.
    Θέλουμε deterministic, token-based matching πάνω στο stored event_name ώστε facts όπως:
      - "ο Αλέξανδρος είναι κατασκήνωση"
      - "το ποδόσφαιρο του Αλέξανδρου σταμάτησε για το καλοκαίρι"
    να μπορούν να βρουν ΟΛΕΣ τις σχετικές ρουτίνες χωρίς να πειράξουν άσχετες.

    Κανόνες:
      - Όλα τα subject_tokens πρέπει να υπάρχουν
      - Αν include_tokens δοθούν, πρέπει να υπάρχει τουλάχιστον ένα
      - Αν exclude_tokens δοθούν, κανένα δεν πρέπει να υπάρχει
      - Ψάχνουμε μόνο σε state='active' ή 'learned'
    """
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """SELECT id, day_of_week, time_str, event_name, event_type, confidence, state
           FROM routines WHERE state IN ('active', 'learned')"""
    )
    rows = cursor.fetchall()
    conn.close()

    required = [normalize_search_text(tok) for tok in (subject_tokens or []) if str(tok).strip()]
    include = [normalize_search_text(tok) for tok in (include_tokens or []) if str(tok).strip()]
    exclude = [normalize_search_text(tok) for tok in (exclude_tokens or []) if str(tok).strip()]

    if not required and not include:
        return []

    results = []
    for row in rows:
        event_text = normalize_search_text(row[3])
        if required and not all(tok in event_text for tok in required):
            continue
        if include and not any(tok in event_text for tok in include):
            continue
        if exclude and any(tok in event_text for tok in exclude):
            continue
        results.append({
            "id": row[0],
            "day": row[1],
            "time": row[2],
            "event": row[3],
            "type": row[4],
            "confidence": round(row[5], 2),
            "state": row[6],
        })
    return results


# ────────────────────────────────────────────────────────────────
# SEASONAL / TEMPORARY INACTIVITY: active_from / active_until / paused_until
#
# Ορθογώνιο στο muted_until (notification layer — "μη μου στείλεις") και στο
# RoutineState (lifecycle layer — learned/active/decayed/...). Το paused_until
# / active_from / active_until είναι business-logic layer: "αυτή η ρουτίνα
# δεν ισχύει τώρα" (π.χ. ποδόσφαιρο που σταματά καλοκαίρι, κατασκήνωση,
# βάρδια). ΔΕΝ αγγίζει confidence, ΔΕΝ αγγίζει state, ΔΕΝ διαγράφει τίποτα.
# ────────────────────────────────────────────────────────────────

def ensure_routine_schedule_columns() -> None:
    """
    Migration-safe προσθήκη πεδίων seasonal/temporary inactivity στο routines:
      active_from, active_until, paused_until, resume_rule, pause_reason.
    Idempotent (PRAGMA table_info guard, ίδιο pattern με setup_db()) — ασφαλές
    να κληθεί πολλές φορές / σε ήδη existing DB.
    """
    conn   = get_connection()
    cursor = conn.cursor()
    existing_cols = [r[1] for r in cursor.execute("PRAGMA table_info(routines)").fetchall()]

    if "active_from" not in existing_cols:
        cursor.execute("ALTER TABLE routines ADD COLUMN active_from TEXT DEFAULT NULL")
        print("[routine_db]: Migration → 'active_from'")
    if "active_until" not in existing_cols:
        cursor.execute("ALTER TABLE routines ADD COLUMN active_until TEXT DEFAULT NULL")
        print("[routine_db]: Migration → 'active_until'")
    if "paused_until" not in existing_cols:
        cursor.execute("ALTER TABLE routines ADD COLUMN paused_until TEXT DEFAULT NULL")
        print("[routine_db]: Migration → 'paused_until'")
    if "resume_rule" not in existing_cols:
        cursor.execute("ALTER TABLE routines ADD COLUMN resume_rule TEXT DEFAULT NULL")
        print("[routine_db]: Migration → 'resume_rule'")
    if "pause_reason" not in existing_cols:
        cursor.execute("ALTER TABLE routines ADD COLUMN pause_reason TEXT DEFAULT NULL")
        print("[routine_db]: Migration → 'pause_reason'")

    conn.commit()
    conn.close()


def get_routine_schedule_meta(routine_id: int) -> dict:
    """
    Επιστρέφει active_from / active_until / paused_until / resume_rule / pause_reason
    για μία ρουτίνα. Άγνωστο id → dict με όλα None (ίδιο defensive pattern με
    get_sentimental_info).
    """
    conn   = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """SELECT active_from, active_until, paused_until, resume_rule, pause_reason
           FROM routines WHERE id=?""",
        (routine_id,)
    )
    row = cursor.fetchone()
    conn.close()
    if not row:
        return {
            "active_from": None, "active_until": None, "paused_until": None,
            "resume_rule": None, "pause_reason": None,
        }
    return {
        "active_from":  row[0],
        "active_until": row[1],
        "paused_until": row[2],
        "resume_rule":  row[3],
        "pause_reason": row[4],
    }


def set_routine_paused_until(routine_id: int, paused_until: str, reason: str | None = None) -> None:
    """
    Παύει προσωρινά τη ρουτίνα μέχρι paused_until (YYYY-MM-DD) — π.χ. καλοκαιρινό
    διάλειμμα, κατασκήνωση. ΔΕΝ αγγίζει confidence/state· η ρουτίνα παραμένει
    ως έχει, απλά δεν "μετράει" στον scheduler μέχρι να περάσει η ημερομηνία
    (βλ. is_routine_temporarily_inactive_meta).
    """
    conn   = get_connection()
    cursor = conn.cursor()
    with db_write_lock:
        cursor.execute(
            "UPDATE routines SET paused_until=?, pause_reason=? WHERE id=?",
            (paused_until, reason, routine_id)
        )
        conn.commit()
    conn.close()
    print(f"[routine_db]: #{routine_id} paused → {paused_until} (reason={reason})")
    from memory.event_log import log_event
    log_event("routines", "paused", routine_id=routine_id, paused_until=paused_until, reason=reason)


def clear_routine_paused_until(routine_id: int) -> None:
    """Αφαιρεί την προσωρινή παύση (manual resume) — καθαρίζει και pause_reason."""
    conn   = get_connection()
    cursor = conn.cursor()
    with db_write_lock:
        cursor.execute(
            "UPDATE routines SET paused_until=NULL, pause_reason=NULL WHERE id=?",
            (routine_id,)
        )
        conn.commit()
    conn.close()
    print(f"[routine_db]: #{routine_id} resumed (paused_until cleared)")
    from memory.event_log import log_event
    log_event("routines", "resumed", routine_id=routine_id)


def set_routine_active_window(routine_id: int, active_from: str | None = None,
                               active_until: str | None = None, reason: str | None = None) -> None:
    """
    Ορίζει (set_window) ή καθαρίζει (clear_window, καλώντας με active_from=None,
    active_until=None) το παράθυρο active_from/active_until μιας ρουτίνας.
    reason είναι προαιρετικό — αν δεν δοθεί, το υπάρχον pause_reason ΔΕΝ αγγίζεται
    (ώστε ένα clear_window χωρίς reason να μη σβήνει σιωπηλά τον λόγο ενός
    προηγούμενου pause).
    """
    conn   = get_connection()
    cursor = conn.cursor()
    with db_write_lock:
        if reason is not None:
            cursor.execute(
                "UPDATE routines SET active_from=?, active_until=?, pause_reason=? WHERE id=?",
                (active_from, active_until, reason, routine_id)
            )
        else:
            cursor.execute(
                "UPDATE routines SET active_from=?, active_until=? WHERE id=?",
                (active_from, active_until, routine_id)
            )
        conn.commit()
    conn.close()
    print(f"[routine_db]: #{routine_id} active window → from={active_from}, until={active_until}")
    from memory.event_log import log_event
    log_event("routines", "active_window_set", routine_id=routine_id,
               active_from=active_from, active_until=active_until, reason=reason)


def set_routine_resume_rule(routine_id: int, resume_rule: str | None = None) -> None:
    """Ορίζει το resume_rule (π.χ. 'every_september', 'next_school_year', 'manual_only')."""
    conn   = get_connection()
    cursor = conn.cursor()
    with db_write_lock:
        cursor.execute(
            "UPDATE routines SET resume_rule=? WHERE id=?",
            (resume_rule, routine_id)
        )
        conn.commit()
    conn.close()
    print(f"[routine_db]: #{routine_id} resume_rule → {resume_rule}")
    from memory.event_log import log_event
    log_event("routines", "resume_rule_set", routine_id=routine_id, resume_rule=resume_rule)


def is_routine_temporarily_inactive_meta(routine: dict, now: datetime | None = None) -> tuple[bool, str | None]:
    """
    Κεντρικό gate: αποφασίζει αν μια ρουτίνα είναι ΠΡΟΣΩΡΙΝΑ ανενεργή, ΧΩΡΙΣ να
    είναι disabled/deleted/decayed. `routine` = dict με (τουλάχιστον) τα κλειδιά
    paused_until / active_from / active_until — π.χ. ό,τι επιστρέφει
    get_routine_schedule_meta().

    ΚΡΙΣΙΜΟ: inactive ≠ disabled, inactive ≠ deleted. Ο caller (scheduler) πρέπει
    να skip-άρει trigger/confirm/send/proactive scoring ΧΩΡΙΣ να το μετρήσει ως
    missed/failure και ΧΩΡΙΣ να αγγίξει confidence/state.

    Επιστρέφει:
      (True,  "paused_until")        — ενεργό paused_until, today <= paused_until
      (True,  "before_active_from")  — today < active_from
      (True,  "after_active_until")  — today > active_until
      (False, None)                  — κανονικά ενεργή
    """
    today = (now or datetime.now()).strftime("%Y-%m-%d")

    paused_until = routine.get("paused_until")
    if paused_until and today <= paused_until:
        return True, "paused_until"

    active_from = routine.get("active_from")
    if active_from and today < active_from:
        return True, "before_active_from"

    active_until = routine.get("active_until")
    if active_until and today > active_until:
        return True, "after_active_until"

    return False, None


# ────────────────────────────────────────────────────────────────
# PENDING CONFIRMATIONS PERSISTENCE (Recovery After Restart)
# ────────────────────────────────────────────────────────────────

def _setup_pending_table():
    conn   = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS pending_confirmations (
            routine_id INTEGER PRIMARY KEY,
            event_name TEXT,
            sent_at    TEXT
        )
    """)
    conn.commit()
    conn.close()


def save_pending_confirmation(routine_id: int, event_name: str, sent_at: datetime):
    conn   = get_connection()
    cursor = conn.cursor()
    with db_write_lock:
        cursor.execute(
            "INSERT OR REPLACE INTO pending_confirmations (routine_id, event_name, sent_at) VALUES (?, ?, ?)",
            (routine_id, event_name, sent_at.isoformat())
        )
        conn.commit()
    conn.close()


def remove_pending_confirmation(routine_id: int):
    conn = get_connection()
    with db_write_lock:
        conn.execute("DELETE FROM pending_confirmations WHERE routine_id=?", (routine_id,))
        conn.commit()
    conn.close()


def clear_pending_confirmations():
    conn = get_connection()
    with db_write_lock:
        conn.execute("DELETE FROM pending_confirmations")
        conn.commit()
    conn.close()


def load_pending_confirmations() -> dict:
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT pc.routine_id, pc.event_name, pc.sent_at
        FROM pending_confirmations pc
        JOIN routines r ON r.id = pc.routine_id
        WHERE r.state = 'trigger_pending'
    """)
    rows = cursor.fetchall()

    # βρες stale rows για cleanup
    cursor.execute("""
        SELECT pc.routine_id
        FROM pending_confirmations pc
        JOIN routines r ON r.id = pc.routine_id
        WHERE r.state != 'trigger_pending'
    """)
    stale_rows = [r[0] for r in cursor.fetchall()]

    conn.close()

    for rid in stale_rows:
        remove_pending_confirmation(rid)

    result = {}
    for r_id, event_name, sent_at_str in rows:
        try:
            sent_at = datetime.fromisoformat(sent_at_str)
        except Exception:
            sent_at = datetime.now()
        result[r_id] = {"event": event_name, "sent_at": sent_at}

    return result


_setup_pending_table()
ensure_routine_schedule_columns()


# ────────────────────────────────────────────────────────────────
# PHASE 3C: ROUTINE CONDITIONS
# ────────────────────────────────────────────────────────────────

def set_routine_condition(
    routine_id: int,
    *,
    condition_type: str | None = None,
    condition_payload: str | None = None,
    condition_mode: str | None = None,
    priority: int | None = None,
    source_memory_ref: str | None = None,
) -> None:
    conn = get_connection(write=True)
    cursor = conn.cursor()

    fields = []
    values = []

    if condition_type is not None:
        fields.append("condition_type = ?")
        values.append(condition_type)

    if condition_payload is not None:
        fields.append("condition_payload = ?")
        values.append(condition_payload)

    if condition_mode is not None:
        fields.append("condition_mode = ?")
        values.append(condition_mode)

    if priority is not None:
        fields.append("priority = ?")
        values.append(priority)

    if source_memory_ref is not None:
        fields.append("source_memory_ref = ?")
        values.append(source_memory_ref)

    if not fields:
        conn.close()
        return

    values.append(routine_id)
    with db_write_lock:
        cursor.execute(
            f"UPDATE routines SET {', '.join(fields)} WHERE id = ?",
            values,
        )
        conn.commit()
    conn.close()

# ─────────────────────────────────────────────────────────────────────────────
# Phase 3C: MULTI-CONDITIONS HELPERS
# ─────────────────────────────────────────────────────────────────────────────
import json

def get_routine_conditions(routine_id: int) -> list[dict]:
    with db_write_lock:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT conditions_json, condition_type, condition_payload, condition_mode FROM routines WHERE id = ?",
            (routine_id,)
        )
        row = cursor.fetchone()
        if not row:
            return []
            
        c_json, c_type, c_payload, c_mode = row
        
        # 1. New multi-condition JSON
        if c_json:
            try:
                parsed = json.loads(c_json)
                if isinstance(parsed, list):
                    return parsed
            except json.JSONDecodeError:
                pass
                
        # 2. Fallback to legacy single condition
        if c_type:
            return [{
                "condition_type": c_type,
                "condition_payload": json.loads(c_payload) if c_payload else None,
                "condition_mode": c_mode
            }]
            
        return []

def append_routine_condition(
    routine_id: int,
    *,
    condition_type: str,
    condition_payload: str | dict,
    condition_mode: str,
    source_memory_ref: str | None = None,
) -> bool:
    """Appends a new condition to conditions_json if it doesn't already exist. Returns True if added."""
    
    # Normalize payload
    if isinstance(condition_payload, str):
        try:
            parsed_payload = json.loads(condition_payload)
        except json.JSONDecodeError:
            parsed_payload = condition_payload
    else:
        parsed_payload = condition_payload

    existing_conditions = get_routine_conditions(routine_id)
    
    # Check for duplicates
    for cond in existing_conditions:
        if (cond.get("condition_type") == condition_type and 
            cond.get("condition_payload") == parsed_payload and 
            cond.get("condition_mode") == condition_mode):
            return False # Duplicate
            
    new_cond = {
        "condition_type": condition_type,
        "condition_payload": parsed_payload,
        "condition_mode": condition_mode,
    }
    if source_memory_ref:
        new_cond["source_memory_ref"] = source_memory_ref
        
    existing_conditions.append(new_cond)
    
    with db_write_lock:
        conn = get_connection(write=True)
        conn.execute(
            "UPDATE routines SET conditions_json = ? WHERE id = ?",
            (json.dumps(existing_conditions), routine_id)
        )
        conn.commit()
    return True

# ─────────────────────────────────────────────────────────────────────────────
# LEGACY CONDITION HELPER (Still used for single overwrites?)
# ─────────────────────────────────────────────────────────────────────────────

def get_routine_condition(routine_id: int) -> dict:
    conn = get_connection()
    cursor = conn.cursor()

    row = cursor.execute(
        """
        SELECT condition_type, condition_payload, condition_mode, priority, source_memory_ref, conflict_group
        FROM routines
        WHERE id = ?
        """,
        (routine_id,),
    ).fetchone()

    conn.close()

    if not row:
        return {}

    return {
        "condition_type": row[0],
        "condition_payload": row[1],
        "condition_mode": row[2],
        "priority": row[3] or 0,
        "source_memory_ref": row[4],
        "conflict_group": row[5],
    }
# ----------------------------------------------------------------
# 3C.1: CONTEXT STATE STORE
# ----------------------------------------------------------------

def get_context_state(key: str) -> dict | None:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT value, expires_at, updated_at FROM context_state WHERE key=?", (key,))
    row = cursor.fetchone()
    conn.close()
    
    if not row:
        return None
    return {
        "value": row[0],
        "expires_at": row[1],
        "updated_at": row[2]
    }

def set_context_state(key: str, value: str, expires_at: str | None = None) -> None:
    conn = get_connection()
    cursor = conn.cursor()
    from datetime import datetime
    now_str = datetime.now().isoformat()
    try:
        with db_write_lock:
            cursor.execute(
                """
                INSERT INTO context_state (key, value, expires_at, updated_at) 
                VALUES (?, ?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET 
                    value=excluded.value, 
                    expires_at=excluded.expires_at, 
                    updated_at=excluded.updated_at
                """,
                (key, value, expires_at, now_str)
            )
            conn.commit()
    finally:
        conn.close()
