# ================================================================
# Project: Astakos AI Agent 🦞
# Developer: Lazaros (Piston-7)
# Description: Modular LLM-agnostic multi-agent framework
# Copyright (c) 2026 - All Rights Reserved
# ================================================================

import os
import json
import threading
from datetime import datetime
import unicodedata
from memory.vector_store import memory
from services.gemini import safe_gemini_call
import re
from core.utils import clean_message
from core.event_bus import bus
import sqlite3
from config import PHOTOS_INDEX_FILE, PHOTOS_DIR, STATE_DB
from memory.conversation_history import (
    append_exchange,
    load_unsummarized_exchanges,
    mark_exchanges_summarized,
)
# ════════════════════════════════════════════════════════════════
# SESSION SUMMARY — "Ημερολόγιο Συνεργάτη"
# ════════════════════════════════════════════════════════════════

SESSION_LOGS: list = []  # Ενιαίο log — όλα τα channels μαζί
AUTO_SESSION_SUMMARY_EXCHANGE_THRESHOLD = 40
_auto_summary_lock = threading.Lock()


def log_exchange(user_text, ai_text, agent: str, channel: str = "web"):
    """Προσθέτει ένα ζεύγος ερώτησης-απάντησης στο session log (per channel)."""
    now = datetime.now()
    safe_user = clean_message(user_text)
    safe_ai = clean_message(ai_text)
    entry = {
        "time": now.strftime("%H:%M"),
        "agent": agent,
        "channel": channel,
        "user": safe_user[:300],
        "ai": safe_ai[:300],
    }
    SESSION_LOGS.append(entry)
    saved_exchange = None
    try:
        saved_exchange = append_exchange(
            user_text=entry["user"],
            ai_text=entry["ai"],
            agent=agent,
            channel=channel,
            timestamp=now,
        )
    except Exception as e:
        print(f"\033[93m[SessionLog]: Shared exchange write failed: {e}\033[0m")
    if saved_exchange:
        _maybe_trigger_auto_session_summary(channel)


def _maybe_trigger_auto_session_summary(channel: str) -> None:
    if is_summarizing:
        return
    try:
        pending = load_unsummarized_exchanges(limit=AUTO_SESSION_SUMMARY_EXCHANGE_THRESHOLD)
    except Exception as e:
        print(f"\033[93m[SessionLog]: Auto-summary check failed: {e}\033[0m")
        return
    if len(pending) < AUTO_SESSION_SUMMARY_EXCHANGE_THRESHOLD:
        return
    if not _auto_summary_lock.acquire(blocking=False):
        return

    def _worker():
        try:
            _run_session_summary(channel=channel)
        finally:
            _auto_summary_lock.release()

    threading.Thread(target=_worker, daemon=True).start()


def load_last_session_hint(channel: str = "web") -> str:
    """Φορτώνει το hint της τελευταίας session."""
    conn = None
    try:
        conn = sqlite3.connect(STATE_DB)
        cursor = conn.cursor()
        cursor.execute('''
            SELECT session_date, pending, next_session_hint 
            FROM sessions 
            ORDER BY id DESC LIMIT 1
        ''')
        row = cursor.fetchone()
        
        if not row:
            return ""
            
        date_str, pending_json, hint = row
        pending = []
        try:
            if pending_json:
                pending = json.loads(pending_json)
        except:
            pass
            
        if not hint and not pending:
            return ""
            
        out = ""
        if hint:
            out += f"Hint από προηγούμενη session ({date_str}): {hint}\n"
        if pending:
            out += f"Εκκρεμότητες/Σκέψεις:\n" + "\n".join(f"- {p}" for p in pending)
        return out.strip()
    except Exception as e:
        print(f"Error loading last session hint: {e}")
        return ""
    finally:
        if conn:
            conn.close()


is_summarizing = False  # Πρέπει να οριστεί έξω από τη συνάρτηση


def _normalize_text(value: str) -> str:
    text = unicodedata.normalize("NFD", str(value or "").lower())
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    return " ".join(text.split())


_TOPIC_CHOICES = {
    "family", "activity", "school", "health", "emotion", "pet",
    "home", "work", "gift", "food", "trip", "project", "routine", "other",
}
_RELATION_TYPE_CHOICES = {
    "new_fact", "follow_up", "state_update", "correction",
    "temporary_state", "preference", "routine_hint", "confirmed",
}
_STATE_MARKER_CHOICES = {
    "started", "stopped", "paused", "resumed", "away", "returned",
    "scheduled", "cancelled", "confirmed", "tired", "better", "sick",
    "emotional", "completed", "ongoing", "seasonal_break",
}


def _empty_memory_candidate() -> dict:
    return {
        "memory_type": "fact",
        "fact": "",
        "category": "other",
        "tags": [],
        "entities": [],
        "topic": "other",
        "topic_detail": "",
        "state_markers": [],
        "time_scope": "",
        "relation_type": "new_fact",
        "confidence": 0.7,
        "source": "unknown",
        "agent_name": "Unknown",
        "reason": "agent_inferred",
    }


def _dedupe_preserve_order(values: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for item in values:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out


def _extract_entities_from_text(text: str) -> list[str]:
    compact = " ".join(clean_message(text).split())
    if not compact:
        return []

    found = []
    for match in re.finditer(r"\b[Α-ΩA-Z][Α-ΩA-Za-zΆ-Ώά-ώϊϋΐΰ]+(?:\s+[Α-ΩA-Z][Α-ΩA-Za-zΆ-Ώά-ώϊϋΐΰ]+)?", compact):
        entity = match.group(0).strip(" .,;:!?")
        if len(entity) >= 3:
            found.append(entity)
    return _dedupe_preserve_order(found)


def _infer_topic_from_text(text: str, category: str) -> str:
    normalized = _normalize_text(text)
    if any(marker in normalized for marker in ("ποδοσφ", "μπασκετ", "κολυμβ", "σκακι", "χορο", "δραστηριοτ", "προπονησ")):
        return "activity"
    if any(marker in normalized for marker in ("σχολει", "δημοτικ", "φροντιστ", "κατασκην")):
        return "school" if "σχολει" in normalized or "δημοτικ" in normalized or "φροντιστ" in normalized else "trip"
    if any(marker in normalized for marker in ("υπν", "πυρετ", "γιατρ", "αρρωστ", "πονα", "κουρασ", "ηρεμησ", "τσιμπουρ")):
        return "health"
    if any(marker in normalized for marker in ("στεναχωρ", "χαρ", "αγχω", "φοβ", "ηρεμησ", "πιεστηκ")):
        return "emotion"
    if any(marker in normalized for marker in ("κουνελ", "σκυλ", "γατ", "ζωακ", "κατοικιδ")):
        return "pet"
    if any(marker in normalized for marker in ("σπιτι", "κουζιν", "καθαρισ", "αφυγραντηρ", "σκουπ", "λαικ", "ψων")):
        return "home"
    if any(marker in normalized for marker in ("δουλει", "βαρδια", "εργοστασ", "πασσια", "συναδελφ")):
        return "work"
    if any(marker in normalized for marker in ("δωρο", "γενεθλ", "ρολοι", "γλαστρ")):
        return "gift"
    if any(marker in normalized for marker in ("φαγητ", "φακες", "ψαρ", "μπριζολ", "φαγα", "εφαγε")):
        return "food"
    if any(marker in normalized for marker in ("ταξιδ", "εκδρομ", "διακοπ", "πηγαμε", "γυρισ", "επιστρ")):
        return "trip"
    if category == "projects":
        return "project"
    if category == "home":
        return "home"
    if category == "family":
        return "family"
    return "other"


def _infer_topic_detail_from_text(text: str) -> str:
    normalized = _normalize_text(text)
    detail_markers = {
        "football": ("ποδοσφ",),
        "camp": ("κατασκην",),
        "park": ("παρκο", "βολτ"),
        "school": ("σχολει", "δημοτικ"),
        "tutoring": ("φροντιστ",),
        "sleep": ("υπν",),
        "gift_watch": ("ρολοι",),
        "gift_plant": ("γλαστρ", "φυτο"),
        "fish_market": ("λαϊκ", "λαικ", "ψαρ"),
        "rabbit": ("κουνελ",),
        "dog": ("σκυλ",),
    }
    for detail, markers in detail_markers.items():
        if any(marker in normalized for marker in markers):
            return detail
    return ""


def _infer_state_markers_from_text(text: str) -> list[str]:
    normalized = _normalize_text(text)
    states: list[str] = []
    rules = {
        "started": ("ξεκινα", "ξεκινησ", "αρχισ"),
        "stopped": ("σταματ", "τελος", "δεν εχει πια"),
        "paused": ("παγωσ", "παυση", "σταματαει για"),
        "resumed": ("ξαναρχ", "συνεχιζ", "επανηλθ"),
        "away": ("λειπ", "εκτος σπιτιου", "δεν ειναι σπιτι", "κατασκην", "ταξιδ", "διακοπ"),
        "returned": ("γυρισ", "επιστρ", "ηρθε σπιτι", "γυρναει σπιτι"),
        "scheduled": ("θα παει", "θα παμε", "ειναι για", "προγραμματισ"),
        "cancelled": ("ακυρω", "δεν θα γινει"),
        "confirmed": ("επιβεβαι", "οκ", "κλειστ"),
        "tired": ("κουρασ",),
        "better": ("καλυτερ", "συνηλθ", "ηρεμησ"),
        "sick": ("αρρωστ", "πυρετ", "πονα"),
        "emotional": ("στεναχωρ", "αγχω", "φοβ", "πιεστηκ"),
        "completed": ("ολοκληρ", "τελειωσ", "εγινε"),
        "ongoing": ("συνεχιζ", "ακομα", "παραμεν"),
        "seasonal_break": ("καλοκαιρ", "σεπτεμβρ", "το χειμωνα", "για το καλοκαιρι"),
    }
    for state, markers in rules.items():
        if any(marker in normalized for marker in markers):
            states.append(state)
    return _dedupe_preserve_order([state for state in states if state in _STATE_MARKER_CHOICES])


def _infer_time_scope_from_text(text: str, *, now: datetime | None = None) -> str:
    normalized = _normalize_text(text)
    ts = now or datetime.now()

    range_match = re.search(r"\b(20\d{2}-\d{2}-\d{2})\s*(?:to|-|εως|έως|μεχρι|μέχρι)\s*(20\d{2}-\d{2}-\d{2})\b", text)
    if range_match:
        return f"{range_match.group(1)}_to_{range_match.group(2)}"

    exact_match = re.search(r"\b20\d{2}-\d{2}-\d{2}\b", text)
    if exact_match:
        return exact_match.group(0)

    if "σεπτεμβρ" in normalized and ("καλοκαιρ" in normalized or "μεχρι" in normalized or "μέχρι" in normalized):
        return f"{ts.strftime('%Y-%m-%d')}_to_{ts.year}-09-01"

    if any(marker in normalized for marker in ("μεχρι", "μέχρι", "εως", "έως", "αυριο", "αύριο", "μεθαυριο", "μεθαύριο")):
        return "ongoing"

    return ts.strftime('%Y-%m-%d')


def _infer_relation_type_from_text(text: str, state_markers: list[str]) -> str:
    normalized = _normalize_text(text)
    if any(marker in normalized for marker in ("διορθ", "οχι αυτο", "τελικα", "update", "correction")):
        return "correction"
    if any(state in state_markers for state in ("away", "returned", "tired", "better", "sick", "seasonal_break")):
        return "state_update"
    if any(state in state_markers for state in ("started", "stopped", "paused", "resumed", "completed")):
        return "follow_up"
    if any(marker in normalized for marker in ("ρουτιν", "καθε", "κάθε", "θυμιζ", "υπενθυμ")):
        return "routine_hint"
    return "new_fact"


def _build_tags(candidate: dict) -> list[str]:
    tags = [str(x).strip().lower() for x in candidate.get("tags", []) if str(x).strip()]
    tags.extend(str(x).strip().lower() for x in candidate.get("entities", []) if str(x).strip())
    if candidate.get("topic"):
        tags.append(candidate["topic"])
    if candidate.get("topic_detail"):
        tags.append(candidate["topic_detail"])
    tags.extend(candidate.get("state_markers", []))
    return _dedupe_preserve_order(tags)


def _normalize_memory_candidate(raw: dict | None, *, now: datetime | None = None) -> dict:
    base = _empty_memory_candidate()
    if not isinstance(raw, dict):
        return base

    base["memory_type"] = str(raw.get("memory_type", base["memory_type"])).strip() or base["memory_type"]
    base["fact"] = str(raw.get("fact", base["fact"])).strip()
    base["category"] = str(raw.get("category", base["category"])).strip().lower() or base["category"]
    if not base["fact"]:
        return base

    try:
        base["confidence"] = float(raw.get("confidence", base["confidence"]) or base["confidence"])
    except Exception:
        pass

    base["source"] = str(raw.get("source", base["source"])).strip() or base["source"]
    base["agent_name"] = str(raw.get("agent_name", base["agent_name"])).strip() or base["agent_name"]
    base["reason"] = str(raw.get("reason", base["reason"])).strip() or base["reason"]

    raw_tags = [str(x).strip().lower() for x in raw.get("tags", []) if str(x).strip()]
    raw_entities = [str(x).strip() for x in raw.get("entities", []) if str(x).strip()]
    raw_topic = str(raw.get("topic", "")).strip().lower()
    raw_topic_detail = str(raw.get("topic_detail", "")).strip().lower()
    raw_states = [str(x).strip().lower() for x in raw.get("state_markers", []) if str(x).strip()]
    raw_time_scope = str(raw.get("time_scope", "")).strip()
    raw_relation_type = str(raw.get("relation_type", "")).strip().lower()

    base["entities"] = _dedupe_preserve_order(raw_entities or _extract_entities_from_text(base["fact"]))
    base["topic"] = raw_topic if raw_topic in _TOPIC_CHOICES else _infer_topic_from_text(base["fact"], base["category"])
    base["topic_detail"] = raw_topic_detail or _infer_topic_detail_from_text(base["fact"])
    base["state_markers"] = _dedupe_preserve_order(
        [state for state in raw_states if state in _STATE_MARKER_CHOICES] or _infer_state_markers_from_text(base["fact"])
    )
    base["time_scope"] = raw_time_scope or _infer_time_scope_from_text(base["fact"], now=now)
    base["relation_type"] = (
        raw_relation_type
        if raw_relation_type in _RELATION_TYPE_CHOICES
        else _infer_relation_type_from_text(base["fact"], base["state_markers"])
    )
    base["tags"] = _build_tags({**base, "tags": raw_tags})
    return base


def _extract_event_memory_candidate(
    user_text: str,
    ai_text: str,
    *,
    agent_name: str = "Unknown",
    channel: str = "web",
    now: datetime | None = None,
) -> dict | None:
    """Deterministic safety net for day-specific events the LLM sifter may skip."""
    safe_user = clean_message(user_text)
    safe_ai = clean_message(ai_text)
    combined = f"{safe_user} {safe_ai}".lower()

    family_markers = ("αλέξανδρ", "αλεξανδρ", "σοφία", "σοφια", "μικρό", "μικρο", "μικρός", "μικρος")
    personal_markers = (
        "εγώ",
        "εγω",
        "εμένα",
        "εμενα",
        "μου",
        "δουλειά",
        "δουλεια",
        "συνέντευξη",
        "συνεντευξη",
        "υγεία",
        "υγεια",
        "ύπνο",
        "υπνο",
    )
    event_markers = (
        "ποδόσφ",
        "ποδοσφ",
        "αγών",
        "αγων",
        "τελικό",
        "τελικο",
        "μετάλλ",
        "μεταλλ",
        "πάρκο",
        "παρκο",
        "βόλτα",
        "βολτα",
        "σχολείο",
        "σχολειο",
        "δουλειά",
        "δουλεια",
        "συνέντευξη",
        "συνεντευξη",
        "γιατρό",
        "γιατρο",
        "υγεία",
        "υγεια",
        "ύπνο",
        "υπνο",
        "γυμναστήριο",
        "γυμναστηριο",
        "δουλεύω",
        "δουλευω",
    )
    statement_markers = (
        "είμαστε",
        "ειμαστε",
        "πήγαμε",
        "πηγαμε",
        "πήγε",
        "πηγε",
        "είχα",
        "ειχα",
        "πήρε",
        "πηρε",
        "τέλος",
        "τελος",
        "γυρνάμε",
        "γυρναμε",
        "φεύγουμε",
        "φευγουμε",
        "πάμε",
        "παμε",
        "είναι στη",
        "ειναι στη",
    )

    has_family_marker = any(marker in combined for marker in family_markers)
    has_personal_marker = any(marker in combined for marker in personal_markers)
    if not (has_family_marker or has_personal_marker):
        return None
    if not any(marker in combined for marker in event_markers):
        return None
    if not any(marker in combined for marker in statement_markers):
        return None

    source_text = " ".join(safe_user.split())
    if not source_text:
        return None
    if len(source_text) > 280:
        source_text = source_text[:277].rstrip() + "..."

    ts = now or datetime.now()
    fact = f"[USER_FACT]: Στις {ts.strftime('%Y-%m-%d')}, {source_text}"
    return _normalize_memory_candidate({
        "memory_type": "fact",
        "fact": fact,
        "category": "family" if has_family_marker else "lazaros",
        "agent_name": agent_name,
        "source": channel,
        "reason": "user_stated",
        "confidence": 0.85,
    }, now=ts)


def _extract_temporary_family_memory_candidate(
    user_text: str,
    ai_text: str,
    *,
    agent_name: str = "Unknown",
    channel: str = "web",
    now: datetime | None = None,
) -> dict | None:
    """Capture temporary family states with time windows (camp, away, return dates)."""
    safe_user = clean_message(user_text)
    safe_ai = clean_message(ai_text)
    source_text = " ".join(safe_user.split())
    if not source_text:
        return None

    normalized = _normalize_text(f"{safe_user} {safe_ai}")
    lowered_source = _normalize_text(source_text)

    if source_text.rstrip().endswith((";", "?")):
        return None

    question_starters = (
        "τι ",
        "πως ",
        "πώς ",
        "γιατι ",
        "γιατί ",
        "που ",
        "πού ",
        "ποιος ",
        "ποια ",
        "ποιο ",
        "ποσο ",
        "πόσο ",
        "ποτε ",
        "πότε ",
    )
    if lowered_source.startswith(question_starters):
        return None

    family_markers = (
        "αλεξανδρ",
        "σοφια",
        "μικρο",
        "μικρος",
        "μικρη",
        "γιος",
        "κορη",
        "παιδι",
        "μαμα",
        "μπαμπας",
    )
    absence_markers = (
        "κατασκην",
        "λειπ",
        "δεν ειναι σπιτι",
        "δεν ειναι μαζι",
        "ταξιδ",
        "εκδρομ",
        "διακοπ",
        "φιλοξεν",
        "μενει στη",
        "μενει στον",
        "μενει στην",
        "κοιμαται στη",
        "κοιμαται στον",
        "κοιμαται στην",
    )
    window_markers = (
        "μεχρι",
        "μέχρι",
        "επιστρ",
        "γυρν",
        "γυρνα",
        "επιστρο",
        "αυριο",
        "μεθαυριο",
        "σε 2 μερες",
        "σε 3 μερες",
        "σε 4 μερες",
        "σε 5 μερες",
        "σε 6 μερες",
        "σε 7 μερες",
        "την αλλη εβδομαδα",
        "την άλλη εβδομάδα",
        "το σαββατο",
        "το σάββατο",
        "την κυριακη",
        "την κυριακή",
        "δευτερα",
        "τριτη",
        "τεταρτη",
        "πεμπτη",
        "παρασκευη",
        "σαββατο",
        "κυριακη",
    )

    if not any(marker in normalized for marker in family_markers):
        return None
    if not any(marker in normalized for marker in absence_markers):
        return None
    if not any(marker in normalized for marker in window_markers):
        return None

    if len(source_text) > 320:
        source_text = source_text[:317].rstrip() + "..."

    ts = now or datetime.now()
    fact = f"[USER_FACT]: Στις {ts.strftime('%Y-%m-%d')}, {source_text}"
    return _normalize_memory_candidate({
        "memory_type": "fact",
        "fact": fact,
        "category": "family",
        "agent_name": agent_name,
        "source": channel,
        "reason": "user_stated",
        "confidence": 0.9,
        "relation_type": "temporary_state",
    }, now=ts)


def _infer_memory_category(text: str) -> str:
    clean = _normalize_text(text)
    if any(marker in clean for marker in ("σοφια", "αλεξανδρ", "μαρια", "μικρο", "παιδι", "γενεθλια", "δωρο")):
        return "family"
    if any(marker in clean for marker in ("mastroapp", "praxis", "astakos", "αστακο", "github", "project", "repo")):
        return "projects"
    if any(marker in clean for marker in ("σπιτι", "κουζινα", "ψυγειο", "αφυγραντηρ", "σκουπα", "ρολοι", "συσκευ")):
        return "home"
    if any(marker in clean for marker in ("κανόνας", "κανονας", "bug", "tool", "prompt", "lesson", "μαθημα")):
        return "lesson"
    return "lazaros"


def _extract_explicit_memory_payload(text: str) -> str | None:
    """Extract the actual payload from explicit commands like 'Κράτα στη μνήμη ότι ...'."""
    compact = " ".join(clean_message(text).split())
    if not compact:
        return None

    patterns = (
        r"(?:κράτα|κρατα|αποθήκευσε|αποθηκευσε|σημείωσε|σημειωσε)\s+(?:στη\s+)?(?:μνήμη|μνημη)\s+(?:ότι|οτι)\s+(.+)",
        r"(?:κράτα|κρατα|αποθήκευσε|αποθηκευσε|σημείωσε|σημειωσε)\s+(?:ότι|οτι)\s+(.+)",
    )
    for pattern in patterns:
        match = re.search(pattern, compact, flags=re.IGNORECASE)
        if match:
            payload = match.group(1).strip(" .")
            return payload or None
    return None


def _looks_like_generic_memory_confirmation(text: str) -> bool:
    clean = _normalize_text(text)
    generic_markers = (
        "το αποθηκευσα στη μνημη",
        "αποθηκευσα στη μνημη",
        "το αποθηκευσα",
        "αποθηκευσα",
        "το σημειωσα",
        "σημειωσα",
        "το σημείωσα",
        "κρατηθηκε στη μνημη",
        "κρατήθηκε στη μνήμη",
    )
    return any(marker in clean for marker in generic_markers) and len(clean) < 80


def _extract_confirmed_memory_candidate(
    user_text: str,
    ai_text: str,
    *,
    agent_name: str = "Unknown",
    channel: str = "web",
    now: datetime | None = None,
) -> dict | None:
    """Capture explicit save/remember confirmations without relying only on the LLM sifter."""
    safe_user = clean_message(user_text)
    safe_ai = clean_message(ai_text)
    combined = _normalize_text(f"{safe_user} {safe_ai}")

    if not any(marker in combined for marker in ("αποθηκευ", "μνημη", "σημειω", "υποψιν", "κρατα")):
        return None
    if any(marker in combined for marker in ("draft", "προσχεδιο", "προσχεδια", "να το στειλω", "να το στείλω")):
        return None

    source_text = " ".join(safe_user.split())
    confirmation_text = " ".join(safe_ai.split())
    if not source_text and not confirmation_text:
        return None
    if len(source_text) < 8 and len(confirmation_text) < 20:
        return None

    # Απαιτείται ρητή επιβεβαίωση από τον AI — και αν ο χρήστης έδωσε ρητό
    # "Κράτα στη μνήμη ότι X", κρατάμε το X, όχι meta-κείμενο τύπου
    # "ο χρήστης ζήτησε να αποθηκευτεί".
    detail = None
    explicit_payload = _extract_explicit_memory_payload(source_text)
    if confirmation_text:
        memory_match = re.search(
            r"(?:αποθηκεύτηκε|αποθηκευτηκε|αποθήκευσα|αποθηκευσα|σημειώθηκε|σημειωθηκε|σημείωσα|σημειωσα|κρατήθηκε|κρατηθηκε)[^\n]{0,220}",
            confirmation_text,
            flags=re.IGNORECASE,
        )
        if memory_match:
            detail = memory_match.group(0).strip()
    if not detail:
        # Ο AI δεν επιβεβαίωσε ρητά → παράκαμψη, ο LLM sifter θα αποφασίσει
        return None
    if explicit_payload and _looks_like_generic_memory_confirmation(detail):
        detail = explicit_payload
    if len(detail) > 300:
        detail = detail[:297].rstrip() + "..."

    category = _infer_memory_category(f"{safe_user} {safe_ai}")

    ts = now or datetime.now()
    fact = f"[USER_FACT]: Στις {ts.strftime('%Y-%m-%d')}, {detail}"
    return _normalize_memory_candidate({
        "memory_type": "fact",
        "fact": fact,
        "category": category,
        "agent_name": agent_name,
        "source": channel,
        "reason": "user_stated",
        "confidence": 0.9,
        "relation_type": "confirmed",
    }, now=ts)


def _run_session_summary(channel: str = "web"):
    """Αρχειοθετεί τη συνεδρία (per channel) με προστασία από διπλοεγγραφές."""
    global is_summarizing, SESSION_LOGS

    try:
        persistent_log = load_unsummarized_exchanges(limit=200)
    except Exception as e:
        print(f"\033[93m[SessionLog]: Shared exchange read failed, using memory log: {e}\033[0m")
        persistent_log = []
    using_persistent_log = bool(persistent_log)
    current_log = persistent_log if using_persistent_log else list(SESSION_LOGS)
    # 1. Ασπίδα: Αν ήδη τρέχει ή αν δεν υπάρχουν μηνύματα, βγες αμέσως
    if is_summarizing or not current_log:
        return

    try:
        is_summarizing = True
        print(f"\n\033[94m[Session/{channel}]: Έναρξη αρχειοθέτησης...\033[0m")
        
        # 2. Αδειάζουμε ΑΜΕΣΩΣ για να μην το ξαναπιάσει άλλος worker
        current_batch = list(current_log)
        SESSION_LOGS.clear()
        channels = sorted({e.get("channel", channel) for e in current_batch})
        summary_channel = channels[0] if len(channels) == 1 else "mixed"

        dialogue_text = "\n".join([
            f"[{e['time']} / {e.get('channel', channel)} / {e['agent']}] Λάζαρος: {e['user']} | Αστακός: {e['ai']}"
            for e in current_batch
        ])

        # 3. Το prompt με αυστηρό format ημερομηνίας (για να ταιριάζει με τα παλιά σου logs)
        summary_prompt = f"""
Ανάλυσε αυτή τη συνομιλία μεταξύ Λάζαρου και Αστακού και συμπλήρωσε ένα JSON αναφοράς.
Απάντησε ΜΟΝΟ με το JSON.

{{
  "date": "{datetime.now().strftime('%Y-%m-%d %H:%M')}",
  "channel": "{summary_channel}",
  "summary": "2-3 προτάσεις τι συζητήθηκε σήμερα",
  "completed": ["λίστα από πράγματα που ολοκληρώθηκαν"],
  "pending": ["λίστα από πράγματα που έμειναν ημιτελή"],
  "next_session_hint": "Τι πρέπει να θυμάται ο Αστακός για την επόμενη φορά",
  "mood": "productive|relaxed|debugging|planning"
}}

[ΣΥΝΟΜΙΛΙΑ]
{dialogue_text}
"""
        response = safe_gemini_call(summary_prompt)
        raw = re.sub(r"```json|```", "", response.text.strip()).strip()

        try:
            summary = json.loads(raw)
        except json.JSONDecodeError:
            # Αν αποτύχει, ξαναβάζουμε τα μηνύματα πίσω για να μην τα χάσουμε
            if not using_persistent_log:
                SESSION_LOGS[:0] = current_batch  # Επαναφορά στην αρχή
                print("\033[91m[Session]: Μη έγκυρο format. Τα μηνύματα επεστράφησαν στο log.\033[0m")
            else:
                print("\033[91m[Session]: Μη έγκυρο format. Τα shared exchanges έμειναν unsummarized.\033[0m")
            return

        # 4. Εμπλουτισμός του κειμένου για τη Vector DB
        session_text = (
            f"[SESSION {summary.get('date', '')}] {summary.get('summary', '')} "
            f"Εκκρεμότητες: {', '.join(summary.get('pending', [])) if summary.get('pending') else 'καμία'}. "
            f"Hint: {summary.get('next_session_hint', '')}"
        )

        # 5. Αποθήκευση (Εδώ ο MemoryManager θα κάνει και το overwrite αν χρειαστεί)
        memory.save(memory_type="session", summary=summary, session_text=session_text)
        if using_persistent_log:
            mark_exchanges_summarized([e["id"] for e in current_batch])
        print(f"\033[92m[Session]: ✅ Αρχειοθετήθηκε επιτυχώς! Mood: {summary.get('mood', '?')}\033[0m")
        bus.emit("session_ended", channel=summary_channel, mood=summary.get("mood", "unknown"), summary=summary.get("summary", ""))

    except Exception as e:
        # Recovery σε περίπτωση σφάλματος
        if not using_persistent_log:
            SESSION_LOGS[:0] = current_batch  # Επαναφορά στην αρχή
        print(f"\033[91m[Session Error]: {e}\033[0m")
    finally:
        is_summarizing = False


def _candidate_identity_key(candidate: dict | None) -> tuple:
    if not candidate:
        return tuple()
    entities = tuple(sorted(x.lower() for x in candidate.get("entities", []) if str(x).strip()))
    topic = candidate.get("topic", "") or "other"
    topic_detail = candidate.get("topic_detail", "") or ""
    time_scope = candidate.get("time_scope", "") or ""
    category = candidate.get("category", "") or "other"
    return (category, entities, topic, topic_detail, time_scope)


_RELATION_TYPE_RANK = {
    "new_fact": 1,
    "confirmed": 2,
    "follow_up": 3,
    "temporary_state": 4,
    "state_update": 5,
    "correction": 6,
    "preference": 2,
    "routine_hint": 2,
}

def _relation_type_rank(value: str) -> int:
    key = str(value or "").strip().lower()
    return _RELATION_TYPE_RANK.get(key, 0)


def _fact_token_set(text: str) -> set[str]:
    clean = _normalize_text(text)
    clean = re.sub(r"^\[user_fact\]:\s*", "", clean, flags=re.IGNORECASE)

    stopwords = {
        "ο", "η", "το", "οι", "τα", "του", "της", "των",
        "και", "να", "που", "στο", "στη", "στην", "στον",
        "με", "σε", "απο", "από", "για", "πια", "πιο",
        "μια", "μία", "ενα", "ένα", "ειναι", "ήταν",
        "τον", "την", "τις", "τους", "μας", "σας",
        "χτες", "χθες", "σημερα", "σήμερα", "αυριο", "αύριο",
        "στις", "στη", "στο", "ως", "μεχρι", "μέχρι",
    }

    tokens = set()
    for token in clean.split():
        token = token.strip(".,;:!?()[]{}\"'")
        if len(token) < 2:
            continue
        if token in stopwords:
            continue
        tokens.add(token)

    return tokens


def _facts_are_near_duplicates(a: str, b: str, threshold: float = 0.75) -> bool:
    ta = _fact_token_set(a)
    tb = _fact_token_set(b)

    if not ta or not tb:
        return False

    overlap = len(ta & tb) / min(len(ta), len(tb))
    return overlap >= threshold


def _same_candidate_fact(a: dict | None, b: dict | None) -> bool:
    if not a or not b:
        return False

    fa = _normalize_text(a.get("fact", ""))
    fb = _normalize_text(b.get("fact", ""))

    if not fa or not fb:
        return False

    if fa == fb or fa in fb or fb in fa:
        return True

    same_identity = _candidate_identity_key(a) == _candidate_identity_key(b)
    same_states = set(a.get("state_markers", [])) == set(b.get("state_markers", []))

    if same_identity and same_states and _facts_are_near_duplicates(
        a.get("fact", ""),
        b.get("fact", ""),
    ):
        return True

    return False


def _candidate_has_new_information(new_candidate: dict, existing_candidate: dict) -> bool:
    new_states = set(new_candidate.get("state_markers", []))
    old_states = set(existing_candidate.get("state_markers", []))

    new_tags = set(new_candidate.get("tags", []))
    old_tags = set(existing_candidate.get("tags", []))

    new_relation = str(new_candidate.get("relation_type", "")).strip().lower()
    old_relation = str(existing_candidate.get("relation_type", "")).strip().lower()

    if new_states - old_states:
        return True

    if new_tags - old_tags:
        return True

    if _relation_type_rank(new_relation) > _relation_type_rank(old_relation):
        return True

    if new_relation in {"follow_up", "state_update", "correction", "temporary_state"}:
        if not _facts_are_near_duplicates(
            new_candidate.get("fact", ""),
            existing_candidate.get("fact", ""),
        ):
            return True

    return False


def _append_candidate_safely(selected: list[dict], candidate: dict) -> None:
    for existing in selected:
        if _same_candidate_fact(candidate, existing):
            return

        same_identity = _candidate_identity_key(candidate) == _candidate_identity_key(existing)
        if same_identity:
            if _candidate_has_new_information(candidate, existing):
                selected.append(candidate)
            return

    selected.append(candidate)


def _candidate_debug_summary(candidate: dict) -> str:
    return (
        f"cat={candidate.get('category')} "
        f"entities={candidate.get('entities', [])} "
        f"topic={candidate.get('topic')} "
        f"detail={candidate.get('topic_detail')} "
        f"states={candidate.get('state_markers', [])} "
        f"rel={candidate.get('relation_type')} "
        f"time={candidate.get('time_scope')}"
    )

# ════════════════════════════════════════════════════════════════
# MEMORY SIFTER — "Αρχειοθέτης"
# ════════════════════════════════════════════════════════════════

def _fact_matches_any(fact: str, existing_facts: list[str]) -> bool:
    def _normalize_text_local(t):
        if not t: return ""
        import unicodedata
        normalized = unicodedata.normalize("NFD", str(t))
        return "".join(ch for ch in normalized if not unicodedata.combining(ch)).lower().strip()

    normalized_fact = _normalize_text_local(fact)
    if not normalized_fact:
        return False

    for existing in existing_facts:
        normalized_existing = _normalize_text_local(existing)
        if not normalized_existing:
            continue
        if normalized_fact == normalized_existing:
            return True
        if normalized_fact in normalized_existing or normalized_existing in normalized_fact:
            return True

    return False

def _collect_deterministic_candidates(
    user_text: str,
    ai_text: str,
    *,
    agent_name: str = "Unknown",
    channel: str = "web",
) -> list[dict]:
    event_candidate = _extract_event_memory_candidate(
        user_text,
        ai_text,
        agent_name=agent_name,
        channel=channel,
    )
    temporary_candidate = _extract_temporary_family_memory_candidate(
        user_text,
        ai_text,
        agent_name=agent_name,
        channel=channel,
    )
    confirmed_candidate = _extract_confirmed_memory_candidate(
        user_text,
        ai_text,
        agent_name=agent_name,
        channel=channel,
    )

    selected_candidates: list[dict] = []
    for candidate in (temporary_candidate, event_candidate, confirmed_candidate):
        if candidate:
            _append_candidate_safely(selected_candidates, _normalize_memory_candidate(candidate))
    return selected_candidates

def run_memory_sifter_fast(user_text: str, ai_text: str, agent_name: str = "Unknown", channel: str = "web"):
    try:
        selected_candidates = _collect_deterministic_candidates(
            user_text,
            ai_text,
            agent_name=agent_name,
            channel=channel,
        )

        for candidate in selected_candidates:
            memory.save(**candidate)

        return [c.get("fact", "") for c in selected_candidates if c.get("fact")]
    except Exception as e:
        print(f"⚠️ [MemorySifterFast Error]: {e}")
        return []

def run_memory_sifter_slow(
    user_text: str,
    ai_text: str,
    agent_name: str = "Unknown",
    channel: str = "web",
    deterministic_seed_facts: list[str] | None = None,
):
    deterministic_seed_facts = deterministic_seed_facts or []
    print("\033[90m[MemorySifterSlow]: start\033[0m")
    
    MEMORY_CATS = {
        "lazaros":  "Προτιμήσεις, συνήθειες, τρόπος σκέψης, δουλειά του Λάζαρου",
        "family":   "Πληροφορίες για Σοφία, Αλέξανδρο, Μαρία, κατοικίδια",
        "projects": "Mastroapp, PraxisERP, Αστακός, Paletes, Shiftmaster",
        "home":     "Σπίτι, εξοπλισμός, συσκευές, Piston-7",
        "lesson":   "Τεχνικά μαθήματα, λύσεις bugs, κανόνες για τον Αστακό",
        "photos":   "Φωτογραφίες, περιγραφή και paths",
    }

    try:
        # 1. Προετοιμασία Prompt για το Gemini
        cats_desc = "\n".join([f'  - "{k}": {v}' for k, v in MEMORY_CATS.items()])
        
        # ── Sliding-window context: τελευταία exchanges πριν το τρέχον ──
        # Ο sifter μπαίνει στην ουρά ΠΡΙΝ το log_exchange (βλ. enqueue σειρά
        # στο api/server.py), άρα το SESSION_LOGS εδώ ΔΕΝ περιέχει ακόμα το
        # τρέχον exchange -> καμία διπλοεγγραφή/race condition.
        recent_context_block = ""
        try:
            recent_entries = SESSION_LOGS[-4:]
            if recent_entries:
                ctx_lines = "\n".join(
                    f"Λάζαρος: {e['user']} | Αστακός: {e['ai']}"
                    for e in recent_entries
                )
                recent_context_block = (
                    "\n[ΠΡΟΗΓΟΥΜΕΝΟ ΠΛΑΙΣΙΟ — μόνο για να καταλάβεις τη ροή της "
                    "συζήτησης, ΜΗΝ εξάγεις facts από αυτό το τμήμα]\n"
                    f"{ctx_lines}\n"
                )
        except Exception:
            recent_context_block = ""

        sifter_prompt = f"""
Είσαι ο Αρχειοθέτης του Αστακού. Εξάγεις ΜΟΝΟ αξιόλογες, νέες μνήμες.
Δεν περιμένεις να πει ο χρήστης "αποθήκευσέ το". Κρίνεις μόνος σου από το περιεχόμενο
αν κάτι αξίζει μακροπρόθεσμη μνήμη και σε ποια κατηγορία ανήκει.

Αν ο χρήστης ανέβασε φωτογραφία (σήμα [USER_UPLOADED_PHOTO] ή [PHOTO PATH]), ΠΡΕΠΕΙ να βγάλεις:
- caption: Μια σύντομη λεζάντα στα Ελληνικά (π.χ. 'Ο Αλέξανδρος και το κουνέλι').
- analysis: Μια πλήρη περιγραφή στα Αγγλικά βασισμένη σε όσα είπε ο Αστακός.

ΚΑΤΗΓΟΡΙΕΣ:
{cats_desc}

ΚΑΝΟΝΕΣ:
1. Κάθε μνήμη (fact) ΠΡΕΠΕΙ να ξεκινάει με: [USER_FACT], [CAPABILITY], [LESSON], ή [PHOTO].
2. ΜΟΡΦΗ JSON array: [{{"fact": "[TAG]: ...", "category": "...", "caption": "...", "analysis": "..."}}]
3. Αν δεν υπάρχει νέα πληροφορία → απάντησε ΜΟΝΟ: ΚΕΝΟ.
4. Κράτα ημερομηνία για ημερήσια γεγονότα/οικογενειακές δραστηριότητες (π.χ. αγώνες, πάρκο, σχολείο, δουλειά): "Στις YYYY-MM-DD, ...".
5. Μην αποθηκεύεις απλά drafts/προσχέδια μηνυμάτων ως facts. Αποθήκευσε μόνο πραγματικά γεγονότα, προτιμήσεις, αποφάσεις ή μαθήματα.
6. Αποθήκευσε χωρίς ρητή εντολή όταν ο διάλογος περιέχει:
   - προσωπικό ή οικογενειακό γεγονός/πλάνο/απόφαση (Σοφία, Αλέξανδρος, γενέθλια, δώρα, υγεία, σχολείο, δουλειά),
   - προσωρινή οικογενειακή κατάσταση με χρονικό παράθυρο (π.χ. κατασκήνωση, ταξίδι, λείπει μέχρι να γυρίσει),
   - σταθερή προτίμηση, συνήθεια, περιορισμό ή κάτι που θα βοηθήσει μελλοντικά,
   - σημαντικό project/tool/bug/κανόνα που μάθαμε,
   - link ή προϊόν που συνδέεται με μελλοντική αγορά/δώρο/εκκρεμότητα.
7. Διάλεξε category από το νόημα:
   - "family": Σοφία, Αλέξανδρος, οικογένεια, δώρα, γενέθλια, σχολείο, δραστηριότητες.
   - "lazaros": προτιμήσεις, υγεία, δουλειά, συνήθειες, προσωπικοί στόχοι του Λάζαρου.
   - "projects": Mastroapp, Astakos, GitHub, κώδικας, προϊόντα, πελατειακά/project θέματα.
   - "home": σπίτι, συσκευές, ψώνια, εργασίες σπιτιού, αυτοματισμοί.
   - "lesson": κανόνες λειτουργίας, bugs που λύθηκαν, συμπεριφορές που πρέπει να θυμάται ο Αστακός.
   - "photos": φωτογραφίες/αρχεία με περιγραφές.
8. Μην αποθηκεύεις απλές απαντήσεις ευγένειας, προσωρινά drafts, αστεία χωρίς μελλοντική αξία,
   ή πληροφορίες που είναι ήδη γνωστές εκτός αν η νέα εκδοχή είναι πιο πλούσια/ακριβής.
   Για προσωρινές οικογενειακές καταστάσεις, κράτα και τη χρονική ένδειξη/παράθυρο επιστροφής αν αναφέρεται.
   Αν το νέο fact είναι εξέλιξη ήδη υπάρχουσας κατάστασης, χρησιμοποίησε relation_type="follow_up" ή "state_update" και βάλε state_markers,
   όχι απλό generic duplicate.
9. ΑΠΑΓΟΡΕΥΕΤΑΙ να αποθηκεύεις ερωτήσεις του χρήστη — αν το μήνυμα είναι ερώτηση (τελειώνει με ";" ή "?"
   ή ξεκινά με "τι", "πώς", "γιατί", "πού", "ποιος", "πόσο", "πότε") → ΚΕΝΟ.
   Ειδικά αν αφορά τη λειτουργία του Αστακού, debug, logs, ή τεχνικές ερωτήσεις για το σύστημα → ΚΕΝΟ.
10. ΑΠΑΓΟΡΕΥΕΤΑΙ να αποθηκεύεις δεδομένα code editing session: diffs, file paths αλλαγών, αποτελέσματα
    terminal commands, grep output, syntax errors, γραμμές κώδικα, αριθμούς γραμμών (π.χ. "Διόρθωσα
    serializers.py γραμμή 408", "edit_project_file επέστρεψε +5 γραμμές") → ΚΕΝΟ.
    ΕΞΑΙΡΕΣΗ: Αποθήκευσε ΜΟΝΟ υψηλού επιπέδου γεγονότα χωρίς τεχνικές λεπτομέρειες:
    π.χ. "Το project mastro_app βρίσκεται στο C:\mastro_app" ή
    "Στο mastro_app υπάρχει πρόβλημα με get_or_create όταν temp_id=None" (lesson/projects).

{recent_context_block}
[ΤΡΕΧΟΥΣΑ ΑΝΤΑΛΛΑΓΗ — εδώ, και ΜΟΝΟ εδώ, εξάγεις νέα facts]
[Ημερομηνία/Ώρα: {datetime.now().strftime('%Y-%m-%d %H:%M')} | Channel: {channel}]
[Agent: {agent_name}]
Λάζαρος: {user_text}
Αστακός: {ai_text}
"""
        response = safe_gemini_call(sifter_prompt)
        raw_text = response.text.strip()
        
        if "ΚΕΝΟ" in raw_text or not raw_text:
            return

        raw_clean = re.sub(r"```json|```", "", raw_text).strip()
        if not raw_clean.startswith("["):
            return
            
        # --- [MASTRO-JSON-SHIELD]: Αυτόματη διόρθωση για ξεχασμένα κόμματα του LLM ---
        try:
            memories = json.loads(raw_clean)
        except json.JSONDecodeError:
            try:
                # Καθαρίζουμε trailing commas πριν από κλείσιμο λίστας ή αντικειμένου
                fixed_raw = re.sub(r',\s*\]', ']', raw_clean)
                fixed_raw = re.sub(r',\s*\}', '}', fixed_raw)
                memories = json.loads(fixed_raw)
                print("\033[93m[Sifter Fixer]: ✅ Το JSON επισκευάστηκε αυτόματα!\033[0m")
            except:
                print("\033[91m⚠️ [Sifter Error]: Το LLM έβγαλε εντελώς κακογραμμένο JSON. Παράκαμψη εγγραφής.\033[0m")
                return

        for mem in memories:
            candidate = _normalize_memory_candidate({
                **mem,
                "source": channel,
                "agent_name": agent_name,
                "reason": mem.get("reason", "agent_inferred"),
            })
            fact = candidate.get("fact", "").strip()
            category = candidate.get("category", "lazaros")

            # [QUESTION GUARD]: Αν το fact είναι ερώτηση, παράκαμψε το
            _fact_body = re.sub(r"^\[USER_FACT\]:\s*", "", fact).strip()
            _question_starters = ("τι ", "πώς ", "πως ", "γιατί ", "γιατι ", "πού ",
                                  "που ", "ποιος ", "ποια ", "ποιο ", "πόσο ", "ποσο ",
                                  "πότε ", "ποτε ", "εδω ", "αυτο ")
            _is_question = (
                _fact_body.endswith("?") or _fact_body.endswith(";") or
                any(_fact_body.lower().startswith(s) for s in _question_starters)
            )
            if _is_question:
                print(f"\033[93m[Sifter]: Question guard — skipping fact: {_fact_body[:60]}\033[0m")
                continue

            if _fact_matches_any(fact, deterministic_seed_facts):
                print(f"\033[90m[MemorySifterSlow]: seed-duplicate skip -> {fact[:80]}\033[0m")
                continue

            # 2. --- ΤΟ ΣΩΣΤΟ JSON INDEXING (Mastro-Restore) ---
            if "[PHOTO]" in fact or category == "photos":
                # Regex για να βρούμε το filename από το user_text
                match = re.search(r"(?:USER_UPLOADED_PHOTO|PHOTO PATH)\]:\s*([^\s\n\]]+)", user_text)
                if match:
                    filename = os.path.basename(match.group(1).strip().replace("]", ""))
                else:
                    # Fallback: ψάξε για πραγματικό filename (.jpg/.png/κλπ) στα texts
                    file_match = re.search(
                        r"\b([a-zA-Z0-9_\-]+\.(?:jpg|jpeg|png|gif|webp|pdf|txt|md))\b",
                        user_text + " " + ai_text,
                        re.IGNORECASE,
                    )
                    if file_match:
                        filename = file_match.group(1)
                    else:
                        # Δεν βρέθηκε έγκυρο filename — αποφυγή corrupted entry
                        print(f"\033[93m[Sifter]: [PHOTO] χωρίς έγκυρο filename — παράκαμψη photo index.\033[0m")
                        filename = None

                if not filename:
                    # Συνέχισε στο ChromaDB save, αλλά μην γράψεις στο photos index
                    memory.save(**candidate)
                    continue

                file_path = os.path.join(PHOTOS_DIR, filename)

                # Αν το Gemini δεν έβγαλε analysis, παίρνουμε την απάντηση του AI ως analysis
                analysis_val = mem.get("analysis")
                if not analysis_val or analysis_val == "No analysis provided.":
                    analysis_val = ai_text # Backup από τον διάλογο

                photo_entry = {
                    "file_path": file_path,
                    "analysis": analysis_val,
                    "caption": mem.get("caption", "Φωτογραφία από τον Λάζαρο"),
                    "date": datetime.now().strftime("%Y-%m-%d"),
                    "timestamp": datetime.now().isoformat()
                }

                # Φόρτωση και ενημέρωση του κεντρικού JSON
                photo_index = []
                if os.path.exists(PHOTOS_INDEX_FILE):
                    with open(PHOTOS_INDEX_FILE, "r", encoding="utf-8") as f:
                        try: photo_index = json.load(f)
                        except: photo_index = []
                
                save_confirmed = any(w in ai_text.lower() for w in ["αρχειοθετ", "αποθηκεύ", "καταγράφ", "σώθηκε", "index"])

                if not any(p.get("file_path") == file_path for p in photo_index) and save_confirmed:
                    photo_index.append(photo_entry)
                    with open(PHOTOS_INDEX_FILE, "w", encoding="utf-8") as f:
                        json.dump(photo_index, f, indent=4, ensure_ascii=False)
                    print(f"\033[92m📸 [Index]: Η φωτογραφία {filename} αρχειοθετήθηκε επιτυχώς.\033[0m")

            # 3. Αποθήκευση στη ChromaDB
            memory.save(**candidate)

        print("\033[90m[MemorySifterSlow]: done\033[0m")

    except Exception as e:
        print(f"⚠️ [Sifter Error]: {e}")


def trigger_memory_sifter(user_text: str, ai_text: str, agent_name: str = "Unknown", channel: str = "web"):
    """Wrapper — εκτελείται μέσω Queue Worker."""
    seed_facts = run_memory_sifter_fast(user_text, ai_text, agent_name, channel)
    run_memory_sifter_slow(user_text, ai_text, agent_name, channel, deterministic_seed_facts=seed_facts)


# ════════════════════════════════════════════════════════════════
# STARTUP STALE CLEANUP
# ════════════════════════════════════════════════════════════════

def startup_stale_cleanup(channel: str = "telegram") -> bool:
    """
    Εκτελείται κατά την εκκίνηση.
    Αν το astakos_working_memory.json έχει entries από προηγούμενη μέρα
    (δηλ. δεν έτρεξε /end λόγω hard restart), τρέχει πρώτα session summary
    (για να αποθηκευτούν οι ανεπεξέργαστοι exchanges) και μετά σβήνει τα tags.

    Επιστρέφει True αν εκτελέστηκε cleanup, False αν δεν χρειαζόταν.
    """
    try:
        from config import WORKING_MEMORY_FILE
        from datetime import date as _date

        if not os.path.exists(WORKING_MEMORY_FILE):
            print("\033[90m[Startup]: Δεν βρέθηκε working memory file — παράκαμψη.\033[0m")
            return False

        # Έλεγξε αν το αρχείο έχει entries
        try:
            with open(WORKING_MEMORY_FILE, "r", encoding="utf-8") as f:
                tags = json.load(f)
        except Exception:
            tags = []

        if not tags:
            print("\033[90m[Startup]: Working memory κενό — παράκαμψη.\033[0m")
            return False

        # Έλεγξε αν το αρχείο τροποποιήθηκε πριν από σήμερα
        mtime = os.path.getmtime(WORKING_MEMORY_FILE)
        file_date = _date.fromtimestamp(mtime)
        today = _date.today()

        if file_date >= today:
            print(f"\033[90m[Startup]: Working memory είναι από σήμερα ({file_date}) — παράκαμψη.\033[0m")
            return False

        print(
            f"\033[93m[Startup]: ⚠️  Βρέθηκαν {len(tags)} stale tags από {file_date} "
            f"(hard restart εντοπίστηκε). Εκτέλεση session summary πριν τον καθαρισμό...\033[0m"
        )

        # 1. Τρέξε πρώτα το session summary (αποθηκεύει unsummarized exchanges)
        _run_session_summary(channel=channel)

        # 2. Σβήσε τα stale tags
        try:
            with open(WORKING_MEMORY_FILE, "w", encoding="utf-8") as f:
                json.dump([], f, ensure_ascii=False, indent=2)
            print(
                f"\033[92m[Startup]: ✅ Working memory cleared — {len(tags)} stale tags "
                f"από {file_date} επεξεργάστηκαν και αφαιρέθηκαν.\033[0m"
            )
            return True
        except Exception as e:
            print(f"\033[91m[Startup]: ❌ Αποτυχία καθαρισμού working memory: {e}\033[0m")
            return False

    except Exception as e:
        print(f"\033[91m[Startup Cleanup Error]: {e}\033[0m")
        return False
