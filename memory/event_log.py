# ================================================================
# Project: Astakos AI Agent 🦞
# Developer: Lazaros (Piston-7)
# Description: Event Logging & Dedup Protection
# ================================================================

import os
import json
import uuid
import hashlib
import threading
from datetime import datetime

LOGS_DIR = os.path.join(os.path.dirname(__file__), "..", "logs", "events")

# ────────────────────────────────────────────────────────────────
# EVENT LOGGING
# ────────────────────────────────────────────────────────────────

def log_event(job: str, action: str, **kwargs):
    """
    Καταγράφει ένα event σε daily JSON file (logs/events/YYYY-MM-DD.json).

    Παράδειγμα:
        log_event("routine_scan", "triggered", routine_id=14, confidence=0.8)
        log_event("reminder",     "sent",      task="Φάρμακο Αλέξανδρος")
        log_event("proactive",    "skipped",   reason="quiet_hours")
    """
    try:
        os.makedirs(LOGS_DIR, exist_ok=True)
        today    = datetime.now().strftime("%Y-%m-%d")
        log_file = os.path.join(LOGS_DIR, f"{today}.json")

        entry = {
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "event_id":  str(uuid.uuid4())[:8],
            "job":       job,
            "action":    action,
            **{k: str(v) if not isinstance(v, (str, int, float, bool, type(None))) else v
               for k, v in kwargs.items()}
        }

        entries = []
        if os.path.exists(log_file):
            try:
                with open(log_file, "r", encoding="utf-8") as f:
                    entries = json.load(f)
            except Exception:
                entries = []

        entries.append(entry)

        with open(log_file, "w", encoding="utf-8") as f:
            json.dump(entries, f, ensure_ascii=False, indent=2)

    except Exception as e:
        print(f"⚠️ [event_log]: {e}")


def get_events(date_str: str = None, job: str = None, action: str = None) -> list:
    """
    Επιστρέφει events από το daily log.
    Χρήση: get_events("2026-05-22", job="routines", action="triggered")
    """
    try:
        target = date_str or datetime.now().strftime("%Y-%m-%d")
        log_file = os.path.join(LOGS_DIR, f"{target}.json")
        if not os.path.exists(log_file):
            return []
        with open(log_file, "r", encoding="utf-8") as f:
            entries = json.load(f)
        if job:
            entries = [e for e in entries if e.get("job") == job]
        if action:
            entries = [e for e in entries if e.get("action") == action]
        return entries
    except Exception:
        return []


# ────────────────────────────────────────────────────────────────
# EVENT DEDUP PROTECTION
# ────────────────────────────────────────────────────────────────

_dedup_cache: dict = {}   # {msg_hash: sent_at_timestamp}
_dedup_lock  = threading.Lock()
DEDUP_COOLDOWN_DEFAULT = 300  # 5 λεπτά default cooldown


def is_duplicate_routine(routine_id: int, cooldown_hours: float) -> bool:
    """
    Per-routine dedup βασισμένο στο last_notified_ts από τη DB.
    Πολύ πιο αξιόπιστο από text-hash dedup γιατί δεν εξαρτάται από το κείμενο.
    Επιστρέφει True αν η ρουτίνα ειδοποιήθηκε πρόσφατα (εντός cooldown).
    """
    try:
        from memory.routine_db import get_routine_notify_info
        from datetime import datetime as _dt
        info     = get_routine_notify_info(routine_id)
        last_ts  = info.get("last_notified_ts")
        if not last_ts:
            return False  # Ποτέ δεν ειδοποιήθηκε → όχι duplicate
        last_dt       = _dt.fromisoformat(last_ts)
        elapsed       = (_dt.now() - last_dt).total_seconds()
        cooldown_secs = cooldown_hours * 3600
        if elapsed < cooldown_secs:
            remaining = int((cooldown_secs - elapsed) / 3600)
            print(f"[event_log]: 🚫 Routine #{routine_id} σε cooldown — {remaining}ω ακόμα")
            return True
        return False
    except Exception as e:
        print(f"[event_log]: is_duplicate_routine error: {e}")
        return False  # Graceful fallback — επιτρέπουμε αποστολή



def is_duplicate_notification(message: str, cooldown_seconds: int = DEDUP_COOLDOWN_DEFAULT) -> bool:
    """
    Επιστρέφει True αν το ίδιο μήνυμα στάλθηκε πρόσφατα (εντός cooldown).
    Χρήση: if is_duplicate_notification(msg): return

    Αυτόματα καθαρίζει παλιές εγγραφές (>1 ώρα).
    """
    import time
    msg_hash = hashlib.md5(message.strip().encode("utf-8")).hexdigest()[:10]
    now      = time.time()

    with _dedup_lock:
        cutoff   = now - 3600
        old_keys = [k for k, v in _dedup_cache.items() if v < cutoff]
        for k in old_keys:
            del _dedup_cache[k]

        if msg_hash in _dedup_cache:
            elapsed = now - _dedup_cache[msg_hash]
            if elapsed < cooldown_seconds:
                return True  # duplicate

        _dedup_cache[msg_hash] = now
        return False
