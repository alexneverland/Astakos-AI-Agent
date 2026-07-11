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
import time
from datetime import datetime

LOGS_DIR = os.path.join(os.path.dirname(__file__), "..", "logs", "events")

# Lock for thread-safety: the scheduler runs multiple jobs in parallel
# and log_event is called by multiple threads simultaneously.
_log_lock = threading.Lock()

# ────────────────────────────────────────────────────────────────
# CROSS-PROCESS LOCK
# The _log_lock above only protects threads WITHIN the same process.
# But the web server (api/server.py, uvicorn) AND the telegram bot are running
# simultaneously as 2 separate OS processes and they write to the SAME daily JSON
# file — without a cross-process lock, the os.replace of the two can
# crashes (WinError 5) because no one sees each other's lock.
# Solution: msvcrt file lock on a separate sentinel file (same technique as
# the run_telegram.lock) — serializes log_event() calls between
# processes, without interfering with the atomic-write file itself.
# ────────────────────────────────────────────────────────────────

def _acquire_cross_process_lock():
    if os.name != "nt":
        return None
    try:
        import msvcrt
        os.makedirs(LOGS_DIR, exist_ok=True)
        lock_path = os.path.join(LOGS_DIR, ".event_log.lock")
        f = open(lock_path, "w")
        for _attempt in range(40):  # up to ~2s wait under heavy contention
            try:
                msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
                return f
            except OSError:
                time.sleep(0.05)
        f.close()
        return None  # failed to acquire lock — proceeding without it (the retry+fallback below remains a safety net)
    except Exception:
        return None


def _release_cross_process_lock(f):
    if f is None:
        return
    try:
        import msvcrt
        f.seek(0)
        msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
    except Exception:
        pass
    try:
        f.close()
    except Exception:
        pass

# ────────────────────────────────────────────────────────────────
# EVENT LOGGING
# ────────────────────────────────────────────────────────────────

def log_event(job: str, action: str, **kwargs):
    """
    Logs an event to a daily JSON file (logs/events/YYYY-MM-DD.json).

    Example:
        log_event("routine_scan", "triggered", routine_id=14, confidence=0.8)
        log_event("reminder",     "sent",      task="Medicine Alexandros")
        log_event("proactive",    "skipped",   reason="quiet_hours")

    Atomic write: writes to .tmp first, fsync, then os.replace → if it
    crashes in the middle, no corrupted file is left behind (nor truncated JSON).
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

        with _log_lock:
            _cross_lock = _acquire_cross_process_lock()
            try:
                entries = []
                if os.path.exists(log_file):
                    try:
                        with open(log_file, "r", encoding="utf-8") as f:
                            entries = json.load(f)
                    except Exception:
                        entries = []   # corrupted → starting fresh for today

                entries.append(entry)

                # Atomic write: .tmp → fsync → os.replace
                # If a power outage/crash occurs before the replace: old file remains intact.
                # If cut after replace: new complete file.
                tmp_file = log_file + ".tmp"
                with open(tmp_file, "w", encoding="utf-8") as f:
                    json.dump(entries, f, ensure_ascii=False, indent=2)
                    f.flush()
                    try:
                        os.fsync(f.fileno())
                    except OSError:
                        pass  # fsync is not supported everywhere — flush is enough
                # With the cross-process lock above, the web server and the
                # telegram bots no longer crash on the same file — this
                # retry+fallback remains only as a safety net for
                # antivirus locks or failed lock acquisition.
                for _attempt in range(5):
                    try:
                        os.replace(tmp_file, log_file)
                        break
                    except OSError:
                        if _attempt < 4:
                            time.sleep(0.05 * (_attempt + 1))
                        else:
                            # Fallback: we wait 500ms and write directly.
                            # Non-atomic but the event is not silently lost.
                            time.sleep(0.5)
                            _written = False
                            try:
                                with open(log_file, "w", encoding="utf-8") as _f:
                                    json.dump(entries, _f, ensure_ascii=False, indent=2)
                                _written = True
                                print("⚠️ [event_log]: os.replace WinError 5 → direct write fallback OK")
                            except Exception as _fe:
                                print(f"⚠️ [event_log]: direct write also failed: {_fe}")
                            finally:
                                try:
                                    os.unlink(tmp_file)
                                except OSError:
                                    pass
                            if not _written:
                                raise
                            break
            finally:
                _release_cross_process_lock(_cross_lock)

    except Exception as e:
        print(f"⚠️ [event_log]: {e}")


def get_events(date_str: str = None, job: str = None, action: str = None) -> list:
    """
    Returns events from the daily log.
    Usage: get_events("2026-05-22", job="routines", action="triggered")
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
DEDUP_COOLDOWN_DEFAULT = 300  # 5 minutes default cooldown


def is_duplicate_routine(routine_id: int, cooldown_hours: float) -> bool:
    """
    Per-routine dedup based on last_notified_ts from the DB.
    Much more reliable than text-hash dedup because it does not depend on the text.
    Returns True if the routine was notified recently (within cooldown).
    """
    try:
        from memory.routine_db import get_routine_notify_info
        from datetime import datetime as _dt
        info     = get_routine_notify_info(routine_id)
        last_ts  = info.get("last_notified_ts")
        if not last_ts:
            return False  # Never notified → not a duplicate
        last_dt       = _dt.fromisoformat(last_ts)
        elapsed       = (_dt.now() - last_dt).total_seconds()
        cooldown_secs = cooldown_hours * 3600
        if elapsed < cooldown_secs:
            remaining = int((cooldown_secs - elapsed) / 3600)
            print(f"[event_log]: 🚫 Routine #{routine_id} on cooldown — {remaining}h remaining")
            return True
        return False
    except Exception as e:
        print(f"[event_log]: is_duplicate_routine error: {e}")
        return False  # Graceful fallback — we allow sending
def is_duplicate_notification(message: str, cooldown_seconds: int = DEDUP_COOLDOWN_DEFAULT) -> bool:
    """
    Returns True if the same message was sent recently (within cooldown).
    Usage: if is_duplicate_notification(msg): return

    Automatically clears old entries (>1 hour).
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

# ────────────────────────────────────────────────────────────────
# REPLAY TIMELINE
# ────────────────────────────────────────────────────────────────

def get_routine_timeline(routine_id: int = None, days: int = 3) -> list:
    """
    Returns a chronological timeline of events for a routine (or all).
    Searches within the last N days.
    """
    from datetime import timedelta
    results = []
    for i in range(days):
        date_str = (datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d")
        log_file = os.path.join(LOGS_DIR, f"{date_str}.json")
        if not os.path.exists(log_file):
            continue
        try:
            with open(log_file, "r", encoding="utf-8") as f:
                entries = json.load(f)
            for e in entries:
                if e.get("job") != "routines":
                    continue  # ignore events from other jobs (reminders, proactive, etc.)
                if routine_id is None or str(e.get("routine_id")) == str(routine_id):
                    if e.get("action") in (
                        "triggered", "sent", "confirmed", "timeout",
                        "dismissed", "decay", "cooldown_extended", "state_change",
                        "deferred_followup", "timeout_decay", "skipped",
                    ):
                        results.append(e)
        except Exception:
            continue

    results.sort(key=lambda x: x.get("timestamp", ""))
    return results
