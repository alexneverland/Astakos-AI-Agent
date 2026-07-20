
# ================================================================
# Project: Astakos AI Agent 🦞
# Description: Modular LLM-agnostic multi-agent framework
# Copyright (c) 2026 - All Rights Reserved
# ================================================================

"""
clients/telegram_bot.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
The Lobster Telegram Bot.
Receives messages/photos from the user and
responds via the graph (LangGraph pipeline).
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

import os
import sys
import time
import json
import requests
import re
import threading
import queue
from datetime import datetime
from time import perf_counter
from zoneinfo import ZoneInfo

# Bootstrap repo root before any project-local imports when this file runs as a script.
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from langchain_core.messages import HumanMessage, AIMessage

from config import TELEGRAM_TOKEN, TELEGRAM_CHAT_ID, PHOTOS_DIR, PHOTOS_INDEX_FILE, NLP_CONFIG
import config
import core.i18n
from core.i18n import t

def _normalize_gr(text: str) -> str:
    """Removes accents from Greek text for accent-insensitive comparison."""
    import unicodedata
    raw = str(text or "").strip().lower()
    normalized = unicodedata.normalize("NFD", raw)
    return "".join(ch for ch in normalized if not unicodedata.combining(ch))

def _partner_match_terms() -> list[str]:
    return [
        term for term in {
            _normalize_gr(getattr(config, "PARTNER_NAME", "")),
            _normalize_gr(getattr(config, "PARTNER_ALIAS", "")),
            "partner",
            "messenger",
        }
        if term
    ]

def _safe_classify_messenger_intent(text: str, *, has_active_draft: bool):
    """Lazy/fail-soft import so tests that stub `services` don't crash telegram_bot import."""
    try:
        from services.messenger_intent import classify_messenger_intent
    except Exception:
        return None
    try:
        return classify_messenger_intent(text, has_active_draft=has_active_draft)
    except Exception:
        return None


def _safe_active_draft_status():
    try:
        from core.messenger_draft import active_draft_status
    except Exception:
        return False, "unavailable", None
    try:
        return active_draft_status()
    except Exception:
        return False, "error", None


def _safe_clear_draft() -> bool:
    try:
        from core.messenger_draft import clear_draft
    except Exception:
        return False
    try:
        return bool(clear_draft())
    except Exception:
        return False

from services.context_extractor import extract_and_update_context_flags
from memory.event_log import log_event, is_duplicate_notification, is_duplicate_routine
from core.exceptions import SchedulerCrashError, PendingTimeoutError, DBWriteError
from core.brain import llm, safe_llm_invoke
from core.graph import graph
from core.agents import clean_message, filter_messages
from memory.vector_store import memory
from memory.working_memory import update_working_memory, update_capabilities_from_exchange
from memory.session_memory import (
    run_memory_sifter_fast,
    run_memory_sifter_slow,
    log_exchange,
    _run_session_summary,
    startup_stale_cleanup,
    _maybe_trigger_auto_session_summary,
)
from tools.telegram import send_telegram_msg, send_telegram_voice, send_telegram_msg_full
from services.gemini import safe_gemini_call
from services.embeddings import embeddings
from memory.pending_followups import (
    ensure_pending_followups_table,
    maybe_create_followup_from_exchange,
    maybe_resolve_followups_from_user_message,
    looks_like_followup_resolution_update,
    extract_followup_candidate_with_llm,
    create_pending_followup_from_candidate,
    get_recently_resolved_followups,
    candidate_is_distinct_from_recently_resolved,
    get_due_pending_followups,
    mark_followup_sent,
    expire_old_followups,
    has_recent_sent_followup,
    has_recent_sent_followup_for_arc,
    build_followup_arc_key,
    record_followup_outcome,
)
from core.event_bus import bus
# ────────────────────────────────────────────────────────────────
# GLOBALS
# ────────────────────────────────────────────────────────────────
_recent_routine_skip_events = {}

def _should_log_routine_skip(routine_id: int, action: str, reason: str, ttl_seconds: int = 600) -> bool:
    now_ts = time.time()
    key = (routine_id, action, str(reason or "").strip())

    expired = [
        k for k, ts in _recent_routine_skip_events.items()
        if now_ts - ts > ttl_seconds
    ]
    for k in expired:
        _recent_routine_skip_events.pop(k, None)

    last_ts = _recent_routine_skip_events.get(key)
    if last_ts is not None:
        return False

    _recent_routine_skip_events[key] = now_ts
    return True

shutdown_event        = threading.Event()
fast_queue            = queue.Queue()
slow_queue            = queue.Queue()
memory_lock           = threading.Lock()

# Cache: telegram message_id → full text (latest 50 bot messages)
# Used by _handle_message_reaction for exact match
_bot_message_cache: dict[int, str] = {}
_bot_message_cache_lock = threading.Lock()
_BOT_CACHE_MAX = 50

_TS_PREFIX_RE = re.compile(r"^\s*\[\d{1,2}:\d{2}\]\s*")


def _strip_existing_time_prefix(text: str) -> str:
    """Avoid duplicate [HH:MM] prefixes when a model already included one."""
    return _TS_PREFIX_RE.sub("", str(text or ""), count=1).strip()


def _cache_bot_message(message_id: int | None, text: str) -> None:
    if not message_id:
        return
    with _bot_message_cache_lock:
        _bot_message_cache[message_id] = text
        # Keep only the last N
        if len(_bot_message_cache) > _BOT_CACHE_MAX:
            oldest = sorted(_bot_message_cache.keys())[0]
            del _bot_message_cache[oldest]
last_interaction_time = time.time()
# Pending routine confirmations: {routine_id: {"event": ..., "sent_at": ...}}
pending_routine_confirmations = {}
pending_exec_command = None
# Pending reflection confirmations (ask-tier, 50-75% confidence): {reflection_id: {full reflection dict}}
pending_reflection_confirmations = {}
# Pending photo: stores the analysis of a photo that arrived without a caption, to be combined with the next message
pending_photo_lock = threading.Lock()
pending_photo      = None   # {analysis, filename, path, timestamp}
pending_georgian_lock = threading.Lock()
pending_georgian_until = 0.0
PENDING_GEORGIAN_TTL_SECONDS = 120
pending_partner_lock = threading.Lock()
pending_partner_until = 0.0   # ka→el mode (Sophia writes Georgian)
# Voice mode toggle: when True, ALL responses are vocal even if you are typing
voice_mode_enabled = False
# Scheduler reference (set in __main__, used by /status command)
astakos_scheduler = None
# ── Rate Limiting ─────────────────────────────────────────────
QUIET_HOURS          = (0, 8)    # 00:00 → 08:00 without proactive
MAX_PROACTIVE_PER_HOUR = 3       # max proactive messages/hour
PROACTIVE_RECENT_ACTIVITY_GRACE_SECONDS = 15 * 60

_proactive_count = {"hour": -1, "count": 0}
_proactive_lock  = threading.Lock()

def is_quiet_hours() -> bool:
    """True if we are within the quiet window or if it has been overridden by context state."""
    from services.routine_context import resolve_quiet_hours
    return resolve_quiet_hours()

def can_send_proactive() -> bool:
    """Rate-limit: max MAX_PROACTIVE_PER_HOUR proactive messages/hour."""
    with _proactive_lock:
        h = datetime.now().hour
        if _proactive_count["hour"] != h:
            _proactive_count["hour"]  = h
            _proactive_count["count"] = 0
        if _proactive_count["count"] >= MAX_PROACTIVE_PER_HOUR:
            return False
        _proactive_count["count"] += 1
        return True


def _seconds_since_user_activity() -> float:
    """Shared last-user-activity across web/Telegram, with local fallback."""
    try:
        from memory.conversation_history import seconds_since_last_user_activity
        elapsed = seconds_since_last_user_activity()
        if elapsed is not None:
            return elapsed
    except Exception as e:
        print(f"[Proactive]: Shared activity read failed, using local timer: {e}")

    with memory_lock:
        return time.time() - last_interaction_time


def should_skip_proactive_for_recent_activity(
    max_age_seconds: int = PROACTIVE_RECENT_ACTIVITY_GRACE_SECONDS,
) -> bool:
    elapsed = _seconds_since_user_activity()
    if elapsed < max_age_seconds:
        print(f"⏸️ [Proactive]: Recent user activity ({int(elapsed)}s ago) — skipped.")
        log_event("proactive", "skipped", reason="recent_activity", elapsed_s=int(elapsed))
        return True
    return False


def _looks_like_contextual_not_needed_reply(text: str) -> bool:
    normalized = _normalize_gr(text or "")

    strong_not_needed_markers = (
        t("clients.telegram_bot.bot_msg_43adbb"),
        t("clients.telegram_bot.bot_msg_3b5a96"),
        t("clients.telegram_bot.bot_msg_096f99"),
        t("clients.telegram_bot.bot_msg_a54877"),
        t("clients.telegram_bot.bot_msg_5adac4"),
        t("clients.telegram_bot.bot_msg_c4476f"),
        t("clients.telegram_bot.bot_msg_eb512e"),
    )
    if any(m in normalized for m in strong_not_needed_markers):
        return True

    phrase_markers = (
        t("clients.telegram_bot.bot_msg_ce4288"),
        t("clients.telegram_bot.bot_msg_cf3cd8"),
        t("clients.telegram_bot.bot_msg_02921b"),
        t("clients.telegram_bot.bot_msg_864cf3"),
        t("clients.telegram_bot.bot_msg_487948"),
        t("clients.telegram_bot.bot_msg_e385db"),
        t("clients.telegram_bot.bot_msg_df2521"),
        t("clients.telegram_bot.bot_msg_a7161a"),
        t("clients.telegram_bot.bot_msg_f3ebcb"),
        t("clients.telegram_bot.bot_msg_1dc463"),
        t("clients.telegram_bot.bot_msg_db9bf6"),
        t("clients.telegram_bot.bot_msg_d2e073"),
        t("clients.telegram_bot.bot_msg_8a0cd2"),
    )

    signal_count = sum(1 for marker in phrase_markers if marker in normalized)
    partner_name_lower = _normalize_gr(config.PARTNER_NAME)
    partner_prefix = partner_name_lower[:3] if len(partner_name_lower) >= 3 else partner_name_lower
    has_partner_ref = (partner_prefix in normalized) or (config.PARTNER_NAME.lower() in normalized)

    return signal_count >= 2 or (has_partner_ref and signal_count >= 1)

def enqueue_fast_task(func, *args):
    fast_queue.put((func, args))

def enqueue_slow_task(func, *args):
    slow_queue.put((func, args))

def _enqueue_slow_memory_sifter(user_text, ai_text, handling_agent, channel):
    seed_facts = run_memory_sifter_fast(user_text, ai_text, handling_agent, channel)
    enqueue_slow_task(
        run_memory_sifter_slow,
        user_text,
        ai_text,
        handling_agent,
        channel,
        seed_facts,
    )

def _enqueue_followup_pipeline(user_text, ai_text, agent_name, channel):
    resolved_count = maybe_resolve_followups_from_user_message(user_text)
    if resolved_count > 0 and looks_like_followup_resolution_update(user_text):
        candidate = extract_followup_candidate_with_llm(user_text, ai_text, agent_name)
        if not candidate or not candidate.get("should_follow_up"):
            print(f"[FollowUp]: create-skip after resolution update ({resolved_count} resolved)")
            return

        recent_resolved = get_recently_resolved_followups(limit=5, within_seconds=180)
        if not candidate_is_distinct_from_recently_resolved(candidate, recent_resolved):
            print(f"[FollowUp]: create-skip redundant arc after resolution update ({resolved_count} resolved)")
            return

        create_pending_followup_from_candidate(
            candidate=candidate,
            source_channel=channel,
            source_agent=agent_name,
            source_user_text=user_text,
            source_ai_text=ai_text,
        )
        return
    maybe_create_followup_from_exchange(
        user_text=user_text,
        ai_text=ai_text,
        agent_name=agent_name,
        channel=channel,
    )

def _build_followup_state_snapshot() -> dict:
    try:
        from memory.routine_db import get_context_states
    except Exception:
        return {}

    keys = [
        "user_at_work",
        "user_out_of_home",
        "family_at_home",
        "kid1_away_from_home",
        "kid1_away_reason",
        "kid1_with_user",
        "kid1_with_partner",
        "quiet_hours",
        "current_shift",
        "state:kid1:outing",
        "state:kid1:sleep",
    ]
    try:
        return get_context_states(keys)
    except Exception as exc:
        print(f"[FollowUpState]: snapshot failed: {exc}")
        return {}


def _render_followup_state_snapshot(state_snapshot: dict) -> str:
    if not state_snapshot:
        return "No live state available."

    lines = []
    for key, item in state_snapshot.items():
        if not isinstance(item, dict):
            continue
        value = str(item.get("value", "")).strip()
        until_date = str(item.get("until_date", "")).strip()
        if until_date:
            lines.append(f"- {key} = {value} (until {until_date})")
        else:
            lines.append(f"- {key} = {value}")
    return "\n".join(lines) if lines else "No live state available."


def _build_safe_followup_fallback(item: dict, stage: str = "") -> str:
    subject = str(item.get("subject") or "").strip()
    topic = str(item.get("topic") or "").strip().lower()

    if stage == "before_prerequisite":
        if subject:
            return t("clients.telegram_bot.proactive_followup", subject=subject)
        return t("clients.telegram_bot.bot_msg_b8a2cc")

    if stage == "decision_pending":
        if subject:
            return t("clients.telegram_bot.followup_decision_pending", subject=subject)
        return t("clients.telegram_bot.bot_msg_7ffced")

    if stage == "after_likely_completion":
        if subject:
            return t("clients.telegram_bot.followup_after_completion", subject=subject)
        return t("clients.telegram_bot.bot_msg_b427bf")

    if stage == "light_outing_checkin":
        if subject:
            return t("clients.telegram_bot.followup_light_outing", subject=subject)
        return t("clients.telegram_bot.bot_msg_62dd6f")

    if topic == "outing":
        return t("clients.telegram_bot.proactive_followup_alt", subject=subject) if subject else t("clients.telegram_bot.bot_msg_111e41")
    if topic == "food_purchase":
        return t("clients.telegram_bot.proactive_followup_alt", subject=subject) if subject else t("clients.telegram_bot.bot_msg_e98f02")
    if topic == "task_progress":
        return t("clients.telegram_bot.followup_task_progress", subject=subject) if subject else t("clients.telegram_bot.bot_msg_9fef07")
    return t("clients.telegram_bot.proactive_followup", subject=subject) if subject else t("clients.telegram_bot.bot_msg_4f0f04")


def _normalize_followup_signal_text(text: str) -> str:
    import unicodedata

    raw = str(text or "").strip().lower()
    if not raw:
        return ""
    normalized = unicodedata.normalize("NFKD", raw)
    return "".join(ch for ch in normalized if not unicodedata.combining(ch))



def _build_followup_decision_with_llm(item: dict, recent_context: str, state_snapshot: dict) -> dict:
    from services.gemini import safe_gemini_call
    from core.utils import clean_message
    import json
    from datetime import datetime

    now_dt = datetime.now()
    state_block = _render_followup_state_snapshot(state_snapshot)

    metadata = item.get("metadata") or {}
    defer_count = int(metadata.get("defer_count") or 0)
    times_sent = int(item.get("times_sent") or 0)
    last_decision = str(item.get("last_decision") or "").strip()
    decision_reason = str(item.get("decision_reason") or "").strip()
    outcome_score = float(item.get("outcome_score") or 0.0)
    topic = str(item.get("topic") or "").strip().lower()

    history_block = (
        f"- defer_count: {defer_count}\n"
        f"- times_sent: {times_sent}\n"
        f"- last_decision: {last_decision or 'none'}\n"
        f"- decision_reason: {decision_reason or 'none'}\n"
        f"- outcome_score: {outcome_score:.2f}"
    )

    prompt = core.i18n.load_prompt("telegram_bot_followup_decision.md").format(
        language=config.RESPONSE_LANGUAGE,
        user_name=config.USER_NAME, 
        local_time=now_dt.strftime("%Y-%m-%d %H:%M"),
        hour=now_dt.hour,
        state_block=state_block,
        history_block=history_block,
        topic=item.get('topic'),
        subject=item.get('subject'),
        source_channel=item.get('source_channel'),
        source_agent=item.get('source_agent'),
        original_user_text=item.get('source_user_text'),
        original_ai_text=item.get('source_ai_text'),
        due_at=item.get('followup_after_ts'),
        recent_context=recent_context[:2500]
    )
    try:
        response = safe_gemini_call(prompt)
        text = response.text if hasattr(response, "text") else str(response)
        cleaned = clean_message(text).strip()

        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise ValueError("No JSON object found in follow-up decision response.")

        payload = json.loads(cleaned[start:end + 1])
        decision = str(payload.get("decision", "")).strip().lower()
        stage = str(payload.get("stage", "")).strip().lower()
        message = clean_message(payload.get("message", "")).strip()
        reason = str(payload.get("reason", "")).strip()
        skip_action = str(payload.get("skip_action") or "none").strip().lower()
        context_evidence = clean_message(
            str(payload.get("context_evidence") or "")
        ).strip()
        if skip_action not in {"resolve", "defer", "none"}:
            skip_action = "none"

        if decision not in {"send", "skip"}:
            decision = "skip"

        if stage not in {
            "before_prerequisite",
            "decision_pending",
            "after_likely_completion",
            "skip",
        }:
            stage = "skip" if decision == "skip" else "decision_pending"

        if topic == "departure":
            evidence_norm = _normalize_followup_signal_text(context_evidence)
            recent_context_norm = _normalize_followup_signal_text(recent_context)

            if (
                decision != "send"
                or not message
                or len(evidence_norm) < 5
                or evidence_norm not in recent_context_norm
            ):
                return {
                    "decision": "skip",
                    "skip_action": "resolve",
                    "stage": "skip",
                    "message": "",
                    "reason": "departure_missing_verified_recent_context",
                }

        if decision == "send" and not message:
            message = _build_safe_followup_fallback(item, stage)

        return {
            "decision": decision,
            "skip_action": skip_action,
            "stage": stage,
            "message": message,
            "reason": reason,
        }

    except Exception as exc:
        print(f"[FollowUpDecision Error]: {exc}")
        return {
            "decision": "skip",
            "skip_action": "resolve" if topic == "departure" else "defer",
            "stage": "skip",
            "message": "",
            "reason": (
                "departure_decision_failed_resolved"
                if topic == "departure"
                else "llm_decision_failed_safe_defer"
            ),
        }

def _followup_log_label(item: dict) -> str:
    topic = str(item.get("topic") or "").strip().lower()
    subject = str(item.get("subject") or "").strip()
    if topic and subject:
        return f"{topic} :: {subject}"
    if subject:
        return subject
    if topic:
        return topic
    return f"id={item.get('id')}"

def _short_followup_reason(reason: str, limit: int = 220) -> str:
    from core.utils import clean_message
    text = clean_message(reason or "").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."

def _followup_skip_means_defer(reason: str) -> bool:
    text = _normalize_followup_signal_text(reason)
    markers = (
        t("clients.telegram_bot.bot_msg_395694"),
        t("clients.telegram_bot.bot_msg_28b202"),
        t("clients.telegram_bot.bot_msg_117791"),
        t("clients.telegram_bot.bot_msg_082854"),
        t("clients.telegram_bot.bot_msg_437093"),
        t("clients.telegram_bot.bot_msg_4f17de"),
        t("clients.telegram_bot.bot_msg_a77d19"),
        t("clients.telegram_bot.bot_msg_251e4d"),
        "before",
        "not yet",
        "later",
        "tonight",
    )
    return any(marker in text for marker in markers)

def _followup_skip_means_resolved(reason: str) -> bool:
    text = _normalize_followup_signal_text(reason)
    markers = (
        t("clients.telegram_bot.bot_msg_39b4e9"),
        t("clients.telegram_bot.bot_msg_48da5a"),
        t("clients.telegram_bot.bot_msg_12e8b7"),
        t("clients.telegram_bot.bot_msg_77d021"),
        t("clients.telegram_bot.bot_msg_451cec"),
        t("clients.telegram_bot.bot_msg_6e8d10"),
        t("clients.telegram_bot.bot_msg_770c84"),
        t("clients.telegram_bot.bot_msg_1b3dde"),
        t("clients.telegram_bot.bot_msg_ef62c0"),
        t("clients.telegram_bot.bot_msg_7755d1"),
        t("clients.telegram_bot.bot_msg_9f7078"),
        "already completed",
        "already discussed",
        "no further follow-up",
        t("clients.telegram_bot.bot_msg_1bbc61"),
        t("clients.telegram_bot.bot_msg_aaa6cf"),
        t("clients.telegram_bot.bot_msg_b1aca8"),
    )
    return any(marker in text for marker in markers)

def _looks_terminal_followup_skip_reason(reason: str) -> bool:
    text = _normalize_gr(reason or "")
    markers = [
        t("clients.telegram_bot.bot_msg_cdf440"),
        t("clients.telegram_bot.bot_msg_055f83"),
        t("clients.telegram_bot.bot_msg_f6a7ce"),
        t("clients.telegram_bot.bot_msg_12a43d"),
        t("clients.telegram_bot.bot_msg_a0f7e2"),
        t("clients.telegram_bot.bot_msg_3ee579"),
        t("clients.telegram_bot.bot_msg_27ae12"),
        t("clients.telegram_bot.bot_msg_062ecf"),
    ]
    return any(m in text for m in markers)

def _apply_followup_skip_outcome(item: dict, decision: dict) -> str:
    from datetime import datetime
    from memory.pending_followups import defer_followup, resolve_followup, _set_followup_decision, normalize_followup_delay

    reason = str(decision.get("reason") or "").strip()
    skip_action = str(decision.get("skip_action") or "none").strip().lower()
    topic = str(item.get("topic") or "").strip().lower()
    metadata = item.get("metadata") or {}
    if topic == "departure":
        resolution_reason = reason or "departure_not_contextually_valid"
        resolve_followup(item["id"], f"resolved_by_skip:{resolution_reason}")
        _set_followup_decision(item["id"], "resolved", resolution_reason)
        return "resolved"

    target_window = str(metadata.get("target_window") or "").strip()
    raw_delay = int(metadata.get("delay_minutes_raw") or metadata.get("delay_minutes_final") or 60)

    if skip_action == "defer" or _followup_skip_means_defer(reason):
        delay_minutes = normalize_followup_delay(
            topic=topic,
            suggested_minutes=raw_delay,
            source_user_text=str(item.get("source_user_text") or ""),
            target_window=target_window,
            now=datetime.now(),
        )
        defer_followup(
            item["id"],
            delay_minutes=delay_minutes,
            reason=f"deferred:skip:{reason or 'too_early'}",
            target_window=target_window,
            topic=topic,
        )
        _set_followup_decision(item["id"], "deferred", reason or "too_early")
        return "deferred"

    if skip_action == "resolve" or _followup_skip_means_resolved(reason) or _looks_terminal_followup_skip_reason(reason):
        resolve_followup(item["id"], f"resolved_by_skip:{reason or 'stale_followup_no_longer_relevant'}")
        _set_followup_decision(item["id"], "resolved", reason or "stale_followup_no_longer_relevant")
        return "resolved"

    _set_followup_decision(item["id"], "skip", reason or "skip_without_state_change")
    return "kept_pending"

_FOLLOWUP_GLOBAL_COOLDOWN_MINUTES = 30
_DEPARTURE_FOLLOWUP_GLOBAL_COOLDOWN_MINUTES = 5
_FOLLOWUP_ARC_COOLDOWN_MINUTES = 240


def job_check_pending_followups():
    from memory.pending_followups import _local_now
    try:
        now_iso = _local_now().isoformat(timespec="seconds")
        expire_old_followups(now_iso)

        due = get_due_pending_followups(now_iso)
        if not due:
            return

        recent_context = _load_recent_proactive_context(limit=10)

        for item in due[:3]:
            global_cooldown_minutes = (
                _DEPARTURE_FOLLOWUP_GLOBAL_COOLDOWN_MINUTES
                if str(item.get("topic") or "").strip().lower() == "departure"
                else _FOLLOWUP_GLOBAL_COOLDOWN_MINUTES
            )
            if has_recent_sent_followup(within_minutes=global_cooldown_minutes):
                print(f"[FollowUp]: skip #{item['id']} ({_followup_log_label(item)}) recent global followup")
                continue

            arc_key = item.get("arc_key") or build_followup_arc_key(
                item.get("topic", ""),
                item.get("subject", ""),
            )
            if has_recent_sent_followup_for_arc(
                arc_key,
                within_minutes=_FOLLOWUP_ARC_COOLDOWN_MINUTES,
            ):
                print(f"[FollowUp]: skip #{item['id']} ({_followup_log_label(item)}) recent arc followup")
                continue

            lower_ctx = (recent_context or "").lower()

            if item.get("topic") == "food_purchase":
                premature_markers = (
                    t("clients.telegram_bot.bot_msg_eb4038"),
                    t("clients.telegram_bot.bot_msg_0e8630"),
                    t("clients.telegram_bot.bot_msg_1398b3"),
                    t("clients.telegram_bot.bot_msg_2c9984"),
                )
                if any(marker in lower_ctx for marker in premature_markers):
                    print(f"[FollowUp]: keep pre-completion stage for #{item['id']} due to work-context")

            state_snapshot = _build_followup_state_snapshot()
            decision = _build_followup_decision_with_llm(
                item,
                recent_context,
                state_snapshot,
            )

            if decision.get("decision") != "send":
                skip_action = _apply_followup_skip_outcome(item, decision)

                print(
                    f"[FollowUp]: skip #{item['id']} "
                    f"({_followup_log_label(item)}) "
                    f"action={skip_action} "
                    f"stage={decision.get('stage')} "
                    f"reason={_short_followup_reason(decision.get('reason', ''))}"
                )
                continue

            msg = str(decision.get("message") or "").strip()
            if not msg:
                continue

            message_id = _send_and_record_assistant(msg, agent="FollowUp_Agent")
            if not message_id:
                print(f"[FollowUp]: send-failed #{item['id']} stage={decision.get('stage')}")
                continue
            mark_followup_sent(
                item["id"],
                f"followup_sent:{decision.get('stage')}",
            )
            record_followup_outcome(item["id"], +0.2, f"followup_sent:{decision.get('stage')}")
            print(
                f"[FollowUp]: sent #{item['id']} "
                f"stage={decision.get('stage')} "
                f"-> {item['subject']}"
            )
    except Exception as exc:
        print(f"[FollowUpJob Error]: {exc}")

# ── Human Override State ──────────────────────────────────────
import time as _time

_OVERRIDE_FILE = os.path.join(os.path.dirname(__file__), "..", "scheduler_state.json")
_override_state = {"pause_reminders": False, "mute_proactive": False, "sleep_until": None}
_override_lock  = threading.Lock()

def _load_override_state():
    global _override_state
    try:
        if os.path.exists(_OVERRIDE_FILE):
            with open(_OVERRIDE_FILE, "r", encoding="utf-8") as f:
                _override_state.update(json.load(f))
    except Exception:
        pass

def _save_override_state():
    try:
        with open(_OVERRIDE_FILE, "w", encoding="utf-8") as f:
            json.dump(_override_state, f, ensure_ascii=False)
    except Exception:
        pass

def fast_queue_worker():
    """Executes fast background tasks (e.g., UI updates, deterministic memory)."""
    print("\033[90m[System]: Telegram Fast Queue Worker Started!\033[0m")
    while not shutdown_event.is_set():
        try:
            task_func, args = fast_queue.get(timeout=2)
            try:
                print(f"\033[90m[FastQueue]: {task_func.__name__}\033[0m")
                task_func(*args)
            except Exception as e:
                print(f"\033[91m[Fast Queue Error in {task_func.__name__}]: {e}\033[0m")
            finally:
                fast_queue.task_done()
        except queue.Empty:
            continue

def slow_queue_worker():
    """Performs slow background tasks (e.g., LLM memory sifting)."""
    print("\033[90m[System]: Telegram Slow Queue Worker Started!\033[0m")
    while not shutdown_event.is_set():
        try:
            task_func, args = slow_queue.get(timeout=2)
            try:
                print(f"\033[90m[SlowQueue]: {task_func.__name__}\033[0m")
                task_func(*args)
            except Exception as e:
                print(f"\033[91m[Slow Queue Error in {task_func.__name__}]: {e}\033[0m")
            finally:
                slow_queue.task_done()
        except queue.Empty:
            continue

def is_reminders_paused() -> bool:
    with _override_lock:
        if _override_state.get("sleep_until") and _time.time() < _override_state["sleep_until"]:
            return True
        return bool(_override_state.get("pause_reminders"))

def is_proactive_muted() -> bool:
    with _override_lock:
        if _override_state.get("sleep_until") and _time.time() < _override_state["sleep_until"]:
            return True
        return bool(_override_state.get("mute_proactive"))


# ────────────────────────────────────────────────────────────────
# DOCUMENT HANDLER (NEW)
# ────────────────────────────────────────────────────────────────

def handle_document(doc_obj: dict, caption: str, chat_id: str):
    """Downloads documents (PDF, Excel etc.) from Telegram to the correct folder."""
    try:
        from config import BASE_DIR
        file_id = doc_obj["file_id"]
        # If it doesn't have a name, we give it a random one
        file_name = doc_obj.get("file_name", f"doc_{int(time.time())}.pdf")

        # Documents go to telegram_uploads (as in the Web UI)
        target_dir = os.path.join(BASE_DIR, "telegram_uploads")
        os.makedirs(target_dir, exist_ok=True)
        local_path = os.path.join(target_dir, file_name)

        # Get file path from Telegram API
        file_resp = requests.get(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getFile",
            params={"file_id": file_id}, timeout=10
        ).json()
        file_path_remote = file_resp["result"]["file_path"]

        # Download
        file_url = f"https://api.telegram.org/file/bot{TELEGRAM_TOKEN}/{file_path_remote}"
        doc_data = requests.get(file_url, timeout=30).content

        with open(local_path, "wb") as f:
            f.write(doc_data)
        print(f"\033[94m[Document]: Saved in Telegram: {local_path}\033[0m")

        # We send a message to the user that we received it
        send_telegram_msg(f"📄 Document received: `{file_name}`\nWait, I'm looking at it...")

        file_ext = os.path.splitext(file_name)[1].lower()
        doc_text = ""
        try:
            if file_ext in (".txt", ".csv", ".json", ".md"):
                with open(local_path, "r", encoding="utf-8", errors="ignore") as df:
                    doc_text = df.read()[:8000]
            elif file_ext == ".pdf":
                import pypdf
                reader = pypdf.PdfReader(local_path)
                doc_text = "\n".join(p.extract_text() or "" for p in reader.pages)[:8000]
            elif file_ext in (".docx",):
                from docx import Document as DocxDoc
                doc_text = "\n".join(p.text for p in DocxDoc(local_path).paragraphs)[:8000]
            elif file_ext in (".xlsx", ".xls"):
                import pandas as pd
                df_data = pd.read_excel(local_path)
                doc_text = df_data.to_string(index=False)[:8000]
            else:
                doc_text = f"Unsupported document type: {file_ext}"
        except Exception as read_err:
            doc_text = f"[Could not read content: {read_err}]"

        from memory.conversation_history import build_asset_context_text
        conversation_context = build_asset_context_text("telegram")

        sum_prompt = core.i18n.load_prompt("telegram_bot_document_analysis.md").format(language=config.RESPONSE_LANGUAGE, user_name=config.USER_NAME, 
            conversation_context=conversation_context or t("clients.telegram_bot.bot_msg_98937a"),
            caption=caption or t("clients.telegram_bot.bot_msg_05a606"),
            file_name=file_name,
            doc_text=doc_text
        )
        from langchain_core.messages import HumanMessage as _HM
        sum_resp = safe_llm_invoke(llm, [_HM(content=sum_prompt)])
        detailed_analysis = clean_message(sum_resp.content).strip() if sum_resp and sum_resp.content else t("clients.telegram_bot.bot_msg_33d466")
        memory_analysis = detailed_analysis[:500]

        chat_ai_msg = (
            f"📄 **Document:** `{file_name}`\n\n"
            f"{detailed_analysis}\n\n"
            "**Should I save it to memory permanently?**\n"
            "Answer only with: yes or no."
        )
        
        send_telegram_msg(chat_ai_msg)

        user_log_msg = f"[USER_UPLOADED_FILE]: {file_name}\n[FILE PATH]: {local_path}\n[VISUAL ANALYSIS]: {memory_analysis}\n[USER_CAPTION]: {caption or ''}\n[CONTENT_SOURCE]: uploaded_document"
        
        # Record in history
        try:
            from memory.conversation_history import append_message
            now = datetime.now()
            append_message("user", user_log_msg, "telegram", agent=None, timestamp=now)
            append_message("assistant", chat_ai_msg, "telegram", agent="Chat_Agent", timestamp=now)
            enqueue_fast_task(log_exchange, user_log_msg, chat_ai_msg, "Chat_Agent", "telegram")
            enqueue_fast_task(update_working_memory, user_log_msg, chat_ai_msg)
            enqueue_fast_task(_enqueue_slow_memory_sifter, user_log_msg, chat_ai_msg, "Chat_Agent", "telegram")
            enqueue_slow_task(update_capabilities_from_exchange, user_log_msg, chat_ai_msg, "Chat_Agent")
            enqueue_slow_task(_enqueue_followup_pipeline, user_log_msg, chat_ai_msg, "Chat_Agent", "telegram")
            enqueue_slow_task(extract_and_update_context_flags, caption or user_log_msg, chat_ai_msg)
        except Exception as e:
            print(f"[Document/History]: {e}")

        try:
            from memory.pending_assets import create_pending_asset_archive
            create_pending_asset_archive(
                channel="telegram",
                asset_type="document",
                file_path=local_path,
                filename=file_name,
                analysis=memory_analysis,
                caption=caption or "",
            )
        except Exception as e:
            print(f"[PendingAssets]: Telegram document upload error: {e}")

    except Exception as e:
        print(f"\033[91m[Document Error]: {e}\033[0m")
        send_telegram_msg(f"❌ Document download error: {str(e)}")
# ────────────────────────────────────────────────────────────────
# VOICE HANDLER (CONSOLIDATED)
# ────────────────────────────────────────────────────────────────
def handle_voice(voice_obj: dict, chat_id: str):
    """Receives audio, converts it to text, and responds vocally."""
    from config import TELEGRAM_TOKEN
    from services.gemini import safe_gemini_call
    from tools.telegram import send_telegram_msg

    local_path = None
    try:
        file_id = voice_obj["file_id"]
        local_path = os.path.join(os.getcwd(), "telegram_uploads", f"voice_{int(time.time())}.ogg")
        os.makedirs(os.path.dirname(local_path), exist_ok=True)

        file_resp = requests.get(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getFile",
            params={"file_id": file_id}, timeout=10
        ).json()
        
        file_path_remote = file_resp["result"]["file_path"]
        file_url = f"https://api.telegram.org/file/bot{TELEGRAM_TOKEN}/{file_path_remote}"
        audio_data = requests.get(file_url, timeout=30).content
        
        with open(local_path, "wb") as f:
            f.write(audio_data)

        print(f"\033[96m[Voice]: Analyzing audio...\033[0m")

        import base64 as _b64
        import vertexai
        from vertexai.generative_models import GenerativeModel, Part
        from core.brain import FAST_MODEL
        vertexai.init(project=config.PROJECT_ID, location=os.getenv("LOCATION", "global"))
        stt_model = GenerativeModel(FAST_MODEL)
        prompt = t("clients.telegram_bot.bot_msg_32a4bf")
        audio_part = Part.from_data(data=audio_data, mime_type="audio/ogg")
        stt_response = stt_model.generate_content([prompt, audio_part])
        ai_reply = stt_response.text.strip() if stt_response and stt_response.text else t("clients.telegram_bot.bot_msg_dacaa2")

        print(f"\033[92m[Voice AI]: {ai_reply}\033[0m")
        # We send the flag [VOICE] + [VOICE_INPUT] so that handle_message knows to reply with audio
        # and the Lobster that the message came from voice (to reply more briefly and colloquially)
        handle_message(f"[VOICE]: [VOICE_INPUT] {ai_reply}", chat_id)

    except Exception as e:
        print(f"\033[91m[Voice Error]: {e}\033[0m")
        # [FIX]: HERE WAS THE ERROR - Only one argument
        send_telegram_msg(t("clients.telegram_bot.bot_msg_37da1a")) 
    finally:
        if local_path and os.path.exists(local_path):
            os.remove(local_path)
def send_telegram_document(file_path, chat_id=None):
    if not chat_id: chat_id = TELEGRAM_CHAT_ID
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendDocument"
        with open(file_path, 'rb') as f:
            requests.post(url, data={'chat_id': chat_id}, files={'document': f})
        print(f"\033[92m[Telegram]: File {os.path.basename(file_path)} sent!\033[0m")
    except Exception as e:
        print(f"❌ Telegram File Error: {e}")         
def handle_end_session(chat_id: str):
    """Closes the session, saves the summary and clears the working memory."""
    try:
        from memory.session_memory import _run_session_summary
        from config import WORKING_MEMORY_FILE
        
        send_telegram_msg(t("clients.telegram_bot.bot_msg_139ed4"))
        
        # 1. We run the main summary (as in server.py)
        _run_session_summary(channel="telegram")
        
        # 2. Clear the Post-it (Working Memory)
        with open(WORKING_MEMORY_FILE, "w", encoding="utf-8") as f:
            f.write(t("clients.telegram_bot.bot_msg_4cd007"))
            
        print("\033[92m[Telegram]: Session closed and archived successfully.\033[0m")
        send_telegram_msg(t("clients.telegram_bot.bot_msg_bfe08b"))

    except Exception as e:
        print(f"\033[91m[End Session Error]: {e}\033[0m")
        send_telegram_msg(f"❌ Something went wrong on close: {str(e)}")       
# ────────────────────────────────────────────────────────────────
# PHOTO HANDLER
# ────────────────────────────────────────────────────────────────

def handle_photo(photo_list: list, caption: str, chat_id: str):
    """
    [MASTRO-PARITY]: Analyzes a photo via Vision LLM.
    - With caption: processes immediately using the caption as the prompt.
    - Without caption: saves the analysis as pending and waits for the next message (30s).
    """
    global pending_photo
    try:
        import base64
        from langchain_core.messages import HumanMessage, AIMessage
        from core.brain import llm
        from core.agents import clean_message

        # 1. Download file from Telegram
        best_photo = max(photo_list, key=lambda p: p.get("file_size", 0))
        file_id = best_photo["file_id"]
        file_resp = requests.get(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getFile", params={"file_id": file_id}).json()
        file_path_remote = file_resp["result"]["file_path"]
        img_data = requests.get(f"https://api.telegram.org/file/bot{TELEGRAM_TOKEN}/{file_path_remote}").content

        # 2. Save locally
        timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename  = f"photo_{timestamp_str}.jpg"
        local_path = os.path.join(PHOTOS_DIR, filename)
        with open(local_path, "wb") as f:
            f.write(img_data)
        print(f"\033[92m[Photo]: Downloaded: {filename}\033[0m")

        # 3. Vision LLM — objective pixel analysis
        img_b64 = base64.b64encode(img_data).decode("utf-8")
        vision_prompt = t("clients.telegram_bot.bot_msg_dec305")
        vision_msg = HumanMessage(content=[
            {"type": "text",      "text": vision_prompt},
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"}}
        ])
        print(f"\033[94m[Vision]: Visual analysis...\033[0m")
        analysis_raw  = safe_llm_invoke(llm, [vision_msg])
        memory_analysis = clean_message(analysis_raw.content)
        print(f"\033[94m[Vision]: {memory_analysis[:120]}...\033[0m")

        # 4a. WITH caption → check for /nutrition, /receipt or normal question
        if caption:
            caption_cmd = caption.strip().lower()
            if caption_cmd == "/nutrition":
                send_telegram_msg(t("clients.telegram_bot.bot_msg_0e0401"))
                threading.Thread(target=_run_nutrition, args=(local_path, chat_id), daemon=True).start()
            elif caption_cmd == "/receipt":
                send_telegram_msg(t("clients.telegram_bot.bot_msg_b2c62a"))
                threading.Thread(target=_run_receipt, args=(local_path, chat_id), daemon=True).start()
            else:
                _process_photo_with_question(filename, local_path, memory_analysis, caption, chat_id)

        # 4b. WITHOUT caption → save as pending, notify
        else:
            with pending_photo_lock:
                pending_photo = {
                    "analysis":  memory_analysis,
                    "filename":  filename,
                    "path":      local_path,
                    "timestamp": time.time()
                }
            send_telegram_msg(t("clients.telegram_bot.bot_msg_477e48"))

    except Exception as e:
        import traceback
        traceback.print_exc()
        send_telegram_msg(f"Master, photo stalled. Error: {e}")


def _process_photo_with_question(filename: str, local_path: str, analysis: str, question: str, chat_id: str):
    """Passes a photo + question to the graph and sends ONE response (correct streaming pattern)."""
    import re
    from langchain_core.messages import HumanMessage, AIMessage
    from core.agents import clean_message

    # Load history from shared SQLite
    context_msgs = _load_shared_context_messages("telegram")

    now_ts = datetime.now().strftime("%H:%M")
    user_log_msg = (
        f"[{now_ts}] "
        f"[USER_UPLOADED_PHOTO]: {filename}\n"
        f"[PHOTO PATH]: {local_path}\n"
        f"[VISUAL ANALYSIS]: {analysis}\n"
        f"Question: {question}"
    )
    print(f"\033[94m[Photo->Graph]: {user_log_msg[:200]}\033[0m")

    # Streaming — collect, send once (same pattern as handle_message)
    final_response = ""
    try:
        from memory.execution_trace import ExecutionTrace
        _ptrace = ExecutionTrace(channel="telegram", user_message=user_log_msg)
        for event in graph.stream({"messages": context_msgs + [HumanMessage(content=user_log_msg)], "channel": "telegram"}, {"recursion_limit": 50}):
            _ptrace.process_event(event)
            for node, data in event.items():
                if data is None:
                    continue
                if node not in ["supervisor", "tools"]:
                    msgs = data.get("messages", [])
                    if msgs and hasattr(msgs[-1], "content"):
                        candidate = clean_message(msgs[-1].content).strip()
                        if candidate:
                            final_response = candidate
        _ptrace.finalize(response=final_response or None)
        _ptrace.save()
    except Exception as e:
        send_telegram_msg(f"❌ Photo processing error: {e}")
        return

    if not final_response:
        send_telegram_msg(t("clients.telegram_bot.bot_msg_226c6b"))
        return

    from memory.pending_assets import looks_like_asset_confirmation_prompt
    if not looks_like_asset_confirmation_prompt(final_response):
        final_response += t("clients.telegram_bot.bot_msg_2d5d94")

    # ── Photo persistence / Pending asset ──
    try:
        from memory.conversation_history import append_message
        now = datetime.now()
        append_message(role="user", content=user_log_msg, channel="telegram", agent=None, timestamp=now)
        append_message(role="assistant", content=final_response, channel="telegram", agent="Chat_Agent", timestamp=now)
    except Exception as e:
        print(f"[Photo/History]: {e}")

    handling_agent = "Chat_Agent"
    enqueue_fast_task(log_exchange, user_log_msg, final_response, handling_agent, "telegram")
    enqueue_fast_task(update_working_memory, user_log_msg, final_response)
    enqueue_fast_task(_enqueue_slow_memory_sifter, user_log_msg, final_response, handling_agent, "telegram")
    enqueue_slow_task(update_capabilities_from_exchange, user_log_msg, final_response, handling_agent)
    enqueue_slow_task(_enqueue_followup_pipeline, user_log_msg, final_response, handling_agent, "telegram")
    enqueue_slow_task(extract_and_update_context_flags, user_log_msg, final_response)

    try:
        from memory.pending_assets import create_pending_asset_archive, looks_like_asset_confirmation_prompt
        if looks_like_asset_confirmation_prompt(final_response):
            create_pending_asset_archive(
                channel="telegram",
                asset_type="photo",
                file_path=local_path,
                filename=filename,
                analysis=analysis,
                caption=question or "",
            )
    except Exception as e:
        print(f"[PendingAssets]: {e}")

    # Interceptor for CREATED_FILE
    file_match = re.search(r"\[CREATED_FILE:\s*(.*?)\]", final_response)
    if file_match:
        file_path = file_match.group(1).strip()
        final_response = re.sub(r"\[CREATED_FILE:\s*(.*?)\]", "", final_response).strip()
        if final_response:
            send_telegram_msg(final_response)
        try:
            from tools.telegram import send_telegram_document
            send_telegram_document(file_path)
        except Exception:
            pass
    else:
        send_telegram_msg(final_response)
def _run_nutrition(image_path: str, chat_id: str):
    """Runs the nutrition analyzer and sends the result."""
    try:
        from astakos_skills.nutrition_analyzer import analyze_nutrition
        result = analyze_nutrition(image_path)
        _send_and_record_assistant(result, chat_id)
    except Exception as e:
        _send_and_record_assistant(f"❌ Nutrition analysis error: {e}", chat_id)


def _run_receipt(image_path: str, chat_id: str):
    """Runs the receipt scanner and sends the result."""
    try:
        from astakos_skills.scan_receipt import scan_receipt
        result = scan_receipt.invoke({"image_path": image_path})
        _send_and_record_assistant(result, chat_id)
    except Exception as e:
        _send_and_record_assistant(f"❌ Receipt scan error: {e}", chat_id)


def _run_story_maker(theme: str, characters: str, chat_id: str):
    """Generates a fairy tale + images and sends them to Telegram."""
    try:
        from astakos_skills.story_maker import make_story
        from tools.telegram import send_telegram_photo
        result = make_story(theme, characters)

        if result.get("error") or not result.get("story"):
            send_telegram_msg(f"❌ {result.get('error', t("clients.telegram_bot.bot_msg_cf83ee"))}")
            return

        # We first send the text (in chunks if it is large)
        story_text = f"📖 *Story: {theme}*\n\n{result['story']}"
        # Telegram limit: 4096 chars
        max_len = 4000
        chunks = [story_text[i:i+max_len] for i in range(0, len(story_text), max_len)]
        for chunk in chunks:
            send_telegram_msg(chunk)
            time.sleep(0.5)

        # We send the images
        images = result.get("images", [])
        if images:
            send_telegram_msg(f"🎨 *{len(images)} images from the story:*")
            for img_path in images:
                if os.path.exists(img_path):
                    try:
                        import asyncio
                        asyncio.run(send_telegram_photo(img_path))
                        time.sleep(1)
                    except Exception as img_e:
                        print(f"⚠️ [StoryMaker] Failed to send image: {img_e}")
        else:
            send_telegram_msg(t("clients.telegram_bot.bot_msg_c594bf"))

        print(f"✅ [StoryMaker] Story '{theme}' completed.")

        # Update the agent with a SHORT note — so they know they wrote a fairy tale
        # and not to call search_memory if the user asks about this
        char_note = f" with characters: {characters}" if characters else ""
        img_note = f"{len(images)} images sent" if images else t("clients.telegram_bot.bot_msg_496a96")
        agent_note = (
            f"[SYSTEM]: Just wrote and sent a story about '{theme}'{char_note}. "
            f"{img_note}. {config.USER_NAME} already has it on Telegram."
        )
        _append_to_analytics_log("ai", agent_note, agent="StoryMaker")
        enqueue_fast_task(update_working_memory, f"/story {theme}", agent_note)
    except Exception as e:
        send_telegram_msg(f"❌ Story maker error: {e}")
        print(f"❌ [StoryMaker] {e}")


def send_voice_reply(text, chat_id):
    """Converts the text to speech and sends it as a voice message."""
    try:
        from tools.telegram import send_telegram_voice # Make sure it exists in tools/telegram.py
        
        voice_path = os.path.join(os.getcwd(), "telegram_uploads", f"reply_{int(time.time())}.mp3")
        os.makedirs(os.path.dirname(voice_path), exist_ok=True)

        # Creation of the sound (in Greek)
        tts = gTTS(text=text, lang='el')
        tts.save(voice_path)

        # Sending of the file
        send_telegram_voice(voice_path, chat_id)

        # Cleanup
        if os.path.exists(voice_path):
            os.remove(voice_path)
            
    except Exception as e:
        print(f"❌ TTS Error: {e}")
        send_telegram_msg(f"Master, I lost my voice... (Error: {e})")
def _append_to_analytics_log(role: str, content: str, agent: str | None = None):
    """Logging of a message in the shared SQLite conversation history (telegram channel)."""
    try:
        now = datetime.now()
        shared_role = "assistant" if role in ("ai", "assistant") else role
        try:
            # notify_telegram_message: saves to shared SQLite + WebSocket broadcast to Web UI
            from api.server import notify_telegram_message
            notify_telegram_message(role=shared_role, content=content, agent=agent)
        except Exception:
            # Fallback: direct append without broadcast (if the server is not running)
            from memory.conversation_history import append_message
            append_message(
                role=shared_role,
                content=content,
                channel="telegram",
                timestamp=now,
                agent=agent,
            )
    except Exception as e:
        print(f"[ConversationHistory/telegram]: Error shared write: {e}")


def _send_and_record_assistant(
    content: str,
    chat_id: str | None = None,
    agent: str | None = "Chat_Agent",
):
    """Sends an assistant reply to Telegram and writes it to the shared history."""
    if len(content) <= 3500:
        message_id = send_telegram_msg(content)
    else:
        from tools.telegram import send_telegram_msg_full
        message_id = send_telegram_msg_full(content)
    if message_id:
        _append_to_analytics_log("ai", content, agent=agent)
    else:
        print(f"[TelegramSend]: outbound send failed for agent={agent}")
    return message_id


def _arm_pending_georgian():
    global pending_georgian_until
    with pending_georgian_lock:
        pending_georgian_until = time.time() + PENDING_GEORGIAN_TTL_SECONDS


def _clear_pending_georgian():
    global pending_georgian_until
    with pending_georgian_lock:
        pending_georgian_until = 0.0


def _consume_pending_georgian() -> bool:
    global pending_georgian_until
    with pending_georgian_lock:
        if pending_georgian_until and time.time() <= pending_georgian_until:
            pending_georgian_until = 0.0
            return True
        pending_georgian_until = 0.0
        return False


def _arm_pending_partner():
    global pending_partner_until
    with pending_partner_lock:
        pending_partner_until = time.time() + PENDING_GEORGIAN_TTL_SECONDS


def _clear_pending_partner():
    global pending_partner_until
    with pending_partner_lock:
        pending_partner_until = 0.0


def _consume_pending_partner() -> bool:
    global pending_partner_until
    with pending_partner_lock:
        if pending_partner_until and time.time() <= pending_partner_until:
            pending_partner_until = 0.0
            return True
        pending_partner_until = 0.0
        return False


def _send_georgian_translation(text: str, *, force_src: str = "auto"):
    from tools.georgian import translate, tts_audio

    try:
        result = translate(text, src=force_src)
    except Exception as e:
        send_telegram_msg(f"❌ Translation error: {e}")
        return

    flag = "🇬🇪" if result["tgt"] == "ka" else "🇬🇷"
    direction = "el→ka" if result["tgt"] == "ka" else "ka→el"

    reply = f"{flag} <code>{result['translated']}</code>"
    if result["phonetic"]:
        reply += f"\n📢 <i>{result['phonetic']}</i>"
    send_telegram_msg(reply)

    try:
        audio_bytes = tts_audio(result["translated"], lang=result["tgt"])
        tg_url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendAudio"
        requests.post(
            tg_url,
            data={"chat_id": TELEGRAM_CHAT_ID},
            files={"audio": ("georgian.mp3", audio_bytes, "audio/mpeg")},
            timeout=20,
        )
        print(f"\033[92m[Georgian]: {direction} '{text}' → '{result['translated']}' + audio\033[0m")
    except Exception as e_audio:
        print(f"\033[93m[Georgian]: audio skip — {e_audio}\033[0m")


def _tool_results_fallback_response(user_text: str, tool_results: list[str]) -> str:
    """Synthesizes a final response when the graph returned only tool results."""
    clean_results = [clean_message(r).strip() for r in tool_results if clean_message(r).strip()]
    if not clean_results:
        return ""

    joined_results = "\n\n---\n\n".join(clean_results[-5:])[:6000]
    prompt = core.i18n.load_prompt("telegram_bot_tools_synthesis.md").format(language=config.RESPONSE_LANGUAGE, user_name=config.USER_NAME, user_text=user_text, joined_results=joined_results)
    try:
        response = safe_llm_invoke(llm, [HumanMessage(content=prompt)])
        content = clean_message(getattr(response, "content", "")).strip()
        if content and not content.startswith(t("clients.telegram_bot.bot_msg_78c917")):
            return content
    except Exception as e:
        print(f"\033[93m[ToolFallback]: synthesis failed — {e}\033[0m")

    return t("clients.telegram_bot.bot_msg_6dd772") + joined_results[:1800]


def _build_web_approval_result_message(tool_name: str, execution_result) -> str:
    """Build a deterministic Web UI reply after Telegram approval of a web-origin tool."""
    from core.utils import (
        clean_message,
        looks_like_terminal_messenger_draft_result,
        build_messenger_draft_ready_reply,
        looks_like_terminal_linkedin_draft_result,
        build_linkedin_draft_ready_reply,
    )

    if tool_name == "execute_local_pipeline":
        return t("clients.telegram_bot.bot_msg_0295de")

    raw = clean_message(str(execution_result or "")).strip()
    if not raw:
        return t("clients.telegram_bot.bot_msg_d901d5")

    tool_results = [raw]

    if any(looks_like_terminal_messenger_draft_result(r) for r in tool_results):
        return build_messenger_draft_ready_reply(tool_results)

    if any(looks_like_terminal_linkedin_draft_result(r) for r in tool_results):
        return build_linkedin_draft_ready_reply(tool_results)

    return _tool_results_fallback_response(tool_name, tool_results)


def _load_shared_context_messages(channel: str) -> list:
    """Loads mixed shared context. If it fails, the caller falls back to legacy history."""
    try:
        from memory.conversation_history import load_recent_context
        entries = load_recent_context(channel=channel, global_limit=12, channel_limit=10, total_limit=20)
    except Exception as e:
        print(f"[ConversationHistory/{channel}]: Error shared read: {e}")
        return []

    context_msgs = []
    for entry in entries:
        content = entry.get("content", "")
        if not content:
            continue
        prefix = f"[{entry.get('date', '')} {entry.get('time', '')} / {entry.get('channel', '')}] "
        if entry.get("role") in ("user", "human", "Human"):
            context_msgs.append(HumanMessage(content=f"{prefix}{content}"))
        else:
            context_msgs.append(AIMessage(content=f"{prefix}{content}"))
    return context_msgs


def _llm_routine_judge(user_msg: str, events: list) -> str:
    """
    Determines whether the user's message confirms or rejects pending routine events.
    Returns: "YES" / "NO" / "UNCLEAR"
    Uses safe_gemini_call with a fallback to UNCLEAR if it fails.
    """
    try:
        from services.gemini import safe_gemini_call
        events_str = chr(10).join(f"- {e}" for e in events)
        prompt = (
            "You are a routine tracking assistant. A user has a pending activity check."
            + chr(10) + chr(10)
            + "Pending events:" + chr(10) + events_str
            + chr(10) + chr(10)
            + f'User message: "{user_msg}"'
            + chr(10) + chr(10)
            + "Does this message indicate the user confirmed they did (or will do) one of the above events? "
            + "Or does it clearly refuse/cancel? "
            + "Reply with exactly one word: YES (confirmed), NO (refused/cancelled), or UNCLEAR (unrelated or ambiguous)."
        )
        result = safe_gemini_call(prompt, retries=2, base_delay=1.0)
        verdict = result.text.strip().upper().split()[0] if result and result.text.strip() else "UNCLEAR"
        if verdict not in ("YES", "NO", "UNCLEAR"):
            verdict = "UNCLEAR"
        print(f"\033[96m🤖 [Routine LLM Judge]: '{user_msg[:50]}' \u2192 {verdict}\033[0m")
        return verdict
    except Exception as e:
        print(f"\033[93m[Routine LLM Judge]: Error, fallback to UNCLEAR: {e}\033[0m")
        return "UNCLEAR"


# ────────────────────────────────────────────────────────────────
# MESSAGE HANDLER
# ────────────────────────────────────────────────────────────────

def _send_pending_reflections_summary() -> None:
    """Sends a single numbered message for all pending reflections."""
    if not pending_reflection_confirmations:
        return

    blocks = []
    for i, (rid, rdata) in enumerate(pending_reflection_confirmations.items(), start=1):
        conf = rdata.get("confidence")
        conf_txt = f" (confidence: {conf:.0%})" if isinstance(conf, (int, float)) else ""
        blocks.append(
            f"🤔 *#{i} Observation:* {rdata.get('observation','')}\n"
            f"→ I suggest: `{rdata.get('action','')}`{conf_txt}"
        )
    msg = (
        t("clients.telegram_bot.bot_msg_8fdaa9")
        + "\n\n---\n\n".join(blocks)
        + t("clients.telegram_bot.bot_msg_94ab69")
    )
    if len(msg) > 4000:
        msg = msg[:3990] + "..."
    _send_and_record_assistant(msg, agent="Reflection_Agent")


from core.utils import is_simple_chat_fast_path_candidate

def _build_fast_chat_context(clean_user_text: str):
    now_ts = datetime.now().strftime("%H:%M")
    context_msgs = _load_shared_context_messages("telegram")
    current_msg = HumanMessage(content=f"[{now_ts}] {clean_user_text}")
    return context_msgs, current_msg

def _run_fast_chat_path(context_msgs, current_msg):
    return list(
        graph.stream(
            {"messages": context_msgs[-6:] + [current_msg], "channel": "telegram"},
            {"recursion_limit": 12},
        )
    )


def handle_message(user_text: str, chat_id: str):
    """Sends the message to Lobster and replies (Text or Audio)."""
    global last_interaction_time
    from tools.telegram import send_telegram_voice, send_telegram_msg
    import re

    # 1. Check if voice was requested (from audio, /voice command, or global toggle)
    is_voice_mode = t("clients.telegram_bot.bot_msg_ad207c") in user_text or "[VOICE_MESSAGE]" in user_text or voice_mode_enabled
    is_voice_input = "[VOICE_INPUT]" in user_text  # the message came from voice

    # 2. We clean the tags before they go to the brain
    clean_user_text = user_text.replace("/voice", "").replace(t("clients.telegram_bot.bot_msg_d42a74"), "").replace("[VOICE_MESSAGE]:", "").strip()
    # /plan is maintained so that the graph router can recognize it
    # If it is a voice input, we keep the hint for Lobster but remove the tag
    if is_voice_input:
        clean_user_text = clean_user_text.replace("[VOICE_INPUT]", "").strip()
        clean_user_text = f"[Voice message — reply short and casually]: {clean_user_text}"
    if not clean_user_text: 
        clean_user_text = t("clients.telegram_bot.bot_msg_630052")
    # ── ROUTINE FEEDBACK LOOP ──
    if pending_routine_confirmations:
        text_check = _normalize_gr(clean_user_text)
        text_words = text_check.replace(",", "").replace(".", "").replace("!", "").split()

        pending_items = [
            (rid, pending_routine_confirmations.get(rid, {}))
            for rid in list(pending_routine_confirmations.keys())
        ]
        has_pending_partner_messenger = any(
            (
                t("clients.telegram_bot.bot_msg_2e67ed") in _normalize_gr(str((pdata or {}).get("event", "")))
                or any(term in _normalize_gr(str((pdata or {}).get("event", ""))) for term in _partner_match_terms())
                or "messenger" in _normalize_gr(str((pdata or {}).get("event", "")))
                or t("clients.telegram_bot.bot_msg_500d81") in _normalize_gr(str((pdata or {}).get("event", "")))
            )
            for _, pdata in pending_items
        )

        if has_pending_partner_messenger and _looks_like_contextual_not_needed_reply(clean_user_text):
            from memory.routine_db import remove_pending_confirmation
            from memory.event_log import log_event

            for rid, pdata in pending_items:
                ev = (pdata or {}).get("event", "?")
                event_l = _normalize_gr(str(ev))
                is_partner_messenger = (
                    t("clients.telegram_bot.bot_msg_2e67ed") in event_l
                    or any(term in event_l for term in _partner_match_terms())
                    or "messenger" in event_l
                    or t("clients.telegram_bot.bot_msg_500d81") in event_l
                )
                if not is_partner_messenger:
                    continue

                print(f"📉 [Routine Dismissed - Contextual, No Decay]: {pdata}")
                log_event(
                    "routines",
                    "routine_context_skip",
                    routine_id=rid,
                    event=ev,
                    reason="user_already_with_partner",
                    debug_type="manual_control",
                    debug_source="user_message",
                    debug_effect="no_decay"
                )
                remove_pending_confirmation(rid)
                bus.emit("routine_dismissed", routine_id=rid, event=ev, channel="telegram")
                pending_routine_confirmations.pop(rid, None)

        yes_words = [_normalize_gr(w) for w in [t("clients.telegram_bot.bot_msg_f4e83b"), "yes", t("clients.telegram_bot.bot_msg_337d7a"), "ok", t("clients.telegram_bot.bot_msg_255bcd"), t("clients.telegram_bot.bot_msg_9e152e"), t("clients.telegram_bot.bot_msg_252996")]]
        no_words  = [_normalize_gr(w) for w in [t("clients.telegram_bot.bot_msg_e0413c"), t("clients.telegram_bot.bot_msg_3e60e0"), "no", t("clients.telegram_bot.bot_msg_b1bd66"), t("clients.telegram_bot.bot_msg_d9175f"), t("clients.telegram_bot.bot_msg_3605b2"), t("clients.telegram_bot.bot_msg_0b4ad0"), t("clients.telegram_bot.bot_msg_3381ac")]]
        question_words = [_normalize_gr(w) for w in [
            t("clients.telegram_bot.bot_msg_0ab538"), t("clients.telegram_bot.bot_msg_03a47d"), t("clients.telegram_bot.bot_msg_0c4b0a"), t("clients.telegram_bot.bot_msg_2053f3"), t("clients.telegram_bot.bot_msg_4126e1"), t("clients.telegram_bot.bot_msg_00308a"), t("clients.telegram_bot.bot_msg_f3dbb1"), t("clients.telegram_bot.bot_msg_d5aba6"),
            t("clients.telegram_bot.bot_msg_12cede"), t("clients.telegram_bot.bot_msg_a7c975"), t("clients.telegram_bot.bot_msg_42541a"), t("clients.telegram_bot.bot_msg_4c18a3"), t("clients.telegram_bot.bot_msg_cd673a"), "show", "check", "why"
        ]]

        action_words = [_normalize_gr(w) for w in [
            t("clients.telegram_bot.bot_msg_cada71"), t("clients.telegram_bot.bot_msg_f41f82"), t("clients.telegram_bot.bot_msg_78e601"), t("clients.telegram_bot.bot_msg_0e436a"), t("clients.telegram_bot.bot_msg_4ebe60"), t("clients.telegram_bot.bot_msg_648c67"),
            t("clients.telegram_bot.bot_msg_6e2acb"), t("clients.telegram_bot.bot_msg_705d25"), t("clients.telegram_bot.bot_msg_d5a67f"), t("clients.telegram_bot.bot_msg_3ede59"), t("clients.telegram_bot.bot_msg_70e4d0"), t("clients.telegram_bot.bot_msg_1813ca"),
            t("clients.telegram_bot.bot_msg_8821ce"), t("clients.telegram_bot.bot_msg_1053ee"), t("clients.telegram_bot.bot_msg_8ce38d"), t("clients.telegram_bot.bot_msg_f3dee4"), t("clients.telegram_bot.bot_msg_2f0a33"), "went",
            "going", "done", "finished", "started"
        ]]
        is_question_like = any(w in text_words for w in question_words) or "?" in clean_user_text
        explicit_yes = (
            not is_question_like
            and len(text_words) <= 4
            and any(w in text_words for w in yes_words)
        )
        implicit_confirmed = False
        llm_dismissed = False
        if not explicit_yes and not is_question_like and not any(w in text_check for w in no_words):
            # LLM judges if the message is an implicit confirmation/dismissal
            event_names = [
                (rdata.get("event", "") if isinstance(rdata, dict) else str(rdata))
                for rdata in pending_routine_confirmations.values()
            ]
            verdict = _llm_routine_judge(clean_user_text, event_names)
            if verdict == "YES":
                implicit_confirmed = True
            elif verdict == "NO":
                llm_dismissed = True

        if explicit_yes or implicit_confirmed:
            from memory.routine_db import (
                confirm_routine,
                mark_routine_responded,
                remove_pending_confirmation,
            )
            from memory.event_log import log_event

            for rid in list(pending_routine_confirmations.keys()):
                pdata = pending_routine_confirmations.get(rid, {})
                ev = pdata.get("event", "?")

                confirm_routine(rid)
                mark_routine_responded(rid)
                remove_pending_confirmation(rid)

                log_event(
                    "routines", 
                    "confirmed", 
                    routine_id=rid, 
                    event=ev,
                    debug_type="manual_control",
                    debug_source="user_message",
                    debug_effect="routine_changed",
                )
                print(f"✅ [Routine Confirmed]: {pdata}")
                bus.emit("routine_confirmed", routine_id=rid, event=ev, channel="telegram")

                pending_routine_confirmations.pop(rid, None)
        elif any(w in text_check for w in no_words) or llm_dismissed:
            from memory.routine_db import (
                decay_routine,
                remove_pending_confirmation,
                mark_routine_responded,
            )
            from memory.event_log import log_event

            for rid in list(pending_routine_confirmations.keys()):
                pdata = pending_routine_confirmations.get(rid, {})
                ev = pdata.get("event", "?")

                _reason = "explicit_dismissal"
                _decay = True

                event_l = (ev or "").lower()
                is_partner_messenger = (
                    t("clients.telegram_bot.bot_msg_2e67ed") in event_l or
                    any(term in event_l for term in _partner_match_terms()) or
                    "messenger" in event_l or
                    t("clients.telegram_bot.bot_msg_500d81") in event_l
                )

                if is_partner_messenger and _looks_like_contextual_not_needed_reply(clean_user_text):
                    _reason = "user_already_with_partner"
                    _decay = False

                if _decay:
                    decay_routine(rid)
                    print(f"📉 [Routine Dismissed - Decayed]: {pdata}")
                    log_event(
                        "routines", 
                        "dismissed", 
                        routine_id=rid, 
                        event=ev,
                        debug_type="manual_control",
                        debug_source="user_message",
                        debug_effect="routine_changed",
                    )
                else:
                    mark_routine_responded(rid)
                    print(f"📉 [Routine Dismissed - Contextual, No Decay]: {pdata}")
                    log_event(
                        "routines",
                        "routine_context_skip",
                        routine_id=rid,
                        event=ev,
                        reason=_reason,
                        debug_type="manual_control",
                        debug_source="user_message",
                        debug_effect="no_decay"
                    )

                remove_pending_confirmation(rid)
                bus.emit("routine_dismissed", routine_id=rid, event=ev, channel="telegram")

                pending_routine_confirmations.pop(rid, None)

    # ── REFLECTION CONFIRMATION LOOP (ask-tier, 50-75% confidence) ──
    global pending_reflection_confirmations
    if pending_reflection_confirmations:
        text_check = _normalize_gr(clean_user_text)
        text_words = text_check.replace(",", "").replace(".", "").replace("!", "").split()
        yes_words = [_normalize_gr(w) for w in NLP_CONFIG.get("telegram", {}).get("confirm_tokens", [])]
        no_words  = [_normalize_gr(w) for w in [t("clients.telegram_bot.bot_msg_e0413c"), t("clients.telegram_bot.bot_msg_3e60e0"), "no", "cancel", t("clients.telegram_bot.bot_msg_5acd9c"), t("clients.telegram_bot.bot_msg_a7cf69")]]
        is_yes = any(w in text_words for w in yes_words)
        is_no  = any(w in text_words for w in no_words)

        if is_yes or is_no:
            import re as _re
            numbers = [int(n) for n in _re.findall(r"\d+", text_check)]
            # Mapping number -> reflection_id, based on the order of appearance
            # to the last numbered message (= insertion order in the dict).
            ordered_ids = list(pending_reflection_confirmations.keys())
            if numbers:
                targets = [ordered_ids[n - 1] for n in numbers if 1 <= n <= len(ordered_ids)]
            else:
                targets = ordered_ids  # without a number → all together (old behavior)

            if not targets:
                send_telegram_msg(t("clients.telegram_bot.bot_msg_fe2716"))
                return

            if is_yes:
                from services.reflection_engine import _apply_action, mark_reflection_applied
                lines = []
                for rid in targets:
                    rdata = pending_reflection_confirmations[rid]
                    success = _apply_action(rdata)
                    if success:
                        try:
                            mark_reflection_applied(rid)
                        except Exception as e:
                            print(f"⚠️ [Reflection Confirm] DB update failed: {e}")
                        lines.append(f"✅ Applied: {rdata.get('observation','')[:80]}")
                        del pending_reflection_confirmations[rid]
                    else:
                        lines.append(f"⚠️ Application failure, remains pending: {rdata.get('observation','')[:80]}")
                send_telegram_msg("\n".join(lines) if lines else t("clients.telegram_bot.bot_msg_59dadd"))
                if pending_reflection_confirmations:
                    _send_pending_reflections_summary()
                return
            else:
                from services.reflection_engine import mark_reflection_rejected
                for rid in targets:
                    try:
                        mark_reflection_rejected(rid)
                    except Exception as e:
                        print(f"⚠️ [Reflection Reject] DB update failed: {e}")
                    del pending_reflection_confirmations[rid]
                send_telegram_msg(t("clients.telegram_bot.bot_msg_4467b9"))
                if pending_reflection_confirmations:
                    _send_pending_reflections_summary()
                return

    # ── SAFE EXECUTOR CONFIRMATION LOOP ──────────────────────────
    global pending_exec_command
    if pending_exec_command:
        text_check = _normalize_gr(clean_user_text)
        if any(w in text_check for w in [_normalize_gr(w) for w in NLP_CONFIG.get("telegram", {}).get("confirm_tokens", [])]):
            cmd = pending_exec_command
            pending_exec_command = None
            from memory.event_log import log_event
            log_event("safe_executor", "confirmed_and_executed", cmd=cmd[:80])
            try:
                import subprocess
                result = subprocess.run(
                    ["powershell", "-Command", cmd],
                    capture_output=True, text=True, timeout=30,
                    encoding='utf-8', errors='ignore'
                )
                output = result.stdout if result.returncode == 0 else f"ERROR:\n{result.stderr}"
                if output.strip():
                    send_telegram_msg_full(output, prefix=t("clients.telegram_bot.bot_msg_0324c2"))
                else:
                    send_telegram_msg(t("clients.telegram_bot.bot_msg_67bac7"))
            except Exception as e:
                send_telegram_msg(f"❌ Execution error: {e}")
            return
        elif any(w in text_check for w in [_normalize_gr(w) for w in NLP_CONFIG.get("telegram", {}).get("cancel_tokens", [])]):
            pending_exec_command = None
            send_telegram_msg(t("clients.telegram_bot.bot_msg_7f065e"))
            return

    with memory_lock:
        last_interaction_time = time.time()

    # ── Pending photo: if a photo arrived without a caption recently, combine it ──
    global pending_photo
    photo_prefix = ""
    with pending_photo_lock:
        if pending_photo and (time.time() - pending_photo["timestamp"]) < 30:
            p = pending_photo
            pending_photo = None
            print(f"\033[94m[Photo+Msg]: Combination of pending photo + message\033[0m")
            _process_photo_with_question(p["filename"], p["path"], p["analysis"], clean_user_text, chat_id)
            return  # The _process_photo_with_question sent the response

    final_ai_response = ""
    handling_agent = "Chat_Agent"

    # ── PENDING ASSET CONFIRMATION ──────────────────────────────
    from memory.pending_assets import (
        clear_expired_pending_assets,
        get_latest_pending_asset,
        mark_pending_asset_confirmed,
        mark_pending_asset_cancelled,
        create_pending_asset_archive,
        classify_pending_asset_reply,
        looks_like_asset_confirmation_prompt,
    )
    clear_expired_pending_assets()
    from memory.pending_assets import is_reply_to_recent_asset_prompt
    pending_photo_asset = get_latest_pending_asset("telegram", "photo")
    pending_doc_asset = get_latest_pending_asset("telegram", "document")
    pending_asset = pending_photo_asset or pending_doc_asset
    reply_kind = classify_pending_asset_reply(clean_user_text) if pending_asset else None
    asset_prompt_active = is_reply_to_recent_asset_prompt("telegram") if pending_asset else False

    if pending_asset and reply_kind in {"yes", "no"} and not asset_prompt_active:
        print("[PendingAssetGuard]: ignored generic yes/no because no recent archive prompt was active")

    if pending_asset and reply_kind == "yes" and asset_prompt_active:
        if pending_asset["asset_type"] == "photo":
            memory.save(
                memory_type="photo",
                file_path=pending_asset["file_path"],
                analysis=pending_asset.get("analysis", ""),
                caption=pending_asset.get("caption", "") or pending_asset["filename"],
            )
        else:
            memory.save(
                memory_type="document",
                file_path=pending_asset["file_path"],
                analysis=pending_asset.get("analysis", ""),
                caption=pending_asset.get("caption", "") or pending_asset["filename"],
            )
            
        mark_pending_asset_confirmed(pending_asset["id"])
        confirm_reply = t("clients.telegram_bot.bot_msg_7e53ac")
        _send_and_record_assistant(confirm_reply, chat_id)
        enqueue_fast_task(log_exchange, clean_user_text, confirm_reply, "Chat_Agent", "telegram")
        enqueue_fast_task(update_working_memory, clean_user_text, confirm_reply)
        enqueue_fast_task(_enqueue_slow_memory_sifter, clean_user_text, confirm_reply, "Chat_Agent", "telegram")
        enqueue_slow_task(update_capabilities_from_exchange, clean_user_text, confirm_reply, "Chat_Agent")
        enqueue_slow_task(_enqueue_followup_pipeline, clean_user_text, confirm_reply, "Chat_Agent", "telegram")
        enqueue_slow_task(extract_and_update_context_flags, clean_user_text, confirm_reply)
        return

    if pending_asset and reply_kind == "no" and asset_prompt_active:
        mark_pending_asset_cancelled(pending_asset["id"])
        cancel_reply = t("clients.telegram_bot.bot_msg_b026c8")
        _send_and_record_assistant(cancel_reply, chat_id)
        enqueue_fast_task(log_exchange, clean_user_text, cancel_reply, "Chat_Agent", "telegram")
        enqueue_fast_task(update_working_memory, clean_user_text, cancel_reply)
        enqueue_fast_task(_enqueue_slow_memory_sifter, clean_user_text, cancel_reply, "Chat_Agent", "telegram")
        enqueue_slow_task(update_capabilities_from_exchange, clean_user_text, cancel_reply, "Chat_Agent")
        enqueue_slow_task(_enqueue_followup_pipeline, clean_user_text, cancel_reply, "Chat_Agent", "telegram")
        enqueue_slow_task(extract_and_update_context_flags, clean_user_text, cancel_reply)
        return

    # ── Messenger Draft Intent Guard ─────────────────────────────
    draft_active, draft_reason, draft_data = _safe_active_draft_status()
    draft_intent = _safe_classify_messenger_intent(
        clean_user_text,
        has_active_draft=draft_active,
    )

    if draft_intent and draft_intent.intent == "clear_draft":
        cleared = _safe_clear_draft()
        now_ts = datetime.now().strftime("%H:%M")
        final_ai_response = (
            t("clients.telegram_bot.bot_msg_draft_clear_done", now_ts=now_ts)
            if cleared
            else t("clients.telegram_bot.bot_msg_draft_clear_none", now_ts=now_ts)
        )

        try:
            send_telegram_msg(final_ai_response)
        except Exception:
            pass

        try:
            _append_to_analytics_log("user", clean_user_text)
            _append_to_analytics_log("ai", final_ai_response)
            from memory.execution_trace import ExecutionTrace
            _trace = ExecutionTrace(channel="telegram", user_message=clean_user_text)
            _trace.mark_phase("messenger_intent_clear_intercept", 1)
            _trace.finalize(response=final_ai_response)
            _trace.save()
        except Exception:
            pass

        return

    if draft_intent and draft_intent.intent == "clarify_draft":
        now_ts = datetime.now().strftime("%H:%M")
        if draft_active and draft_data and draft_data.get("message"):
            draft_message = str(draft_data.get("message") or "").strip()
            final_ai_response = t("clients.telegram_bot.bot_msg_draft_ask_action", now_ts=now_ts, draft=draft_message)
        else:
            final_ai_response = t("clients.telegram_bot.bot_msg_draft_empty_idea", now_ts=now_ts)

        try:
            send_telegram_msg(final_ai_response)
        except Exception:
            pass

        try:
            _append_to_analytics_log("user", clean_user_text)
            _append_to_analytics_log("ai", final_ai_response)
            from memory.execution_trace import ExecutionTrace
            _trace = ExecutionTrace(channel="telegram", user_message=clean_user_text)
            _trace.mark_phase("messenger_intent_clarify_intercept", 1)
            _trace.finalize(response=final_ai_response)
            _trace.save()
        except Exception:
            pass

        return

    if draft_intent and draft_intent.intent == "confirm_send":
        if draft_active and draft_data and draft_data.get("message") and draft_data.get("target_name"):
            import uuid
            from core.approval import save_pending, _notify_telegram
            
            call_id = f"call_{uuid.uuid4().hex[:12]}"
            
            save_pending("execute_local_pipeline", {}, call_id, channel="telegram")
            
            tool_call_fake = {
                "name": "execute_local_pipeline",
                "id": call_id,
                "args": {}
            }
            _notify_telegram(tool_call_fake)
            
            try:
                _append_to_analytics_log("user", clean_user_text)
                from memory.execution_trace import ExecutionTrace
                _trace = ExecutionTrace(channel="telegram", user_message=clean_user_text)
                _trace.mark_phase("messenger_intent_confirm_intercept_pending", 1)
                _trace.save()
            except Exception:
                pass

            return

    # ── Typing indicator — shows "Lobster is typing..." ──
    _typing_active = {"on": True}
    def _typing_loop():
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendChatAction"
        while _typing_active["on"]:
            try:
                requests.post(url, json={"chat_id": chat_id, "action": "typing"}, timeout=5)
            except Exception:
                pass
            time.sleep(4)  # Telegram shows typing for 5s — we refresh every 4s
    typing_thread = threading.Thread(target=_typing_loop, daemon=True)
    typing_thread.start()

    try:
        # ── Context: shared mixed history from SQLite ────────────
        t_context_0 = perf_counter()
        context_msgs, current_msg = _build_fast_chat_context(clean_user_text)
        context_load_ms = int((perf_counter() - t_context_0) * 1000)
        # ── Flow via LangGraph ───────────────────────────────────_
        import tools.system as _ts; _ts._CURRENT_CHANNEL = "telegram"
        from memory.execution_trace import ExecutionTrace
        _trace = ExecutionTrace(channel="telegram", user_message=clean_user_text)
        _trace.mark_phase("context_load_ms", context_load_ms)
        
        t_graph_0 = perf_counter()
        
        from core.utils import (
            is_simple_chat_fast_path_candidate,
            is_medium_web_chat_path_candidate,
            is_ultra_light_ack,
            get_ultra_light_ack_response,
            is_reply_to_recent_mail_prompt,
            is_reply_to_recent_linkedin_prompt,
            looks_like_terminal_linkedin_draft_result,
            build_linkedin_draft_ready_reply,
            should_attach_linkedin_draft_reply,
            looks_like_terminal_messenger_draft_result,
            build_messenger_draft_ready_reply,
        )
        
        is_ultra_ack = is_ultra_light_ack(clean_user_text)
        fast_path_used = False
        medium_path_used = False

        # 1. graph_call_ms
        graph_call_started = perf_counter()

        mail_prompt_active = is_reply_to_recent_mail_prompt(context_msgs)
        
        if is_ultra_ack and not mail_prompt_active:
            _trace.mark_phase("ultra_light_ack_used", 1)
            handling_agent = "UltraLightACK"
            final_ai_response = get_ultra_light_ack_response()
            print(f"\033[92m[Telegram->UltraLightACK]: Instant reply in '{clean_user_text}'\033[0m")
            events = []
        else:
            medium_path_used = is_medium_web_chat_path_candidate(clean_user_text)
            fast_path_used = (not medium_path_used) and is_simple_chat_fast_path_candidate(clean_user_text)

            _trace.mark_phase("fast_path_candidate", 1 if fast_path_used else 0)
            _trace.mark_phase("medium_path_candidate", 1 if medium_path_used else 0)

            if fast_path_used:
                events = _run_fast_chat_path(context_msgs, current_msg)
            elif medium_path_used:
                events = list(
                    graph.stream(
                        {"messages": context_msgs[-8:] + [current_msg], "channel": "telegram"},
                        {"recursion_limit": 24},
                    )
                )
            else:
                events = list(
                    graph.stream(
                        {"messages": context_msgs + [current_msg], "channel": "telegram"},
                        {"recursion_limit": 100},
                    )
                )
        graph_call_ms = int((perf_counter() - graph_call_started) * 1000)
        _trace.mark_phase("graph_call_ms", graph_call_ms)
        _trace.mark_phase("fast_path_used", 1 if fast_path_used else 0)
        _trace.mark_phase("medium_path_used", 1 if medium_path_used else 0)

        if fast_path_used:
            _trace.mark_phase("telegram_graph_budget", 12)
        elif medium_path_used:
            _trace.mark_phase("telegram_graph_budget", 24)
        else:
            _trace.mark_phase("telegram_graph_budget", 100)

        for event in events:
            _trace.process_event(event)

        # 2. graph_result_extract_ms
        extract_started = perf_counter()
        for event in events:
            for node, data in event.items():
                if data is None:
                    continue
                if node not in ["supervisor", "tools"]:
                    handling_agent = node
                    msgs = data.get("messages", [])
                    if msgs and hasattr(msgs[-1], "content"):
                        last_msg = msgs[-1]
                        # [MASTRO-FIX]: Skip intermediate tool-call steps
                        if getattr(last_msg, "tool_calls", None):
                            continue
                        from core.utils import clean_message
                        candidate_raw = clean_message(last_msg.content)
                        # Skip tool-call announcement strings (internal debug output)
                        if candidate_raw and not candidate_raw.startswith(t("clients.telegram_bot.bot_msg_78c917")):
                            final_ai_response = candidate_raw
        graph_result_extract_ms = int((perf_counter() - extract_started) * 1000)
        _trace.mark_phase("graph_result_extract_ms", graph_result_extract_ms)

        # 3. tool_message_collect_ms
        tool_collect_started = perf_counter()
        tool_result_fallbacks = []
        for event in events:
            for node, data in event.items():
                if data is None:
                    continue
                if node == "tools":
                    for msg in data.get("messages", []):
                        if getattr(msg, "type", "") == "tool":
                            tool_content = clean_message(getattr(msg, "content", "")).strip()
                            if tool_content:
                                tool_result_fallbacks.append(tool_content)
        tool_message_collect_ms = int((perf_counter() - tool_collect_started) * 1000)
        _trace.mark_phase("tool_message_collect_ms", tool_message_collect_ms)

        graph_stream_ms = int((perf_counter() - t_graph_0) * 1000)
        _trace.mark_phase("graph_stream_ms", graph_stream_ms)

        # 4. final_response_build_ms
        response_build_started = perf_counter()

        if final_ai_response:
            final_ai_response = clean_message(final_ai_response).strip()
            
            from core.utils import strip_operational_assistant_paragraphs
            cleaned_response = strip_operational_assistant_paragraphs(final_ai_response).strip()
            if cleaned_response:
                final_ai_response = cleaned_response

        linkedin_prompt_active = is_reply_to_recent_linkedin_prompt(context_msgs)
        if should_attach_linkedin_draft_reply(
            clean_user_text,
            tool_result_fallbacks,
            recent_linkedin_prompt_active=linkedin_prompt_active,
        ):
            final_ai_response = build_linkedin_draft_ready_reply(tool_result_fallbacks)

        if any(looks_like_terminal_messenger_draft_result(r) for r in tool_result_fallbacks):
            is_confirm = draft_intent and draft_intent.intent == 'confirm_send'
            if not is_confirm:
                final_ai_response = build_messenger_draft_ready_reply(tool_result_fallbacks)

        if not final_ai_response:
            t_fallback_0 = perf_counter()
            final_ai_response = _tool_results_fallback_response(clean_user_text, tool_result_fallbacks)
            fallback_ms = int((perf_counter() - t_fallback_0) * 1000)
            _trace.mark_phase("fallback_llm_ms", fallback_ms)

        if not final_ai_response:
            # [MASTRO-FIX]: Fallback when the agent did not generate text (e.g., loop/recursion)
            send_telegram_msg(t("clients.telegram_bot.bot_msg_125f2d"))
            return

        file_path_to_send = None
        if final_ai_response:
            # --- MASTRO INTERCEPTOR FOR DOCUMENTS ---
            file_match = re.search(r"\[CREATED_FILE:\s*(.*?)\]", final_ai_response)
            if file_match:
                file_path_to_send = file_match.group(1).strip()
                final_ai_response = re.sub(r"\[CREATED_FILE:\s*(.*?)\]", "", final_ai_response).strip()

        final_response_build_ms = int((perf_counter() - response_build_started) * 1000)
        _trace.mark_phase("final_response_build_ms", final_response_build_ms)

        _trace.agent = handling_agent
        _trace.finalize(response=final_ai_response or None)

        if final_ai_response:
            final_ai_response = _strip_existing_time_prefix(final_ai_response)
            if file_path_to_send:
                if final_ai_response:
                    if is_voice_mode:
                        import asyncio
                        t_voice_0 = perf_counter()
                        asyncio.run(send_telegram_voice(final_ai_response))
                        voice_send_ms = int((perf_counter() - t_voice_0) * 1000)
                        _trace.mark_phase("telegram_voice_send_ms", voice_send_ms)
                    else:
                        t_send_0 = perf_counter()
                        _mid = send_telegram_msg(final_ai_response)
                        send_ms = int((perf_counter() - t_send_0) * 1000)
                        _trace.mark_phase("telegram_send_ms", send_ms)
                        _cache_bot_message(_mid, final_ai_response)

                # Send the file to Telegram as a document
                try:
                    from tools.telegram import send_telegram_document
                    import os as _os
                    _fname = _os.path.basename(file_path_to_send)
                    send_telegram_document(file_path_to_send, caption=f"📎 <b>{_fname}</b>")
                except Exception as _de:
                    print(f"❌ [Doc send error]: {_de}")
                    send_telegram_msg(t("clients.telegram_bot.bot_msg_file", file=file_path_to_send))
            else:
                # Normal Flow (No Documents)
                if is_voice_mode:
                    import asyncio
                    t_voice_0 = perf_counter()
                    asyncio.run(send_telegram_voice(final_ai_response))
                    voice_send_ms = int((perf_counter() - t_voice_0) * 1000)
                    _trace.mark_phase("telegram_voice_send_ms", voice_send_ms)
                else:
                    t_send_0 = perf_counter()
                    _mid = send_telegram_msg(final_ai_response)
                    send_ms = int((perf_counter() - t_send_0) * 1000)
                    _trace.mark_phase("telegram_send_ms", send_ms)
                    _cache_bot_message(_mid, final_ai_response)
            # We keep context for the next message
            _typing_active["on"] = False  # We stop typing
            _append_to_analytics_log("user", clean_user_text)
            _append_to_analytics_log("ai", final_ai_response)
            # Photos
            if "[SEND_PHOTO:" in final_ai_response:
                match = re.search(r"\[SEND_PHOTO:\s*(.+?)\]", final_ai_response)
                if match:
                    photo_path = match.group(1).strip()
                    try:
                        _send_photo_to_telegram(photo_path, chat_id)
                    except:
                        pass

            # Background Tasks
            t_bg_0 = perf_counter()
            enqueue_fast_task(log_exchange,                       user_text, final_ai_response, handling_agent, "telegram")
            enqueue_fast_task(update_working_memory,              user_text, final_ai_response)
            enqueue_fast_task(_enqueue_slow_memory_sifter,        user_text, final_ai_response, handling_agent, "telegram")
            enqueue_slow_task(update_capabilities_from_exchange,  user_text, final_ai_response, handling_agent)
            enqueue_slow_task(_enqueue_followup_pipeline, user_text, final_ai_response, handling_agent, "telegram")
            enqueue_slow_task(extract_and_update_context_flags, user_text, final_ai_response)
            
            background_enqueue_ms = int((perf_counter() - t_bg_0) * 1000)
            _trace.mark_phase("background_enqueue_ms", background_enqueue_ms)
            _trace.save()

    except Exception as e:
        _typing_active["on"] = False  # We stop typing even on error
        send_telegram_msg(t("clients.telegram_bot.bot_msg_error", e=str(e)))

def _send_photo_to_telegram(photo_path: str, chat_id: str):
    """Sends a photo file to the Telegram chat."""
    if not os.path.exists(photo_path):
        send_telegram_msg(t("clients.telegram_bot.bot_msg_photo_not_found", path=photo_path))
        return
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendPhoto"
        with open(photo_path, "rb") as photo_file:
            requests.post(
                url,
                data={"chat_id": chat_id},
                files={"photo": photo_file},
                timeout=30
            )
        print(f"\033[92m[TelegramBot]: Photo sent: {photo_path}\033[0m")
    except Exception as e:
        print(f"\033[91m[TelegramBot Photo Send Error]: {e}\033[0m")
        send_telegram_msg(t("clients.telegram_bot.bot_msg_photo_send_fail", e=str(e)))
_DEPARTURE_ANCHOR_SECONDS = 45 * 60
_DEPARTURE_DISTANCE_METERS = 300
_DEPARTURE_FOLLOWUP_TTL_HOURS = 1


def _haversine_distance_meters(lat1, lon1, lat2, lon2) -> float:
    import math

    radius_m = 6_371_000
    radians = math.pi / 180
    a = (
        math.sin((lat2 - lat1) * radians / 2) ** 2
        + math.cos(lat1 * radians)
        * math.cos(lat2 * radians)
        * math.sin((lon2 - lon1) * radians / 2) ** 2
    )
    return 2 * radius_m * math.asin(math.sqrt(a))
def handle_location(msg, live_update=False):
    """Receives live location and checks for location-based reminders."""
    import math

    chat_id = str(msg.get("chat", {}).get("id", ""))
    loc     = msg.get("location", {})
    lat     = loc.get("latitude")
    lon     = loc.get("longitude")
    if lat is None or lon is None:
        return
    departure_event = None
    try:
        from config import GPS_STORAGE_FILE
        import time

        now_ts = time.time()
        gps_data = {}

        if os.path.exists(GPS_STORAGE_FILE):
            try:
                with open(GPS_STORAGE_FILE, "r", encoding="utf-8") as f:
                    stored_data = json.load(f)
                if isinstance(stored_data, dict):
                    gps_data = stored_data
            except (OSError, ValueError, json.JSONDecodeError):
                gps_data = {}

        try:
            anchor_lat = float(gps_data.get("anchor_lat", lat))
            anchor_lon = float(gps_data.get("anchor_lon", lon))
            anchor_ts = float(gps_data.get("anchor_timestamp", now_ts))
        except (TypeError, ValueError):
            anchor_lat, anchor_lon, anchor_ts = lat, lon, now_ts

        distance_m = _haversine_distance_meters(anchor_lat, anchor_lon, lat, lon)
        anchored_seconds = max(0, now_ts - anchor_ts)

        if distance_m > _DEPARTURE_DISTANCE_METERS:
            if anchored_seconds >= _DEPARTURE_ANCHOR_SECONDS:
                departure_event = {
                    "anchor_minutes": int(anchored_seconds // 60),
                    "distance_meters": int(distance_m),
                }

                # For live departures, preserve the old anchor until persistence
                # succeeds so a transient database error can be retried.
                if not live_update:
                    anchor_lat, anchor_lon, anchor_ts = lat, lon, now_ts
            else:
                # A short stop is not a departure event; begin a new anchor now.
                anchor_lat, anchor_lon, anchor_ts = lat, lon, now_ts

        gps_data.update(
            {
                "lat": lat,
                "lon": lon,
                "timestamp": now_ts,
                "anchor_lat": anchor_lat,
                "anchor_lon": anchor_lon,
                "anchor_timestamp": anchor_ts,
            }
        )
        with open(GPS_STORAGE_FILE, "w", encoding="utf-8") as f:
            json.dump(gps_data, f, ensure_ascii=False)
    except OSError as exc:
        print(f"\033[91m[Location State Error]: {exc}\033[0m")
    #print(f"\033[94m[Location]: {lat}, {lon}\033[0m")

    # ── Location Reminders (SQL: time = 'loc:<name>' convention) ──
    try:
        import sqlite3
        from config import HOME_COORDS, HOME_RADIUS_M, STATE_DB

        def haversine(lat1, lon1, lat2, lon2):
            R = 6371000
            p = math.pi / 180
            a = (math.sin((lat2-lat1)*p/2)**2 +
                 math.cos(lat1*p) * math.cos(lat2*p) *
                 math.sin((lon2-lon1)*p/2)**2)
            return 2 * R * math.asin(math.sqrt(a))

        if os.path.exists(STATE_DB):
            conn = sqlite3.connect(STATE_DB)
            try:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT id, task, time FROM reminders WHERE status='pending' AND time LIKE 'loc:%'"
                )
                pending = cursor.fetchall()
                if pending:
                    pass # print("HANDLE_LOCATION PENDING:", pending)
                for rid, task, tm in pending:
                    target = tm.split(":", 1)[1] if tm and ":" in tm else "home"
                    if target == "home":
                        dist = haversine(lat, lon, HOME_COORDS[0], HOME_COORDS[1])
                        if dist <= HOME_RADIUS_M:
                            _send_and_record_assistant(
                                f"📍 REMINDER (You reached home!): {task}",
                                agent="Reminder_Agent",
                            )
                            print(f"\033[93m[Location Reminder]: {task} fired ({dist:.0f}m)\033[0m")
                            cursor.execute("UPDATE reminders SET status='done' WHERE id=?", (rid,))
                conn.commit()
            finally:
                conn.close()
    except Exception as e:
        print(f"\033[91m[Location Reminder Error]: {e}\033[0m")

    # ── Web Agent only for manual location (no live updates) ──
    if live_update:
        if departure_event:
            from memory.pending_followups import _local_now

            event_now = _local_now()
            from memory.pending_followups import create_pending_followup

            import sqlite3

            try:
                followup_id = create_pending_followup(
                    source_channel="telegram",
                    source_agent="Location_Event",
                    topic="departure",
                    subject="stable_location_departure",
                    source_user_text=(
                        "Live location detected departure after a stable stay of "
                        f"{departure_event['anchor_minutes']} minutes."
                    ),
                    source_ai_text="",
                    followup_after_ts=event_now.isoformat(timespec="seconds"),
                    confidence=0.70,
                    metadata={
                        "reason": "live_location_departure",
                        "anchor_duration_minutes": departure_event["anchor_minutes"],
                        "departure_distance_meters": departure_event["distance_meters"],
                        "defer_count": 0,
                    },
                    ttl_hours=_DEPARTURE_FOLLOWUP_TTL_HOURS,
                )
            except sqlite3.Error as exc:
                print(f"\033[91m[DepartureFollowUp Error]: {exc}\033[0m")
                return

            # Successful create or active-arc dedupe consumes this departure.
            anchor_lat, anchor_lon, anchor_ts = lat, lon, now_ts
            gps_data.update(
                {
                    "anchor_lat": anchor_lat,
                    "anchor_lon": anchor_lon,
                    "anchor_timestamp": anchor_ts,
                }
            )
            try:
                with open(GPS_STORAGE_FILE, "w", encoding="utf-8") as f:
                    json.dump(gps_data, f, ensure_ascii=False)
            except OSError as exc:
                print(f"\033[91m[Location State Error]: {exc}\033[0m")

            if followup_id:
                print(
                    f"[DepartureFollowUp]: created #{followup_id} "
                    f"after {departure_event['anchor_minutes']}m / "
                    f"{departure_event['distance_meters']}m"
                )

        return

    from core.graph import graph
    from langchain_core.messages import HumanMessage
    location_prompt = core.i18n.load_prompt("telegram_bot_location_update.md").format(language=config.RESPONSE_LANGUAGE, user_name=config.USER_NAME, lat=lat, lon=lon)
    try:
        final = ""
        for event in graph.stream({"messages": [HumanMessage(content=location_prompt)]}):
            for node, data in event.items():
                if data is None:
                    continue
                msgs = data.get("messages", [])
                if msgs and hasattr(msgs[-1], "content"):
                    content = msgs[-1].content
                    if isinstance(content, list):
                        content = " ".join(p.get("text","") for p in content if isinstance(p, dict))
                    if content.strip():
                        final = content.strip()
        if final:
            from core.agents import clean_message
            send_telegram_msg(clean_message(final))
    except Exception as e:
        print(f"\033[91m[Location Handler Error]: {e}\033[0m")
        send_telegram_msg(t("clients.telegram_bot.bot_msg_location", lat=lat, lon=lon))

# ────────────────────────────────────────────────────────────────
# POLLING LOOP
# ────────────────────────────────────────────────────────────────

def _handle_approval_callback(cq: dict):
    """Handles the ✅/❌ approval callbacks from inline keyboard."""
    try:
        from core.approval import execute_approved_pending, get_pending, pop_pending
        from tools.system import all_tools

        cq_id   = cq["id"]
        data    = cq.get("data", "")
        chat_id = str(cq["message"]["chat"]["id"])
        msg_id  = cq["message"]["message_id"]

        # Answer the callback (remove loading spinner)
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/answerCallbackQuery",
            json={"callback_query_id": cq_id},
            timeout=5,
        )

        if ":" not in data:
            return

        action, tool_call_id = data.split(":", 1)

        if action == "approve":
            item = get_pending(tool_call_id)  # get first, NOT pop
            if not item:
                # Duplicate/stale callback after a reload or an already executed action.
                # Keep the chat quiet and just remove the old inline keyboard if possible.
                requests.post(
                    f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/editMessageReplyMarkup",
                    json={"chat_id": chat_id, "message_id": msg_id, "reply_markup": {"inline_keyboard": []}},
                    timeout=5,
                )
                print(f"\033[93m[ApprovalCallback]: stale approve callback ignored ({tool_call_id})\033[0m")
                return

            tool_name = item["tool_name"]
            origin_channel = item.get("channel", "telegram")

            # Update keyboard → "✅ Approved"
            requests.post(
                f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/editMessageReplyMarkup",
                json={"chat_id": chat_id, "message_id": msg_id, "reply_markup": {"inline_keyboard": []}},
                timeout=5,
            )

            if tool_name != "execute_local_pipeline":
                send_telegram_msg(t("clients.telegram_bot.bot_msg_tool_exec", tool=tool_name))

            execution = execute_approved_pending(tool_call_id, all_tools)
            
            if origin_channel == "web":
                if execution["ok"]:
                    send_telegram_msg(t("clients.telegram_bot.bot_msg_tool_success_web", tool=tool_name))
                    
                    try:
                        from api.server import append_to_chat_history

                        final_resp = _build_web_approval_result_message(
                            tool_name,
                            execution.get("result"),
                        )
                        append_to_chat_history("assistant", final_resp, agent="Web_Agent")
                    except Exception as e:
                        print(f"[ApprovalCallback Web Resume Error]: {e}")

                elif execution["status"] == "tool_not_found":
                    send_telegram_msg(t("clients.telegram_bot.bot_msg_tool_not_found_web", tool=tool_name))
                    try:
                        from api.server import append_to_chat_history
                        append_to_chat_history("assistant", t("clients.telegram_bot.bot_msg_tool_not_found_web_hist", tool=tool_name), agent="Web_Agent")
                    except Exception as e:
                        print(f"[ApprovalCallback Web Error Notify]: {e}")
                else:
                    send_telegram_msg(t("clients.telegram_bot.bot_msg_tool_fail_web", tool=tool_name, e=execution["error"]))
                    try:
                        from api.server import append_to_chat_history
                        append_to_chat_history(
                            "assistant",
                            t("clients.telegram_bot.bot_msg_tool_fail_web_hist", tool=tool_name, e=execution["error"]),
                            agent="Web_Agent",
                        )
                    except Exception as e:
                        print(f"[ApprovalCallback Web Error Notify]: {e}")
            else:
                if execution["ok"]:
                    if tool_name == "execute_local_pipeline":
                        send_telegram_msg(t("clients.telegram_bot.bot_msg_df3588"))
                    else:
                        send_telegram_msg_full(
                            str(execution["result"]),
                            prefix="✅ `" + tool_name + t("clients.telegram_bot.bot_msg_3fadfb"),
                        )
                elif execution["status"] == "tool_not_found":
                    send_telegram_msg(t("clients.telegram_bot.bot_msg_tool_not_found", tool=tool_name))
                else:
                    send_telegram_msg(t("clients.telegram_bot.bot_msg_tool_fail", tool=tool_name, e=execution["error"]))
        elif action == "reject":
            item = get_pending(tool_call_id)
            origin_channel = (item or {}).get("channel", "telegram")
            tool_name = (item or {}).get("tool_name", t("clients.telegram_bot.bot_msg_596fbf"))
            pop_pending(tool_call_id)
            requests.post(
                f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/editMessageReplyMarkup",
                json={"chat_id": chat_id, "message_id": msg_id, "reply_markup": {"inline_keyboard": []}},
                timeout=5,
            )
            send_telegram_msg(t("clients.telegram_bot.bot_msg_b2a34d"))
            if origin_channel == "web":
                try:
                    from api.server import append_to_chat_history
                    append_to_chat_history(
                        "assistant",
                        t("clients.telegram_bot.bot_msg_tool_cancel", tool=tool_name),
                        agent="Web_Agent",
                    )
                except Exception as e:
                    print(f"[ApprovalCallback Web Reject Notify]: {e}")

    except Exception as e:
        print(f"\033[91m[ApprovalCallback]: {e}\033[0m")


def _handle_message_reaction(reaction: dict) -> None:
    """
    When {config.USER_NAME} reacts with ❤️ to a message from {config.BOT_NAME},
    it saves the content of the message to the long-term memory.
    """
    try:
        chat_id = str(reaction.get("chat", {}).get("id", ""))
        if chat_id != str(TELEGRAM_CHAT_ID):
            return

        # Only new reactions (not removal)
        new_reactions = reaction.get("new_reaction", [])
        emojis = [r.get("emoji", "") for r in new_reactions if r.get("type") == "emoji"]
        if "❤" not in emojis and "❤️" not in emojis:
            return

        # Find the content of the message that was reacted to
        msg_id = reaction.get("message_id")
        bot_text = None

        # 1. First search in the in-memory cache (exact match)
        with _bot_message_cache_lock:
            bot_text = _bot_message_cache.get(msg_id)

        # 2. Fallback: last assistant message from SQLite
        if not bot_text:
            try:
                from memory.conversation_history import load_messages
                recent = load_messages(channel="telegram", limit=20)
                for entry in reversed(recent):
                    if entry.get("role") in ("assistant", "ai", "bot"):
                        bot_text = entry.get("content", "")
                        break
            except Exception as e:
                print(f"⚠️ [Reaction]: history lookup failed: {e}")

        if not bot_text:
            send_telegram_msg(t("clients.telegram_bot.bot_msg_3d8488"))
            return

        from core.utils import looks_like_operational_assistant_text

        if looks_like_operational_assistant_text(bot_text):
            print("\033[90m[Reaction ❤️]: operational assistant text skip\033[0m")
            send_telegram_msg(t("clients.telegram_bot.bot_msg_4379e1"))
            return

        # Save to long-term memory`of`
        preview = bot_text[:80].replace("\n", " ")
        print(f"\033[92m[Reaction ❤️]: Saving: {preview}...\033[0m")
        threading.Thread(
            target=_save_reaction_to_memory,
            args=(bot_text,),
            daemon=True
        ).start()

    except Exception as e:
        print(f"⚠️ [Reaction Handler]: {e}")


def _save_reaction_to_memory(text: str) -> None:
    """Background: stores the text in ChromaDB and sends a notification."""
    try:
        from core.utils import looks_like_operational_assistant_text

        if looks_like_operational_assistant_text(text):
            print("\033[90m[Reaction Save]: skipped operational assistant text\033[0m")
            return

        from tools.system import save_to_memory
        preview = text[:60].replace("\n", " ")
        result = save_to_memory.invoke({
            "fact": text,
            "entities": t("clients.telegram_bot.bot_msg_eb0632"),
            "category": "saved_by_user",
        })
        send_telegram_msg(t("clients.telegram_bot.bot_msg_memory_saved", preview=preview))
    except Exception as e:
        print(f"⚠️ [Reaction Save]: {e}")


def run_polling():
    """Long-polling loop — reads updates from the Telegram API."""
    global voice_mode_enabled
    if not TELEGRAM_TOKEN:
        print("\033[91m[TelegramBot]: Missing TELEGRAM_TOKEN!\033[0m")
        return

    if not TELEGRAM_CHAT_ID:
        print("\033[91m[TelegramBot]: Missing TELEGRAM_CHAT_ID!\033[0m")
        return

    # ── Definition of commands in the Telegram menu (the "/" autocomplete) ──────────────
    _bot_commands = [
        {"command": "g",                "description": t("clients.telegram_bot.bot_msg_8023cc")},
        {"command": "gr",               "description": t("clients.telegram_bot.bot_msg_29b0b6")},
        {"command": "g_phrases",        "description": t("clients.telegram_bot.bot_msg_e6b247")},
        {"command": "nutrition",        "description": t("clients.telegram_bot.bot_msg_c88847")},
        {"command": "receipt",          "description": t("clients.telegram_bot.bot_msg_cfa8e2")},
        {"command": "story",            "description": t("clients.telegram_bot.bot_msg_0a3ea6")},
        {"command": "voice",            "description": t("clients.telegram_bot.bot_msg_7c1625")},
        {"command": "status",           "description": t("clients.telegram_bot.bot_msg_12478c")},
        {"command": "doctor",           "description": t("clients.telegram_bot.bot_msg_cde5a6")},
        {"command": "mute",             "description": t("clients.telegram_bot.bot_msg_664071")},
        {"command": "pause",            "description": t("clients.telegram_bot.bot_msg_06c029")},
        {"command": "resume",           "description": t("clients.telegram_bot.bot_msg_23b7f3")},
        {"command": "end",              "description": t("clients.telegram_bot.bot_msg_f27666")},
        {"command": "help",             "description": t("clients.telegram_bot.bot_msg_6c8aa9")},
    ]
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/setMyCommands",
            json={"commands": _bot_commands},
            timeout=10,
        )
        print("\033[92m[TelegramBot]: Bot commands menu updated ✓\033[0m")
    except Exception as _e:
        print(f"\033[93m[TelegramBot]: setMyCommands failed: {_e}\033[0m")

    offset = 0
    print(f"\033[92m[TelegramBot]: Polling started (allowed chat: {TELEGRAM_CHAT_ID})\033[0m")

    while not shutdown_event.is_set():
        try:
            resp = requests.get(
                f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates",
                params={"offset": offset, "timeout": 30, "allowed_updates": '["message","callback_query","message_reaction","edited_message"]'},
                timeout=35
            )

            if resp.status_code != 200:
                print(f"\033[91m[TelegramBot]: API Error {resp.status_code}\033[0m")
                time.sleep(5)
                continue

            updates = resp.json().get("result", [])

            for update in updates:
                offset = update["update_id"] + 1

                # ── Approval callbacks (inline keyboard ✅/❌) ──────────
                cq = update.get("callback_query")
                if cq:
                    _handle_approval_callback(cq)
                    continue

                # ── ❤️ Reaction → save bot message to memory ──────────
                reaction = update.get("message_reaction")
                if reaction:
                    _handle_message_reaction(reaction)
                    continue

                # [MASTRO-FIX]: We also catch Live Locations that arrive as edited_message
                msg = update.get("message") or update.get("edited_message")
                if not msg:
                    continue
                
                chat_id = str(msg["chat"]["id"])

                # Security: only the configured user
                if chat_id != str(TELEGRAM_CHAT_ID):
                    print(f"\033[93m[TelegramBot]: Unauthorized chat: {chat_id}\033[0m")
                    continue

                # 1. Location (GPS) - Only once, in a thread, passing the entire msg
                if "location" in msg:
                    is_live_update = "edited_message" in update
                    threading.Thread(
                        target=handle_location,
                        args=(msg,),
                        kwargs={"live_update": is_live_update},
                        daemon=True
                    ).start()
                    continue

                # 2. Photo
                if "photo" in msg:
                    caption = msg.get("caption", "")
                    threading.Thread(
                        target=handle_photo,
                        args=(msg["photo"], caption, chat_id),
                        daemon=True
                    ).start()
                    continue

                # 3. Voice (Voice)
                if "voice" in msg:
                    threading.Thread(
                        target=handle_voice,
                        args=(msg["voice"], chat_id),
                        daemon=True
                    ).start()
                    continue

                # 4. Documents (PDF, etc.)
                if "document" in msg:
                    caption = msg.get("caption", "")
                    threading.Thread(
                        target=handle_document,
                        args=(msg["document"], caption, chat_id),
                        daemon=True
                    ).start()
                    continue
                
                # 5. Text & Commands
                user_text = msg.get("text", "").strip()
                if not user_text:
                    continue

                # --- [MASTRO-COMMANDS] ---
                cmd = user_text.lower().strip()

                if not cmd.startswith("/") and _consume_pending_georgian():
                    _send_georgian_translation(user_text)
                    continue
                if not cmd.startswith("/") and _consume_pending_partner():
                    _send_georgian_translation(user_text, force_src="ka")
                    continue
                if cmd.startswith("/") and cmd not in ("/georgian", "/geo", "/g", "/georgian_phrases", "/gr", "/greek"):
                    _clear_pending_georgian()
                    _clear_pending_partner()

                if cmd == "/pause":
                    with _override_lock:
                        _override_state["pause_reminders"] = True
                    _save_override_state()
                    send_telegram_msg(t("clients.telegram_bot.bot_msg_4c769a"))
                    continue

                if cmd == "/mute":
                    with _override_lock:
                        _override_state["mute_proactive"] = True
                    _save_override_state()
                    send_telegram_msg(t("clients.telegram_bot.bot_msg_c9478b"))
                    continue

                if cmd.startswith("/sleep"):
                    parts = cmd.split()
                    hours = float(parts[1]) if len(parts) > 1 else 8.0
                    with _override_lock:
                        _override_state["sleep_until"] = _time.time() + hours * 3600
                    _save_override_state()
                    send_telegram_msg(t("clients.telegram_bot.bot_msg_sleep_mode", hours=f"{hours:.0f}"))
                    continue

                if cmd == "/resume":
                    with _override_lock:
                        _override_state.update({"pause_reminders": False, "mute_proactive": False, "sleep_until": None})
                    _save_override_state()
                    send_telegram_msg(t("clients.telegram_bot.bot_msg_b33ab5"))
                    continue
                if user_text.lower().startswith("/confirm"):
                    cmd_to_confirm = user_text[len("/confirm"):].strip()
                    if not cmd_to_confirm:
                        send_telegram_msg(t("clients.telegram_bot.bot_msg_359906"))
                        continue
                    pending_exec_command = cmd_to_confirm
                    send_telegram_msg(
                        t("clients.telegram_bot.bot_msg_confirm_req", cmd=cmd_to_confirm)
                    )
                    continue
                if cmd == "/help":
                    voice_status = "🔊 ON" if voice_mode_enabled else "✍️ OFF"
                    send_telegram_msg(
                        t("clients.telegram_bot.bot_msg_commands_title", bot_name=config.BOT_NAME) +
                        t("clients.telegram_bot.bot_msg_help_menu", voice_status=voice_status)
                    )
                    continue

                if cmd == "/doctor":
                    try:
                        from tools.system import system_doctor
                        send_telegram_msg(system_doctor(days=1))
                    except Exception as e:
                        send_telegram_msg(t("clients.telegram_bot.bot_msg_doctor_error", e=e))
                    continue

                if cmd == "/status":
                    if astakos_scheduler:
                        send_telegram_msg(astakos_scheduler.status())
                    else:
                        send_telegram_msg(t("clients.telegram_bot.bot_msg_8c16dd"))
                    continue

                if cmd == "/voice":
                    voice_mode_enabled = not voice_mode_enabled
                    if voice_mode_enabled:
                        send_telegram_msg(t("clients.telegram_bot.bot_msg_c19e9a"))
                    else:
                        send_telegram_msg(t("clients.telegram_bot.bot_msg_adde11"))
                    continue

                if cmd in ("/georgian", "/geo", "/g", "/georgian_phrases"):
                    from tools.georgian import phrases_message
                    rest = user_text[len(cmd):].strip()

                    # /georgian_phrases → quick list
                    if cmd == "/georgian_phrases" or rest.lower() == "phrases":
                        send_telegram_msg(phrases_message())
                        continue

                    # /georgian without text → instructions
                    if not rest:
                        _arm_pending_georgian()
                        send_telegram_msg(
                            t("clients.telegram_bot.bot_msg_42fbb6")
                        )
                        continue

                    _send_georgian_translation(rest)
                    continue

                if cmd in ("/gr", "/greek"):
                    rest = user_text[len(cmd):].strip()
                    if rest:
                        # Direct translation ka→el
                        _send_georgian_translation(rest, force_src="ka")
                    else:
                        # Pending mode: next message is considered Georgian
                        _arm_pending_partner()
                        send_telegram_msg(t("clients.telegram_bot.bot_msg_bdc64e"))
                    continue

                if user_text.lower() == "/nutrition":
                    global pending_photo
                    with pending_photo_lock:
                        p = pending_photo if (pending_photo and (time.time() - pending_photo["timestamp"]) < 30) else None
                        if p:
                            pending_photo = None
                    if p:
                        send_telegram_msg(t("clients.telegram_bot.bot_msg_0e0401"))
                        threading.Thread(
                            target=_run_nutrition,
                            args=(p["path"], chat_id),
                            daemon=True
                        ).start()
                    else:
                        send_telegram_msg(t("clients.telegram_bot.bot_msg_28166e"))
                    continue

                if user_text.lower() == "/receipt":
                    with pending_photo_lock:
                        p = pending_photo if (pending_photo and (time.time() - pending_photo["timestamp"]) < 30) else None
                        if p:
                            pending_photo = None
                    if p:
                        send_telegram_msg(t("clients.telegram_bot.bot_msg_b2c62a"))
                        threading.Thread(
                            target=_run_receipt,
                            args=(p["path"], chat_id),
                            daemon=True
                        ).start()
                    else:
                        send_telegram_msg(t("clients.telegram_bot.bot_msg_f4f189"))
                    continue

                if user_text.lower() == "/end":
                    print(f"\033[94m[Telegram]: End session command from {config.USER_NAME}.\033[0m")
                    threading.Thread(
                        target=handle_end_session,
                        args=(chat_id,),
                        daemon=True
                    ).start()
                    continue

                if cmd.startswith("/story"):
                    # /story [theme]  or  /story [theme] | [characters]
                    rest = user_text[len("/story"):].strip()
                    if "|" in rest:
                        theme_part, chars_part = rest.split("|", 1)
                        story_theme = theme_part.strip()
                        story_chars = chars_part.strip()
                    else:
                        story_theme = rest or t("clients.telegram_bot.bot_msg_9e64ca")
                        story_chars = ""
                    send_telegram_msg(t("clients.telegram_bot.bot_msg_creating_story", story_theme=story_theme))
                    threading.Thread(
                        target=_run_story_maker,
                        args=(story_theme, story_chars, chat_id),
                        daemon=True
                    ).start()
                    continue

                # Regular message to the Lobster
                print(f"\n\033[96m[Telegram] {config.USER_NAME}: {user_text}\033[0m")
                threading.Thread(
                    target=handle_message,
                    args=(user_text, chat_id),
                    daemon=True
                ).start()

        except requests.exceptions.Timeout:
            continue
        except Exception as e:
            print(f"\033[91m[TelegramBot Polling Error]: {e}\033[0m")
            time.sleep(5)

# ────────────────────────────────────────────────────────────────
# SCHEDULER JOBS (without while loop — called by the scheduler)
# ────────────────────────────────────────────────────────────────

def job_check_reminders():
    """Checks for reminders (SQL) and sends them to Telegram."""
    if is_reminders_paused():
        return
    import sqlite3
    from config import STATE_DB
    if not os.path.exists(STATE_DB):
        return
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    conn = None
    try:
        conn = sqlite3.connect(STATE_DB)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, task FROM reminders WHERE status='pending' AND time NOT LIKE 'loc:%' AND time <= ?",
            (now,),
        )
        due = cursor.fetchall()
        for rid, task in due:
            msg = f"🔔 REMINDER: {task}"
            if is_duplicate_notification(msg, cooldown_seconds=60):
                continue
            _send_and_record_assistant(msg, agent="Routine_Agent")
            log_event("reminders", "sent", task=task)
            cursor.execute("UPDATE reminders SET status='done' WHERE id=?", (rid,))
            conn.commit()
    except Exception as e:
        print(f"\033[91m[ReminderCheck Error]: {e}\033[0m")
    finally:
        if conn:
            conn.close()

def _load_recent_proactive_context(limit: int = 10) -> str:
    """Return a compact mixed-channel conversation snippet for proactive messages."""
    try:
        from memory.context_builder import build_memory_context

        context = build_memory_context(
            "",
            channel="telegram",
            recent_limit=limit,
            semantic_k=0,
            write_debug=True,
        )
        return "\n".join(context.recent_lines)
    except Exception as exc:
        print(f"\033[93m[ProactiveContext]: failed to load recent context: {exc}\033[0m")
        return ""


def _build_proactive_memory_context(event_name: str) -> str:
    """Build richer context for routine nudges, including recent cancellation clues."""
    try:
        from memory.context_builder import build_memory_context

        recall_query = (
            f"do you remember {event_name}; recent context regarding if the routine is still valid, "
            f"if it already happened, if it is in progress, if it was cancelled, "
            f"if the relevant person is missing or has returned home, "
            f"or if there is a temporary schedule change"
        )
        context = build_memory_context(
            recall_query,
            channel="telegram",
            recent_limit=18,
            temporal_limit=12,
            semantic_k=6,
            write_debug=True,
        )
        return context.render()
    except Exception as exc:
        print(f"\033[93m[ProactiveContext]: rich context builder failed: {exc}\033[0m")
        return ""


def _proactive_state_keys_for_event(event_name: str) -> list[str]:
    event_l = (event_name or "").lower()

    keys = []

    # Generic away/home flags
    keys.extend([
        "kid1_away_from_home",
        "kid1_away_reason",
        "kid1_with_user",
        "kid1_with_partner",
        "football_season",
        "school_open",
        "user_at_work",
        "user_out_of_home",
        "quiet_hours",
    ])

    # Generic namespaced states from reconciler Phase 1
    if t("clients.telegram_bot.bot_msg_18ce09") in event_l or "kid1" in event_l or t("clients.telegram_bot.bot_msg_258767") in event_l:
        keys.extend([
            "state:kid1:outing",
            "state:kid1:sleep",
            "state:kid1:sports_training",
            "state:kid1:school",
        ])

    if t("clients.telegram_bot.bot_msg_2e67ed") in event_l or "messenger" in event_l:
        keys.extend([
            "partner_with_user",
            "partner_work_mode",
        ])

    # de-dup preserve order
    seen = set()
    out = []
    for k in keys:
        if k not in seen:
            seen.add(k)
            out.append(k)
    return out

def _build_proactive_state_snapshot(event_name: str) -> dict:
    try:
        from memory.routine_db import get_context_states
    except Exception:
        return {}

    keys = _proactive_state_keys_for_event(event_name)
    if not keys:
        return {}

    try:
        return get_context_states(keys)
    except Exception as exc:
        print(f"\033[93m[ProactiveState]: snapshot failed: {exc}\033[0m")
        return {}

def _force_proactive_skip_from_state(event_name: str, state_snapshot: dict) -> str | None:
    """
    Structured state guard before phrase-based fallback.
    Returns:
      - "[SILENT_SKIP]"
      - "[CONTEXT_SKIP]"
      - None
    """
    if not event_name or not state_snapshot:
        return None

    event_l = event_name.lower()

    def state_value(key: str):
        item = state_snapshot.get(key) or {}
        return str(item.get("value", "")).strip().lower()

    # Shared state
    away = state_value("kid1_away_from_home") == "true"
    away_reason = state_value("kid1_away_reason")
    football_season = state_value("football_season")
    school_open = state_value("school_open")
    user_at_work = state_value("user_at_work") == "true"
    user_out_of_home = state_value("user_out_of_home") == "true"
    quiet_hours = state_value("quiet_hours") == "true"
    kid1_with_user = state_value("kid1_with_user") == "true"
    kid1_with_partner = state_value("kid1_with_partner") == "true"
    partner_with_user = state_value("partner_with_user") == "true"

    # Namespaced generic states
    outing_state = state_value("state:kid1:outing")
    sleep_state = state_value("state:kid1:sleep")
    sports_state = state_value("state:kid1:sports_training")

    # PARK / OUTING
    if t("clients.telegram_bot.bot_msg_48ded7") in event_l or "park" in event_l or t("clients.telegram_bot.bot_msg_09fd55") in event_l:
        if outing_state in {"in_progress", "done"}:
            return "[SILENT_SKIP] outing already handled"
        if away:
            return t("clients.telegram_bot.bot_msg_9b132d")
        if kid1_with_partner and not kid1_with_user:
            return t("clients.telegram_bot.bot_msg_00c825")
        if user_at_work:
            return t("clients.telegram_bot.bot_msg_869876") 

    # COOKING / HOME MEAL
    if (
        t("clients.telegram_bot.bot_msg_19c623") in event_l
        or t("clients.telegram_bot.bot_msg_ae103d") in event_l
        or t("clients.telegram_bot.bot_msg_51c012") in event_l
        or t("clients.telegram_bot.bot_msg_46c594") in event_l
    ):
        if user_out_of_home:
            return t("clients.telegram_bot.bot_msg_026b01")
        if user_at_work:
            return t("clients.telegram_bot.bot_msg_c4f7f2")

    # SLEEP
    if (t("clients.telegram_bot.bot_msg_ebba28") in event_l or t("clients.telegram_bot.bot_msg_c11689") in event_l or "sleep" in event_l) and t("clients.telegram_bot.bot_msg_560d13") not in event_l and t("clients.telegram_bot.bot_msg_0b50a2") not in event_l:
        if sleep_state in {"in_progress", "done"}:
            return "[SILENT_SKIP] sleep already handled"
        if away:
            return t("clients.telegram_bot.bot_msg_06027b")
        if kid1_with_partner and not kid1_with_user:
            return t("clients.telegram_bot.bot_msg_00c825")
        if user_out_of_home or user_at_work:
            return t("clients.telegram_bot.bot_msg_026b01")
        if quiet_hours:
            return t("clients.telegram_bot.bot_msg_6b827c")

    # FOOTBALL / TRAINING
    if t("clients.telegram_bot.bot_msg_7dfa6d") in event_l or t("clients.telegram_bot.bot_msg_c93336") in event_l or "training" in event_l or t("clients.telegram_bot.bot_msg_f32e25") in event_l:
        if sports_state in {"off_season", "paused", "done"}:
            return "[SILENT_SKIP] sports training already handled or paused"
        if football_season == "false":
            return "[SILENT_SKIP] not football season"
        if away:
            return t("clients.telegram_bot.bot_msg_9fbd6e")
        if kid1_with_partner and not kid1_with_user:
            return t("clients.telegram_bot.bot_msg_9ba3e7")

    # SCHOOL
    if t("clients.telegram_bot.bot_msg_712f3e") in event_l:
        if school_open == "false":
            return t("clients.telegram_bot.bot_msg_802883")
        if away:
            return t("clients.telegram_bot.bot_msg_9fbd6e")
    # MESSAGE TO PARTNER
    if "messenger" in event_l or config.PARTNER_NAME.lower() in event_l:
        if partner_with_user:
            return "[CONTEXT_SKIP] together"
    # WAKE UP
    if t("clients.telegram_bot.bot_msg_288e54") in event_l or t("clients.telegram_bot.bot_msg_d02a5b") in event_l:
        if user_at_work:
            return t("clients.telegram_bot.bot_msg_b31806")
        if user_out_of_home:
            return t("clients.telegram_bot.bot_msg_7a69ca")

    # WORK DEPARTURE
    if t("clients.telegram_bot.bot_msg_a633eb") in event_l and t("clients.telegram_bot.bot_msg_b561c6") in event_l:
        if user_at_work:
            return t("clients.telegram_bot.bot_msg_0e63c1")

    return None


def _clear_routine_pending_confirmation(routine_id: int) -> None:
    """Best-effort cleanup for stale pending confirmations on context-driven skips."""
    pending_routine_confirmations.pop(routine_id, None)
    try:
        from memory.routine_db import remove_pending_confirmation

        remove_pending_confirmation(routine_id)
    except Exception as exc:
        print(f"\033[93m[RoutinePendingCleanup]: #{routine_id} failed: {exc}\033[0m")


def _apply_context_mute(routine_id: int, event_name: str, memory_context: str) -> str | None:
    """Infer mute window from context and pre-classify sentimental family routines."""
    if not memory_context:
        return None
    try:
        until = _infer_muted_until(event_name, memory_context)
    except Exception as exc:
        print(f"\033[93m[RoutineMute]: #{routine_id} infer failed: {exc}\033[0m")
        return None
    if not until:
        return None

    try:
        from memory.routine_db import (
            get_sentimental_info,
            set_routine_muted_until,
            set_routine_sentimental,
        )

        info = get_sentimental_info(routine_id)
        if info.get("sentimental") is None:
            is_sentimental = _infer_sentimental(event_name, memory_context)
            set_routine_sentimental(routine_id, is_sentimental)

        set_routine_muted_until(routine_id, until)
        return until
    except Exception as exc:
        print(f"\033[93m[RoutineMute]: #{routine_id} apply failed: {exc}\033[0m")
        return None


_ENV_CONTEXT_CACHE = {
    "ts": 0.0,
    "value": "",
    "gps_key": None,
}

def _get_env_context() -> str:
    """Returns GPS location and current weather context if recent location exists."""
    global _ENV_CONTEXT_CACHE
    import os
    import json
    import time
    import math
    import requests
    from config import GPS_STORAGE_FILE, HOME_COORDS, HOME_RADIUS_M

    if not os.path.exists(GPS_STORAGE_FILE):
        return ""

    try:
        with open(GPS_STORAGE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        
        lat = data.get("lat")
        lon = data.get("lon")
        timestamp = data.get("timestamp", 0)

        # Ensure location is recent (within 4 hours)
        if lat is None or lon is None or (time.time() - timestamp > 14400):
            _ENV_CONTEXT_CACHE["value"] = ""
            _ENV_CONTEXT_CACHE["gps_key"] = None
            return ""

        now_ts = time.time()
        gps_key = (round(float(lat), 4), round(float(lon), 4), int(timestamp))

        if (
            _ENV_CONTEXT_CACHE.get("gps_key") == gps_key
            and (now_ts - _ENV_CONTEXT_CACHE.get("ts", 0.0)) < 300
        ):
            return _ENV_CONTEXT_CACHE.get("value", "")

        # Check distance to home and work
        def haversine(lat1, lon1, lat2, lon2):
            R = 6371000
            p = math.pi / 180
            a = (math.sin((lat2-lat1)*p/2)**2 +
                 math.cos(lat1*p) * math.cos(lat2*p) *
                 math.sin((lon2-lon1)*p/2)**2)
            return 2 * R * math.asin(math.sqrt(a))
            
        try:
            from config import WORK_COORDS, WORK_RADIUS_M
        except ImportError:
            WORK_COORDS = None
            WORK_RADIUS_M = 300
            
        dist_home = haversine(lat, lon, HOME_COORDS[0], HOME_COORDS[1])
        
        if WORK_COORDS:
            dist_work = haversine(lat, lon, WORK_COORDS[0], WORK_COORDS[1])
        else:
            dist_work = float('inf')
            
        if dist_home <= HOME_RADIUS_M:
            location_status = t("clients.telegram_bot.bot_msg_be27d8")
        elif dist_work <= WORK_RADIUS_M:
            location_status = t("clients.telegram_bot.bot_msg_664997")
        else:
            location_status = t("clients.telegram_bot.bot_msg_43b33d")

        weather_url = (
            f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}"
            "&current=temperature_2m,precipitation,weather_code"
        )
        try:
            resp = requests.get(weather_url, timeout=5).json()
            curr = resp.get("current", {})
            temp = curr.get("temperature_2m", "")
            precip = curr.get("precipitation", "")
            wcode = curr.get("weather_code", 0)

            _wmo_dict = NLP_CONFIG.get('telegram', {}).get('wmo_codes', {})
            WMO_CODES = {int(k): v for k, v in _wmo_dict.items()}
            w_desc = WMO_CODES.get(wcode, t("clients.telegram_bot.bot_msg_e8006a"))

            env_str = (
                f"[USER ENVIRONMENTAL DATA]\n"
                f"- Location: {location_status} (GPS: lat={lat:.4f}, lon={lon:.4f})\n"
                f"- Weather there: {w_desc}, {temp}°C, precip {precip}mm\n"
            )
            _ENV_CONTEXT_CACHE["ts"] = now_ts
            _ENV_CONTEXT_CACHE["gps_key"] = gps_key
            _ENV_CONTEXT_CACHE["value"] = env_str
            return env_str
        except Exception as e:
            print(f"\033[93m[EnvContext]: Weather fetch failed: {e}\033[0m")
            env_str = (
                f"[USER ENVIRONMENTAL DATA]\n"
                f"- Location: {location_status} (GPS: lat={lat:.4f}, lon={lon:.4f})\n"
            )
            _ENV_CONTEXT_CACHE["ts"] = now_ts
            _ENV_CONTEXT_CACHE["gps_key"] = gps_key
            _ENV_CONTEXT_CACHE["value"] = env_str
            return env_str

    except Exception as e:
        print(f"\033[93m[EnvContext]: GPS read failed: {e}\033[0m")
        return ""


def _should_send_sentimental_context_note(
    routine_id: int,
    event_name: str,
) -> bool:
    """Return whether a skipped sentimental routine may send one warm note."""
    from memory.routine_db import get_sentimental_info, set_routine_sentimental
    import random

    info = get_sentimental_info(routine_id)
    if info.get("sentimental_silenced"):
        return False

    sentimental = info.get("sentimental")
    if sentimental is None:
        sentimental = _infer_sentimental(event_name, "")
        set_routine_sentimental(routine_id, bool(sentimental))

    if not sentimental:
        return False

    return random.random() < config.SENTIMENTAL_CONTEXT_NOTE_PROBABILITY


def _craft_proactive_msg(event_name: str, confidence: float, count: int = 1) -> str:
    """LLM creates a natural proactive message instead of a template."""
    from langchain_core.messages import HumanMessage
    from core.brain import llm

    if count > 1:
        context = t("clients.telegram_bot.bot_msg_has_routines_mins", user_name=config.USER_NAME, count=count, event_name=event_name)
    elif confidence >= 0.8:
        context = t("clients.telegram_bot.bot_msg_almost_always_does", user_name=config.USER_NAME, event_name=event_name)
    elif confidence >= 0.5:
        context = t("clients.telegram_bot.bot_msg_usually_does", user_name=config.USER_NAME, event_name=event_name)
    else:
        context = t("clients.telegram_bot.bot_msg_previously_did", user_name=config.USER_NAME, event_name=event_name)

    memory_context = _build_proactive_memory_context(event_name)
    memory_block = f"\n\n{memory_context}\n" if memory_context else ""

    state_snapshot = _build_proactive_state_snapshot(event_name)

    if state_snapshot:
        try:
            compact = {k: v.get("value") for k, v in state_snapshot.items()}
            print(f"\033[90m[ProactiveState]: {event_name} -> {compact}\033[0m")
        except Exception:
            pass

    forced_skip = _force_proactive_skip_from_state(event_name, state_snapshot)
    if forced_skip:
        return forced_skip

    env_context = _get_env_context()
    env_block = f"\n{env_context}\n" if env_context else ""

    prompt = core.i18n.load_prompt("telegram_bot_craft_proactive.md").format(
        context=context,
        memory_block=memory_block,
        env_block=env_block,
        language=config.RESPONSE_LANGUAGE,
        user_name=config.USER_NAME
    )

    try:
        response = safe_llm_invoke(llm, [HumanMessage(content=prompt)])
        content = response.content
        if isinstance(content, list):
            content = "".join(
                part.get("text", "") if isinstance(part, dict) else str(part)
                for part in content
            )
        return content.strip()
    except Exception as e:
        print(f"[Proactive Craft Error]: {e}")
        return t("clients.telegram_bot.bot_msg_oops_remembered", event_name=event_name)


def _infer_muted_until(event_name: str, memory_context: str) -> str | None:
    """
    Small LLM call: based on context, returns until when the routine should be muted.
    Returns a YYYY-MM-DD string or None if it cannot estimate.
    Called ONLY after [SILENT_SKIP] has been detected for the first time.
    """
    from langchain_core.messages import HumanMessage
    from core.brain import llm
    from datetime import date

    today = date.today().isoformat()
    prompt = (
        f"Today is {today}.\n"
        f"Routine '{event_name}' is deemed invalid right now due to context.\n\n"
        f"Context:\n{memory_context}\n\n"
        "Based on context, until what date (YYYY-MM-DD) should this routine be muted? "
        "If you can estimate, answer ONLY with the date in YYYY-MM-DD format. "
        "If you cannot estimate, answer ONLY with NULL. "
        "No other words."
    )
    try:
        response = safe_llm_invoke(llm, [HumanMessage(content=prompt)])
        content = response.content
        if isinstance(content, list):
            content = "".join(
                p.get("text", "") if isinstance(p, dict) else str(p) for p in content
            )
        content = content.strip()
        if content.upper() == "NULL" or not content:
            return None
        # Validate format YYYY-MM-DD
        import re as _re
        if _re.match(r"^\d{4}-\d{2}-\d{2}$", content):
            # Ensure it's in the future
            if content > today:
                return content
        return None
    except Exception as e:
        print(f"[_infer_muted_until Error]: {e}")
        return None



def _infer_sentimental(event_name: str, memory_context: str) -> bool:
    """
    One-time LLM assessment: determines if the routine has sentimental value.
    Sentimental = relates to children, family, shared experiences, emotionally charged habits.
    Called once and permanently stored in the DB.
    """
    from langchain_core.messages import HumanMessage
    from core.brain import llm

    prompt = (
        f"Routine: '{event_name}'.\n\n"
        f"Context:\n{memory_context}\n\n"
        "Does this routine involve family, child, shared experiences or have "
        "emotional value (e.g. walk with child, playing, child sleeping)? "
        "Answer ONLY: YES or NO."
    )
    try:
        response = safe_llm_invoke(llm, [HumanMessage(content=prompt)])
        content = response.content
        if isinstance(content, list):
            content = "".join(
                p.get("text", "") if isinstance(p, dict) else str(p) for p in content
            )
        return content.strip().upper().startswith("YES")
    except Exception as e:
        print(f"[_infer_sentimental Error]: {e}")
        return False


def _should_allow_sentimental_override(event_name: str, cond_result: dict) -> bool:
    """
    Keep sentimental overrides for family/home-like routines, but block them
    for work/shift-driven suppressions.
    """
    try:
        results = cond_result.get("results") or []
        reason_blob = " ".join(
            str(item.get("reason", "")) for item in results if isinstance(item, dict)
        ).lower()

        from config import SENTIMENTAL_OVERRIDE_KEYWORDS
        
        if any(token in reason_blob for token in ("shift_mode", "user_at_work", "partner_work_mode")):
            return False

        event_norm = _normalize_gr(event_name)
        return any(token in event_norm for token in SENTIMENTAL_OVERRIDE_KEYWORDS)
    except Exception:
        return False


def _craft_sentimental_absent_msg(
    event_name: str, muted_from: str, muted_until: str, memory_context: str
) -> str:
    """
    Creates an emotional message for a routine that cannot be done right now.
    Does NOT remind of the routine — acknowledges with warmth/humor.
    """
    from langchain_core.messages import HumanMessage
    from core.brain import llm
    from datetime import date

    today = date.today().isoformat()
    prompt = (
        f"Today: {today}. Routine '{event_name}' cannot be done "
        f"from {muted_from} to {muted_until}.\n\n"
        f"Context:\n{memory_context}\n\n"
        "Write ONE short message (1-2 sentences) that:\n"
        "- DOES NOT say 'remember to...' or 'time for...' — no reminders\n"
        "- Acknowledges emotionally (nostalgia, countdown, humor)\n"
        "- Reads like a message from a friend who knows the situation\n"
        "Language MUST BE GREEK. No tags. No quotes."
    )
    try:
        response = safe_llm_invoke(llm, [HumanMessage(content=prompt)])
        content = response.content
        if isinstance(content, list):
            content = "".join(
                p.get("text", "") if isinstance(p, dict) else str(p) for p in content
            )
        return content.strip()
    except Exception as e:
        print(f"[_craft_sentimental_absent_msg Error]: {e}")
        return ""


def _craft_deferred_msg(event_name: str, confidence: float, missed_minutes: int) -> str:

    """
    LLM creates a deferred follow-up: it knows it was offline and time has passed.
    Instead of a reminder, it asks/comments on whether the event took place — like a friend who arrived late.
    Same full pipeline (memory context, personality) as the regular proactive one.
    """
    from langchain_core.messages import HumanMessage
    from core.brain import llm

    if confidence >= 0.8:
        certainty = t("clients.telegram_bot.bot_msg_almost_always_does", user_name=config.USER_NAME, event_name=event_name)
    else:
        certainty = t("clients.telegram_bot.bot_msg_usually_does", user_name=config.USER_NAME, event_name=event_name)

    try:
        from memory.context_builder import build_memory_context
        memory_context = build_memory_context(
            event_name,
            channel="telegram",
            recent_limit=8,
            semantic_k=4,
            write_debug=True,
        ).render()
    except Exception as exc:
        print(f"\033[93m[DeferredMsg]: context builder failed: {exc}\033[0m")
        memory_context = ""
    memory_block = f"\n\n{memory_context}\n" if memory_context else ""

    env_context = _get_env_context()
    env_block = f"\n{env_context}\n" if env_context else ""

    prompt = core.i18n.load_prompt("telegram_bot_craft_deferred.md").format(language=config.RESPONSE_LANGUAGE, user_name=config.USER_NAME, 
        certainty=certainty,
        missed_minutes=missed_minutes,
        memory_block=memory_block,
        env_block=env_block
    )

    try:
        response = safe_llm_invoke(llm, [HumanMessage(content=prompt)])
        content = response.content
        if isinstance(content, list):
            content = "".join(
                part.get("text", "") if isinstance(part, dict) else str(part)
                for part in content
            )
        return content.strip()
    except Exception as e:
        print(f"[Deferred Craft Error]: {e}")
        return t("clients.telegram_bot.bot_msg_917edc")


def startup_check_missed_routines():
    """
    Runs ONCE at startup (with a short initialization delay).
    Looks for active routines that should have been triggered while the bot was offline,
    within ROUTINE_MISS_GRACE_MINUTES, and sends a deferred follow-up with full memory context.
    """
    import sqlite3
    import time as _time
    from datetime import timedelta
    from config import BASE_DIR, ROUTINE_MISS_GRACE_MINUTES

    if is_quiet_hours() or is_proactive_muted():
        print("\033[90m[MissedRoutines]: Quiet hours / muted — skip startup check.\033[0m")
        return

    DB_PATH = config.ROUTINES_DB
    if not os.path.exists(DB_PATH):
        return

    DAYS_MAP = {
        "Monday":    ["Monday", t("clients.telegram_bot.bot_msg_33602e")],
        "Tuesday":   ["Tuesday", t("clients.telegram_bot.bot_msg_fbed5e")],
        "Wednesday": ["Wednesday", t("clients.telegram_bot.bot_msg_6d29a3")],
        "Thursday":  ["Thursday", t("clients.telegram_bot.bot_msg_400527")],
        "Friday":    ["Friday", t("clients.telegram_bot.bot_msg_032239")],
        "Saturday":  ["Saturday", t("clients.telegram_bot.bot_msg_078afa")],
        "Sunday":    ["Sunday", t("clients.telegram_bot.bot_msg_1a9537")],
    }

    try:
        now           = datetime.now()
        today_str     = now.strftime("%Y-%m-%d")
        now_str       = now.strftime("%H:%M")
        grace_start   = (now - timedelta(minutes=ROUTINE_MISS_GRACE_MINUTES)).strftime("%H:%M")
        day_en        = now.strftime("%A")
        possible_days = DAYS_MAP.get(day_en, [day_en])

        group_cond = ""
        if day_en in ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday"):
            group_cond = t("clients.telegram_bot.bot_msg_27bbe4")
        elif day_en in ("Saturday", "Sunday"):
            group_cond = t("clients.telegram_bot.bot_msg_2cbc37")

        placeholders  = ",".join("?" * len(possible_days))

        conn   = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute(f"""
            SELECT id, event_name, confidence, time_str FROM routines
            WHERE (day_of_week IN ({placeholders}) OR day_of_week='Everyday'{group_cond})
              AND state='active'
              AND (last_triggered IS NULL OR last_triggered != ?)
              AND time_str <  ?
              AND time_str >= ?
        """, (*possible_days, today_str, now_str, grace_start))
        missed = cursor.fetchall()
        conn.close()

        if not missed:
            print("\033[90m[MissedRoutines]: No missed routines within grace window.\033[0m")
            return

        print(f"\033[93m[MissedRoutines]: {len(missed)} missed routine(s) — deferred follow-up.\033[0m")

        from memory.routine_db import (
            get_routine_notify_info, mark_routine_notified, save_pending_confirmation,
            get_routine_schedule_meta, is_routine_temporarily_inactive_meta,
            get_routine_conditions,
        )
        from services.routine_context import build_runtime_routine_context
        from services.routine_conditions import evaluate_routine_conditions

        rt_context = build_runtime_routine_context(now=now)

        for r_id, event_name, confidence, time_str in missed:
            # ── Seasonal/temporary inactivity check (paused_until / active window) ──
            # Must run BEFORE any missed/trigger logic — a routine in
            # pause or out of active window is not "lost", it just does not apply right now.
            schedule_meta = get_routine_schedule_meta(r_id)
            inactive, inactive_reason = is_routine_temporarily_inactive_meta(schedule_meta, now=now)
            if inactive:
                log_event("routines", "routine_inactive_skip", routine_id=r_id, event=event_name,
                          reason=inactive_reason, paused_until=schedule_meta.get("paused_until"),
                          debug_type="scheduler_decision", debug_source="scheduler", debug_effect="inactive_skip",
                          active_from=schedule_meta.get("active_from"), active_until=schedule_meta.get("active_until"))
                print(f"\033[90m[MissedRoutines]: #{r_id} '{event_name}' — inactive ({inactive_reason}), skip.\033[0m")
                continue

            # Cooldown check — avoid spamming if notified recently
            info = get_routine_notify_info(r_id)
            if is_duplicate_routine(r_id, info["cooldown_hours"]):
                print(f"\033[90m[MissedRoutines]: #{r_id} '{event_name}' — cooldown, skip.\033[0m")
                continue

            cond_list = get_routine_conditions(r_id)
            if cond_list:
                cond_result = evaluate_routine_conditions(cond_list, rt_context, now=now)
                if not cond_result.get("allowed", True):
                    blocked_reason = str(cond_result.get("results"))
                    log_event(
                        "routines", "routine_condition_blocked",
                        routine_id=r_id, event=event_name,
                        deferred=True,
                        failed_count=cond_result.get("failed_count", 1),
                        reason=blocked_reason,
                        context_snapshot=rt_context,
                        debug_type="condition_eval",
                        debug_source="scheduler",
                        debug_effect="blocked",
                    )
                    print(f"\033[90m[MissedRoutines]: #{r_id} '{event_name}' - condition blocked, skip.\033[0m")
                    continue

            try:
                h, m       = map(int, time_str.split(":"))
                routine_dt = now.replace(hour=h, minute=m, second=0, microsecond=0)
                missed_min = max(1, int((now - routine_dt).total_seconds() / 60))
            except Exception:
                missed_min = ROUTINE_MISS_GRACE_MINUTES // 2

            msg = _craft_deferred_msg(event_name, confidence, missed_min)
            ctx = ""
            if msg.strip().startswith("[SILENT_SKIP]") or "[CONTEXT_SKIP]" in msg:
                try:
                    ctx = _build_proactive_memory_context(event_name)
                except Exception:
                    ctx = ""

            # Mark as triggered so that the regular job does not send it again today
            conn2   = sqlite3.connect(DB_PATH)
            cursor2 = conn2.cursor()
            cursor2.execute("UPDATE routines SET last_triggered=? WHERE id=?", (today_str, r_id))
            conn2.commit()
            conn2.close()

            if msg.strip().startswith("[SILENT_SKIP]"):
                _clear_routine_pending_confirmation(r_id)
                muted_until = _apply_context_mute(r_id, event_name, ctx)
                log_event("routines", "routine_silent_skip", routine_id=r_id, event=event_name,
                          deferred=True, muted_until=muted_until, debug_type="proactive_policy", debug_source="scheduler", debug_effect="silent_skip")
                bus.emit("routine_skipped_context", routine_id=r_id, event=event_name,
                         deferred=True, channel="telegram")
                print(f"\033[90m[MissedRoutines]: SILENT_SKIP '{event_name}' ({missed_min} minutes late)\033[0m")
                continue

            is_context_skip = "[CONTEXT_SKIP]" in msg
            context_skip_preview = ""
            if is_context_skip:
                context_skip_preview = msg.replace("[CONTEXT_SKIP]", "").strip()
                if not context_skip_preview:
                    context_skip_preview = "context_skip_without_explanation"
                msg = context_skip_preview

            if is_context_skip:
                _clear_routine_pending_confirmation(r_id)
                muted_until = None
                log_event("routines", "routine_context_skip", routine_id=r_id, event=event_name,
                          deferred=True, missed_minutes=missed_min,
                          muted_until=muted_until, preview=(context_skip_preview or msg)[:160], debug_type="proactive_policy", debug_source="scheduler", debug_effect="context_skip")
                bus.emit("routine_skipped_context", routine_id=r_id, event=event_name,
                         deferred=True, channel="telegram")
                print(f"\033[90m[MissedRoutines]: CONTEXT_SKIP '{event_name}' ({missed_min} minutes late) → '{msg[:80]}'\033[0m")
                continue

            _send_and_record_assistant(msg, agent="Routine_Agent")

            mark_routine_notified(r_id)
            sent_at = datetime.now()
            pending_routine_confirmations[r_id] = {"event": event_name, "sent_at": sent_at}
            save_pending_confirmation(r_id, event_name, sent_at)
            log_event("routines", "deferred_followup",
                      routine_id=r_id, event=event_name,
                      missed_minutes=missed_min, preview=msg[:160])
            bus.emit("routine_triggered", routine_id=r_id, event=event_name,
                     confidence=confidence, deferred=True, channel="telegram")
            print(f"\033[92m[MissedRoutines]: ✅ Deferred '{event_name}' ({missed_min} minutes late) → '{msg[:80]}'\033[0m")

            if len(missed) > 1:
                _time.sleep(300)  # 5-minute pause — to allow a response to the first one

    except Exception as e:
        print(f"\033[91m[MissedRoutines]: {e}\033[0m")


def job_check_routines():
    """
    Checks for upcoming routines (30' in advance) and performs timeout decay
    on pending confirmations that were not answered.
    """
    import sqlite3
    from datetime import timedelta
    from config import BASE_DIR

    DB_PATH = config.ROUTINES_DB
    DAYS_MAP = {
        "Monday":    ["Monday", t("clients.telegram_bot.bot_msg_33602e")],
        "Tuesday":   ["Tuesday", t("clients.telegram_bot.bot_msg_fbed5e")],
        "Wednesday": ["Wednesday", t("clients.telegram_bot.bot_msg_6d29a3")],
        "Thursday":  ["Thursday", t("clients.telegram_bot.bot_msg_400527")],
        "Friday":    ["Friday", t("clients.telegram_bot.bot_msg_032239")],
        "Saturday":  ["Saturday", t("clients.telegram_bot.bot_msg_078afa")],
        "Sunday":    ["Sunday", t("clients.telegram_bot.bot_msg_1a9537")],
    }

    if pending_routine_confirmations:
        from memory.routine_db import get_routine_muted_until, remove_pending_confirmation
        for rid in list(pending_routine_confirmations.keys()):
            try:
                muted_until = get_routine_muted_until(rid)
            except Exception:
                muted_until = None
            if muted_until:
                ev = pending_routine_confirmations[rid]["event"]
                del pending_routine_confirmations[rid]
                remove_pending_confirmation(rid)
                log_event(
                    "routines", 
                    "pending_cleared_muted", 
                    routine_id=rid, 
                    event=ev, 
                    muted_until=muted_until,
                    debug_type="pending_cleanup",
                    debug_source="system",
                    debug_effect="pending_cleared",
                )
                print(f"\033[90m[RoutinePendingCleanup]: #{rid} '{ev}' cleared because muted until {muted_until}\033[0m")

    # Quiet hours or proactive muted_
    if is_proactive_muted():
        return
    if is_quiet_hours():
        if pending_routine_confirmations:
            from memory.routine_db import decay_routine, remove_pending_confirmation, get_routine_state, RoutineState
            now_check = datetime.now()
            for rid in list(pending_routine_confirmations.keys()):
                if (now_check - pending_routine_confirmations[rid]["sent_at"]).total_seconds() > 1800:
                    try:
                        current_state = get_routine_state(rid)
                    except Exception:
                        current_state = None

                    if current_state != RoutineState.TRIGGER_PENDING:
                        log_event("routines", "routine_pending_stale_cleared",
                            routine_id=rid,
                            event=pending_routine_confirmations[rid]["event"],
                            state=(current_state.value if current_state else "unknown"),
                            elapsed_s=1800,
                            debug_type="pending_cleanup",
                            debug_source="timeout_guard",
                            debug_effect="pending_cleared",
                        )
                        pending_routine_confirmations.pop(rid, None)
                        remove_pending_confirmation(rid)
                        continue

                    decay_routine(rid)
                    log_event(
                        "routines", 
                        "routine_timeout_decay", 
                        routine_id=rid,
                        event=pending_routine_confirmations[rid]["event"],
                        elapsed_s=1800,
                        debug_type="pending_cleanup",
                        debug_source="timeout_guard",
                        debug_effect="cooldown_changed",
                    )
                    pending_routine_confirmations.pop(rid, None)
                    remove_pending_confirmation(rid)
    # 2. Timeout decay for pending confirmations (>30')
    # TRIGGER_PENDING → IGNORED → ACTIVE (cooldown doubled, confidence intact)
    if pending_routine_confirmations:
        from memory.routine_db import (
            mark_routine_ignored,
            remove_pending_confirmation,
            get_routine_state,
            RoutineState,
        )

        now_check = datetime.now()
        for rid in list(pending_routine_confirmations.keys()):
            elapsed = (now_check - pending_routine_confirmations[rid]["sent_at"]).total_seconds()
            if elapsed > 1800:
                ev = pending_routine_confirmations[rid]["event"]

                try:
                    current_state = get_routine_state(rid)
                except Exception:
                    current_state = None

                if current_state != RoutineState.TRIGGER_PENDING:
                    log_event("routines", "routine_pending_stale_cleared",
                        routine_id=rid,
                        event=ev,
                        state=(current_state.value if current_state else "unknown"),
                        elapsed_s=int(elapsed),
                        debug_type="pending_cleanup",
                        debug_source="timeout_guard",
                        debug_effect="pending_cleared",
                    )
                    del pending_routine_confirmations[rid]
                    remove_pending_confirmation(rid)
                    continue

                try:
                    mark_routine_ignored(rid)  # TRIGGER_PENDING → IGNORED → ACTIVE + doubled cooldown
                except DBWriteError as e:
                    print(f"\033[91m[Timeout Decay DBWriteError]: {e}\033[0m")

                timeout_err = PendingTimeoutError(rid, ev, elapsed)
                log_event("routines", "routine_timeout_decay",
                    routine_id=rid,
                    event=ev,
                    elapsed_s=int(elapsed),
                    error=str(timeout_err),
                    debug_type="pending_cleanup",
                    debug_source="timeout_guard",
                    debug_effect="cooldown_changed",
                )

                del pending_routine_confirmations[rid]
                remove_pending_confirmation(rid)

    # 1. Upcoming routine notifications
    try:
        if os.path.exists(DB_PATH):
            conn   = sqlite3.connect(DB_PATH)
            cursor = conn.cursor()
            try:
                now          = datetime.now()
                target_time  = now + timedelta(minutes=30)
                day_en       = target_time.strftime("%A")
                possible_days = DAYS_MAP.get(day_en, [day_en])
                target_time_str = target_time.strftime("%H:%M")
                today_str       = now.strftime("%Y-%m-%d")

                group_cond = ""
                if day_en in ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday"):
                    group_cond = t("clients.telegram_bot.bot_msg_27bbe4")
                elif day_en in ("Saturday", "Sunday"):
                    group_cond = t("clients.telegram_bot.bot_msg_2cbc37")

                placeholders = ",".join("?" * len(possible_days))
                cursor.execute(f"""
                    SELECT id, event_name, confidence, priority, conflict_group, time_str FROM routines
                    WHERE (day_of_week IN ({placeholders}) OR day_of_week='Everyday'{group_cond})
                    AND state='active'
                    AND (last_triggered IS NULL OR last_triggered != ?)
                    ORDER BY priority DESC, CASE WHEN condition_type IS NOT NULL THEN 1 ELSE 0 END DESC, id ASC
                """, (*possible_days, today_str))

                # ── Anti-Spam: filtering with per-routine cooldown ──────────
                from memory.routine_db import (
                    get_routine_notify_info, mark_routine_notified,
                    save_pending_confirmation, get_routine_muted_until,
                    get_routine_schedule_meta, is_routine_temporarily_inactive_meta,
                    get_routine_conditions,
                )
                from services.routine_context import build_runtime_routine_context
                from services.routine_conditions import evaluate_routine_conditions
                due_routines = []
                triggered_conflict_groups = set()
                rt_context = build_runtime_routine_context(now=now)

                def _get_conflict_group(name: str) -> str:
                    parts = name.lower().split()
                    return parts[0] if parts else name.lower()

                for r_id, event_name, confidence, priority, db_conflict_group, time_str in cursor.fetchall():
                    # --- NEW WINDOW LOGIC TO PREVENT TIME LIMBO ---
                    try:
                        h, m = map(int, time_str.split(':'))
                        routine_dt = now.replace(hour=h, minute=m, second=0, microsecond=0)
                    except ValueError:
                        continue
                
                    time_diff_mins = (routine_dt - now).total_seconds() / 60.0
                
                    # Handle midnight wrap-around (if routine is past midnight but matches day of week)
                    if time_diff_mins < -1000:
                        time_diff_mins += 24 * 60
                    
                    # We trigger if the routine is anywhere between 0 and 15 minutes in the future.
                    # Because we update the state to 'trigger_pending', it won't spam.
                    # If bot was offline and we missed the exact 15-min mark, it catches it now!
                    if not (0 <= time_diff_mins <= 15):
                        continue

                    conflict_group = db_conflict_group if db_conflict_group else _get_conflict_group(event_name)
                
                    if conflict_group in triggered_conflict_groups:
                        # print(f"\U0001f6ab [job_check_routines]: #{r_id} '{event_name}' skipped due to conflict with higher priority routine in group '{conflict_group}'")
                        continue

                    # ── Seasonal/temporary inactivity check (paused_until / active window) ──
                    # Must run BEFORE muted_until/cooldown/proactive scoring — a
                    # a paused routine (e.g. summer break) is never considered "missed",
                    # confidence does not matter, and it does not pass through the sentimental/mute branch.
                    schedule_meta = get_routine_schedule_meta(r_id)
                    inactive, inactive_reason = is_routine_temporarily_inactive_meta(schedule_meta, now=now)
                    if inactive:
                        skip_reason = f"inactive:{inactive_reason}"
                        if _should_log_routine_skip(r_id, "routine_inactive_skip", skip_reason):
                            log_event("routines", "routine_inactive_skip", routine_id=r_id, event=event_name,
                                      reason=inactive_reason, paused_until=schedule_meta.get("paused_until"), debug_type="scheduler_decision", debug_source="scheduler", debug_effect="inactive_skip",
                                      active_from=schedule_meta.get("active_from"), active_until=schedule_meta.get("active_until"))
                            print(f"\U0001f6ab [job_check_routines]: #{r_id} '{event_name}' inactive ({inactive_reason}) — skipped")
                        continue
                    # ── Phase 3C: Conditions Evaluator ───────────────────────
                    cond_list = get_routine_conditions(r_id)
                    if cond_list:
                        cond_result = evaluate_routine_conditions(cond_list, rt_context, now=now)
                        if not cond_result.get("allowed", True):
                            blocked_reason = str(cond_result.get("results"))
                            should_log = _should_log_routine_skip(r_id, "routine_condition_blocked", blocked_reason)
                            if should_log:
                                log_event("routines", "routine_condition_blocked",
                                    routine_id=r_id, 
                                    event=event_name,
                                    failed_count=cond_result.get("failed_count", 1),
                                    reason=blocked_reason,
                                    context_snapshot=rt_context,
                                    debug_type="condition_eval",
                                    debug_source="scheduler",
                                    debug_effect="blocked",
                                )
                        
                            import random
                            # 30% chance for a Sentimental Override (approx 2 times a week for a daily routine)
                            if random.random() < 0.30 and _should_allow_sentimental_override(event_name, cond_result):
                                blocked_reason_text = ", ".join(str(r.get("reason", "blocked")) for r in cond_result.get("results", []) if not r.get("allowed"))
                                override_name = f"{event_name} [CANCELLED TODAY DUE TO: {blocked_reason_text}]"
                                if should_log:
                                    print(f"\U0001f496 [job_check_routines]: #{r_id} '{event_name}' blocked but triggering sentimental override!")
                                # Fall through to due_routines to let the LLM generate a [CONTEXT_SKIP]
                                event_name = override_name
                            else:
                                if should_log:
                                    print(f"\U0001f6ab [job_check_routines]: #{r_id} '{event_name}' condition blocked ({cond_result.get('failed_count')} failed) — skipped")
                                continue
                        else:
                            log_event(
                                "routines", 
                                "routine_condition_allowed",
                                routine_id=r_id, 
                                event=event_name,
                                reason="All conditions passed",
                                debug_type="condition_eval",
                                debug_source="scheduler",
                                debug_effect="no_change",
                            )

                    # ── muted_until check ────────────────────────────────────
                    muted_until = get_routine_muted_until(r_id)
                    if muted_until:
                        cursor.execute("UPDATE routines SET last_triggered=? WHERE id=?", (today_str, r_id))
                        conn.commit()

                        # When the routine is already muted, the proactive for this slot ends here.
                        # We DO NOT send a second sentimental message from the polling loop; the
                        # emotional/contextual messages are only generated at the moment that
                        # context skip / mute detected, not again in each subsequent poll.
                        skip_reason = f"muted_until:{muted_until}"
                        if _should_log_routine_skip(r_id, "routine_silent_skip", skip_reason):
                            log_event(
                                "routines", 
                                "routine_silent_skip", 
                                routine_id=r_id, 
                                event=event_name,
                                reason="muted_until", 
                                muted_until=muted_until,
                                debug_type="proactive_decision",
                                debug_source="scheduler",
                                debug_effect="notification_skipped",
                            )
                            print(f"\U0001f507 [job_check_routines]: #{r_id} '{event_name}' muted until {muted_until} — skipped")
                        continue
                    info = get_routine_notify_info(r_id)
                    cd_hours = info["cooldown_hours"]
                    if is_duplicate_routine(r_id, cd_hours):
                        skip_reason = f"cooldown:{cd_hours}"
                        if _should_log_routine_skip(r_id, "routine_cooldown_skip", skip_reason):
                            log_event("routines", "routine_cooldown_skip", routine_id=r_id, event=event_name, cooldown_hours=cd_hours, debug_type="scheduler_decision", debug_source="scheduler", debug_effect="cooldown_skip")
                        continue
                    due_routines.append((r_id, event_name, confidence))
                    triggered_conflict_groups.add(conflict_group)


                if not due_routines:
                    conn.close()
                    return

                if not can_send_proactive():
                    for r_id, event_name, _ in due_routines:
                        log_event("routines", "routine_rate_limit_skip",
                                  routine_id=r_id, event=event_name,
                                  debug_type="scheduler_decision", debug_source="scheduler", debug_effect="rate_limit_skip")
                    print(f"⏸️ [job_check_routines]: Rate limit, {len(due_routines)} routine(s) skipped")
                    conn.close()
                    return

                # ── Batching: multiple routines → one message ──────────────────
                if len(due_routines) > 1:
                    names = ", ".join(f"'{e}'" for _, e, _ in due_routines)
                    msg = _craft_proactive_msg(names, 0.9, count=len(due_routines))

                    if msg.strip().startswith("[CONTEXT_NOTE]"):
                        msg = msg.replace("[CONTEXT_NOTE]", "[CONTEXT_SKIP]", 1)

                    if msg.strip().startswith("[SILENT_SKIP]"):
                        # First time SILENT_SKIP — estimate muted_until for each routine
                        try:
                            ctx = _build_proactive_memory_context(names)
                        except Exception:
                            ctx = ""
                        for r_id, event_name, confidence in due_routines:
                            cursor.execute("UPDATE routines SET last_triggered=? WHERE id=?", (today_str, r_id))
                            log_event(
                                "routines", 
                                "routine_silent_skip", 
                                routine_id=r_id, 
                                event=event_name, 
                                batch=True,
                                debug_type="proactive_decision",
                                debug_source="scheduler",
                                debug_effect="notification_skipped",
                            )
                            bus.emit("routine_skipped_context", routine_id=r_id, event=event_name, batch=True, channel="telegram")
                            _clear_routine_pending_confirmation(r_id)
                            _apply_context_mute(r_id, event_name, ctx)
                        conn.commit()
                    else:
                        is_context_skip = False
                        context_skip_preview = ""
                        if "[CONTEXT_SKIP]" in msg:
                            is_context_skip = True
                            context_skip_preview = msg.replace("[CONTEXT_SKIP]", "").strip()
                            if not context_skip_preview:
                                context_skip_preview = "context_skip_without_explanation"
                            msg = context_skip_preview

                        context_skip_ctx = ""
                        if is_context_skip:
                            try:
                                context_skip_ctx = _build_proactive_memory_context(names)
                            except Exception:
                                context_skip_ctx = ""
                        for r_id, event_name, confidence in due_routines:
                            cursor.execute("UPDATE routines SET last_triggered=? WHERE id=?", (today_str, r_id))
                            if is_context_skip:
                                _clear_routine_pending_confirmation(r_id)
                                muted_until = None
                                log_event(
                                    "routines",
                                    "routine_context_skip",
                                    routine_id=r_id,
                                    event=event_name,
                                    batch=True, 
                                    muted_until=muted_until, 
                                    preview=(context_skip_preview or msg)[:160],
                                    debug_type="proactive_decision",
                                    debug_source="scheduler",
                                    debug_effect="notification_skipped",
                                )
                                bus.emit("routine_skipped_context", routine_id=r_id, event=event_name, batch=True, channel="telegram")
                            else:
                                _send_and_record_assistant(msg, agent="Routine_Agent")
                                sent_at = datetime.now()
                                mark_routine_notified(r_id)
                                log_event("routines", "routine_triggered", 
                                    routine_id=r_id,
                                    event=event_name, 
                                    confidence=confidence,
                                    batch=len(due_routines, debug_type="scheduler_decision", debug_source="scheduler", debug_effect="triggered"), 
                                    preview=msg[:160],
                                    debug_type="proactive_decision",
                                    debug_source="scheduler",
                                    debug_effect="notification_sent",
                                )
                                pending_routine_confirmations[r_id] = {"event": event_name, "sent_at": sent_at}
                                save_pending_confirmation(r_id, event_name, sent_at)
                                bus.emit("routine_triggered", routine_id=r_id, event=event_name, confidence=confidence, batch=True, channel="telegram")
                        conn.commit()
                else:
                    # One routine → personalized message
                    r_id, event_name, confidence = due_routines[0]
                    msg = _craft_proactive_msg(event_name, confidence)

                    if msg.strip().startswith("[SILENT_SKIP]"):
                        # First time SILENT_SKIP — estimate muted_until
                        try:
                            ctx = _build_proactive_memory_context(event_name)
                        except Exception:
                            ctx = ""
                        cursor.execute("UPDATE routines SET last_triggered=? WHERE id=?", (today_str, r_id))
                        conn.commit()
                        log_event(
                            "routines", 
                            "routine_silent_skip", 
                            routine_id=r_id, 
                            event=event_name,
                            debug_type="proactive_decision",
                            debug_source="scheduler",
                            debug_effect="notification_skipped",
                        )
                        bus.emit("routine_skipped_context", routine_id=r_id, event=event_name, channel="telegram")
                        _clear_routine_pending_confirmation(r_id)
                        _apply_context_mute(r_id, event_name, ctx)
                    else:
                        is_context_note = msg.strip().startswith("[CONTEXT_NOTE]")
                        is_context_skip = "[CONTEXT_SKIP]" in msg or is_context_note
                        context_skip_preview = ""

                        if is_context_skip:
                            marker = "[CONTEXT_NOTE]" if is_context_note else "[CONTEXT_SKIP]"
                            context_skip_preview = msg.replace(marker, "").strip()
                            if not context_skip_preview:
                                context_skip_preview = "context_skip_without_explanation"
                            msg = context_skip_preview

                        cursor.execute("UPDATE routines SET last_triggered=? WHERE id=?", (today_str, r_id))
                        conn.commit()

                        if is_context_skip:
                            if (
                                is_context_note
                                and _should_send_sentimental_context_note(
                                    r_id,
                                    event_name,
                                )
                            ):
                                _send_and_record_assistant(
                                    msg,
                                    agent="Routine_Agent",
                                )
                                log_event(
                                    "routines",
                                    "routine_context_note",
                                    routine_id=r_id,
                                    event=event_name,
                                    preview=msg[:160],
                                    debug_type="proactive_decision",
                                    debug_source="scheduler",
                                    debug_effect="context_note_sent",
                                )
                            _clear_routine_pending_confirmation(r_id)
                            muted_until = None
                            log_event(
                                "routines",
                                "routine_context_skip",
                                routine_id=r_id,
                                event=event_name,
                                muted_until=muted_until, 
                                preview=(context_skip_preview or msg)[:160],
                                debug_type="proactive_decision",
                                debug_source="scheduler",
                                debug_effect="notification_skipped",
                            )
                            # DO NOT mark as pending, just keep it active.
                            bus.emit("routine_skipped_context", routine_id=r_id, event=event_name, channel="telegram")
                        else:
                            _send_and_record_assistant(msg, agent="Routine_Agent")
                            mark_routine_notified(r_id)
                            log_event(
                                "routines", 
                                "routine_triggered", 
                                routine_id=r_id,
                                event=event_name, 
                                confidence=confidence,
                                preview=msg[:160],
                                debug_type="proactive_decision",
                                debug_source="scheduler",
                                debug_effect="notification_sent",
                            )
                            sent_at = datetime.now()
                            pending_routine_confirmations[r_id] = {"event": event_name, "sent_at": sent_at}
                            save_pending_confirmation(r_id, event_name, sent_at)
                            bus.emit("routine_triggered", routine_id=r_id, event=event_name, confidence=confidence, batch=False, channel="telegram")


                conn.close()
            finally:
                conn.close()
    except Exception as e:
        print(f"❌ [job_check_routines]: {e}")


def job_proactive_scan():
    """
    The 'Nightwatchman' — scans the watch_folder and if it finds an issue, sends an alert.
    """
    from tools.system import read_local_file
    import config
    WATCH_DIR = config.WATCH_DIR

    if is_proactive_muted():
        return
    if is_quiet_hours():
        print("🌙 [job_proactive_scan]: Quiet hours — skipped.")
        return
    if should_skip_proactive_for_recent_activity():
        return
    if not can_send_proactive():
        print("⏸️ [job_proactive_scan]: Rate limit reached — skipped.")
        return

    print("🦞 [Proactive]: Starting silent system scan...")
    try:
        os.makedirs(WATCH_DIR, exist_ok=True)
        files_to_scan = os.listdir(WATCH_DIR)
        if not files_to_scan:
            return

        collected_data = ""
        for file in files_to_scan:
            filepath = os.path.join(WATCH_DIR, file)
            try:
                content = read_local_file.invoke(filepath)
            except TypeError:
                content = read_local_file.invoke({"file_path": filepath})
            collected_data += f"\n--- FILE: {file} ---\n{str(content)[:2000]}\n"

        prompt = core.i18n.load_prompt("telegram_bot_proactive_scan.md").format(language=config.RESPONSE_LANGUAGE, user_name=config.USER_NAME)
        response = safe_gemini_call(f"{prompt}\n\n[DATA]:\n{collected_data}")
        reply = response.text.strip()

        if reply and t("clients.telegram_bot.bot_msg_841230") not in reply:
            if not is_duplicate_notification(reply, cooldown_seconds=3600):
                _send_and_record_assistant(reply, agent="Proactive_Agent")
                log_event("proactive", "alert_sent", preview=reply[:80])
                print(f"⚠️ [Proactive Alert Sent]: {reply[:50]}...")
        else:
            log_event("proactive", "all_clear")
            print("✔️ [Proactive]: All clear.")
    except Exception as e:
        print(f"⚠️ [job_proactive_scan]: {e}")

def job_analytics_engine():
    """Nightly passive routine detection — runs only 03:00–04:00."""
    now_hour = datetime.now().hour
    if now_hour != 3:
        return
    try:
        from services.analytics_engine import run_analytics
        stats = run_analytics()
        if stats.get("created", 0) + stats.get("merged", 0) > 0:
            send_telegram_msg(
                f"🧠 [Analytics]: Detected new routines!\n"
                f"✅ New: {stats['created']} | 🔗 Merged: {stats['merged']} | "
                f"📊 Detected: {stats['detected']}"
            )
    except Exception as e:
        print(f"[Analytics Job Error]: {e}")

    # Reflection engine — runs immediately after the analytics
    try:
        from services.reflection_engine import run_reflection
        global pending_reflection_confirmations
        r_stats = run_reflection()
        for item in r_stats.get("pending_items", []):
            pending_reflection_confirmations[item["id"]] = item

        if pending_reflection_confirmations:
            _send_pending_reflections_summary()

        print(f"[Reflection Job]: applied={r_stats.get('applied',0)}, pending={r_stats.get('pending',0)}")
    except Exception as re:
        print(f"[Reflection Job Error]: {re}")

def job_morning_fit_briefing():
    """Morning Google Fit briefing — runs only 08:00–09:00, once."""
    now_hour = datetime.now().hour
    if now_hour != 8:
        return
    # Avoid double sending — we check if we already sent it today_
    flag_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".fit_briefing_sent")
    today_str = datetime.now().strftime("%Y-%m-%d")
    if os.path.exists(flag_file):
        with open(flag_file, "r") as f:
            if f.read().strip() == today_str:
                return
    try:
        from astakos_skills.google_fit import get_morning_summary
        summary = get_morning_summary()
        message_id = _send_and_record_assistant(
            t("clients.telegram_bot.bot_msg_morning_master_summary", summary=summary),
            agent="Fit_Briefing",
        )
        if not message_id:
            print("[Fit_Briefing]: send failed, flag not written.")
            return

        with open(flag_file, "w") as f:
            f.write(today_str)
        print(f"✅ [FitBriefing]: Morning briefing sent.")
    except Exception as e:
        print(f"⚠️ [FitBriefing]: {e}")

def job_daily_backup():
    """Daily Backup to Google Drive — runs at 04:00 AM, once."""
    now_hour = datetime.now().hour
    if now_hour != 4:
        return
    
    flag_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".daily_backup_sent")
    today_str = datetime.now().strftime("%Y-%m-%d")
    if os.path.exists(flag_file):
        with open(flag_file, "r") as f:
            if f.read().strip() == today_str:
                return

    try:
        from astakos_skills.daily_backup import daily_backup_to_drive
        result = daily_backup_to_drive()
        with open(flag_file, "w") as f:
            f.write(today_str)
        print(f"✅ [DailyBackup]: Backup completed.")
    except Exception as e:
        print(f"⚠️ [DailyBackup]: {e}")

def job_morning_calendar_briefing():
    """Morning Google Calendar briefing — runs only 08:00–09:00, once."""
    now_hour = datetime.now().hour
    if now_hour != 8:
        return

    flag_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".calendar_briefing_sent")
    today_str = datetime.now().strftime("%Y-%m-%d")
    if os.path.exists(flag_file):
        with open(flag_file, "r") as f:
            if f.read().strip() == today_str:
                return

    try:
        from astakos_skills.gcalendar import google_calendar_tool

        today_events = google_calendar_tool.invoke({"action": "today"})
        week_events  = google_calendar_tool.invoke({"action": "week"})

        # If there are no events today, we only send a weekly summaryof
        if t("clients.telegram_bot.bot_msg_908de1") in today_events:
            msg = t("clients.telegram_bot.bot_msg_morning_lazaros_empty", user_name=config.USER_NAME, week_events=week_events)
        else:
            msg = t("clients.telegram_bot.bot_msg_morning_lazaros_events", user_name=config.USER_NAME, today_events=today_events)

        message_id = _send_and_record_assistant(msg, agent="Calendar_Briefing")
        if not message_id:
            print("[Calendar_Briefing]: send failed, flag not written.")
            return

        with open(flag_file, "w") as f:
            f.write(today_str)
        print(t("clients.telegram_bot.bot_msg_941efd"))
    except Exception as e:
        print(f"⚠️ [CalendarBriefing]: {e}")

def job_morning_ai_briefing():
    """Morning AI/Tech/Roblox briefing — runs only 08:00–09:00, once."""
    now_hour = datetime.now().hour
    if now_hour != 8:
        return

    flag_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".ai_briefing_sent")
    today_str = datetime.now().strftime("%Y-%m-%d")
    if os.path.exists(flag_file):
        with open(flag_file, "r") as f:
            if f.read().strip() == today_str:
                return

    try:
        from astakos_skills.morning_briefing import get_morning_briefing
        msg = get_morning_briefing()

        message_id = _send_and_record_assistant(msg, agent="News_Briefing")
        if not message_id:
            print("[News_Briefing]: send failed, flag not written.")
            return

        with open(flag_file, "w") as f:
            f.write(today_str)
        print("✅ [News_Briefing]: Morning AI briefing sent.")
    except Exception as e:
        print(f"⚠️ [News_Briefing]: {e}")


def job_morning_hn_briefing():
    """Morning Hacker News briefing — runs only 09:00–10:00, once."""
    now_hour = datetime.now().hour
    if now_hour != 9:
        return

    flag_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".hn_briefing_sent")
    today_str = datetime.now().strftime("%Y-%m-%d")
    if os.path.exists(flag_file):
        with open(flag_file, "r") as f:
            if f.read().strip() == today_str:
                return

    try:
        from astakos_skills.hn_briefing import get_hn_briefing

        msg = get_hn_briefing(limit=8)
        message_id = _send_and_record_assistant(msg, agent="HN_Briefing")
        if not message_id:
            print("[HN_Briefing]: send failed, flag not written.")
            return

        with open(flag_file, "w") as f:
            f.write(today_str)
        print("✅ [HN_Briefing]: Morning HN briefing sent.")
    except Exception as e:
        print(f"⚠️ [HN_Briefing]: {e}")

def job_goal_followup():
    """
    Checks active goals that have not been reported in the last 7 days.
    Runs once a day at 10:00.
    """
    now_hour = datetime.now().hour
    if now_hour != 10:
        return

    flag_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".goal_followup_sent")
    today_str = datetime.now().strftime("%Y-%m-%d")
    if os.path.exists(flag_file):
        with open(flag_file, "r") as f:
            if f.read().strip() == today_str:
                return

    try:
        from memory.vector_store import get_active_goals
        from config import BASE_DIR
        import json

        goals = get_active_goals()
        if not goals:
            return

        # Semantic search: we search if there are recent memories for each goal
        from datetime import timedelta
        from memory.vector_store import vector_store, vector_lock
        cutoff_ts = (datetime.now() - timedelta(days=7)).timestamp()

        stale_goals = []
        for g in goals:
            try:
                emb = vector_store.embeddings.embed_query(g["project"] + " " + g["description"])
                with vector_lock:
                    results = vector_store._collection.query(
                        query_embeddings=[emb],
                        n_results=3,
                        where={"timestamp": {"$gte": cutoff_ts}},
                    )
                # If nothing recent was found → stale
                if not results["ids"] or not results["ids"][0]:
                    stale_goals.append(g)
                    print(f"[GoalFollowup]: '{g['project']}' → stale (0 recent memories)")
                else:
                    print(f"[GoalFollowup]: '{g['project']}' → active ({len(results['ids'][0])} recent memories)")
            except Exception as _e:
                print(f"[GoalFollowup]: semantic check error for '{g['project']}': {_e}")
                stale_goals.append(g)

        if not stale_goals:
            return

        # LLM crafts natural follow-up message
        from services.gemini import safe_gemini_call
        goals_text_lines = []
        for g in stale_goals[:3]:
            line = f"- {g['project']}: {g['description']}"
            if g.get('progress'):
                line += t("clients.telegram_bot.bot_msg_progress_percent", progress=g["progress"])
            if g.get('milestones'):
                line += f"\n  Milestones: {g['milestones']}"
            goals_text_lines.append(line)
        goals_text = "\n".join(goals_text_lines)

        prompt = core.i18n.load_prompt("telegram_bot_goal_followup.md").format(language=config.RESPONSE_LANGUAGE, user_name=config.USER_NAME, goals_text=goals_text)

        response = safe_gemini_call(prompt)
        msg = response.text.strip() if hasattr(response, "text") else str(response).strip()

        if msg:
            _send_and_record_assistant(f"🎯 {msg}", agent="Goal_Followup")
            with open(flag_file, "w") as f:
                f.write(today_str)
            print(f"✅ [GoalFollowup]: Sent for {len(stale_goals)} goals.")

    except Exception as e:
        print(f"⚠️ [GoalFollowup]: {e}")


# ────────────────────────────────────────────────────────────────
# ASTAKOS SCHEDULER (Central Event Bus)
# ────────────────────────────────────────────────────────────────

class AstakosScheduler:
    """
    One thread, all background jobs.
    - Heartbeat 10s
    - Watchdog: fail_count + disabled_after_N_failures
    - Duration tracking
    - status() for /status command
    """

    MAX_FAILURES = 5  # disable after this many consecutive failures

    def __init__(self):
        self._jobs = []

    def register(self, func, interval_seconds: int, name: str = None, verbose: bool = True):
        """
        verbose=True  → log start/complete of each run (for rare/important jobs)
        verbose=False → log only errors (for frequent jobs: reminders, routines)
        """
        self._jobs.append({
            "name":          name or func.__name__,
            "func":          func,
            "interval":      interval_seconds,
            "last_run":      0,
            "last_duration": 0.0,
            "fail_count":    0,
            "last_error":    None,
            "disabled":      False,
            "verbose":       verbose,
        })
        print(f"\033[90m[Scheduler]: Registered '{name or func.__name__}' every {interval_seconds}s (verbose={verbose})\033[0m")

    def _write_snapshot(self):
        """Writes runtime_snapshot.json on every heartbeat — read by /debug/runtime."""
        try:
            from config import BASE_DIR
            import json
            now = time.time()
            memory_context_path = os.path.join(BASE_DIR, "runtime_memory_context.json")
            try:
                with open(memory_context_path, "r", encoding="utf-8") as f:
                    memory_context_debug = _json.load(f)
            except Exception:
                memory_context_debug = {}
            snapshot = {
                "written_at":  datetime.now().isoformat(timespec="seconds"),
                "jobs": [
                    {
                        "name":          j["name"],
                        "interval":      j["interval"],
                        "last_run":      datetime.fromtimestamp(j["last_run"]).strftime("%H:%M:%S") if j["last_run"] > 0 else None,
                        "next_in_secs":  max(0, int(j["interval"] - (now - j["last_run"]))) if j["last_run"] > 0 else 0,
                        "last_duration": round(j["last_duration"], 3),
                        "fail_count":    j["fail_count"],
                        "last_error":    j["last_error"],
                        "disabled":      j["disabled"],
                    }
                    for j in self._jobs
                ],
                "pending_confirmations": len(pending_routine_confirmations),
                "fast_queue_size":       fast_queue.qsize(),
                "slow_queue_size":       slow_queue.qsize(),
                "quiet_hours":           is_quiet_hours(),
                "proactive_muted":       is_proactive_muted(),
                "reminders_paused":      is_reminders_paused(),
                "memory_context":        memory_context_debug,
            }
            with _proactive_lock:
                snapshot["proactive_this_hour"] = _proactive_count["count"]
            path = os.path.join(BASE_DIR, "runtime_snapshot.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump(snapshot, f, ensure_ascii=False)
        except Exception as e:
            print(f"[Scheduler]: snapshot write error: {e}")

    def run(self):
        print(t("clients.telegram_bot.bot_msg_338d22"))
        while not shutdown_event.is_set():
            now = time.time()
            for job in self._jobs:
                if job["disabled"]:
                    continue
                if now - job["last_run"] < job["interval"]:
                    continue

                t_start = time.time()
                if job.get("verbose", True):
                    log_event(job["name"], "start")
                try:
                    job["func"]()
                    job["fail_count"] = 0
                    job["last_error"] = None
                    if job.get("verbose", True):
                        log_event(job["name"], "complete", duration=round(time.time()-t_start, 2))
                except DBWriteError as e:
                    job["fail_count"] += 1
                    job["last_error"] = str(e)
                    log_event(job["name"], "db_error", error=str(e), fail_count=job["fail_count"])
                    print(f"\033[91m💾 [Scheduler/{job['name']}]: DBWriteError: {e}\033[0m")
                    if job["fail_count"] >= self.MAX_FAILURES:
                        crash = SchedulerCrashError(job["name"], job["fail_count"], str(e))
                        job["disabled"] = True
                        log_event(job["name"], "disabled", reason="db_crash", error=str(crash))
                        print(f"\033[91m\U0001f6ab [Scheduler]: {crash}\033[0m")
                        send_telegram_msg(f"\u26a0\ufe0f Watchdog: Job `{job['name']}` \u03b1\u03c0\u03b5\u03bd\u03b5\u03c1\u03b3\u03bf\u03c0\u03bf\u03b9\u03ae\u03b8\u03b7\u03ba\u03b5 (DB errors).\n\u03a4\u03b5\u03bb\u03b5\u03c5\u03c4\u03b1\u03af\u03bf: {str(e)[:200]}")
                except Exception as e:
                    job["fail_count"] += 1
                    job["last_error"] = str(e)
                    log_event(job["name"], "error", error=str(e), fail_count=job["fail_count"])
                    print(f"\033[91m\u274c [Scheduler/{job['name']}]: {e} (fail {job['fail_count']}/{self.MAX_FAILURES})\033[0m")
                    if job["fail_count"] >= self.MAX_FAILURES:
                        crash = SchedulerCrashError(job["name"], job["fail_count"], str(e))
                        job["disabled"] = True
                        log_event(job["name"], "disabled", reason="max_failures", error=str(crash))
                        print(f"\033[91m\U0001f6ab [Scheduler]: {crash}\033[0m")
                        send_telegram_msg(f"\u26a0\ufe0f Watchdog: Job `{job['name']}` \u03b1\u03c0\u03b5\u03bd\u03b5\u03c1\u03b3\u03bf\u03c0\u03bf\u03b9\u03ae\u03b8\u03b7\u03ba\u03b5 \u03bc\u03b5\u03c4\u03ac \u03b1\u03c0\u03cc {self.MAX_FAILURES} \u03c3\u03c6\u03ac\u03bb\u03bc\u03b1\u03c4\u03b1.\n\u03a4\u03b5\u03bb\u03b5\u03c5\u03c4\u03b1\u03af\u03bf: {str(e)[:200]}")
                job["last_run"]      = time.time()
                job["last_duration"] = time.time() - t_start

            self._write_snapshot()
            shutdown_event.wait(timeout=10)

    def status(self) -> str:
        now   = time.time()
        lines = ["\U0001f4ca *Scheduler Status:*"]
        for job in self._jobs:
            icon = "\U0001f6ab" if job["disabled"] else "\u2705"
            if job["last_run"] > 0:
                last_str  = datetime.fromtimestamp(job["last_run"]).strftime("%H:%M:%S")
                next_secs = max(0, int(job["interval"] - (now - job["last_run"])))
                next_str  = f"{next_secs}s"
            else:
                last_str = "\u2014"
                next_str = t("clients.telegram_bot.bot_msg_8f25d1")
            lines.append(
                f"{icon} `{job['name']}` | last: {last_str} | next: {next_str} "
                f"| {job['last_duration']:.1f}s | fails: {job['fail_count']}"
            )
            if job["last_error"]:
                lines.append(f"   \u2514\u2500 \u26a0\ufe0f _{job['last_error'][:100]}_")

        lines.append("")
        lines.append(f"\u23f3 Pending confirmations: {len(pending_routine_confirmations)}")
        lines.append(f"\U0001f4ec Fast Queue: {fast_queue.qsize()} | Slow Queue: {slow_queue.qsize()}")
        quiet = is_quiet_hours()
        quiet_label = t("clients.telegram_bot.bot_msg_1e9be7") if quiet else t("clients.telegram_bot.bot_msg_4e73eb")
        lines.append(f"\U0001f319 Quiet hours: {quiet_label} ({QUIET_HOURS[0]:02d}:00\u2013{QUIET_HOURS[1]:02d}:00)")
        with _proactive_lock:
            lines.append(f"\U0001f4e3 Proactive this hour: {_proactive_count['count']}/{MAX_PROACTIVE_PER_HOUR}")
        with _override_lock:
            paused  = _override_state.get("pause_reminders")
            muted   = _override_state.get("mute_proactive")
            sleep_u = _override_state.get("sleep_until")
            sleeping = sleep_u and _time.time() < sleep_u
        if paused or muted or sleeping:
            ovr = []
            if paused:   ovr.append("reminders paused")
            if muted:    ovr.append("proactive muted")
            if sleeping: ovr.append(f"sleep until {datetime.fromtimestamp(sleep_u).strftime('%H:%M')}")
            lines.append(f"\U0001f6d1 Override: {', '.join(ovr)}")
        return "\n".join(lines)


# ────────────────────────────────────────────────────────────────
# ENTRY POINT
# ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import signal as _signal

    def _handle_exit(*args):
        print(t("clients.telegram_bot.bot_msg_35e7e8"))
        shutdown_event.set()

    _signal.signal(_signal.SIGTERM, _handle_exit)
    _signal.signal(_signal.SIGINT,  _handle_exit)

    threading.Thread(target=fast_queue_worker, daemon=True).start()
    threading.Thread(target=slow_queue_worker, daemon=True).start()

    _load_override_state()
    try:
        from memory.pending_assets import init_pending_assets_table
        init_pending_assets_table()
        ensure_pending_followups_table()
    except Exception as e:
        print(f"[PendingAssets]: Init failed: {e}")
    from memory.routine_db import load_pending_confirmations
    from services.reflection_engine import load_pending_reflections
    pending_routine_confirmations.update(load_pending_confirmations())
    pending_reflection_confirmations.update(load_pending_reflections())
    if pending_routine_confirmations:
        print(f"\033[93m[Recovery]: \u03a6\u03bf\u03c1\u03c4\u03ce\u03b8\u03b7\u03ba\u03b1\u03bd {len(pending_routine_confirmations)} pending confirmations.\033[0m")
    if pending_reflection_confirmations:
        print(f"\033[93m[Recovery]: Loaded {len(pending_reflection_confirmations)} pending reflections.\033[0m")

    astakos_scheduler = AstakosScheduler()
    astakos_scheduler.register(job_check_reminders, interval_seconds=20,    name="reminders",   verbose=False)
    astakos_scheduler.register(job_check_routines,  interval_seconds=60,    name="routines",    verbose=False)
    astakos_scheduler.register(job_proactive_scan,  interval_seconds=43200, name="proactive",   verbose=True)
    astakos_scheduler.register(job_analytics_engine, interval_seconds=3600, name="analytics",   verbose=True)
    astakos_scheduler.register(job_check_pending_followups, interval_seconds=600, name="pending_followups", verbose=False)
    astakos_scheduler.register(job_morning_fit_briefing,       interval_seconds=3600, name="fit_briefing",      verbose=True)
    astakos_scheduler.register(job_morning_calendar_briefing,  interval_seconds=3600, name="cal_briefing",      verbose=True)
    astakos_scheduler.register(job_morning_ai_briefing,        interval_seconds=3600, name="ai_briefing",       verbose=True)
    astakos_scheduler.register(job_morning_hn_briefing,        interval_seconds=3600, name="hn_briefing",       verbose=True)
    astakos_scheduler.register(job_goal_followup,              interval_seconds=3600, name="goal_followup",     verbose=True)
    # astakos_scheduler.register(job_daily_backup,               interval_seconds=3600, name="daily_backup",      verbose=True) # User runs this from Windows Scheduler
    threading.Thread(target=astakos_scheduler.run, daemon=True).start()

    # Startup check for lost routines (10s delay for full initialization)
    def _delayed_missed_check():
        import time as _t
        _t.sleep(10)
        startup_check_missed_routines()
    threading.Thread(target=_delayed_missed_check, daemon=True).start()

    # Stale working memory cleanup (hard restart recovery)
    startup_stale_cleanup(channel="telegram")
    
    # Resume pending summaries that might have crashed mid-flight or piled up
    _maybe_trigger_auto_session_summary(channel="telegram")


    print("\u2501" * 50)
    print(t("clients.telegram_bot.bot_msg_58a238"))
    print("\u2501" * 50)
    
    send_telegram_msg(t("clients.telegram_bot.bot_msg_2cf679"))
    try:
        run_polling()
    except KeyboardInterrupt:
        _handle_exit()
    finally:
        shutdown_event.set()
        # Drain queue before summary (max 5s)
        try:
            import threading as _th
            _done = _th.Event()
            def _drain(): 
                fast_queue.join()
                slow_queue.join()
                _done.set()
            _th.Thread(target=_drain, daemon=True).start()
            _done.wait(timeout=5)
        except Exception:
            pass
        # Graceful ChromaDB shutdown — wait for any pending writes to finish
        try:
            from memory.vector_store import vector_lock
            acquired = vector_lock.acquire(timeout=3)
            if acquired:
                vector_lock.release()
        except Exception:
            pass
        try:
            handle_end_session(TELEGRAM_CHAT_ID)
        except Exception:
            pass
        print('[TelegramBot]: Terminated.')
