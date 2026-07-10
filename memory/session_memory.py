# ================================================================
# Project: Astakos AI Agent 🦞
# Developer: Lazaros (Piston-7)
# Description: Modular LLM-agnostic multi-agent framework
# Copyright (c) 2026 - All Rights Reserved
# ================================================================

import os
import json
import threading
import hashlib
from datetime import datetime, timedelta
import unicodedata
from memory.vector_store import memory, get_profile_facts, memory_overlap_ratio
from services.gemini import safe_gemini_call
from memory.family_arc_resolution import (
    _same_family_arc,
    _decide_family_arc_resolution,
    _pick_richer_candidate,
)
import re
from core.utils import clean_message, looks_like_operational_assistant_text
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
AUTO_SESSION_SUMMARY_EXCHANGE_THRESHOLD = 20
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


def _strip_leading_ack_prefix(text: str) -> str:
    normalized = _normalize_text(text)
    prefixes = (
        "ναι ",
        "ναι, ",
        "οκ ",
        "ok ",
        "ωραια ",
        "ωραία ",
        "λοιπον ",
        "λοιπόν ",
        "ε ",
        "ε και ",
    )
    changed = True
    while changed:
        changed = False
        for prefix in prefixes:
            if normalized.startswith(prefix):
                normalized = normalized[len(prefix):].strip()
                changed = True
                break
    return normalized


def _strip_user_fact_scaffold(text: str) -> str:
    body = re.sub(r"^\[[A-Z_]+\]:\s*", "", str(text or ""), flags=re.IGNORECASE).strip()
    body = re.sub(r"^στις\s+20\d{2}-\d{2}-\d{2},?\s*", "", body, flags=re.IGNORECASE).strip()
    return body


def _looks_like_question_fact(text: str) -> bool:
    body = _strip_user_fact_scaffold(text)
    normalized = _strip_leading_ack_prefix(body)
    question_starters = (
        "τι ",
        "πώς ",
        "πως ",
        "γιατί ",
        "γιατι ",
        "πού ",
        "που ",
        "ποιος ",
        "ποια ",
        "ποιο ",
        "πόσο ",
        "ποσο ",
        "πότε ",
        "ποτε ",
    )
    return (
        body.endswith("?")
        or body.endswith(";")
        or normalized.endswith("?")
        or normalized.endswith(";")
        or any(normalized.startswith(s) for s in question_starters)
    )


def _looks_like_operational_user_request(user_text: str, ai_text: str = "") -> bool:
    source_text = " ".join(clean_message(user_text).split())
    if not source_text:
        return False

    normalized = _strip_leading_ack_prefix(source_text)
    ai_normalized = _normalize_text(ai_text)

    if normalized.startswith("id: "):
        return True

    imperative_starts = (
        "διαβασε",
        "βρες",
        "ψαξε",
        "φτιαξε",
        "γραψε",
        "στειλε",
        "μπες",
        "ανοιξε",
        "δες",
        "τσεκαρε",
        "κοιτα",
        "θελω να βρεις",
        "θελω να διαβασεις",
        "θελω να φτιαξεις",
        "θελω να μπεις",
    )
    tool_targets = (
        "mail",
        "email",
        "thread",
        "συνομιλι",
        "εικονα",
        "φωτο",
        "photo",
        "site",
        "link",
        "url",
        "αρχει",
        "file",
        "pdf",
        "trip.com",
    )

    if any(normalized.startswith(prefix) for prefix in imperative_starts) and any(token in normalized for token in tool_targets):
        return True

    if "📋 **plan για:" in ai_normalized and any(token in normalized for token in tool_targets):
        return True

    return False

def _looks_like_operational_asset_confirmation(text: str) -> bool:
    txt = (text or "").strip().lower()

    markers = (
        "την αποθηκευσα στη μνημη μου",
        "την αποθήκευσα στη μνήμη μου",
        "δεν την αποθηκευω μονιμα",
        "δεν την αποθηκεύω μόνιμα",
        "δεν την αρχειοθετω μονιμα",
        "δεν την αρχειοθετώ μόνιμα",
        "την αρχειοθετησα",
        "την αρχειοθέτησα",
        "αρχειοθετηθηκε",
        "αρχειοθετήθηκε",
        "δεν την κραταω",
        "δεν την κρατάω",
    )

    return any(m in txt for m in markers)


def _looks_like_operational_memory_noise(fact: str, ai_text: str = "") -> bool:
    fact_body = _strip_user_fact_scaffold(fact)
    fact_norm = clean_message(fact_body).strip()
    ai_norm = clean_message(ai_text).strip()

    if looks_like_operational_assistant_text(fact_norm):
        return True

    if ai_norm and looks_like_operational_assistant_text(ai_norm):
        return True

    low_fact = fact_norm.lower()
    low_ai = ai_norm.lower()

    direct_markers = (
        "αναμονή έγκρισης",
        "action approval required",
        "εκτελώ `execute_local_pipeline`",
        "εκτελώ `",
        "στάλθηκε, μάστορα",
        "το draft καθαρίστηκε",
        "δεν υπάρχει ενεργό draft",
        "εννοούσα αυτό το draft",
        "θέλεις αλλαγές, να το σβήσω ή να το στείλω",
    )

    return any(marker in low_fact or marker in low_ai for marker in direct_markers)

_MEMORY_SIFTER_RUN_TTL_HOURS = 48


def _ensure_memory_sifter_runs_table() -> None:
    conn = sqlite3.connect(STATE_DB)
    try:
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS memory_sifter_runs (
                fingerprint TEXT PRIMARY KEY,
                processed_at TEXT NOT NULL,
                channel TEXT,
                agent_name TEXT,
                user_preview TEXT,
                ai_preview TEXT
            )
        """)
        conn.commit()
    finally:
        conn.close()


def _memory_sifter_fingerprint(
    user_text: str,
    ai_text: str,
    agent_name: str = "Unknown",
    channel: str = "web",
) -> str:
    payload = "||".join([
        _normalize_text(channel),
        _normalize_text(agent_name),
        _normalize_text(user_text),
        _normalize_text(ai_text),
    ])
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _memory_sifter_user_fingerprint(
    user_text: str,
    agent_name: str = "Unknown",
    channel: str = "web",
) -> str:
    payload = "||".join([
        "user_only",
        _normalize_text(channel),
        _normalize_text(agent_name),
        _normalize_text(user_text),
    ])
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()

def _memory_sifter_already_processed(fingerprint: str) -> bool:
    _ensure_memory_sifter_runs_table()
    cutoff = (datetime.now() - timedelta(hours=_MEMORY_SIFTER_RUN_TTL_HOURS)).isoformat()

    conn = sqlite3.connect(STATE_DB)
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT 1
            FROM memory_sifter_runs
            WHERE fingerprint = ?
              AND processed_at >= ?
            LIMIT 1
        """, (fingerprint, cutoff))
        return cur.fetchone() is not None
    finally:
        conn.close()


def _mark_memory_sifter_processed(
    fingerprint: str,
    user_text: str,
    ai_text: str,
    agent_name: str = "Unknown",
    channel: str = "web",
) -> None:
    _ensure_memory_sifter_runs_table()

    conn = sqlite3.connect(STATE_DB)
    try:
        cur = conn.cursor()
        cur.execute("""
            INSERT OR REPLACE INTO memory_sifter_runs
            (fingerprint, processed_at, channel, agent_name, user_preview, ai_preview)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            fingerprint,
            datetime.now().isoformat(),
            channel,
            agent_name,
            clean_message(user_text)[:160],
            clean_message(ai_text)[:160],
        ))
        conn.commit()
    finally:
        conn.close()

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


_LOW_SIGNAL_ENTITY_TOKENS = {
    "στις", "στο", "στη", "στην", "στον", "στα", "στους", "στις",
    "και", "για", "απο", "από", "με", "θα", "να", "την", "τον", "του",
    "της", "τους", "μας", "σας", "τους", "ολοι", "όλοι", "ολη", "όλη",
    "οικογενεια", "οικογένεια", "γυρω", "γύρω", "περιπου", "περίπου",
    "κιλο", "κιλό", "κιλα", "κιλά", "γραμμαρια", "γραμμάρια", "φουρνο",
    "φούρνο", "τηγανιες", "τηγανιές", "παρει", "πήρε", "πηρα", "πήρα",
    "πηραμε", "πήραμε", "αγορασα", "αγόρασα", "αγορασε", "αγόρασε",
}


def _extract_food_subject_tokens(text: str) -> list[str]:
    cleaned_text = _strip_user_fact_scaffold(text)
    if not _looks_like_food_context(cleaned_text):
        return []

    compact = " ".join(clean_message(cleaned_text).lower().split())
    tokens = re.findall(r"[a-zA-Zα-ωάέήίόύώϊϋΐΰ]{4,}", compact)
    out: list[str] = []
    for token in tokens:
        if token in _LOW_SIGNAL_ENTITY_TOKENS:
            continue
        if token.endswith(("ουμε", "ουνε", "ουν", "εις", "ωσει", "ώσει", "ει", "οντας")):
            continue
        if token.endswith(("μενος", "μένη", "μενη", "μενο", "ητες", "ητές", "ητος", "ητή", "ητό")):
            continue
        out.append(token)
    return _dedupe_preserve_order(out[:6])


def _extract_entities_from_text(text: str) -> list[str]:
    cleaned_text = _strip_user_fact_scaffold(text)
    compact = " ".join(clean_message(cleaned_text).split())
    if not compact:
        return []

    found = []
    for match in re.finditer(r"\b[Α-ΩA-Z][Α-ΩA-Za-zΆ-Ώά-ώϊϋΐΰ]+(?:\s+[Α-ΩA-Z][Α-ΩA-Za-zΆ-Ώά-ώϊϋΐΰ]+)?", compact):
        entity = match.group(0).strip(" .,;:!?")
        if len(entity) >= 3:
            found.append(entity)
    found.extend(_extract_food_subject_tokens(compact))
    out: list[str] = []
    seen_casefold: set[str] = set()
    for item in found:
        key = str(item).strip().casefold()
        if not key or key in seen_casefold:
            continue
        seen_casefold.add(key)
        out.append(item)
    return out


def _looks_like_food_context(text: str) -> bool:
    normalized = _normalize_text(text)
    compact = " ".join(clean_message(text).lower().split())

    direct_food_markers = (
        "φαγητ", "φακες", "ψαρ", "μπριζολ", "φαγα", "εφαγε",
        "κρεας", "κοτοπ", "μακαρον", "ρυζ", "φασολ", "σουπα",
        "σαλατ", "τυρι", "πιτα", "πιτσ", "μπιφτεκ", "ψην",
    )
    prep_markers = (
        "φουρν", "τηγαν", "ψησ", "μαγειρ", "συνταγ", "αντιστασ",
        "αερα", "βρασ", "κατσαρολ", "σχαρ", "ριγαν", "λεμον",
    )
    meal_context_markers = (
        "πατατ", "οικογεν", "τραπεζ", "μεσημερ", "βραδιν", "γευμα",
        "φαμε", "φαω", "πιατο",
    )
    purchase_markers = (
        "αγορασ", "πηρα", "πηραμε", "κιλο", "κιλα", "γραμμαρ",
        "τεμαχ", "κομματ",
    )

    if any(marker in normalized for marker in direct_food_markers):
        return True

    has_weight_or_count = bool(
        re.search(r"\b\d+(?:[.,]\d+)?\s*(?:κιλ(?:ο|ά)?|κιλα|γρ|γραμμ?)\b", compact)
        or re.search(r"\b\d+\s*(?:τεμαχ|κομματ)\b", compact)
    )
    has_prep = any(marker in normalized for marker in prep_markers)
    has_meal_context = any(marker in normalized for marker in meal_context_markers)
    has_purchase_context = any(marker in normalized for marker in purchase_markers)

    return has_prep and (has_meal_context or has_purchase_context or has_weight_or_count)


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
    if _looks_like_food_context(text):
        return "food"
    if any(marker in normalized for marker in ("σπιτι", "κουζιν", "καθαρισ", "αφυγραντηρ", "σκουπ", "λαικ", "ψων")):
        return "home"
    if any(marker in normalized for marker in ("δουλει", "βαρδια", "εργοστασ", "πασσια", "συναδελφ")):
        return "work"
    if any(marker in normalized for marker in ("δωρο", "γενεθλ", "ρολοι", "γλαστρ")):
        return "gift"
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
    if _looks_like_food_context(text):
        return "meal_prep"
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


def build_canonical_memory_candidate(
    *,
    fact: str,
    category: str = "other",
    memory_type: str = "fact",
    tags: list[str] | None = None,
    entities: list[str] | None = None,
    topic: str = "",
    topic_detail: str = "",
    state_markers: list[str] | None = None,
    time_scope: str = "",
    relation_type: str = "",
    confidence: float = 0.7,
    source: str = "unknown",
    agent_name: str = "Unknown",
    reason: str = "agent_inferred",
    now: datetime | None = None,
) -> dict:
    return _normalize_memory_candidate(
        {
            "memory_type": memory_type,
            "fact": fact,
            "category": category,
            "tags": tags or [],
            "entities": entities or [],
            "topic": topic,
            "topic_detail": topic_detail,
            "state_markers": state_markers or [],
            "time_scope": time_scope,
            "relation_type": relation_type,
            "confidence": confidence,
            "source": source,
            "agent_name": agent_name,
            "reason": reason,
        },
        now=now,
    )


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

    if _looks_like_ephemeral_conversational_source(source_text):
        return None

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


def _resolve_family_candidate_conflict(existing_candidate: dict, new_candidate: dict):
    decision = _decide_family_arc_resolution(existing_candidate, new_candidate)

    if decision == "skip_exact_duplicate":
        return existing_candidate, "skip"

    if decision == "merge_enrich_existing":
        richer = _pick_richer_candidate(existing_candidate, new_candidate)
        return richer, "merge"

    return [existing_candidate, new_candidate], "add_both"


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

def _extract_fact_date(text: str) -> str:
    match = re.search(r"\b(20\d{2}-\d{2}-\d{2})\b", str(text or ""))
    return match.group(0) if match else ""


def _same_day_personal_or_work_near_duplicate(candidate: dict, accepted_candidates: list[dict]) -> bool:
    allowed = {"family", "work", "lazaros"}
    cand_category = str(candidate.get("category") or "").lower()
    if cand_category not in allowed:
        return False

    cand_fact = str(candidate.get("fact") or "").strip()
    cand_scope = str(candidate.get("time_scope") or "").strip()
    cand_topic = str(candidate.get("topic") or "").lower().strip()
    cand_detail = str(candidate.get("topic_detail") or "").lower().strip()

    if not cand_fact:
        return False

    cand_date = _extract_fact_date(cand_fact)

    for existing in accepted_candidates:
        existing_category = str(existing.get("category") or "").lower()
        if existing_category not in allowed:
            continue

        existing_fact = str(existing.get("fact") or "").strip()
        existing_scope = str(existing.get("time_scope") or "").strip()
        existing_topic = str(existing.get("topic") or "").lower().strip()
        existing_detail = str(existing.get("topic_detail") or "").lower().strip()

        if not existing_fact:
            continue

        existing_date = _extract_fact_date(existing_fact)

        if cand_scope and existing_scope and cand_scope != existing_scope:
            if not (cand_date and existing_date and cand_date == existing_date):
                continue

        same_topic = cand_topic and cand_topic == existing_topic
        same_detail = cand_detail and cand_detail == existing_detail

        overlap = memory_overlap_ratio(existing_fact, cand_fact)

        if same_topic or same_detail:
            if overlap >= 0.78:
                return True
        elif cand_date and existing_date and cand_date == existing_date and overlap >= 0.86:
            return True

    return False

def _family_fact_same_day_near_duplicate(candidate: dict, accepted_candidates: list[dict]) -> bool:
    if str(candidate.get("category") or "").lower() != "family":
        return False

    cand_fact = str(candidate.get("fact") or "").strip()
    cand_topic = str(candidate.get("topic") or "").lower().strip()
    cand_detail = str(candidate.get("topic_detail") or "").lower().strip()
    cand_scope = str(candidate.get("time_scope") or "").strip()

    if not cand_fact:
        return False

    for existing in accepted_candidates:
        if str(existing.get("category") or "").lower() != "family":
            continue

        existing_fact = str(existing.get("fact") or "").strip()
        existing_topic = str(existing.get("topic") or "").lower().strip()
        existing_detail = str(existing.get("topic_detail") or "").lower().strip()
        existing_scope = str(existing.get("time_scope") or "").strip()

        cand_date = _extract_fact_date(cand_fact)
        existing_date = _extract_fact_date(existing_fact)

        if cand_scope and existing_scope and cand_scope != existing_scope:
            if not (cand_date and existing_date and cand_date == existing_date):
                continue

        same_topic = cand_topic and cand_topic == existing_topic
        same_detail = cand_detail and cand_detail == existing_detail
        same_arc = _same_family_arc(existing, candidate)

        if same_arc:
            return True

        overlap = memory_overlap_ratio(existing_fact, cand_fact)

        if not (same_topic or same_detail):
            if overlap < 0.88:
                continue

        if overlap >= 0.82:
            return True

    return False

def _existing_family_fact_same_day_near_duplicate(candidate: dict) -> bool:
    if str(candidate.get("category") or "").lower() != "family":
        return False

    cand_fact = str(candidate.get("fact") or "").strip()
    cand_topic = str(candidate.get("topic") or "").lower().strip()
    cand_detail = str(candidate.get("topic_detail") or "").lower().strip()
    cand_scope = str(candidate.get("time_scope") or "").strip()

    if not cand_fact:
        return False

    try:
        docs = get_profile_facts(category="family", limit=200)
    except Exception:
        return False

    for existing in docs:
        existing_fact = str(existing.get("fact") or "").strip()
        existing_topic = str(existing.get("topic") or "").lower().strip()
        existing_detail = str(existing.get("topic_detail") or "").lower().strip()
        existing_scope = str(existing.get("time_scope") or "").strip()

        if not existing_fact:
            continue

        cand_date = _extract_fact_date(cand_fact)
        existing_date = _extract_fact_date(existing_fact)

        if cand_scope and existing_scope and cand_scope != existing_scope:
            if not (cand_date and existing_date and cand_date == existing_date):
                continue

        same_topic = cand_topic and cand_topic == existing_topic
        same_detail = cand_detail and cand_detail == existing_detail
        same_arc = _same_family_arc(existing, candidate)

        if same_arc:
            return True

        overlap = memory_overlap_ratio(cand_fact, existing_fact)

        if not (same_topic or same_detail):
            if overlap < 0.88:
                continue

        if overlap >= 0.82:
            return True

    return False

def _looks_low_signal_family_fact(fact: str) -> bool:
    body = re.sub(r"^\[[A-Z_]+\]:\s*", "", str(fact or "")).strip()
    norm = _normalize_text(body)

    if len(norm) < 28:
        return True

    low_signal_starts = (
        "ναι ",
        "ε ναι ",
        "κατω ",
        "οκ ",
        "ενταξει ",
        "ωραια ",
    )
    if norm.startswith(low_signal_starts):
        return True

    return False


def _looks_like_ephemeral_conversational_source(text: str) -> bool:
    norm = _normalize_text(_strip_user_fact_scaffold(text))

    if not norm:
        return False

    ack_prefixes = (
        "ναι ",
        "ε ναι ",
        "οκ ",
        "ok ",
        "ωραια ",
        "ωραία ",
        "καλα ",
        "καλά ",
    )

    immediate_markers = (
        "σε λιγο",
        "σε λίγο",
        "σε 5 λεπτ",
        "σε 10 λεπτ",
        "σε 15 λεπτ",
        "σε 20 λεπτ",
        "τωρα",
        "τώρα",
        "μολις",
        "μόλις",
        "μετα",
        "μετά",
        "παμε για",
        "πάμε για",
        "παω για",
        "πάω για",
        "γυρναμε",
        "γυρνάμε",
        "φευγουμε",
        "φεύγουμε",
    )

    durable_markers = (
        "του αρεσε",
        "του άρεσε",
        "ενθουσιαστ",
        "προτιμα",
        "προτιμά",
        "σταματησ",
        "σταμάτησ",
        "ξεκινα",
        "ξεκινά",
        "γυρισε",
        "γύρισε",
        "επεστρε",
        "επέστρε",
        "αγορασ",
        "αγόρασ",
        "εκλεισ",
        "έκλεισ",
        "βελτιωθ",
        "καλυτερ",
        "κουρασ",
        "αρρωστ",
        "βαρδια",
        "δουλευ",
        "κατασκην",
        "διακοπ",
    )

    has_ack_prefix = norm.startswith(ack_prefixes)
    has_immediate = any(marker in norm for marker in immediate_markers)
    has_durable = any(marker in norm for marker in durable_markers)

    return has_ack_prefix and has_immediate and not has_durable


def _should_skip_ephemeral_candidate(candidate: dict, source_text: str) -> bool:
    category = str(candidate.get("category") or "").lower()
    relation_type = str(candidate.get("relation_type") or "").lower()
    state_markers = candidate.get("state_markers") or []
    entities = candidate.get("entities") or []
    topic = str(candidate.get("topic") or "").lower()

    if category not in {"lazaros", "family", "work", "home"}:
        return False

    if relation_type not in {"new_fact", "confirmed"}:
        return False

    if state_markers:
        return False

    # Food/family outcomes τύπου "του άρεσε", "ενθουσιάστηκε" κτλ. να μη χαθούν.
    if topic == "food":
        norm = _normalize_text(source_text)
        if any(marker in norm for marker in ("του αρεσε", "του άρεσε", "ενθουσιαστ", "ξανατρω", "τρωει", "τρώει")):
            return False

    return _looks_like_ephemeral_conversational_source(source_text)


def _looks_like_operational_reminder_exchange(user_text: str, ai_text: str) -> bool:
    user_norm = _normalize_text(user_text)
    ai_norm = _normalize_text(ai_text)

    if not user_norm or not ai_norm:
        return False

    user_has_reminder_request = (
        ("θυμ" in user_norm or "υπενθυμ" in user_norm)
        and bool(re.search(r"\b\d{1,2}:\d{2}\b", user_norm))
    )

    ai_has_reminder_confirmation = (
        "υπενθυμιση ρυθμιστηκε" in ai_norm
        or "υπενθυμιση ρυθμιστηκε για τις" in ai_norm
    )

    return user_has_reminder_request and ai_has_reminder_confirmation


def _looks_like_operational_message_exchange(user_text: str, ai_text: str) -> bool:
    """Skip short control/system exchanges that should not become user facts."""
    user_norm = _normalize_text(user_text)
    ai_norm = _normalize_text(ai_text)

    if user_norm.startswith("[system]:") or user_norm.startswith("[story_sent]"):
        return True

    short_send = user_norm in {"στείλε", "στειλε", "send", "ναι", "οκ", "ok"}
    draft_or_error = any(marker in ai_norm for marker in (
        "δεν βρέθηκε προσχέδιο",
        "δεν βρεθηκε προσχεδιο",
        "messenger_draft.json",
        "προσχέδιο messenger",
        "προσχεδιο messenger",
    ))

    return short_send and draft_or_error


def _looks_like_recent_followup_resolution_reply(user_text: str, within_seconds: int = 300) -> bool:
    text = _normalize_text(_strip_user_fact_scaffold(user_text))

    if not text:
        return False

    if len(text.split()) > 18:
        return False

    resolution_markers = (
        "τελικα",
        "ήδη",
        "ηδη",
        "εδω ειμαστε",
        "εδώ είμαστε",
        "γυρισαμε",
        "γυρίσαμε",
        "βρηκα",
        "βρήκα",
        "τους βρηκα",
        "τους βρήκα",
        "πηγα",
        "πήγα",
        "παω",
        "πάω",
        "εφυγα",
        "έφυγα",
        "δεν εγινε",
        "δεν έγινε",
        "αυριο",
        "αύριο",
    )

    if not any(marker in text for marker in resolution_markers):
        return False

    import sqlite3
    from datetime import datetime, timedelta
    conn = sqlite3.connect(STATE_DB)
    try:
        rows = conn.execute(
            """
            SELECT topic, subject, resolved_at, resolution_reason
            FROM pending_followups
            WHERE status='resolved'
              AND resolved_at IS NOT NULL
            ORDER BY resolved_at DESC, id DESC
            LIMIT 5
            """
        ).fetchall()
    finally:
        conn.close()

    # cutoff = datetime.now() - timedelta(seconds=within_seconds) # moved inside loop

    for topic, subject, resolved_at, resolution_reason in rows:
        try:
            resolved_dt = datetime.fromisoformat(str(resolved_at).replace(" ", "T"))
        except Exception:
            continue

        if resolved_dt.tzinfo is None:
            cutoff = datetime.now() - timedelta(seconds=within_seconds)
        else:
            cutoff = datetime.now(resolved_dt.tzinfo) - timedelta(seconds=within_seconds)

        if resolved_dt < cutoff:
            continue

        subject_norm = _normalize_text(subject or "")
        subject_tokens = [tok for tok in subject_norm.split() if len(tok) >= 4]

        if any(tok in text for tok in subject_tokens):
            return True

        topic = str(topic or "").strip().lower()
        reason = _normalize_text(resolution_reason or "")

        if topic == "outing" and any(marker in text for marker in ("εδω ειμαστε", "εδώ είμαστε", "γυρισαμε", "γυρίσαμε", "βρηκα", "βρήκα", "παω", "πάω")):
            return True

        if topic == "food_purchase" and any(marker in text for marker in ("τις πηρα", "τις πήρα", "το πηρα", "το πήρα", "δεν πηρα", "δεν πήρα")):
            return True

        if "resolved_by_user_message" in reason:
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

    resolved_candidates = []

    for candidate in (temporary_candidate, event_candidate, confirmed_candidate):
        if not candidate:
            continue
            
        cand_norm = _normalize_memory_candidate(candidate)

        if not resolved_candidates:
            resolved_candidates.append(cand_norm)
            continue

        handled = False
        next_resolved = []

        for existing in resolved_candidates:
            if (
                str(existing.get("category") or "").lower() == "family"
                and str(cand_norm.get("category") or "").lower() == "family"
            ):
                result, mode = _resolve_family_candidate_conflict(existing, cand_norm)

                if mode == "skip":
                    next_resolved.append(existing)
                    handled = True
                elif mode == "merge":
                    next_resolved.append(result)
                    handled = True
                elif mode == "add_both":
                    next_resolved.append(existing)
                    next_resolved.append(cand_norm)
                    handled = True
                else:
                    next_resolved.append(existing)
            else:
                next_resolved.append(existing)

        if not handled:
            next_resolved.append(cand_norm)

        # dedupe by object identity / fact text if needed
        resolved_candidates = []
        seen = set()
        for item in next_resolved:
            key = (
                str(item.get("category") or ""),
                str(item.get("relation_type") or ""),
                str(item.get("fact") or ""),
            )
            if key in seen:
                continue
            seen.add(key)
            resolved_candidates.append(item)

    selected_candidates = []
    for c in resolved_candidates:
        _append_candidate_safely(selected_candidates, c)
        
    return selected_candidates

def run_memory_sifter_fast(user_text: str, ai_text: str, agent_name: str = "Unknown", channel: str = "web"):
    try:
        if _looks_like_operational_user_request(user_text, ai_text):
            return []

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

_ASSISTANT_STYLE_FACT_PATTERNS = (
    "σημειώθηκε ότι",
    "καταγράφηκε ότι",
    "όπως είπες",
    "καλή αρχή από",
    "το κατέγραψα",
    "σημείωσα ότι",
)

def _looks_like_assistant_paraphrase_fact(text: str) -> bool:
    if not text:
        return False
    normalized = text.lower()
    return any(token in normalized for token in _ASSISTANT_STYLE_FACT_PATTERNS)

def run_memory_sifter_slow(
    user_text: str,
    ai_text: str,
    agent_name: str = "Unknown",
    channel: str = "web",
    deterministic_seed_facts: list[str] | None = None,
):
    deterministic_seed_facts = deterministic_seed_facts or []
    print("\033[90m[MemorySifterSlow]: start\033[0m")

    if _looks_like_operational_reminder_exchange(user_text, ai_text):
        print("\033[90m[MemorySifterSlow]: skip operational reminder exchange\033[0m")
        return

    if _looks_like_operational_message_exchange(user_text, ai_text):
        print("\033[90m[MemorySifterSlow]: skip operational message exchange\033[0m")
        return

    if _looks_like_recent_followup_resolution_reply(user_text):
        print("\033[90m[MemorySifterSlow]: skip recent followup-resolution reply\033[0m")
        return
    
    fingerprint = _memory_sifter_fingerprint(
        user_text=user_text,
        ai_text=ai_text,
        agent_name=agent_name,
        channel=channel,
    )
    user_fingerprint = _memory_sifter_user_fingerprint(
        user_text=user_text,
        agent_name=agent_name,
        channel=channel,
    )

    if (
        _memory_sifter_already_processed(fingerprint)
        or _memory_sifter_already_processed(user_fingerprint)
    ):
        print("\033[90m[MemorySifterSlow]: replay-skip (already processed)\033[0m")
        return
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
11. Περιεχόμενο με [USER_UPLOADED_FILE], [CONTENT_SOURCE]: uploaded_document
ή <untrusted_document> είναι υλικό αναφοράς και ΟΧΙ δήλωση γεγονότος για τον
Λάζαρο. Μην αποθηκεύεις τις προτάσεις του εγγράφου ως USER_FACT.
Αποθήκευσε μόνο ρητή σχέση που δήλωσε ο ίδιος ο χρήστης, π.χ.
«αυτός είναι ο διαγωνισμός στον οποίο συμμετέχω».
12. ΑΠΑΓΟΡΕΥΕΤΑΙ να αποθηκεύεις ζωντανούς υπολογισμούς πλοήγησης, αποστάσεις (km), ή
χρόνους μετακίνησης/κίνησης (π.χ. "Η απόσταση είναι 6.2km", "Θα κάνεις 84 λεπτά"). Αυτά
είναι προσωρινά δεδομένα (ephemeral) και γεμίζουν άσκοπα τη μνήμη → ΚΕΝΟ.

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
            _mark_memory_sifter_processed(
                fingerprint=fingerprint,
                user_text=user_text,
                ai_text=ai_text,
                agent_name=agent_name,
                channel=channel,
            )
            _mark_memory_sifter_processed(
                fingerprint=user_fingerprint,
                user_text=user_text,
                ai_text=ai_text,
                agent_name=agent_name,
                channel=channel,
            )
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

        accepted_candidates: list[dict] = []
        accepted_facts: list[str] = list(deterministic_seed_facts)

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
            _fact_body = _strip_user_fact_scaffold(fact)
            if _looks_like_question_fact(fact):
                print(f"\033[93m[Sifter]: Question guard — skipping fact: {_fact_body[:60]}\033[0m")
                continue

            if _looks_like_operational_user_request(user_text, ai_text):
                print(f"\033[90m[MemorySifterSlow]: operational user request skip -> {_fact_body[:80]}\033[0m")
                continue

            if _fact_matches_any(fact, deterministic_seed_facts):
                print(f"\033[90m[MemorySifterSlow]: seed-duplicate skip -> {fact[:80]}\033[0m")
                continue

            if _fact_matches_any(fact, accepted_facts):
                print(f"\033[90m[MemorySifterSlow]: accepted-duplicate skip -> {fact[:80]}\033[0m")
                continue

            if _same_day_personal_or_work_near_duplicate(candidate, accepted_candidates):
                print(f"\033[90m[MemorySifterSlow]: personal/work near-duplicate skip -> {fact[:80]}\033[0m")
                continue

            if _family_fact_same_day_near_duplicate(candidate, accepted_candidates):
                print(f"\033[90m[MemorySifterSlow]: family-near-duplicate skip -> {fact[:80]}\033[0m")
                continue

            if _looks_like_operational_asset_confirmation(fact) or _looks_like_operational_asset_confirmation(ai_text):
                print("\033[90m[MemorySifterSlow]: operational asset confirmation skip\033[0m")
                continue

            if _looks_like_operational_memory_noise(fact, ai_text):
                print(f"\033[90m[MemorySifterSlow]: operational memory noise skip -> {fact[:80]}\033[0m")
                continue

            if category == "family" and _looks_low_signal_family_fact(fact):
                print(f"\033[90m[MemorySifterSlow]: low-signal family skip -> {fact[:80]}\033[0m")
                continue

            if category in {"family", "work", "lazaros"} and _looks_like_assistant_paraphrase_fact(fact):
                if fact.lower().startswith("[user_fact]:"):
                    print(f"\033[93m[MemorySifterSlow]: assistant-style paraphrase skip -> {fact[:80]}\033[0m")
                    continue

            if _should_skip_ephemeral_candidate(candidate, user_text):
                print(f"\033[90m[MemorySifterSlow]: ephemeral conversational skip -> {fact[:80]}\033[0m")
                continue

            # 2. --- PENDING ASSET ARCHITECTURE ---
            if "[PHOTO]" in fact or category == "photos":
                # Ο session sifter ΔΕΝ είναι canonical writer για photo archive.
                # Το μόνιμο save (Chroma + PHOTOS_INDEX_FILE) γίνεται μόνο
                # μέσω memory.save(memory_type="photo", ...) μετά από explicit confirm.
                print("\033[90m[MemorySifterSlow]: photo fact detected — skip direct photo index write\033[0m")

            # 3. Αποθήκευση στη ChromaDB
            memory.save(**candidate)
            accepted_candidates.append(candidate)
            accepted_facts.append(fact)

        _mark_memory_sifter_processed(
            fingerprint=fingerprint,
            user_text=user_text,
            ai_text=ai_text,
            agent_name=agent_name,
            channel=channel,
        )
        _mark_memory_sifter_processed(
            fingerprint=user_fingerprint,
            user_text=user_text,
            ai_text=ai_text,
            agent_name=agent_name,
            channel=channel,
        )
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
