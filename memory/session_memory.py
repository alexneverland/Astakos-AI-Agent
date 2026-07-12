# ================================================================
# Project: Astakos AI Agent 🦞
# Developer: Lazaros (Piston-7)
# Description: Modular LLM-agnostic multi-agent framework
# Copyright (c) 2026 - All Rights Reserved
# ================================================================

import os
import json
from core.i18n import t, load_prompt
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
import config
from config import PHOTOS_INDEX_FILE, PHOTOS_DIR, STATE_DB
from memory.conversation_history import (
    append_exchange,
    load_unsummarized_exchanges,
    mark_exchanges_summarized,
)
# ════════════════════════════════════════════════════════════════
# SESSION SUMMARY — "Partner Log"
# ════════════════════════════════════════════════════════════════

SESSION_LOGS: list = []  # Unified log — all channels together
AUTO_SESSION_SUMMARY_EXCHANGE_THRESHOLD = 20
_auto_summary_lock = threading.Lock()


def log_exchange(user_text, ai_text, agent: str, channel: str = "web"):
    """Adds a question-answer pair to the session log (per channel)."""
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
    """Loads the hint from the last session."""
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
            out += t("memory.hint_prefix", date_str=date_str, hint=hint)
        if pending:
            out += t("memory.pending_prefix") + "\n".join(f"- {p}" for p in pending)
        return out.strip()
    except Exception as e:
        print(f"Error loading last session hint: {e}")
        return ""
    finally:
        if conn:
            conn.close()


is_summarizing = False  # Must be defined outside the function


def _normalize_text(value: str) -> str:
    text = unicodedata.normalize("NFD", str(value or "").lower())
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    return " ".join(text.split())


def _strip_leading_ack_prefix(text: str) -> str:
    normalized = _normalize_text(text)
    prefixes = (
        t("prompts.ext_str_764"),
        t("prompts.ext_str_564"),
        t("prompts.ext_str_813"),
        "ok ",
        t("prompts.ext_str_475"),
        t("prompts.ext_str_493"),
        t("prompts.ext_str_388"),
        t("prompts.ext_str_413"),
        t("prompts.ext_str_838"),
        t("prompts.ext_str_542"),
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
    body = re.sub(t("prompts.ext_s_20_d_2_d_2_d_2_s"), "", body, flags=re.IGNORECASE).strip()
    return body


def _looks_like_question_fact(text: str) -> bool:
    body = _strip_user_fact_scaffold(text)
    normalized = _strip_leading_ack_prefix(body)
    question_starters = (
        t("prompts.ext_str_789"),
        t("prompts.ext_str_761"),
        t("prompts.ext_str_753"),
        t("prompts.ext_str_502"),
        t("prompts.ext_str_506"),
        t("prompts.ext_str_710"),
        t("prompts.ext_str_695"),
        t("prompts.ext_str_548"),
        t("prompts.ext_str_570"),
        t("prompts.ext_str_631"),
        t("prompts.ext_str_622"),
        t("prompts.ext_str_665"),
        t("prompts.ext_str_669"),
        t("prompts.ext_str_587"),
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
        t("prompts.ext_str_416"),
        t("prompts.ext_str_705"),
        t("prompts.ext_str_765"),
        t("prompts.ext_str_494"),
        t("prompts.ext_str_581"),
        t("prompts.ext_str_509"),
        t("prompts.ext_str_758"),
        t("prompts.ext_str_525"),
        t("prompts.ext_str_770"),
        t("prompts.ext_str_407"),
        t("prompts.ext_str_580"),
        t("prompts.ext_str_150"),
        t("prompts.ext_str_99"),
        t("prompts.ext_str_114"),
        t("prompts.ext_str_161"),
    )
    tool_targets = (
        "mail",
        "email",
        "thread",
        t("prompts.ext_str_305"),
        t("prompts.ext_str_482"),
        t("prompts.ext_str_728"),
        "photo",
        "site",
        "link",
        "url",
        t("prompts.ext_str_609"),
        "file",
        "pdf",
        "trip.com",
    )

    if any(normalized.startswith(prefix) for prefix in imperative_starts) and any(token in normalized for token in tool_targets):
        return True

    if t("prompts.ext_plan_4") in ai_normalized and any(token in normalized for token in tool_targets):
        return True

    return False

def _looks_like_operational_asset_confirmation(text: str) -> bool:
    txt = (text or "").strip().lower()

    markers = (
        t("prompts.ext_str_21"),
        t("prompts.ext_str_19"),
        t("prompts.ext_str_41"),
        t("prompts.ext_str_44"),
        t("prompts.ext_str_39"),
        t("prompts.ext_str_36"),
        t("prompts.ext_str_106"),
        t("prompts.ext_str_119"),
        t("prompts.ext_str_143"),
        t("prompts.ext_str_139"),
        t("prompts.ext_str_134"),
        t("prompts.ext_str_135"),
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
        t("prompts.ext_str_107"),
        "action approval required",
        t("prompts.ext_execute_local_pipeline"),
        t("prompts.ext_str_304"),
        t("prompts.ext_str_101"),
        t("prompts.ext_draft_4"),
        t("prompts.ext_draft"),
        t("prompts.ext_draft_1"),
        t("prompts.ext_str_7"),
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
    t("prompts.ext_str_730"), t("prompts.ext_str_772"), t("prompts.ext_str_804"), t("prompts.ext_str_724"), t("prompts.ext_str_685"), t("prompts.ext_str_791"), t("prompts.ext_str_617"), t("prompts.ext_str_730"),
    t("prompts.ext_str_776"), t("prompts.ext_str_806"), t("prompts.ext_str_800"), t("prompts.ext_str_827"), t("prompts.ext_str_835"), t("prompts.ext_str_844"), t("prompts.ext_str_841"), t("prompts.ext_str_786"), t("prompts.ext_str_807"), t("prompts.ext_str_809"),
    t("prompts.ext_str_801"), t("prompts.ext_str_729"), t("prompts.ext_str_788"), t("prompts.ext_str_828"), t("prompts.ext_str_729"), t("prompts.ext_str_735"), t("prompts.ext_str_677"), t("prompts.ext_str_808"), t("prompts.ext_str_815"),
    t("prompts.ext_str_225"), t("prompts.ext_str_227"), t("prompts.ext_str_716"), t("prompts.ext_str_718"), t("prompts.ext_str_356"), t("prompts.ext_str_402"),
    t("prompts.ext_str_714"), t("prompts.ext_str_683"), t("prompts.ext_str_712"), t("prompts.ext_str_755"), t("prompts.ext_str_265"), t("prompts.ext_str_248"), t("prompts.ext_str_520"),
    t("prompts.ext_str_513"), t("prompts.ext_str_294"), t("prompts.ext_str_301"), t("prompts.ext_str_641"), t("prompts.ext_str_739"), t("prompts.ext_str_722"), t("prompts.ext_str_741"),
    t("prompts.ext_str_540"), t("prompts.ext_str_468"), t("prompts.ext_str_355"), t("prompts.ext_str_386"), t("prompts.ext_str_370"), t("prompts.ext_str_400"),
}


def _extract_food_subject_tokens(text: str) -> list[str]:
    cleaned_text = _strip_user_fact_scaffold(text)
    if not _looks_like_food_context(cleaned_text):
        return []

    compact = " ".join(clean_message(cleaned_text).lower().split())
    tokens = re.findall(r"\w{4,}", compact, flags=re.UNICODE)
    out: list[str] = []
    for token in tokens:
        if token in _LOW_SIGNAL_ENTITY_TOKENS:
            continue
        if token.endswith((t("prompts.ext_str_769"), t("prompts.ext_str_732"), t("prompts.ext_str_773"), t("prompts.ext_str_810"), t("prompts.ext_str_721"), t("prompts.ext_str_752"), t("prompts.ext_str_837"), t("prompts.ext_str_594"))):
            continue
        if token.endswith((t("prompts.ext_str_586"), t("prompts.ext_str_746"), t("prompts.ext_str_709"), t("prompts.ext_str_734"), t("prompts.ext_str_699"), t("prompts.ext_str_742"), t("prompts.ext_str_678"), t("prompts.ext_str_817"), t("prompts.ext_str_794"))):
            continue
        out.append(token)
    return _dedupe_preserve_order(out[:6])


def _extract_entities_from_text(text: str) -> list[str]:
    cleaned_text = _strip_user_fact_scaffold(text)
    compact = " ".join(clean_message(cleaned_text).split())
    if not compact:
        return []

    found = []
    for match in re.finditer(t("prompts.ext_b_a_z_a_za_z_s_a_z_a_za_z"), compact):
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
        t("prompts.ext_str_662"), t("prompts.ext_str_645"), t("prompts.ext_str_830"), t("prompts.ext_str_395"), t("prompts.ext_str_687"), t("prompts.ext_str_628"),
        t("prompts.ext_str_593"), t("prompts.ext_str_614"), t("prompts.ext_str_440"), t("prompts.ext_str_825"), t("prompts.ext_str_610"), t("prompts.ext_str_605"),
        t("prompts.ext_str_601"), t("prompts.ext_str_686"), t("prompts.ext_str_675"), t("prompts.ext_str_723"), t("prompts.ext_str_422"), t("prompts.ext_str_814"),
    )
    prep_markers = (
        t("prompts.ext_str_647"), t("prompts.ext_str_555"), t("prompts.ext_str_774"), t("prompts.ext_str_441"), t("prompts.ext_str_485"), t("prompts.ext_str_307"),
        t("prompts.ext_str_682"), t("prompts.ext_str_707"), t("prompts.ext_str_314"), t("prompts.ext_str_763"), t("prompts.ext_str_642"), t("prompts.ext_str_598"),
    )
    meal_context_markers = (
        t("prompts.ext_str_549"), t("prompts.ext_str_362"), t("prompts.ext_str_449"), t("prompts.ext_str_404"), t("prompts.ext_str_545"), t("prompts.ext_str_620"),
        t("prompts.ext_str_767"), t("prompts.ext_str_812"), t("prompts.ext_str_618"),
    )
    purchase_markers = (
        t("prompts.ext_str_507"), t("prompts.ext_str_722"), t("prompts.ext_str_540"), t("prompts.ext_str_714"), t("prompts.ext_str_712"), t("prompts.ext_str_376"),
        t("prompts.ext_str_607"), t("prompts.ext_str_472"),
    )

    if any(marker in normalized for marker in direct_food_markers):
        return True

    has_weight_or_count = bool(
        re.search(t("prompts.ext_b_d_d_s_b"), compact)
        or re.search(t("prompts.ext_b_d_s_b"), compact)
    )
    has_prep = any(marker in normalized for marker in prep_markers)
    has_meal_context = any(marker in normalized for marker in meal_context_markers)
    has_purchase_context = any(marker in normalized for marker in purchase_markers)

    return has_prep and (has_meal_context or has_purchase_context or has_weight_or_count)


def _infer_topic_from_text(text: str, category: str) -> str:
    normalized = _normalize_text(text)
    if any(marker in normalized for marker in (t("prompts.ext_str_535"), t("prompts.ext_str_420"), t("prompts.ext_str_531"), t("prompts.ext_str_661"), t("prompts.ext_str_731"), t("prompts.ext_str_217"), t("prompts.ext_str_338"))):
        return "activity"
    if any(marker in normalized for marker in (t("prompts.ext_str_460"), t("prompts.ext_str_385"), t("prompts.ext_str_302"), t("prompts.ext_str_292"))):
        return "school" if t("prompts.ext_str_460") in normalized or t("prompts.ext_str_385") in normalized or t("prompts.ext_str_302") in normalized else "trip"
    if any(marker in normalized for marker in (t("prompts.ext_str_785"), t("prompts.ext_str_592"), t("prompts.ext_str_583"), t("prompts.ext_str_498"), t("prompts.ext_str_694"), t("prompts.ext_str_523"), t("prompts.ext_str_445"), t("prompts.ext_str_306"))):
        return "health"
    if any(marker in normalized for marker in (t("prompts.ext_str_283"), t("prompts.ext_str_803"), t("prompts.ext_str_700"), t("prompts.ext_str_811"), t("prompts.ext_str_445"), t("prompts.ext_str_373"))):
        return "emotion"
    if any(marker in normalized for marker in (t("prompts.ext_str_489"), t("prompts.ext_str_704"), t("prompts.ext_str_782"), t("prompts.ext_str_701"), t("prompts.ext_str_318"))):
        return "pet"
    if _looks_like_food_context(text):
        return "food"
    if any(marker in normalized for marker in (t("prompts.ext_str_589"), t("prompts.ext_str_547"), t("prompts.ext_str_417"), t("prompts.ext_str_223"), t("prompts.ext_str_612"), t("prompts.ext_str_697"), t("prompts.ext_str_805"))):
        return "home"
    if any(marker in normalized for marker in (t("prompts.ext_str_496"), t("prompts.ext_str_479"), t("prompts.ext_str_341"), t("prompts.ext_str_505"), t("prompts.ext_str_300"))):
        return "work"
    if any(marker in normalized for marker in (t("prompts.ext_str_702"), t("prompts.ext_str_476"), t("prompts.ext_str_668"), t("prompts.ext_str_467"))):
        return "gift"
    if any(marker in normalized for marker in (t("prompts.ext_str_562"), t("prompts.ext_str_499"), t("prompts.ext_str_477"), t("prompts.ext_str_486"), t("prompts.ext_str_623"), t("prompts.ext_str_470"))):
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
        "football": (t("prompts.ext_str_535"),),
        "camp": (t("prompts.ext_str_292"),),
        "park": (t("prompts.ext_str_574"), t("prompts.ext_str_760")),
        "school": (t("prompts.ext_str_460"), t("prompts.ext_str_385")),
        "tutoring": (t("prompts.ext_str_302"),),
        "sleep": (t("prompts.ext_str_785"),),
        "gift_watch": (t("prompts.ext_str_668"),),
        "gift_plant": (t("prompts.ext_str_467"), t("prompts.ext_str_708")),
        "fish_market": (t("prompts.ext_str_688"), t("prompts.ext_str_697"), t("prompts.ext_str_830")),
        "rabbit": (t("prompts.ext_str_489"),),
        "dog": (t("prompts.ext_str_704"),),
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
        "started": (t("prompts.ext_str_474"), t("prompts.ext_str_387"), t("prompts.ext_str_597")),
        "stopped": (t("prompts.ext_str_501"), t("prompts.ext_str_667"), t("prompts.ext_str_169")),
        "paused": (t("prompts.ext_str_652"), t("prompts.ext_str_599"), t("prompts.ext_str_162")),
        "resumed": (t("prompts.ext_str_532"), t("prompts.ext_str_434"), t("prompts.ext_str_435")),
        "away": (t("prompts.ext_str_676"), t("prompts.ext_str_154"), t("prompts.ext_str_127"), t("prompts.ext_str_292"), t("prompts.ext_str_562"), t("prompts.ext_str_477")),
        "returned": (t("prompts.ext_str_623"), t("prompts.ext_str_470"), t("prompts.ext_str_211"), t("prompts.ext_str_159")),
        "scheduled": (t("prompts.ext_str_368"), t("prompts.ext_str_389"), t("prompts.ext_str_246"), t("prompts.ext_str_176")),
        "cancelled": (t("prompts.ext_str_619"), t("prompts.ext_str_175")),
        "confirmed": (t("prompts.ext_str_287"), t("prompts.ext_str_833"), t("prompts.ext_str_526")),
        "tired": (t("prompts.ext_str_523"),),
        "better": (t("prompts.ext_str_367"), t("prompts.ext_str_465"), t("prompts.ext_str_445")),
        "sick": (t("prompts.ext_str_498"), t("prompts.ext_str_592"), t("prompts.ext_str_694")),
        "emotional": (t("prompts.ext_str_283"), t("prompts.ext_str_700"), t("prompts.ext_str_811"), t("prompts.ext_str_373")),
        "completed": (t("prompts.ext_str_346"), t("prompts.ext_str_432"), t("prompts.ext_str_558")),
        "ongoing": (t("prompts.ext_str_434"), t("prompts.ext_str_663"), t("prompts.ext_str_409")),
        "seasonal_break": (t("prompts.ext_str_288"), t("prompts.ext_str_293"), t("prompts.ext_str_226"), t("prompts.ext_str_105")),
    }
    for state, markers in rules.items():
        if any(marker in normalized for marker in markers):
            states.append(state)
    return _dedupe_preserve_order([state for state in states if state in _STATE_MARKER_CHOICES])


def _infer_time_scope_from_text(text: str, *, now: datetime | None = None) -> str:
    normalized = _normalize_text(text)
    ts = now or datetime.now()

    range_match = re.search(t("prompts.ext_b_20_d_2_d_2_d_2_s_to_s_20_d_2"), text)
    if range_match:
        return f"{range_match.group(1)}_to_{range_match.group(2)}"

    exact_match = re.search(r"\b20\d{2}-\d{2}-\d{2}\b", text)
    if exact_match:
        return exact_match.group(0)

    if t("prompts.ext_str_293") in normalized and (t("prompts.ext_str_288") in normalized or t("prompts.ext_str_666") in normalized or t("prompts.ext_str_636") in normalized):
        return f"{ts.strftime('%Y-%m-%d')}_to_{ts.year}-09-01"

    if any(marker in normalized for marker in (t("prompts.ext_str_666"), t("prompts.ext_str_636"), t("prompts.ext_str_819"), t("prompts.ext_str_780"), t("prompts.ext_str_588"), t("prompts.ext_str_655"), t("prompts.ext_str_309"), t("prompts.ext_str_279"))):
        return "ongoing"

    return ts.strftime('%Y-%m-%d')


def _infer_relation_type_from_text(text: str, state_markers: list[str]) -> str:
    normalized = _normalize_text(text)
    if any(marker in normalized for marker in (t("prompts.ext_str_638"), t("prompts.ext_str_286"), t("prompts.ext_str_543"), "update", "correction")):
        return "correction"
    if any(state in state_markers for state in ("away", "returned", "tired", "better", "sick", "seasonal_break")):
        return "state_update"
    if any(state in state_markers for state in ("started", "stopped", "paused", "resumed", "completed")):
        return "follow_up"
    if any(marker in normalized for marker in (t("prompts.ext_str_471"), t("prompts.ext_str_749"), t("prompts.ext_str_762"), t("prompts.ext_str_654"), t("prompts.ext_str_344"))):
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

    family_markers = (t("prompts.ext_str_323"), t("prompts.ext_str_334"), t("prompts.ext_str_561"), t("prompts.ext_str_604"), t("prompts.ext_str_643"), t("prompts.ext_str_648"), t("prompts.ext_str_546"), t("prompts.ext_str_528"))
    personal_markers = (
        t("prompts.ext_str_778"),
        t("prompts.ext_str_771"),
        t("prompts.ext_str_615"),
        t("prompts.ext_str_571"),
        t("prompts.ext_str_822"),
        t("prompts.ext_str_352"),
        t("prompts.ext_str_342"),
        t("prompts.ext_str_218"),
        t("prompts.ext_str_228"),
        t("prompts.ext_str_553"),
        t("prompts.ext_str_557"),
        t("prompts.ext_str_748"),
        t("prompts.ext_str_750"),
    )
    event_markers = (
        t("prompts.ext_str_464"),
        t("prompts.ext_str_535"),
        t("prompts.ext_str_720"),
        t("prompts.ext_str_696"),
        t("prompts.ext_str_510"),
        t("prompts.ext_str_514"),
        t("prompts.ext_str_456"),
        t("prompts.ext_str_497"),
        t("prompts.ext_str_634"),
        t("prompts.ext_str_574"),
        t("prompts.ext_str_616"),
        t("prompts.ext_str_569"),
        t("prompts.ext_str_406"),
        t("prompts.ext_str_371"),
        t("prompts.ext_str_352"),
        t("prompts.ext_str_342"),
        t("prompts.ext_str_218"),
        t("prompts.ext_str_228"),
        t("prompts.ext_str_539"),
        t("prompts.ext_str_483"),
        t("prompts.ext_str_553"),
        t("prompts.ext_str_557"),
        t("prompts.ext_str_748"),
        t("prompts.ext_str_750"),
        t("prompts.ext_str_185"),
        t("prompts.ext_str_189"),
        t("prompts.ext_str_429"),
        t("prompts.ext_str_372"),
    )
    statement_markers = (
        t("prompts.ext_str_433"),
        t("prompts.ext_str_377"),
        t("prompts.ext_str_459"),
        t("prompts.ext_str_486"),
        t("prompts.ext_str_743"),
        t("prompts.ext_str_744"),
        t("prompts.ext_str_736"),
        t("prompts.ext_str_684"),
        t("prompts.ext_str_739"),
        t("prompts.ext_str_768"),
        t("prompts.ext_str_556"),
        t("prompts.ext_str_667"),
        t("prompts.ext_str_418"),
        t("prompts.ext_str_378"),
        t("prompts.ext_str_337"),
        t("prompts.ext_str_340"),
        t("prompts.ext_str_715"),
        t("prompts.ext_str_691"),
        t("prompts.ext_str_271"),
        t("prompts.ext_str_251"),
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
    fact = t("memory.session_memory.user_fact", date=ts.strftime('%Y-%m-%d'), text=source_text)
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
        t("prompts.ext_str_789"),
        t("prompts.ext_str_753"),
        t("prompts.ext_str_761"),
        t("prompts.ext_str_506"),
        t("prompts.ext_str_502"),
        t("prompts.ext_str_695"),
        t("prompts.ext_str_710"),
        t("prompts.ext_str_548"),
        t("prompts.ext_str_570"),
        t("prompts.ext_str_631"),
        t("prompts.ext_str_665"),
        t("prompts.ext_str_622"),
        t("prompts.ext_str_587"),
        t("prompts.ext_str_669"),
    )
    if lowered_source.startswith(question_starters):
        return None

    family_markers = (
        t("prompts.ext_str_334"),
        t("prompts.ext_str_604"),
        t("prompts.ext_str_648"),
        t("prompts.ext_str_528"),
        t("prompts.ext_str_582"),
        t("prompts.ext_str_673"),
        t("prompts.ext_str_693"),
        t("prompts.ext_str_657"),
        t("prompts.ext_str_766"),
        t("prompts.ext_str_343"),
    )
    absence_markers = (
        t("prompts.ext_str_292"),
        t("prompts.ext_str_676"),
        t("prompts.ext_str_127"),
        t("prompts.ext_str_144"),
        t("prompts.ext_str_562"),
        t("prompts.ext_str_499"),
        t("prompts.ext_str_477"),
        t("prompts.ext_str_431"),
        t("prompts.ext_str_272"),
        t("prompts.ext_str_236"),
        t("prompts.ext_str_208"),
        t("prompts.ext_str_167"),
        t("prompts.ext_str_158"),
        t("prompts.ext_str_153"),
    )
    window_markers = (
        t("prompts.ext_str_666"),
        t("prompts.ext_str_636"),
        t("prompts.ext_str_470"),
        t("prompts.ext_str_733"),
        t("prompts.ext_str_560"),
        t("prompts.ext_str_436"),
        t("prompts.ext_str_588"),
        t("prompts.ext_str_309"),
        t("prompts.ext_2"),
        t("prompts.ext_3"),
        t("prompts.ext_4"),
        t("prompts.ext_5"),
        t("prompts.ext_6"),
        t("prompts.ext_7_1"),
        t("prompts.ext_str_103"),
        t("prompts.ext_str_102"),
        t("prompts.ext_str_235"),
        t("prompts.ext_str_232"),
        t("prompts.ext_str_181"),
        t("prompts.ext_str_184"),
        t("prompts.ext_str_357"),
        t("prompts.ext_str_554"),
        t("prompts.ext_str_396"),
        t("prompts.ext_str_457"),
        t("prompts.ext_str_258"),
        t("prompts.ext_str_383"),
        t("prompts.ext_str_415"),
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
    fact = t("memory.session_memory.user_fact", date=ts.strftime('%Y-%m-%d'), text=source_text)
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
    if any(marker in clean for marker in (t("prompts.ext_str_604"), t("prompts.ext_str_334"), t("prompts.ext_str_552"), t("prompts.ext_str_648"), t("prompts.ext_str_657"), t("prompts.ext_str_315"), t("prompts.ext_str_702"))):
        return "family"
    if any(marker in clean for marker in ("mastroapp", "praxis", "astakos", t("prompts.ext_str_533"), "github", "project", "repo")):
        return "projects"
    if any(marker in clean for marker in (t("prompts.ext_str_589"), t("prompts.ext_str_401"), t("prompts.ext_str_452"), t("prompts.ext_str_223"), t("prompts.ext_str_495"), t("prompts.ext_str_668"), t("prompts.ext_str_527"))):
        return "home"
    if any(marker in clean for marker in (t("prompts.ext_str_379"), t("prompts.ext_str_423"), "bug", "tool", "prompt", "lesson", t("prompts.ext_str_458"))):
        return "lesson"
    return "lazaros"


def _extract_explicit_memory_payload(text: str) -> str | None:
    """Extract the actual payload from explicit commands like 'Keep in memory that ...'."""
    compact = " ".join(clean_message(text).split())
    if not compact:
        return None

    patterns = (
        t("prompts.ext_s_s_s_s"),
        t("prompts.ext_s_s"),
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
        t("prompts.ext_str_46"),
        t("prompts.ext_str_61"),
        t("prompts.ext_str_156"),
        t("prompts.ext_str_216"),
        t("prompts.ext_str_187"),
        t("prompts.ext_str_320"),
        t("prompts.ext_str_192"),
        t("prompts.ext_str_77"),
        t("prompts.ext_str_82"),
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

    if not any(marker in combined for marker in (t("prompts.ext_str_327"), t("prompts.ext_str_639"), t("prompts.ext_str_536"), t("prompts.ext_str_463"), t("prompts.ext_str_603"))):
        return None
    if any(marker in combined for marker in ("draft", t("prompts.ext_str_264"), t("prompts.ext_str_257"), t("prompts.ext_str_168"), t("prompts.ext_str_179"))):
        return None

    source_text = " ".join(safe_user.split())
    confirmation_text = " ".join(safe_ai.split())
    if not source_text and not confirmation_text:
        return None
    if len(source_text) < 8 and len(confirmation_text) < 20:
        return None

    # Explicit confirmation from the AI is required — and whether the user gave explicit
    # "Remember that X", we keep X, not meta-text like
    # "the user requested to save".of_thought
    detail = None
    explicit_payload = _extract_explicit_memory_payload(source_text)
    if confirmation_text:
        memory_match = re.search(
            t("prompts.ext_n_0_220"),
            confirmation_text,
            flags=re.IGNORECASE,
        )
        if memory_match:
            detail = memory_match.group(0).strip()
    if not detail:
        # AI did not explicitly confirm → bypass, the LLM sifter will decide
        return None
    if explicit_payload and _looks_like_generic_memory_confirmation(detail):
        detail = explicit_payload
    if len(detail) > 300:
        detail = detail[:297].rstrip() + "..."

    category = _infer_memory_category(f"{safe_user} {safe_ai}")

    ts = now or datetime.now()
    fact = t("memory.session_memory.user_fact", date=ts.strftime('%Y-%m-%d'), text=detail)
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
    """Archives the session (per channel) with protection against duplicate entries."""
    global is_summarizing, SESSION_LOGS

    try:
        persistent_log = load_unsummarized_exchanges(limit=200)
    except Exception as e:
        print(f"\033[93m[SessionLog]: Shared exchange read failed, using memory log: {e}\033[0m")
        persistent_log = []
    using_persistent_log = bool(persistent_log)
    current_log = persistent_log if using_persistent_log else list(SESSION_LOGS)
    # 1. Shield: If it is already running or if there are no messages, exit immediately
    if is_summarizing or not current_log:
        return

    try:
        is_summarizing = True
        print(f"\n\033[94m[Session/{channel}]: Starting archiving...\033[0m")
        
        # 2. We empty it IMMEDIATELY so that no other worker grabs it again
        current_batch = list(current_log)
        SESSION_LOGS.clear()
        channels = sorted({e.get("channel", channel) for e in current_batch})
        summary_channel = channels[0] if len(channels) == 1 else "mixed"

        dialogue_text = "\n".join([
            t("memory.session_memory.conversation_log", time=e['time'], channel=e.get('channel', channel), agent=e['agent'], user=e['user'], ai=e['ai'])
            for e in current_batch
        ])

        # 3. The prompt with a strict date format (to match your old logs)
        summary_prompt = load_prompt("session_summary.md").replace(
            "{language}", config.RESPONSE_LANGUAGE
        ).replace(
            "{user_name}", config.USER_NAME
        ).replace(
            "{date}", datetime.now().strftime('%Y-%m-%d %H:%M')
        ).replace(
            "{channel}", summary_channel
        ).replace(
            "{dialogue_text}", dialogue_text
        )
        response = safe_gemini_call(summary_prompt)
        raw = re.sub(r"```json|```", "", response.text.strip()).strip()

        try:
            summary = json.loads(raw)
        except json.JSONDecodeError:
            # If it fails, we put the messages back so we don't lose them
            if not using_persistent_log:
                SESSION_LOGS[:0] = current_batch  # Reset to start
                print("\033[91m[Session]: Invalid format. Messages returned to log.\033[0m")
            else:
                print("\033[91m[Session]: Invalid format. Shared exchanges left unsummarized.\033[0m")
            return

        # 4. Enrichment of the text for the Vector DB
        session_text = (
            f"[SESSION {summary.get('date', '')}] {summary.get('summary', '')} " +
            t("memory.session_memory.pending_tasks", pending=', '.join(summary.get('pending', [])) if summary.get('pending') else t("memory.session_memory.none")) +
            f"Hint: {summary.get('next_session_hint', '')}"
        )

        # 5. Save (Here the MemoryManager will also perform the overwrite if needed)
        memory.save(memory_type="session", summary=summary, session_text=session_text)
        if using_persistent_log:
            mark_exchanges_summarized([e["id"] for e in current_batch])
        print(f"\033[92m[Session]: ✅ Archived successfully! Mood: {summary.get('mood', '?')}\033[0m")
        bus.emit("session_ended", channel=summary_channel, mood=summary.get("mood", "unknown"), summary=summary.get("summary", ""))

    except Exception as e:
        # Recovery in case of error
        if not using_persistent_log:
            SESSION_LOGS[:0] = current_batch  # Reset to the beginning
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
        t("prompts.ext_str_846"), t("prompts.ext_str_847"), t("prompts.ext_str_839"), t("prompts.ext_str_831"), t("prompts.ext_str_843"), t("prompts.ext_str_809"), t("prompts.ext_str_801"), t("prompts.ext_str_795"),
        t("prompts.ext_str_776"), t("prompts.ext_str_841"), t("prompts.ext_str_824"), t("prompts.ext_str_772"), t("prompts.ext_str_804"), t("prompts.ext_str_724"), t("prompts.ext_str_685"),
        t("prompts.ext_str_835"), t("prompts.ext_str_840"), t("prompts.ext_str_800"), t("prompts.ext_str_827"), t("prompts.ext_str_806"), t("prompts.ext_str_797"), t("prompts.ext_str_818"),
        t("prompts.ext_str_796"), t("prompts.ext_str_777"), t("prompts.ext_str_783"), t("prompts.ext_str_823"), t("prompts.ext_str_656"), t("prompts.ext_str_703"),
        t("prompts.ext_str_807"), t("prompts.ext_str_786"), t("prompts.ext_str_793"), t("prompts.ext_str_729"), t("prompts.ext_str_788"), t("prompts.ext_str_828"),
        t("prompts.ext_str_679"), t("prompts.ext_str_727"), t("prompts.ext_str_530"), t("prompts.ext_str_524"), t("prompts.ext_str_588"), t("prompts.ext_str_655"),
        t("prompts.ext_str_730"), t("prompts.ext_str_804"), t("prompts.ext_str_772"), t("prompts.ext_str_834"), t("prompts.ext_str_666"), t("prompts.ext_str_636"),
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
# MEMORY SIFTER — "Archivist"
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
        t("prompts.ext_str_764"),
        t("prompts.ext_str_487"),
        t("prompts.ext_str_577"),
        t("prompts.ext_str_813"),
        t("prompts.ext_str_328"),
        t("prompts.ext_str_475"),
    )
    if norm.startswith(low_signal_starts):
        return True

    return False


def _looks_like_ephemeral_conversational_source(text: str) -> bool:
    norm = _normalize_text(_strip_user_fact_scaffold(text))

    if not norm:
        return False

    ack_prefixes = (
        t("prompts.ext_str_764"),
        t("prompts.ext_str_487"),
        t("prompts.ext_str_813"),
        "ok ",
        t("prompts.ext_str_475"),
        t("prompts.ext_str_493"),
        t("prompts.ext_str_626"),
        t("prompts.ext_str_630"),
    )

    immediate_markers = (
        t("prompts.ext_str_353"),
        t("prompts.ext_str_421"),
        t("prompts.ext_5_1"),
        t("prompts.ext_10"),
        t("prompts.ext_15"),
        t("prompts.ext_20"),
        t("prompts.ext_str_740"),
        t("prompts.ext_str_690"),
        t("prompts.ext_str_600"),
        t("prompts.ext_str_584"),
        t("prompts.ext_str_689"),
        t("prompts.ext_str_681"),
        t("prompts.ext_str_295"),
        t("prompts.ext_str_325"),
        t("prompts.ext_str_364"),
        t("prompts.ext_str_412"),
        t("prompts.ext_str_378"),
        t("prompts.ext_str_418"),
        t("prompts.ext_str_340"),
        t("prompts.ext_str_337"),
    )

    durable_markers = (
        t("prompts.ext_str_249"),
        t("prompts.ext_str_255"),
        t("prompts.ext_str_240"),
        t("prompts.ext_str_410"),
        t("prompts.ext_str_438"),
        t("prompts.ext_str_339"),
        t("prompts.ext_str_329"),
        t("prompts.ext_str_474"),
        t("prompts.ext_str_453"),
        t("prompts.ext_str_537"),
        t("prompts.ext_str_473"),
        t("prompts.ext_str_361"),
        t("prompts.ext_str_394"),
        t("prompts.ext_str_507"),
        t("prompts.ext_str_511"),
        t("prompts.ext_str_504"),
        t("prompts.ext_str_481"),
        t("prompts.ext_str_398"),
        t("prompts.ext_str_367"),
        t("prompts.ext_str_523"),
        t("prompts.ext_str_498"),
        t("prompts.ext_str_479"),
        t("prompts.ext_str_442"),
        t("prompts.ext_str_292"),
        t("prompts.ext_str_477"),
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

    # Food/family outcomes of the type "liked it", "was thrilled", etc. should not be lost.
    if topic == "food":
        norm = _normalize_text(source_text)
        if any(marker in norm for marker in (t("prompts.ext_str_249"), t("prompts.ext_str_255"), t("prompts.ext_str_240"), t("prompts.ext_str_439"), t("prompts.ext_str_579"), t("prompts.ext_str_624"))):
            return False

    return _looks_like_ephemeral_conversational_source(source_text)


def _looks_like_operational_reminder_exchange(user_text: str, ai_text: str) -> bool:
    user_norm = _normalize_text(user_text)
    ai_norm = _normalize_text(ai_text)

    if not user_norm or not ai_norm:
        return False

    user_has_reminder_request = (
        (t("prompts.ext_str_790") in user_norm or t("prompts.ext_str_344") in user_norm)
        and bool(re.search(r"\b\d{1,2}:\d{2}\b", user_norm))
    )

    ai_has_reminder_confirmation = (
        t("prompts.ext_str_58") in ai_norm
        or t("prompts.ext_str_17") in ai_norm
    )

    return user_has_reminder_request and ai_has_reminder_confirmation


def _looks_like_operational_message_exchange(user_text: str, ai_text: str) -> bool:
    """Skip short control/system exchanges that should not become user facts."""
    user_norm = _normalize_text(user_text)
    ai_norm = _normalize_text(ai_text)

    if user_norm.startswith("[system]:") or user_norm.startswith("[story_sent]"):
        return True

    short_send = user_norm in {t("prompts.ext_str_522"), t("prompts.ext_str_509"), "send", t("prompts.ext_str_802"), t("prompts.ext_str_833"), "ok"}
    draft_or_error = any(marker in ai_norm for marker in (
        t("prompts.ext_str_56"),
        t("prompts.ext_str_59"),
        "messenger_draft.json",
        t("prompts.ext_messenger"),
        t("prompts.ext_messenger_1"),
    ))

    return short_send and draft_or_error


def _looks_like_recent_followup_resolution_reply(user_text: str, within_seconds: int = 300) -> bool:
    text = _normalize_text(_strip_user_fact_scaffold(user_text))

    if not text:
        return False

    if len(text.split()) > 18:
        return False

    resolution_markers = (
        t("prompts.ext_str_543"),
        t("prompts.ext_str_821"),
        t("prompts.ext_str_779"),
        t("prompts.ext_str_196"),
        t("prompts.ext_str_195"),
        t("prompts.ext_str_298"),
        t("prompts.ext_str_278"),
        t("prompts.ext_str_572"),
        t("prompts.ext_str_551"),
        t("prompts.ext_str_239"),
        t("prompts.ext_str_198"),
        t("prompts.ext_str_738"),
        t("prompts.ext_str_713"),
        t("prompts.ext_str_792"),
        t("prompts.ext_str_787"),
        t("prompts.ext_str_649"),
        t("prompts.ext_str_608"),
        t("prompts.ext_str_254"),
        t("prompts.ext_str_253"),
        t("prompts.ext_str_588"),
        t("prompts.ext_str_655"),
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

        if topic == "outing" and any(marker in text for marker in (t("prompts.ext_str_196"), t("prompts.ext_str_195"), t("prompts.ext_str_298"), t("prompts.ext_str_278"), t("prompts.ext_str_572"), t("prompts.ext_str_551"), t("prompts.ext_str_792"), t("prompts.ext_str_787"))):
            return True

        if topic == "food_purchase" and any(marker in text for marker in (t("prompts.ext_str_313"), t("prompts.ext_str_285"), t("prompts.ext_str_403"), t("prompts.ext_str_369"), t("prompts.ext_str_308"), t("prompts.ext_str_316"))):
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
    t("prompts.ext_str_140"),
    t("prompts.ext_str_123"),
    t("prompts.ext_str_241"),
    t("prompts.ext_str_149"),
    t("prompts.ext_str_174"),
    t("prompts.ext_str_172"),
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
        "lazaros":  t("prompts.ext_str_3"),
        "family":   t("prompts.ext_str_5"),
        "projects": t("prompts.ext_mastroapp_praxiserp_paletes_sh"),
        "home":     t("prompts.ext_piston_7"),
        "lesson":   t("prompts.ext_bugs"),
        "photos":   t("prompts.ext_paths"),
    }

    try:
        # 1. Prompt Preparation for Gemini
        cats_desc = "\n".join([f'  - "{k}": {v}' for k, v in MEMORY_CATS.items()])
        
        # ── Sliding-window context: last exchanges before the current one ──
        # The sifter enters the queue BEFORE the log_exchange (see enqueue order)
        # in api/server.py), so the SESSION_LOGS here does NOT yet contain the
        # current exchange -> no double entry/race condition.
        recent_context_block = ""
        try:
            recent_entries = SESSION_LOGS[-4:]
            if recent_entries:
                ctx_lines = "\n".join(
                    t("memory.session_memory.conversation_log_short", user=e['user'], ai=e['ai'])
                    for e in recent_entries
                )
                recent_context_block = (
                    f"{t('memory.session_memory.context_warning')}\n"
                    f"{ctx_lines}\n"
                )
        except Exception:
            recent_context_block = ""

        sifter_prompt = load_prompt("memory_sifter.md").replace(
            "{language}", config.RESPONSE_LANGUAGE
        ).replace(
            "{user_name}", config.USER_NAME
        ).replace(
            "{cats_desc}", cats_desc
        ).replace(
            "{today_date}", datetime.now().strftime('%Y-%m-%d')
        ).replace(
            "{recent_context_block}", recent_context_block
        ).replace(
            "{timestamp}", datetime.now().strftime('%Y-%m-%d %H:%M')
        ).replace(
            "{channel}", channel
        ).replace(
            "{agent_name}", agent_name
        ).replace(
            "{user_text}", user_text
        ).replace(
            "{ai_text}", ai_text
        )
        response = safe_gemini_call(sifter_prompt)
        raw_text = response.text.strip()
        
        if t("prompts.ext_str_680") in raw_text or not raw_text:
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
            
        # --- [MASTRO-JSON-SHIELD]: Automatic correction for LLM's forgotten commas ---
        try:
            memories = json.loads(raw_clean)
        except json.JSONDecodeError:
            try:
                # We clean trailing commas before closing a list or object
                fixed_raw = re.sub(r',\s*\]', ']', raw_clean)
                fixed_raw = re.sub(r',\s*\}', '}', fixed_raw)
                memories = json.loads(fixed_raw)
                print("\033[93m[Sifter Fixer]: ✅ JSON auto-repaired!\033[0m")
            except:
                print("\033[91m⚠️ [Sifter Error]: LLM generated completely malformed JSON. Skipping write.\033[0m")
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

            # [QUESTION GUARD]: If the fact is a question, skip it
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
                # The session sifter is NOT a canonical writer for the photo archive.
                # Permanent saving (Chroma + PHOTOS_INDEX_FILE) is done only
                # via memory.save(memory_type="photo", ...) after explicit confirm.
                print("\033[90m[MemorySifterSlow]: photo fact detected — skip direct photo index write\033[0m")

            # 3. Save to ChromaDB
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
    """Wrapper — executed via Queue Worker."""
    seed_facts = run_memory_sifter_fast(user_text, ai_text, agent_name, channel)
    run_memory_sifter_slow(user_text, ai_text, agent_name, channel, deterministic_seed_facts=seed_facts)


# ════════════════════════════════════════════════════════════════
# STARTUP STALE CLEANUP
# ════════════════════════════════════════════════════════════════

def startup_stale_cleanup(channel: str = "telegram") -> bool:
    """
    Executed during startup.
    If astakos_working_memory.json has entries from a previous day
    (i.e., /end did not run due to a hard restart), it first runs session summary
    (so that unprocessed exchanges are saved) and then clears the tags.

    Returns True if cleanup was executed, False if it was not needed.
    """
    try:
        from config import WORKING_MEMORY_FILE
        from datetime import date as _date

        if not os.path.exists(WORKING_MEMORY_FILE):
            print("\033[90m[Startup]: Working memory file not found — skipping.\033[0m")
            return False

        # Check if the file has entries
        try:
            with open(WORKING_MEMORY_FILE, "r", encoding="utf-8") as f:
                tags = json.load(f)
        except Exception:
            tags = []

        if not tags:
            print("\033[90m[Startup]: Working memory empty — skipping.\033[0m")
            return False

        # Check if the file was modified before today
        mtime = os.path.getmtime(WORKING_MEMORY_FILE)
        file_date = _date.fromtimestamp(mtime)
        today = _date.today()

        if file_date >= today:
            print(f"\033[90m[Startup]: Working memory is from today ({file_date}) — skipping.\033[0m")
            return False

        print(
            f"\033[93m[Startup]: ⚠️  Found {len(tags)} stale tags from {file_date} "
            f"(hard restart detected). Running session summary before cleanup...\033[0m"
        )

        # 1. Run the session summary first (stores unsummarized exchanges)_
        _run_session_summary(channel=channel)

        # 2. Delete the stale tags
        try:
            with open(WORKING_MEMORY_FILE, "w", encoding="utf-8") as f:
                json.dump([], f, ensure_ascii=False, indent=2)
            print(
                f"\033[92m[Startup]: ✅ Working memory cleared — {len(tags)} stale tags "
                f"from {file_date} processed and removed.\033[0m"
            )
            return True
        except Exception as e:
            print(f"\033[91m[Startup]: ❌ Failed to clear working memory: {e}\033[0m")
            return False

    except Exception as e:
        print(f"\033[91m[Startup Cleanup Error]: {e}\033[0m")
        return False

