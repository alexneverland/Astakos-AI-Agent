# ================================================================
# Project: Astakos AI Agent 🦞
# Module:  Analytics Engine — Passive Routine Detection
# Τρέχει κάθε βράδυ 03:00. Αναλύει το chat history, βρίσκει
# recurring patterns και καλεί upsert_routine αυτόματα.
# ================================================================

import json
import os
import re
from collections import defaultdict
from datetime import datetime, timedelta
from difflib import SequenceMatcher

# ── Config ───────────────────────────────────────────────────────
LOOKBACK_DAYS     = 30    # Μέρες ιστορικού
MIN_OCCURRENCES   = 3     # Ελάχιστες εμφανίσεις συνολικά
MIN_WEEKS         = 2     # Σε πόσες διαφορετικές εβδομάδες
TIME_BUCKET_MIN   = 30    # Παράθυρο ώρας (±15 λεπτά)
SIMILARITY_THRESH = 0.60  # Difflib threshold για grouping
EVERYDAY_DAYS     = 5     # Αν εμφανίζεται σε 5+ ημέρες → Everyday

_BASE             = os.path.dirname(os.path.abspath(__file__))
CHAT_HISTORY_FILE = os.path.join(_BASE, "..", "astakos_chat_history.json")
LOG_FILE          = os.path.join(_BASE, "..", "analytics_engine_log.json")

# ── Stop words ───────────────────────────────────────────────────
STOP_WORDS = {
    "και", "να", "στο", "στη", "στον", "στα", "το", "τα", "τη", "τον",
    "μου", "σου", "του", "της", "μας", "σας", "τους", "τις", "αυτό",
    "αυτή", "αυτός", "εδώ", "εκεί", "πώς", "τι", "που", "γιατί",
    "αλλά", "όμως", "ή", "με", "για", "από", "σε", "ότι", "είναι",
    "ήταν", "έχει", "έχω", "θα", "δεν", "μην", "ναι", "όχι",
    "ok", "οκ", "εντάξει", "γεια", "χαρά", "κάνε", "κάνω", "έκανα",
}

# ── Activity keyword map ─────────────────────────────────────────
# keyword (lowercase) → (canonical_name, event_type)
ACTIVITY_HINTS = {
    "καλημέρα":     ("καλημέρα",           "general"),
    "καλημερα":     ("καλημέρα",           "general"),
    "καφέ":         ("καφές",              "general"),
    "καφε":         ("καφές",              "general"),
    "γυμναστήριο":  ("γυμναστήριο",        "hobby"),
    "γυμναστηριο":  ("γυμναστήριο",        "hobby"),
    "λαϊκή":        ("λαϊκή αγορά",        "general"),
    "λαικη":        ("λαϊκή αγορά",        "general"),
    "λαϊκη":        ("λαϊκή αγορά",        "general"),
    "δουλειά":      ("δουλειά",            "work"),
    "δουλεια":      ("δουλειά",            "work"),
    "γραφείο":      ("γραφείο",            "work"),
    "γραφειο":      ("γραφείο",            "work"),
    "αλέξανδρος":   ("Αλέξανδρος",         "family"),
    "αλεξανδρος":   ("Αλέξανδρος",         "family"),
    "σχολείο":      ("σχολείο",            "family"),
    "σχολειο":      ("σχολείο",            "family"),
    "βόλτα":        ("βόλτα",              "general"),
    "βολτα":        ("βόλτα",              "general"),
    "πάρκο":        ("πάρκο",              "general"),
    "παρκο":        ("πάρκο",              "general"),
    "ύπνος":        ("ύπνος",              "general"),
    "υπνος":        ("ύπνος",              "general"),
    "κοιμάται":     ("ύπνος Αλέξανδρου",   "family"),
    "κοιμαται":     ("ύπνος Αλέξανδρου",   "family"),
    "κοιμήθηκε":    ("ύπνος Αλέξανδρου",   "family"),
    "κοιμηθηκε":    ("ύπνος Αλέξανδρου",   "family"),
    "καληνύχτα":    ("καληνύχτα",          "general"),
    "καληνυχτα":    ("καληνύχτα",          "general"),
    "καλησπέρα":    ("καλησπέρα",          "general"),
    "καλησπερα":    ("καλησπέρα",          "general"),
    "φαγητό":       ("φαγητό",             "general"),
    "φαγητο":       ("φαγητό",             "general"),
    "μεσημέρι":     ("μεσημεριανό",        "general"),
    "μεσημερι":     ("μεσημεριανό",        "general"),
    "ψώνια":        ("ψώνια",              "general"),
    "ψωνια":        ("ψώνια",              "general"),
    "σούπερ μάρκετ":("σούπερ μάρκετ",      "general"),
    "σκούπα":       ("σκούπα",             "home"),
    "σκουπα":       ("σκούπα",             "home"),
}


# ────────────────────────────────────────────────────────────────
# HELPERS
# ────────────────────────────────────────────────────────────────

def _round_to_bucket(time_str: str, bucket_min: int = TIME_BUCKET_MIN) -> str:
    """07:22 → 07:00 | 07:47 → 08:00 (nearest 30-min bucket)"""
    try:
        h, m = map(int, time_str.split(":"))
        total = h * 60 + m
        rounded = round(total / bucket_min) * bucket_min
        rh, rm = divmod(rounded % (24 * 60), 60)
        return f"{rh:02d}:{rm:02d}"
    except Exception:
        return time_str


def _extract_activity(content: str):
    """Επιστρέφει (event_name, event_type) ή None αν δεν βρεθεί δραστηριότητα."""
    # Αφαίρεσε timestamps [HH:MM] και URLs
    text = re.sub(r'\[\d{2}:\d{2}\]', '', content)
    text = re.sub(r'https?://\S+', '', text)
    text = text.strip().lower()

    # Έλεγξε hints
    for keyword, result in ACTIVITY_HINTS.items():
        if keyword in text:
            return result

    # Fallback: πρώτες 3 σημαντικές λέξεις
    words = re.findall(r'[α-ωάέήίόύώΑ-ΩΆΈΉΊΌΎΏa-zA-Z]+', text)
    meaningful = [w for w in words if w not in STOP_WORDS and len(w) > 3]
    if len(meaningful) >= 2:
        return (" ".join(meaningful[:3]), "general")

    return None


def _get_week_id(date_str: str) -> str:
    """Επιστρέφει "2026-W21" για dedup ανά εβδομάδα."""
    try:
        d = datetime.strptime(date_str, "%Y-%m-%d")
        return f"{d.year}-W{d.isocalendar()[1]:02d}"
    except Exception:
        return date_str


def _similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()


# ────────────────────────────────────────────────────────────────
# CORE
# ────────────────────────────────────────────────────────────────

def run_analytics() -> dict:
    """
    Κύρια συνάρτηση του Analytics Engine.
    Επιστρέφει stats dict: {detected, created, merged, updated, skipped, errors}
    """
    from memory.routine_db import upsert_routine

    stats = {"detected": 0, "created": 0, "merged": 0,
             "updated": 0, "skipped": 0, "errors": 0}
    found_routines = []

    # ── 1. Φόρτωση history ───────────────────────────────────────
    if not os.path.exists(CHAT_HISTORY_FILE):
        print("[Analytics]: Δεν βρέθηκε chat history.")
        return stats

    with open(CHAT_HISTORY_FILE, "r", encoding="utf-8") as f:
        history = json.load(f)

    cutoff = (datetime.now() - timedelta(days=LOOKBACK_DAYS)).strftime("%Y-%m-%d")

    user_msgs = [
        m for m in history
        if m.get("role") in ("user", "human")
        and m.get("date", "") >= cutoff
        and m.get("time")
        and m.get("date")
    ]

    if not user_msgs:
        print("[Analytics]: Δεν υπάρχουν μηνύματα με date field (πρόσφατα).")
        _write_log(stats, found_routines)
        return stats

    print(f"[Analytics]: Ανάλυση {len(user_msgs)} μηνυμάτων ({LOOKBACK_DAYS} ημερών)...")

    # ── 2. Εξαγωγή & grouping ────────────────────────────────────
    # Key: (day_of_week, time_bucket, event_name, event_type)
    # Value: list of {date, week_id}
    groups = defaultdict(list)

    for msg in user_msgs:
        activity = _extract_activity(msg.get("content", ""))
        if not activity:
            continue

        event_name, event_type = activity

        try:
            d = datetime.strptime(msg["date"], "%Y-%m-%d")
            day_of_week = d.strftime("%A")
        except Exception:
            continue

        time_bucket = _round_to_bucket(msg["time"])
        week_id = _get_week_id(msg["date"])

        groups[(day_of_week, time_bucket, event_name, event_type)].append({
            "date": msg["date"],
            "week": week_id
        })

    # ── 3. Merge παρόμοια groups (same day/time, similar event) ──
    merged = {}
    used = set()
    group_list = list(groups.items())

    for i, (k1, v1) in enumerate(group_list):
        if k1 in used:
            continue
        day1, time1, ev1, type1 = k1
        combined = list(v1)

        for j, (k2, v2) in enumerate(group_list):
            if j == i or k2 in used:
                continue
            day2, time2, ev2, type2 = k2
            if day1 == day2 and time1 == time2 and _similarity(ev1, ev2) >= SIMILARITY_THRESH:
                combined.extend(v2)
                used.add(k2)

        merged[k1] = combined
        used.add(k1)

    # ── 4. Everyday detection ────────────────────────────────────
    # Αν ίδιο event/time εμφανίζεται σε 5+ διαφορετικές ημέρες → Everyday
    # Ομαδοποίηση ανά (time_bucket, event_name) αγνοώντας day
    by_time_event = defaultdict(lambda: {"entries": [], "days": set()})
    for (day, time, event, evtype), entries in merged.items():
        key = (time, event, evtype)
        by_time_event[key]["entries"].extend(entries)
        by_time_event[key]["days"].add(day)

    # Αν εμφανίζεται σε 5+ διαφορετικές μέρες, αντικατέστησε με Everyday
    final_groups = {}
    promoted_to_everyday = set()

    for (time, event, evtype), data in by_time_event.items():
        if len(data["days"]) >= EVERYDAY_DAYS:
            # Promote σε Everyday
            final_groups[("Everyday", time, event, evtype)] = data["entries"]
            promoted_to_everyday.update(
                (day, time, event, evtype) for day in data["days"]
            )

    # Πρόσθεσε τα μη-promoted
    for key, entries in merged.items():
        if key not in promoted_to_everyday:
            final_groups[key] = entries

    # ── 5. Threshold check & upsert ──────────────────────────────
    for (day_of_week, time_bucket, event_name, event_type), entries in final_groups.items():
        total   = len(entries)
        weeks   = len(set(e["week"] for e in entries))
        stats["detected"] += 1

        required_weeks = 1 if day_of_week == "Everyday" else MIN_WEEKS

        if total >= MIN_OCCURRENCES and weeks >= required_weeks:
            try:
                result = upsert_routine(
                    day=day_of_week,
                    time=time_bucket,
                    event=event_name,
                    ev_type=event_type,
                    confidence_boost=0.2
                )
                if result in stats:
                    stats[result] += 1

                found_routines.append({
                    "day": day_of_week, "time": time_bucket,
                    "event": event_name, "count": total,
                    "weeks": weeks, "result": result
                })
                print(f"[Analytics]: ✅ '{event_name}' {day_of_week} {time_bucket} → {result} ({total}x / {weeks}w)")
            except Exception as e:
                stats["errors"] += 1
                print(f"[Analytics ERROR]: {e}")
        else:
            stats["skipped"] += 1

    print(f"[Analytics]: Ολοκληρώθηκε → {stats}")
    _write_log(stats, found_routines)
    return stats


def get_candidates() -> list:
    """
    Επιστρέφει τα patterns που δεν πέρασαν threshold ακόμα.
    Χρήση: ο Αστακός μπορεί να απαντήσει 'τι ρουτίνες έχεις εντοπίσει;'
    """
    if not os.path.exists(LOG_FILE):
        return []
    with open(LOG_FILE, "r", encoding="utf-8") as f:
        log = json.load(f)
    if not log:
        return []
    # Τελευταίο run
    last = log[-1]
    return last.get("detected_routines", [])


# ────────────────────────────────────────────────────────────────
# LOG
# ────────────────────────────────────────────────────────────────

def _write_log(stats: dict, routines: list):
    try:
        log = []
        if os.path.exists(LOG_FILE):
            with open(LOG_FILE, "r", encoding="utf-8") as f:
                log = json.load(f)
        log.append({
            "run_at":            datetime.now().isoformat(timespec="seconds"),
            "stats":             stats,
            "detected_routines": routines
        })
        log = log[-30:]  # Κράτα τελευταία 30 runs
        with open(LOG_FILE, "w", encoding="utf-8") as f:
            json.dump(log, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[Analytics Log Error]: {e}")


# ────────────────────────────────────────────────────────────────
# STANDALONE EXECUTION
# ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    results = run_analytics()
    print(f"\n📊 Analytics Results: {results}")
