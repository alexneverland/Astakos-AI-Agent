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
        sim = _embedding_similarity(c_event, ex_ev)
        if sim >= 0.88:
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
        is_everyday = row[2] in ("Everyday", "Καθημερινά")

        if new_conf < 0.1:
            new_state   = RoutineState.DECAYED
            active_flag = 0
        elif is_everyday:
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
        WHERE (day_of_week=? OR day_of_week='Everyday')
        AND state='active'
        ORDER BY time_str ASC
    """, (c_day,))
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
            "UPDATE routines SET ignore_count=0, notify_cooldown_hours=?, state='active', is_active=1 WHERE id=?",
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
