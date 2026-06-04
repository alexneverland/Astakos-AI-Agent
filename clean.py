# ================================================================
# Project: Astakos AI Agent 🦞
# Developer: Lazaros (Piston-7)
# Description: Mastro-Cleaner — Standalone maintenance script for
#              the Astakos JSON memory files. Run periodically to
#              compact and de-duplicate memory state.
# Copyright (c) 2026 - All Rights Reserved
# ================================================================
#
# Usage:
#   python clean.py                       # Όλα τα tasks (default)
#   python clean.py --dry-run             # Δες τι θα έκανε χωρίς αλλαγή
#   python clean.py --capabilities        # Μόνο σύμπτυξη capabilities
#   python clean.py --chat-history        # Μόνο trim chat history
#   python clean.py --sessions            # Μόνο trim sessions
#   python clean.py --working-memory      # Μόνο σύμπτυξη working memory
#   python clean.py --chat-keep 50        # Custom όριο για chat history
#   python clean.py --sessions-keep 20    # Custom όριο για sessions
#   python clean.py --no-backup           # Παράκαμψη backup (όχι recommended)
#   python clean.py --photos              # Σβήσε temp φωτογραφίες (αναρχειοθέτητες)
#
# Συνδυάζονται:
#   python clean.py --capabilities --chat-history --dry-run
#
# ================================================================

import os
import sys
import json
import shutil
import argparse
import sqlite3
from datetime import datetime

# Προσθήκη του project root στο path για να φορτώσει core/config
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# ────────────────────────────────────────────────────────────────
# CONFIGURATION
# ────────────────────────────────────────────────────────────────

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
BACKUP_DIR   = os.path.join(PROJECT_ROOT, "_cleaner_backups")

# Προεπιλεγμένα όρια rotation
DEFAULT_CHAT_KEEP     = 100
DEFAULT_SESSIONS_KEEP = 30

# Paths αρχείων (με fallback αν δεν φορτώσει το config)
try:
    from config import (
        WORKING_MEMORY_FILE,
        SESSIONS_FILE,
        PROFILE_FILE,
        CONVERSATION_DB_FILE,
    )
    CHAT_HISTORY_FILE     = os.path.join(PROJECT_ROOT, "astakos_chat_history.json")
    TELEGRAM_HISTORY_FILE = os.path.join(PROJECT_ROOT, "astakos_telegram_history.json")
    CAPABILITIES_FILE     = os.path.join(PROJECT_ROOT, "astakos_capabilities.json")
except ImportError:
    CHAT_HISTORY_FILE     = os.path.join(PROJECT_ROOT, "astakos_chat_history.json")
    TELEGRAM_HISTORY_FILE = os.path.join(PROJECT_ROOT, "astakos_telegram_history.json")
    CAPABILITIES_FILE   = os.path.join(PROJECT_ROOT, "astakos_capabilities.json")
    SESSIONS_FILE       = os.path.join(PROJECT_ROOT, "astakos_sessions.json")
    WORKING_MEMORY_FILE = os.path.join(PROJECT_ROOT, "astakos_working_memory.json")
    PROFILE_FILE        = os.path.join(PROJECT_ROOT, "astakos_profile.json")
    CONVERSATION_DB_FILE = os.path.join(PROJECT_ROOT, "astakos_conversation_history.db")

PHOTOS_INDEX_FILE = os.path.join(PROJECT_ROOT, "astakos_photos_index.json")
PHOTOS_DIR        = os.path.join(PROJECT_ROOT, "telegram_photos")

# LLM loader (lazy, με fallback αν δεν φορτώσει)
def _load_llm():
    try:
        from core.brain import llm_heavy
        return llm_heavy
    except Exception as e:
        log(f"⚠️ Δεν φόρτωσε το llm_heavy: {e}", "warn")
        return None


# ────────────────────────────────────────────────────────────────
# MASTRO-STYLE LOGGING
# ────────────────────────────────────────────────────────────────

_COLORS = {
    "info":   "\033[94m",  # μπλε
    "ok":     "\033[92m",  # πράσινο
    "warn":   "\033[93m",  # κίτρινο
    "err":    "\033[91m",  # κόκκινο
    "header": "\033[95m",  # μωβ
    "dim":    "\033[90m",  # γκρι
}
_RESET = "\033[0m"


def log(msg: str, color: str = "info") -> None:
    """Έγχρωμο logging Mastro-style."""
    c = _COLORS.get(color, "")
    print(f"{c}{msg}{_RESET}")


def header(title: str) -> None:
    """Header για κάθε task."""
    line = "─" * 60
    log(f"\n{line}", "dim")
    log(f"🦞 {title}", "header")
    log(line, "dim")


# ────────────────────────────────────────────────────────────────
# BACKUP HELPER
# ────────────────────────────────────────────────────────────────

def backup_file(path: str, enabled: bool = True) -> str:
    """
    Αντιγράφει το αρχείο σε φάκελο _cleaner_backups/ με timestamp.
    Επιστρέφει το path του backup ή "" αν δεν έγινε.
    """
    if not enabled:
        log("⏭️  Παράκαμψη backup (--no-backup)", "warn")
        return ""
    if not os.path.exists(path):
        return ""
    os.makedirs(BACKUP_DIR, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = os.path.join(BACKUP_DIR, f"{os.path.basename(path)}.{ts}.bak")
    shutil.copy2(path, backup_path)
    log(f"💾 Backup → {os.path.relpath(backup_path, PROJECT_ROOT)}", "dim")
    return backup_path


def safe_load_json(path: str):
    """Φορτώνει JSON με fallback σε None αν αποτύχει."""
    if not os.path.exists(path):
        log(f"⚠️  Δεν υπάρχει: {os.path.basename(path)}", "warn")
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        log(f"❌ Σφάλμα ανάγνωσης {os.path.basename(path)}: {e}", "err")
        return None


def safe_save_json(path: str, data, dry_run: bool = False) -> bool:
    """Γράφει JSON. Σε dry_run, δεν αγγίζει το αρχείο."""
    if dry_run:
        log("🧪 DRY-RUN: δεν γράφτηκε τίποτα", "warn")
        return True
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        log(f"✅ Αποθηκεύτηκε: {os.path.basename(path)}", "ok")
        return True
    except Exception as e:
        log(f"❌ Σφάλμα εγγραφής: {e}", "err")
        return False


def strip_markdown_json(text: str) -> str:
    """Καθαρίζει markdown wrappers (```json ... ```) γύρω από LLM output."""
    text = text.strip()
    if text.startswith("```json"):
        text = text[7:]
    elif text.startswith("```"):
        text = text[3:]
    if text.endswith("```"):
        text = text[:-3]
    return text.strip()


# ────────────────────────────────────────────────────────────────
# TASK 1: CAPABILITIES — LLM CONSOLIDATION
# ────────────────────────────────────────────────────────────────

def consolidate_capabilities(dry_run: bool = False, backup: bool = True) -> bool:
    header("Σύμπτυξη astakos_capabilities.json (can_do / cannot_do)")
    data = safe_load_json(CAPABILITIES_FILE)
    if not data or not isinstance(data, dict):
        log("⚠️  Άκυρο schema — περίμενα {can_do:[], cannot_do:[]}", "warn")
        return False

    can_do    = data.get("can_do", [])
    cannot_do = data.get("cannot_do", [])
    log(f"📊 Πριν: {len(can_do)} can_do  |  {len(cannot_do)} cannot_do", "info")

    llm = _load_llm()
    if llm is None:
        log("❌ Δεν φόρτωσε το LLM — παρακάμπτεται η σύμπτυξη.", "err")
        return False

    prompt = f"""Είσαι ο μηχανικός συντήρησης για τη μνήμη ενός AI agent.

Σου δίνω 2 λίστες:
  - "can_do": πράγματα που μπορεί να κάνει
  - "cannot_do": περιορισμοί και αδυναμίες

Δουλειά σου:
  1. Συγχώνευσε διπλότυπα και πολύ παρόμοια entries σε ένα σαφές.
  2. Αφαίρεσε αντιφάσεις (αν κάτι είναι ταυτόχρονα can_do και cannot_do, κρίνε με βάση την πιο πρόσφατη/συγκεκριμένη γραφή).
  3. Δώσε γενικευμένη, καθαρή διατύπωση (όχι 5 παραλλαγές της ίδιας ιδέας).
  4. Κράτα την αρχική γλώσσα (Ελληνικά).

ΕΠΕΣΤΡΕΨΕ ΑΠΟΚΛΕΙΣΤΙΚΑ valid JSON με αυτή τη μορφή, χωρίς markdown:
{{"can_do": [...], "cannot_do": [...]}}

ΛΙΣΤΑ CAN_DO:
{json.dumps(can_do, ensure_ascii=False, indent=2)}

ΛΙΣΤΑ CANNOT_DO:
{json.dumps(cannot_do, ensure_ascii=False, indent=2)}
"""

    log("🤖 Κλήση LLM για consolidation...", "info")
    try:
        response = llm.invoke(prompt)
        # Multimodal-safe extraction
        from core.utils import clean_message
        raw = clean_message(response.content)
        raw = strip_markdown_json(raw)
        new_data = json.loads(raw)
    except Exception as e:
        log(f"❌ Σφάλμα κατά τη σύμπτυξη: {e}", "err")
        return False

    # Validation
    if not isinstance(new_data, dict) or "can_do" not in new_data or "cannot_do" not in new_data:
        log("❌ Το LLM γύρισε άκυρο schema. Δεν γράφω.", "err")
        return False
    if not isinstance(new_data["can_do"], list) or not isinstance(new_data["cannot_do"], list):
        log("❌ can_do/cannot_do δεν είναι λίστες. Δεν γράφω.", "err")
        return False

    new_can    = len(new_data["can_do"])
    new_cannot = len(new_data["cannot_do"])
    saved_can    = len(can_do) - new_can
    saved_cannot = len(cannot_do) - new_cannot

    log(f"📊 Μετά: {new_can} can_do (-{saved_can})  |  {new_cannot} cannot_do (-{saved_cannot})", "ok")

    if dry_run:
        log("🧪 DRY-RUN — δες παρακάτω τι θα γραφόταν:", "warn")
        print(json.dumps(new_data, ensure_ascii=False, indent=2))
        return True

    backup_file(CAPABILITIES_FILE, enabled=backup)
    return safe_save_json(CAPABILITIES_FILE, new_data, dry_run=False)


# ────────────────────────────────────────────────────────────────
# TASK 2: CHAT HISTORY — ROTATION
# ────────────────────────────────────────────────────────────────

def _trim_history_file(path: str, label: str, keep: int, dry_run: bool, backup: bool) -> bool:
    header(f"Trim {label} (κρατά τα τελευταία {keep})")
    data = safe_load_json(path)
    if data is None:
        return False
    if not isinstance(data, list):
        log("⚠️  Άκυρο schema — περίμενα list", "warn")
        return False

    total = len(data)
    log(f"📊 Πριν: {total} μηνύματα", "info")

    if total <= keep:
        log(f"ℹ️  Δεν χρειάζεται trim (≤ {keep}).", "dim")
        return True

    trimmed = data[-keep:]
    removed = total - keep
    log(f"📊 Μετά: {len(trimmed)} μηνύματα (−{removed})", "ok")

    if dry_run:
        return True

    backup_file(path, enabled=backup)
    return safe_save_json(path, trimmed, dry_run=False)


def trim_chat_history(keep: int = DEFAULT_CHAT_KEEP, dry_run: bool = False, backup: bool = True) -> bool:
    return _trim_history_file(CHAT_HISTORY_FILE, "legacy astakos_chat_history.json mirror", keep, dry_run, backup)


def trim_telegram_history(keep: int = DEFAULT_CHAT_KEEP, dry_run: bool = False, backup: bool = True) -> bool:
    return _trim_history_file(TELEGRAM_HISTORY_FILE, "legacy astakos_telegram_history.json mirror", keep, dry_run, backup)


def maintain_conversation_db(dry_run: bool = False, backup: bool = True) -> bool:
    header("Shared conversation SQLite maintenance")
    if not os.path.exists(CONVERSATION_DB_FILE):
        log(f"Δεν υπάρχει ακόμα: {os.path.basename(CONVERSATION_DB_FILE)}", "warn")
        return True

    try:
        conn = sqlite3.connect(CONVERSATION_DB_FILE, timeout=30, isolation_level=None)
        conn.row_factory = sqlite3.Row
        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            log(f"SQLite integrity_check: {integrity}", "err")
            conn.close()
            return False

        total_messages = conn.execute("SELECT COUNT(*) FROM conversation_messages").fetchone()[0]
        total_exchanges = conn.execute("SELECT COUNT(*) FROM session_exchanges").fetchone()[0]
        by_channel = conn.execute(
            """
            SELECT channel, COUNT(*) AS count
            FROM conversation_messages
            GROUP BY channel
            ORDER BY channel
            """
        ).fetchall()
        log("SQLite integrity_check: ok", "ok")
        log(f"conversation_messages: {total_messages}", "info")
        for row in by_channel:
            log(f"   - {row['channel']}: {row['count']}", "dim")
        log(f"session_exchanges: {total_exchanges}", "info")

        if dry_run:
            log("DRY-RUN: δεν έγινε checkpoint/optimize/vacuum", "warn")
            conn.close()
            return True

        backup_file(CONVERSATION_DB_FILE, enabled=backup)
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        conn.execute("PRAGMA optimize")
        conn.execute("VACUUM")
        conn.close()
        log("SQLite checkpoint + optimize + vacuum ολοκληρώθηκαν", "ok")
        return True
    except Exception as e:
        log(f"Σφάλμα conversation SQLite maintenance: {e}", "err")
        return False


# ────────────────────────────────────────────────────────────────
# TASK 3: SESSIONS — ROTATION BY DATE
# ────────────────────────────────────────────────────────────────

def trim_sessions(keep: int = DEFAULT_SESSIONS_KEEP, dry_run: bool = False, backup: bool = True) -> bool:
    header(f"Trim astakos_sessions.json (κρατά τις {keep} πιο πρόσφατες)")
    data = safe_load_json(SESSIONS_FILE)
    if data is None:
        return False
    if not isinstance(data, list):
        log("⚠️  Άκυρο schema — περίμενα list", "warn")
        return False

    total = len(data)
    log(f"📊 Πριν: {total} sessions", "info")

    if total <= keep:
        log(f"ℹ️  Δεν χρειάζεται trim (≤ {keep}).", "dim")
        return True

    # Sort by date descending, αν υπάρχει date field
    def _date_key(item):
        try:
            return datetime.strptime(item.get("date", ""), "%Y-%m-%d %H:%M")
        except Exception:
            return datetime.min

    sorted_sessions = sorted(data, key=_date_key, reverse=True)
    trimmed = sorted_sessions[:keep]
    # Επαναφορά σε χρονολογική (αύξουσα) σειρά για το αρχείο
    trimmed.sort(key=_date_key)
    removed = total - keep
    log(f"📊 Μετά: {len(trimmed)} sessions (−{removed})", "ok")

    if dry_run:
        return True

    backup_file(SESSIONS_FILE, enabled=backup)
    return safe_save_json(SESSIONS_FILE, trimmed, dry_run=False)


# ────────────────────────────────────────────────────────────────
# TASK 4: WORKING MEMORY — DEDUP + LLM CONSOLIDATION
# ────────────────────────────────────────────────────────────────

def consolidate_working_memory(dry_run: bool = False, backup: bool = True) -> bool:
    header("Σύμπτυξη astakos_working_memory.json")
    data = safe_load_json(WORKING_MEMORY_FILE)
    if data is None:
        return False
    if not isinstance(data, list):
        log("⚠️  Άκυρο schema — περίμενα list", "warn")
        return False

    total = len(data)
    log(f"📊 Πριν: {total} entries", "info")

    if total == 0:
        log("ℹ️  Κενό αρχείο, παρακάμπτεται.", "dim")
        return True

    # Step 1: Πρώτο πέρασμα — απλό dedup με βάση το tag (case-insensitive trim)
    seen = set()
    deduped = []
    for item in data:
        tag = (item.get("tag", "") if isinstance(item, dict) else str(item)).strip()
        key = tag.lower()
        if key and key not in seen:
            seen.add(key)
            deduped.append(item)

    after_dedup = len(deduped)
    log(f"📊 Μετά από dedup: {after_dedup} entries (−{total - after_dedup})", "info")

    # Step 2: Αν είναι ακόμα πολλά (>10), ζητάμε LLM σύμπτυξη
    final = deduped
    if after_dedup > 10:
        llm = _load_llm()
        if llm is None:
            log("⚠️  Δεν φόρτωσε το LLM — μένω στο απλό dedup.", "warn")
        else:
            tags_only = [item.get("tag", "") if isinstance(item, dict) else str(item) for item in deduped]
            prompt = f"""Έχεις μια λίστα από working memory tags ενός AI agent.
Κάθε tag είναι μια σύντομη σύνοψη από προηγούμενη αλληλεπίδραση.

Δουλειά σου:
  1. Συγχώνευσε διπλότυπα και πολύ παρόμοια tags σε ένα.
  2. Κράτα γενικευμένη, καθαρή διατύπωση.
  3. Διατήρησε τη σειρά (από πιο παλιά σε πιο πρόσφατα).

ΕΠΕΣΤΡΕΨΕ ΑΠΟΚΛΕΙΣΤΙΚΑ valid JSON array από strings, χωρίς markdown:
["tag1", "tag2", ...]

ΛΙΣΤΑ:
{json.dumps(tags_only, ensure_ascii=False, indent=2)}
"""
            try:
                log("🤖 Κλήση LLM για σύμπτυξη tags...", "info")
                response = llm.invoke(prompt)
                from core.utils import clean_message
                raw = clean_message(response.content)
                raw = strip_markdown_json(raw)
                new_tags = json.loads(raw)
                if isinstance(new_tags, list) and all(isinstance(t, str) for t in new_tags):
                    # Επαναδημιουργία items με τρέχουσα ώρα για τα νέα
                    now_str = datetime.now().strftime("%H:%M")
                    final = [{"tag": t, "time": now_str} for t in new_tags]
                else:
                    log("⚠️  LLM γύρισε άκυρο format — μένω στο απλό dedup.", "warn")
            except Exception as e:
                log(f"⚠️  Σφάλμα LLM consolidation: {e} — μένω στο απλό dedup.", "warn")

    log(f"📊 Τελικό: {len(final)} entries", "ok")

    if dry_run:
        log("🧪 DRY-RUN — δες παρακάτω τι θα γραφόταν:", "warn")
        print(json.dumps(final, ensure_ascii=False, indent=2))
        return True

    backup_file(WORKING_MEMORY_FILE, enabled=backup)
    return safe_save_json(WORKING_MEMORY_FILE, final, dry_run=False)


# ────────────────────────────────────────────────────────────────
# TASK 5: PROFILE — LLM CONSOLIDATION ΑΝΑ CATEGORY
# ────────────────────────────────────────────────────────────────

# Κατηγορίες που ΠΟΤΕ δεν τις αγγίζουμε (κρίσιμα δεδομένα)
PROFILE_PROTECTED_CATEGORIES = {"contacts"}

# Ελάχιστος αριθμός entries σε category για να αξίζει LLM σύμπτυξη
PROFILE_MIN_ENTRIES_FOR_LLM = 5


def consolidate_profile(dry_run: bool = False, backup: bool = True) -> bool:
    header("Σύμπτυξη astakos_profile.json (LLM consolidation ανά category)")
    data = safe_load_json(PROFILE_FILE)
    if data is None:
        return False
    if not isinstance(data, dict):
        log("⚠️  Άκυρο schema — περίμενα dict {category: [items]}", "warn")
        return False

    total_before = sum(len(v) if isinstance(v, list) else 1 for v in data.values())
    log(f"📊 Πριν: {total_before} entries σε {len(data)} categories", "info")

    llm = _load_llm()
    if llm is None:
        log("❌ Δεν φόρτωσε το LLM — παρακάμπτεται.", "err")
        return False

    new_data = {}
    any_change = False

    for category, items in data.items():
        # Protected categories — pass-through χωρίς αλλαγή
        if category in PROFILE_PROTECTED_CATEGORIES:
            new_data[category] = items
            log(f"🔒 {category}: protected ({len(items) if isinstance(items, list) else 1} entries) — αμετάβλητο", "dim")
            continue

        # Non-list categories — pass-through
        if not isinstance(items, list):
            new_data[category] = items
            log(f"⏭️  {category}: δεν είναι λίστα — αμετάβλητο", "dim")
            continue

        # Πολύ λίγα entries — δεν αξίζει LLM
        if len(items) < PROFILE_MIN_ENTRIES_FOR_LLM:
            new_data[category] = items
            log(f"⏭️  {category}: {len(items)} entries (< {PROFILE_MIN_ENTRIES_FOR_LLM}) — αμετάβλητο", "dim")
            continue

        log(f"\n🔹 {category}: {len(items)} entries → LLM consolidation...", "info")

        prompt = f"""Έχεις μια λίστα από facts/lessons/capabilities ενός AI agent στην κατηγορία "{category}".

Δουλειά σου:
1. Συγχώνευσε σαφή διπλότυπα και πολύ παρόμοιες διατυπώσεις σε ένα entry.
2. Επίλυσε αντιφάσεις (π.χ. δύο διαφορετικές ηλικίες για το ίδιο πρόσωπο — κράτα την πιο πρόσφατη/σαφέστερη).
3. Διατήρησε ΑΥΣΤΗΡΑ τα prefixes που υπάρχουν στην αρχή κάθε entry (π.χ. [USER_FACT], [CAPABILITY], [LESSON]).
4. Κράτα την αρχική γλώσσα (Ελληνικά).
5. Αν κάτι είναι εντελώς άσχετο/περίεργο, μπορείς να το αφαιρέσεις.

ΕΠΕΣΤΡΕΨΕ ΑΠΟΚΛΕΙΣΤΙΚΑ valid JSON array από strings, χωρίς markdown:
["[USER_FACT]: ...", "[CAPABILITY]: ...", ...]

ΛΙΣΤΑ:
{json.dumps(items, ensure_ascii=False, indent=2)}
"""

        try:
            response = llm.invoke(prompt)
            from core.utils import clean_message
            raw = clean_message(response.content)
            raw = strip_markdown_json(raw)
            new_items = json.loads(raw)
        except Exception as e:
            log(f"   ⚠️  Σφάλμα LLM: {e} — κρατάω τα αρχικά", "warn")
            new_data[category] = items
            continue

        # Validation
        if not isinstance(new_items, list) or not all(isinstance(t, str) for t in new_items):
            log(f"   ⚠️  Άκυρο format από LLM — κρατάω τα αρχικά", "warn")
            new_data[category] = items
            continue

        saved = len(items) - len(new_items)
        if saved > 0:
            any_change = True
            log(f"   📊 {len(items)} → {len(new_items)} (−{saved})", "ok")
        else:
            log(f"   📊 {len(items)} → {len(new_items)} (καμία οικονομία)", "dim")

        new_data[category] = new_items

    total_after = sum(len(v) if isinstance(v, list) else 1 for v in new_data.values())
    log(f"\n📊 Σύνολο: {total_before} → {total_after} (−{total_before - total_after})", "ok")

    if not any_change:
        log("ℹ️  Καμία ουσιαστική αλλαγή — δεν χρειάζεται γράψιμο.", "dim")
        return True

    if dry_run:
        log("🧪 DRY-RUN — δες παρακάτω τι θα γραφόταν (truncated 3000 chars):", "warn")
        preview = json.dumps(new_data, ensure_ascii=False, indent=2)
        if len(preview) > 3000:
            preview = preview[:3000] + "\n... [truncated]"
        print(preview)
        return True

    backup_file(PROFILE_FILE, enabled=backup)
    return safe_save_json(PROFILE_FILE, new_data, dry_run=False)


# ────────────────────────────────────────────────────────────────
# TASK 6: PHOTOS — Σβήσε αναρχειοθέτητες φωτογραφίες
# ────────────────────────────────────────────────────────────────

def clean_photos(dry_run: bool = False) -> bool:
    """
    Διαβάζει το astakos_photos_index.json, βρίσκει ποια .jpg στο telegram_photos/
    δεν είναι αρχειοθετημένη, και τα σβήνει.
    """
    header("Καθαρισμός αναρχειοθέτητων φωτογραφιών (telegram_photos/)")

    if not os.path.isdir(PHOTOS_DIR):
        log(f"⚠️  Ο φάκελος {PHOTOS_DIR} δεν υπάρχει.", "warn")
        return True

    # Φόρτωση index
    index_data = safe_load_json(PHOTOS_INDEX_FILE) or []
    archived_paths = set()
    for entry in index_data:
        fp = entry.get("file_path", "")
        if fp:
            # Κρατάμε μόνο το basename για σύγκριση
            archived_paths.add(os.path.basename(fp).lower())

    log(f"📚 Αρχειοθετημένες φωτό στο index: {len(archived_paths)}", "info")

    # Σάρωση φακέλου
    all_files = [f for f in os.listdir(PHOTOS_DIR) if f.lower().endswith((".jpg", ".jpeg", ".png", ".webp"))]
    log(f"📁 Φωτογραφίες στον φάκελο: {len(all_files)}", "info")

    to_delete = [f for f in all_files if f.lower() not in archived_paths]
    to_keep   = [f for f in all_files if f.lower() in archived_paths]

    log(f"✅ Αρχειοθετημένες (θα κρατηθούν): {len(to_keep)}", "ok")
    log(f"🗑️  Temp / αναρχειοθέτητες (θα σβηστούν): {len(to_delete)}", "warn")

    if not to_delete:
        log("ℹ️  Τίποτα να σβηστεί.", "dim")
        return True

    for fname in to_delete:
        fpath = os.path.join(PHOTOS_DIR, fname)
        if dry_run:
            log(f"   🧪 DRY-RUN: θα σβηνόταν → {fname}", "warn")
        else:
            try:
                os.remove(fpath)
                log(f"   🗑️  Σβήστηκε: {fname}", "ok")
            except Exception as e:
                log(f"   ❌ Σφάλμα διαγραφής {fname}: {e}", "err")

    if not dry_run:
        log(f"\n✅ Καθαρίστηκαν {len(to_delete)} αρχεία.", "ok")

    return True


# ────────────────────────────────────────────────────────────────
# MAIN — CLI
# ────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="🦞 Mastro-Cleaner — Maintenance script for Astakos memory files."
    )
    parser.add_argument("--all", action="store_true",
                        help="Τρέξε όλα τα tasks (default αν δεν δοθεί άλλο)")
    parser.add_argument("--capabilities", action="store_true",
                        help="Σύμπτυξη can_do / cannot_do με LLM")
    parser.add_argument("--chat-history", action="store_true",
                        help="Trim παλιών μηνυμάτων από το legacy web JSON mirror")
    parser.add_argument("--telegram-history", action="store_true",
                        help="Trim παλιών μηνυμάτων από το legacy telegram JSON mirror")
    parser.add_argument("--conversation-db", action="store_true",
                        help="Έλεγχος/maintenance της shared SQLite conversation history")
    parser.add_argument("--sessions", action="store_true",
                        help="Trim παλιών sessions (κρατά τις πιο πρόσφατες)")
    parser.add_argument("--working-memory", action="store_true",
                        help="Σύμπτυξη working memory (dedup + LLM)")
    parser.add_argument("--profile", action="store_true",
                        help="Σύμπτυξη astakos_profile.json (LLM ανά category)")
    parser.add_argument("--photos", action="store_true",
                        help="Σβήσε αναρχειοθέτητες φωτογραφίες από telegram_photos/")
    parser.add_argument("--chat-keep", type=int, default=DEFAULT_CHAT_KEEP,
                        help=f"Πόσα chat messages να κρατήσει (default {DEFAULT_CHAT_KEEP})")
    parser.add_argument("--sessions-keep", type=int, default=DEFAULT_SESSIONS_KEEP,
                        help=f"Πόσες sessions να κρατήσει (default {DEFAULT_SESSIONS_KEEP})")
    parser.add_argument("--dry-run", action="store_true",
                        help="Δείξε τι θα γίνει χωρίς να αλλάξεις αρχεία")
    parser.add_argument("--no-backup", action="store_true",
                        help="Παράκαμψη backup (όχι recommended)")

    args = parser.parse_args()

    # Αν δεν επιλέχθηκε κανένα συγκεκριμένο task, τα τρέχουμε όλα
    no_specific = not any([
        args.capabilities, args.chat_history, args.telegram_history, args.conversation_db,
        args.sessions, args.working_memory, args.profile, args.photos
    ])
    run_all = args.all or no_specific

    backup_enabled = not args.no_backup

    log("\n🦞🦞🦞 MASTRO-CLEANER START 🦞🦞🦞", "header")
    log(f"   Mode: {'DRY-RUN' if args.dry_run else 'APPLY'}", "info")
    log(f"   Backup: {'ON' if backup_enabled else 'OFF'}", "info")
    log(f"   Project: {PROJECT_ROOT}", "dim")

    results = {}

    if run_all or args.capabilities:
        results["capabilities"] = consolidate_capabilities(
            dry_run=args.dry_run, backup=backup_enabled
        )

    if run_all or args.conversation_db:
        results["conversation_db"] = maintain_conversation_db(
            dry_run=args.dry_run, backup=backup_enabled
        )

    if run_all or args.chat_history:
        results["chat_history"] = trim_chat_history(
            keep=args.chat_keep, dry_run=args.dry_run, backup=backup_enabled
        )

    if run_all or args.telegram_history:
        results["telegram_history"] = trim_telegram_history(
            keep=args.chat_keep, dry_run=args.dry_run, backup=backup_enabled
        )

    if run_all or args.sessions:
        results["sessions"] = trim_sessions(
            keep=args.sessions_keep, dry_run=args.dry_run, backup=backup_enabled
        )

    if run_all or args.working_memory:
        results["working_memory"] = consolidate_working_memory(
            dry_run=args.dry_run, backup=backup_enabled
        )

    if run_all or args.profile:
        results["profile"] = consolidate_profile(
            dry_run=args.dry_run, backup=backup_enabled
        )

    if run_all or args.photos:
        results["photos"] = clean_photos(dry_run=args.dry_run)

    # Summary
    log("\n" + "─" * 60, "dim")
    log("📋 ΣΥΝΟΨΗ", "header")
    log("─" * 60, "dim")
    for task, ok in results.items():
        status = "✅ OK" if ok else "❌ ΑΠΟΤΥΧΙΑ"
        color = "ok" if ok else "err"
        log(f"   {task}: {status}", color)

    log("\n🦞 MASTRO-CLEANER DONE\n", "header")


if __name__ == "__main__":
    main()
