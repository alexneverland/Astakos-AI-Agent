from core.i18n import t
from core import nl_config
import json
import sqlite3
import unicodedata
from datetime import datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

from config import STATE_DB



def _coerce_text_scalar(value, default: str = "") -> str:
    if value is None:
        return default

    if isinstance(value, list):
        flat = []
        for item in value:
            if item is None:
                continue
            if isinstance(item, (str, int, float, bool)):
                s = str(item).strip()
                if s:
                    flat.append(s)
        return " ".join(flat) if flat else default

    if isinstance(value, dict):
        return default

    return str(value).strip()

def _coerce_int_scalar(value, default: int = 0) -> int:
    if isinstance(value, list):
        if not value:
            return default
        value = value[0]
    try:
        return int(value)
    except Exception:
        return default

def _coerce_float_scalar(value, default: float = 0.0) -> float:
    if isinstance(value, list):
        if not value:
            return default
        value = value[0]
    try:
        return float(value)
    except Exception:
        return default

FOLLOWUP_TTL_HOURS = 12
FOLLOWUP_LOCAL_TZ = ZoneInfo("Europe/Athens")


def _local_now() -> datetime:
    return datetime.now(FOLLOWUP_LOCAL_TZ)


def _apply_quiet_hours(target: datetime) -> datetime:
    if 0 <= target.hour < 8:
        return target.replace(hour=8, minute=30, second=0, microsecond=0)
    return target

def _coerce_local_dt(dt: Optional[datetime] = None) -> datetime:
    dt = dt or _local_now()
    if dt.tzinfo is None:
        return dt.replace(tzinfo=FOLLOWUP_LOCAL_TZ)
    return dt.astimezone(FOLLOWUP_LOCAL_TZ)


def _conn():
    return sqlite3.connect(STATE_DB)


def _normalize_match_text(text: str) -> str:
    raw = str(text or "").strip().lower()
    if not raw:
        return ""
    normalized = unicodedata.normalize("NFKD", raw)
    return "".join(ch for ch in normalized if not unicodedata.combining(ch))


def ensure_pending_followups_table():
    conn = _conn()
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS pending_followups (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_channel TEXT NOT NULL,
                source_agent TEXT,
                topic TEXT NOT NULL,
                subject TEXT NOT NULL,
                source_user_text TEXT,
                source_ai_text TEXT,
                followup_after_ts TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                confidence REAL DEFAULT 0.0,
                status TEXT NOT NULL DEFAULT 'pending',
                resolution_reason TEXT DEFAULT '',
                metadata_json TEXT DEFAULT '',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                sent_at TEXT,
                resolved_at TEXT
            )
            """
        )
        existing_cols = {
            row[1] for row in conn.execute("PRAGMA table_info(pending_followups)").fetchall()
        }

        if "arc_key" not in existing_cols:
            conn.execute("ALTER TABLE pending_followups ADD COLUMN arc_key TEXT DEFAULT ''")
        if "last_decision" not in existing_cols:
            conn.execute("ALTER TABLE pending_followups ADD COLUMN last_decision TEXT DEFAULT ''")
        if "decision_reason" not in existing_cols:
            conn.execute("ALTER TABLE pending_followups ADD COLUMN decision_reason TEXT DEFAULT ''")
        if "outcome_score" not in existing_cols:
            conn.execute("ALTER TABLE pending_followups ADD COLUMN outcome_score REAL DEFAULT 0.0")
        if "times_sent" not in existing_cols:
            conn.execute("ALTER TABLE pending_followups ADD COLUMN times_sent INTEGER DEFAULT 0")

        conn.commit()
    finally:
        conn.close()


def build_followup_arc_key(topic: str, subject: str) -> str:
    tokens = [tok for tok in (subject or "").lower().split() if len(tok) >= 4]
    tokens = sorted(set(tokens))[:4]
    return f"{(topic or '').strip().lower()}::{' '.join(tokens)}".strip()


def _tokenize_followup_text(text: str) -> list[str]:
    normalized = _normalize_match_text(text or "")
    return [tok for tok in normalized.split() if len(tok) >= 4]


def _build_followup_theme_tokens(
    *,
    topic: str,
    subject: str = "",
    source_user_text: str = "",
    reason: str = "",
    include_reason: bool = True,
) -> set[str]:
    parts = [
        subject or "",
        source_user_text or "",
    ]

    if include_reason:
        parts.append(reason or "")

    tokens = set()
    for part in parts:
        for tok in _tokenize_followup_text(part):
            if len(tok) >= 4:
                tokens.add(tok)

    generic = {
        t("prompts.ext_str_530"), t("prompts.ext_str_588"), t("prompts.ext_str_543"), t("prompts.ext_str_689"), t("prompts.ext_str_290"),
        t("prompts.ext_str_674"), t("prompts.ext_str_751"), t("prompts.ext_str_469"), t("prompts.ext_str_691"), t("prompts.ext_str_738"), t("prompts.ext_str_792"),
        t("prompts.ext_str_829"), t("prompts.ext_str_672"), t("prompts.ext_str_591"), t("prompts.ext_str_836"), t("prompts.ext_str_784"), t("prompts.ext_str_822"),
        "follow", "check", "later", "update", t("prompts.ext_str_722"), t("prompts.ext_str_759"),
    }
    return {tok for tok in tokens if tok not in generic}


def _active_followup_is_same_theme(
    *,
    topic: str,
    subject: str,
    source_user_text: str,
    reason: str,
    existing_topic: str,
    existing_subject: str,
    existing_source_user_text: str,
    existing_reason: str,
) -> bool:
    topic = _coerce_text_scalar(topic, "").lower()
    existing_topic = (existing_topic or "").strip().lower()

    if not topic or topic != existing_topic:
        return False

    new_tokens = _build_followup_theme_tokens(
        topic=topic,
        subject=subject,
        source_user_text=source_user_text,
        reason=reason,
        include_reason=False,
    )
    old_tokens = _build_followup_theme_tokens(
        topic=existing_topic,
        subject=existing_subject,
        source_user_text=existing_source_user_text,
        reason=existing_reason,
        include_reason=False,
    )

    if not new_tokens or not old_tokens:
        return False

    new_subject_tokens = _build_followup_theme_tokens(
        topic="",
        subject=subject,
        source_user_text="",
        reason="",
        include_reason=False,
    )
    old_subject_tokens = _build_followup_theme_tokens(
        topic="",
        subject=existing_subject,
        source_user_text="",
        reason="",
        include_reason=False,
    )

    overlap = new_tokens & old_tokens
    subject_overlap = new_subject_tokens & old_subject_tokens

    if len(subject_overlap) >= 2:
        return True

    if any(len(tok) >= 8 for tok in subject_overlap):
        return True

    if len(overlap) >= 2:
        return True

    if len(overlap) == 1:
        only_token = next(iter(overlap))
        if len(only_token) >= 8:
            return True

    return False



def _delay_until_next_window(now: datetime, hour: int, minute: int = 0) -> int:
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target <= now:
        target = target + timedelta(days=1)
    return max(1, int((target - now).total_seconds() / 60))


def _apply_weekend_window_adjustment(target: datetime) -> datetime:
    if target.weekday() >= 5 and (target.hour, target.minute) < (11, 0):
        return target.replace(hour=11, minute=0, second=0, microsecond=0)
    return target


def _delay_until_target(now: datetime, target: datetime) -> int:
    target = _coerce_local_dt(target)
    if target <= now:
        target = target + timedelta(days=1)
    return max(1, int((target - now).total_seconds() / 60))


def _delay_until_next_day_window(now: datetime, hour: int, minute: int = 0) -> int:
    target = (now + timedelta(days=1)).replace(
        hour=hour,
        minute=minute,
        second=0,
        microsecond=0,
    )
    target = _apply_weekend_window_adjustment(target)
    return _delay_until_target(now, target)


def _compute_followup_ttl_hours(
    delay_minutes: int,
    target_window: str = "",
    topic: str = "",
) -> int:
    target_window = _coerce_text_scalar(target_window, "").lower()
    topic = _coerce_text_scalar(topic, "").lower()

    if target_window in {
        "next_day_morning",
        "next_day_late_morning",
        "next_day_afternoon",
        "next_day_evening",
    }:
        return 18

    if target_window == "explicit_timer":
        if delay_minutes >= 12 * 60:
            return 18
        if delay_minutes >= 6 * 60:
            return 12
        return 8

    if target_window == "after_likely_completion":
        if topic in {"food_purchase", "appointment", "family_plan"}:
            return 12
        return 8

    if delay_minutes >= 12 * 60:
        return 18
    if delay_minutes >= 6 * 60:
        return 12
    return 6


def _infer_legacy_target_window(
    *,
    topic: str,
    source_user_text: str = "",
    reason: str = "",
    delay_minutes_raw: int = 0,
) -> str:
    text = _normalize_match_text(f"{source_user_text} {reason}")
    topic = _coerce_text_scalar(topic, "").lower()

    if t("prompts.ext_str_820") in text and t("prompts.ext_str_842") in text:
        return "explicit_timer"

    if any(marker in text for marker in (t("prompts.ext_str_588"), *nl_config.RI_FOLLOWUP_NEXT_DAY_WORDS)):
        if topic == "food_purchase":
            return "next_day_late_morning"
        if topic == "outing":
            return "next_day_afternoon"
        if topic == "appointment":
            return "next_day_afternoon"
        return "next_day_morning"

    if any(
        marker in text
        for marker in (
            t("prompts.ext_str_646"),
            t("prompts.ext_str_747"),
            *nl_config.RI_FOLLOWUP_SAME_DAY_EVENING_WORDS,
        )
    ):
        return "same_day_evening"

    if topic == "outing":
        return "same_day_short_checkin"
    if topic == "food_purchase":
        return "after_likely_completion"

    if delay_minutes_raw >= 12 * 60:
        return "next_day_morning"
    if delay_minutes_raw <= 90:
        return "same_day_short_checkin"
    return "after_likely_completion"


def _next_occurrence_for_window(now: datetime, target_window: str, fallback_delay_minutes: int) -> datetime:
    target_window = _coerce_text_scalar(target_window, "").lower()
    fallback_delay_minutes = max(15, int(fallback_delay_minutes or 60))

    def _today_or_tomorrow(hour: int, minute: int = 0, *, force_tomorrow: bool = False) -> datetime:
        import random
        jitter_minutes = random.randint(-15, 30)
        base = now + timedelta(days=1) if force_tomorrow else now
        target = base.replace(hour=hour, minute=minute, second=0, microsecond=0) + timedelta(minutes=jitter_minutes)
        target = _apply_weekend_window_adjustment(target)
        if not force_tomorrow and target <= now:
            target = target + timedelta(days=1)
            target = _apply_weekend_window_adjustment(target)
        return _apply_quiet_hours(target)

    if target_window == "same_day_short_checkin":
        return _apply_quiet_hours(now + timedelta(minutes=min(fallback_delay_minutes, 90)))
    if target_window == "same_day_evening":
        return _today_or_tomorrow(19, 30)
    if target_window == "next_day_morning":
        return _today_or_tomorrow(9, 30, force_tomorrow=True)
    if target_window == "next_day_late_morning":
        return _today_or_tomorrow(11, 30, force_tomorrow=True)
    if target_window == "next_day_afternoon":
        return _today_or_tomorrow(14, 30, force_tomorrow=True)
    if target_window == "next_day_evening":
        return _today_or_tomorrow(19, 30, force_tomorrow=True)
    if target_window == "after_likely_completion":
        return _apply_quiet_hours(now + timedelta(minutes=min(max(fallback_delay_minutes, 60), 300)))
    if target_window == "explicit_timer":
        return _apply_quiet_hours(now + timedelta(minutes=fallback_delay_minutes))

    return _apply_quiet_hours(now + timedelta(minutes=min(max(fallback_delay_minutes, 60), 300)))


_FOLLOWUP_TARGET_WINDOWS = frozenset(
    {
        "",
        "explicit_timer",
        "same_day_short_checkin",
        "same_day_evening",
        "next_day_morning",
        "next_day_late_morning",
        "next_day_afternoon",
        "next_day_evening",
        "after_likely_completion",
    }
)

_NEXT_DAY_FOLLOWUP_WINDOWS = frozenset(
    {
        "next_day_morning",
        "next_day_late_morning",
        "next_day_afternoon",
        "next_day_evening",
    }
)


def normalize_followup_target_window(
    target_window: str,
    source_user_text: str = "",
) -> str:
    """Allow next-day scheduling only when the user explicitly says so."""
    window = _coerce_text_scalar(target_window, "").lower()
    if window not in _FOLLOWUP_TARGET_WINDOWS:
        return ""

    if window not in _NEXT_DAY_FOLLOWUP_WINDOWS:
        return window

    text = _normalize_match_text(source_user_text)
    next_day_markers = tuple(
        _normalize_match_text(marker)
        for marker in nl_config.RI_FOLLOWUP_NEXT_DAY_WORDS
        if marker
    )
    if any(marker in text for marker in next_day_markers):
        return window

    return "after_likely_completion"


def normalize_followup_delay(
    topic: str,
    suggested_minutes: int,
    source_user_text: str = "",
    target_window: str = "",
    now: Optional[datetime] = None,
) -> int:
    text = _normalize_match_text(source_user_text or "")
    topic = _coerce_text_scalar(topic, "").lower()
    target_window = normalize_followup_target_window(
        target_window,
        source_user_text,
    )
        
    raw_value = int(suggested_minutes or 0)
    now = _coerce_local_dt(now)

    # Base trust in LLM, but keep sane bounds
    value = max(15, min(raw_value, 48 * 60))

    # 1) If user explicitly asked for a concrete timer, trust the LLM delay
    if target_window == "explicit_timer":
        target_time = _apply_quiet_hours(now + timedelta(minutes=value))
        final_minutes = int((target_time - now).total_seconds() / 60.0)
        return max(15, final_minutes)

    # 2) Semantic windows still own the scheduling intent
    if target_window == "same_day_short_checkin":
        semantic_delay = max(20, min(value, 90))
        target_time = _apply_quiet_hours(now + timedelta(minutes=semantic_delay))
        final_minutes = int((target_time - now).total_seconds() / 60.0)
        return max(15, final_minutes)

    if target_window == "same_day_evening":
        target_time = _next_occurrence_for_window(now, target_window, value)
        final_minutes = int((target_time - now).total_seconds() / 60.0)
        return max(15, final_minutes)

    if target_window in {
        "next_day_morning",
        "next_day_late_morning",
        "next_day_afternoon",
        "next_day_evening",
        "after_likely_completion",
    }:
        target_time = _next_occurrence_for_window(now, target_window, value)
        final_minutes = int((target_time - now).total_seconds() / 60.0)
        return max(15, final_minutes)

    # 3) Fallback semantic heuristics when LLM didn't provide a good window
    if topic == "outing":
        fallback_delay = max(30, min(value, 180))
        target_time = _apply_quiet_hours(now + timedelta(minutes=fallback_delay))
        final_minutes = int((target_time - now).total_seconds() / 60.0)
        return max(15, final_minutes)

    if topic == "food_purchase":
        if t("prompts.ext_str_588") in text or t("prompts.ext_str_655") in text:
            target_time = _next_occurrence_for_window(now, "next_day_late_morning", value)
            final_minutes = int((target_time - now).total_seconds() / 60.0)
            return max(15, final_minutes)

        if t("prompts.ext_str_646") in text or t("prompts.ext_str_653") in text or t("prompts.ext_str_747") in text:
            fallback_delay = max(45, min(value, 240))
            target_time = _apply_quiet_hours(now + timedelta(minutes=fallback_delay))
            final_minutes = int((target_time - now).total_seconds() / 60.0)
            return max(15, final_minutes)

        fallback_delay = max(90, min(value, 360))
        target_time = _apply_quiet_hours(now + timedelta(minutes=fallback_delay))
        final_minutes = int((target_time - now).total_seconds() / 60.0)
        return max(15, final_minutes)

    # 4) Generic fallback: trust LLM minutes, then quiet hours
    target_time = _apply_quiet_hours(now + timedelta(minutes=value))
    final_minutes = int((target_time - now).total_seconds() / 60.0)
    return max(15, final_minutes)


def create_pending_followup(
    *,
    source_channel: str,
    source_agent: str,
    topic: str,
    subject: str,
    source_user_text: str,
    source_ai_text: str,
    followup_after_ts: str,
    confidence: float = 0.0,
    metadata: Optional[dict] = None,
    ttl_hours: Optional[int] = None,
):
    ensure_pending_followups_table()
    conn = _conn()
    try:
        ttl_hours = int(ttl_hours or FOLLOWUP_TTL_HOURS)
        due_dt = datetime.fromisoformat(followup_after_ts)
        if due_dt.tzinfo is None:
            due_dt = due_dt.replace(tzinfo=FOLLOWUP_LOCAL_TZ)
        else:
            due_dt = due_dt.astimezone(FOLLOWUP_LOCAL_TZ)

        expires_at = (due_dt + timedelta(hours=ttl_hours)).isoformat(timespec="seconds")

        metadata_json = json.dumps(metadata or {}, ensure_ascii=False)
        arc_key = build_followup_arc_key(topic, subject)

        existing = conn.execute(
            """
            SELECT id, topic, subject, source_user_text, metadata_json, arc_key
            FROM pending_followups
            WHERE status='pending'
            ORDER BY id DESC
            """
        ).fetchall()

        for row in existing:
            existing_id = int(row[0])
            existing_topic = str(row[1] or "").strip().lower()
            existing_subject = str(row[2] or "")
            existing_source_user_text = str(row[3] or "")
            existing_arc_key = str(row[5] or "").strip()

            try:
                existing_meta = json.loads(row[4] or "{}")
            except Exception:
                existing_meta = {}

            existing_reason = str(existing_meta.get("reason") or "")

            if topic == existing_topic and subject == existing_subject:
                return None

            if arc_key and existing_arc_key and arc_key == existing_arc_key:
                return None

            if _active_followup_is_same_theme(
                topic=topic,
                subject=subject,
                source_user_text=source_user_text,
                reason=str((metadata or {}).get("reason") or ""),
                existing_topic=existing_topic,
                existing_subject=existing_subject,
                existing_source_user_text=existing_source_user_text,
                existing_reason=existing_reason,
            ):
                print(f"[FollowUp]: create-skip same-theme active arc (existing #{existing_id})")
                return None

        cur = conn.execute(
            """
            INSERT INTO pending_followups (
                source_channel,
                source_agent,
                topic,
                subject,
                arc_key,
                source_user_text,
                source_ai_text,
                followup_after_ts,
                expires_at,
                confidence,
                metadata_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                source_channel,
                source_agent,
                topic,
                subject,
                arc_key,
                source_user_text,
                source_ai_text,
                followup_after_ts,
                expires_at,
                confidence,
                metadata_json,
            ),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def create_pending_followup_from_candidate(
    *,
    candidate: dict,
    source_channel: str,
    source_agent: str,
    source_user_text: str,
    source_ai_text: str,
):
    topic = str(candidate.get("topic") or "").strip().lower()
    subject = str(candidate.get("subject") or "").strip()
    delay_minutes_raw = int(candidate.get("delay_minutes") or 0)
    confidence = float(candidate.get("confidence") or 0.0)

    if not topic or not subject:
        return None
    if confidence < 0.45:
        return None

    now = _local_now()

    target_window = normalize_followup_target_window(
        str(candidate.get("target_window") or ""),
        source_user_text,
    )

    delay_minutes = normalize_followup_delay(
        topic=topic,
        suggested_minutes=delay_minutes_raw,
        source_user_text=source_user_text,
        target_window=target_window,
        now=now,
    )

    ttl_hours = _compute_followup_ttl_hours(
        delay_minutes=delay_minutes,
        target_window=target_window,
        topic=topic,
    )

    followup_after_ts = (
        now + timedelta(minutes=delay_minutes)
    ).isoformat(timespec="seconds")

    followup_id = create_pending_followup(
        source_channel=source_channel,
        source_agent=source_agent,
        topic=topic,
        subject=subject,
        source_user_text=source_user_text,
        source_ai_text=source_ai_text,
        followup_after_ts=followup_after_ts,
        confidence=confidence,
        ttl_hours=ttl_hours,
        metadata={
            "reason": candidate.get("reason", ""),
            "target_window": target_window,
            "ttl_hours": ttl_hours,
            "delay_minutes_raw": delay_minutes_raw,
            "delay_minutes_final": delay_minutes,
            "defer_count": 0,
        },
    )

    if followup_id:
        print(
            f"[FollowUp]: created #{followup_id} ({topic}) -> {subject} "
            f"[{delay_minutes_raw}m -> {delay_minutes}m]"
        )
    return followup_id


def get_due_pending_followups(now_iso: str) -> list[dict]:
    ensure_pending_followups_table()
    conn = _conn()
    try:
        rows = conn.execute(
            """
            SELECT
                id,
                source_channel,
                source_agent,
                topic,
                subject,
                source_user_text,
                source_ai_text,
                followup_after_ts,
                expires_at,
                confidence,
                metadata_json,
                created_at,
                last_decision,
                decision_reason,
                outcome_score,
                times_sent
            FROM pending_followups
            WHERE status='pending'
              AND followup_after_ts <= ?
              AND expires_at > ?
            ORDER BY followup_after_ts ASC, id ASC
            """,
            (now_iso, now_iso),
        ).fetchall()

        out = []
        for row in rows:
            out.append(
                {
                    "id": row[0],
                    "source_channel": row[1],
                    "source_agent": row[2],
                    "topic": row[3],
                    "subject": row[4],
                    "source_user_text": row[5] or "",
                    "source_ai_text": row[6] or "",
                    "followup_after_ts": row[7],
                    "expires_at": row[8],
                    "confidence": float(row[9] or 0.0),
                    "metadata": json.loads(row[10] or "{}"),
                    "created_at": row[11],
                    "last_decision": row[12] or "",
                    "decision_reason": row[13] or "",
                    "outcome_score": float(row[14] or 0.0),
                    "times_sent": int(row[15] or 0),
                }
            )
        return out
    finally:
        conn.close()


def get_recently_resolved_followups(limit: int = 5, within_seconds: int = 180) -> list[dict]:
    ensure_pending_followups_table()
    conn = _conn()
    try:
        cutoff = _local_now() - timedelta(seconds=within_seconds)
        rows = conn.execute(
            """
            SELECT id, topic, subject, arc_key, resolution_reason, decision_reason, resolved_at
            FROM pending_followups
            WHERE status='resolved'
              AND resolved_at IS NOT NULL
            ORDER BY resolved_at DESC, id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()

        out = []
        for row in rows:
            try:
                resolved_at = _coerce_local_dt(datetime.fromisoformat(str(row[6]).replace(" ", "T")))
            except Exception:
                continue
            if resolved_at < cutoff:
                continue
            out.append(
                {
                    "id": row[0],
                    "topic": row[1] or "",
                    "subject": row[2] or "",
                    "arc_key": row[3] or "",
                    "resolution_reason": row[4] or "",
                    "decision_reason": row[5] or "",
                    "resolved_at": str(row[6]),
                }
            )
        return out
    finally:
        conn.close()


def candidate_is_distinct_from_recently_resolved(candidate: dict, recent_resolved: list[dict]) -> bool:
    topic = str(candidate.get("topic") or "").strip().lower()
    subject = str(candidate.get("subject") or "").strip()
    arc_key = build_followup_arc_key(topic, subject)

    for item in recent_resolved or []:
        existing_arc = str(item.get("arc_key") or "").strip()
        if arc_key and existing_arc and arc_key == existing_arc:
            return False
    return True


def mark_followup_sent(followup_id: int, decision_reason: str = "followup_sent"):
    conn = _conn()
    try:
        from datetime import datetime
        now_iso = _local_now().isoformat(timespec="seconds")
        conn.execute(
            """
            UPDATE pending_followups
            SET status='sent',
                sent_at=?,
                resolved_at=NULL,
                last_decision='sent',
                decision_reason=?,
                times_sent=COALESCE(times_sent, 0) + 1
            WHERE id=?
            """,
            (now_iso, decision_reason, followup_id),
        )
        conn.commit()
    finally:
        conn.close()

    record_followup_outcome(followup_id, +0.2, decision_reason)


def resolve_followup(followup_id: int, reason: str):
    conn = _conn()
    try:
        now_iso = _local_now().isoformat(timespec="seconds")
        conn.execute(
            """
            UPDATE pending_followups
            SET status='resolved',
                resolution_reason=?,
                resolved_at=?,
                last_decision='resolved',
                decision_reason=?
            WHERE id=?
            """,
            (reason, now_iso, reason, followup_id),
        )
        conn.commit()
    finally:
        conn.close()
        
    record_followup_outcome(followup_id, +1.0, reason)


def defer_followup(
    followup_id: int,
    *,
    delay_minutes: int,
    reason: str = "deferred_by_user_reply",
    target_window: str = "",
    topic: str = "",
) -> None:
    ensure_pending_followups_table()
    conn = _conn()
    try:
        now = _local_now()
        safe_delay = max(15, int(delay_minutes))
        next_due = now + timedelta(minutes=safe_delay)
        ttl_hours = _compute_followup_ttl_hours(
            delay_minutes=safe_delay,
            target_window=target_window,
            topic=topic,
        )
        next_expires = next_due + timedelta(hours=ttl_hours)

        row = conn.execute(
            "SELECT metadata_json FROM pending_followups WHERE id=?",
            (followup_id,),
        ).fetchone()

        metadata = {}
        if row and row[0]:
            try:
                metadata = json.loads(row[0])
            except Exception:
                metadata = {}

        metadata["ttl_hours"] = ttl_hours
        metadata["delay_minutes_final"] = safe_delay
        metadata["defer_count"] = int(metadata.get("defer_count") or 0) + 1
        if target_window:
            metadata["target_window"] = target_window

        conn.execute(
            """
            UPDATE pending_followups
            SET
                status='pending',
                followup_after_ts=?,
                expires_at=?,
                metadata_json=?,
                last_decision='deferred',
                decision_reason=?,
                resolution_reason='',
                sent_at=NULL
            WHERE id=?
            """,
            (
                next_due.isoformat(timespec="seconds"),
                next_expires.isoformat(timespec="seconds"),
                json.dumps(metadata, ensure_ascii=False),
                reason,
                followup_id,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def delete_followup(followup_id: int, reason: str = "manual_delete") -> bool:
    ensure_pending_followups_table()
    conn = _conn()
    try:
        cur = conn.execute(
            "DELETE FROM pending_followups WHERE id=?",
            (followup_id,),
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def backfill_legacy_followups(limit: Optional[int] = None, force_retime: bool = False) -> int:
    ensure_pending_followups_table()
    conn = _conn()
    try:
        sql = """
            SELECT
                id, topic, subject, status, followup_after_ts, expires_at,
                created_at, source_user_text, metadata_json
            FROM pending_followups
            ORDER BY id ASC
        """
        params: tuple = ()
        if limit is not None:
            sql += " LIMIT ?"
            params = (int(limit),)

        rows = conn.execute(sql, params).fetchall()
        updated = 0
        now = _local_now()

        for row in rows:
            followup_id = int(row[0])
            topic = str(row[1] or "").strip().lower()
            status = str(row[3] or "").strip().lower()
            created_raw = str(row[6] or "").strip()
            source_user_text = str(row[7] or "").strip()

            try:
                metadata = json.loads(row[8] or "{}")
            except Exception:
                metadata = {}

            missing_target = not str(metadata.get("target_window") or "").strip()
            missing_ttl = not metadata.get("ttl_hours")
            missing_delay = not metadata.get("delay_minutes_final")
            needs_full_retiming = force_retime or missing_target or missing_ttl

            if not (missing_target or missing_ttl or missing_delay or force_retime):
                continue

            created_dt = _coerce_local_dt(datetime.fromisoformat(created_raw.replace(" ", "T")))
            existing_due_raw = str(row[4] or "").strip()
            try:
                existing_due_dt = _coerce_local_dt(datetime.fromisoformat(existing_due_raw.replace(" ", "T")))
            except Exception:
                existing_due_dt = created_dt + timedelta(hours=6)

            raw_delay = int(
                metadata.get("delay_minutes_raw")
                or max(30, int((existing_due_dt - created_dt).total_seconds() / 60))
            )
            inferred_window = str(
                metadata.get("target_window")
                or _infer_legacy_target_window(
                    topic=topic,
                    source_user_text=source_user_text,
                    reason=str(metadata.get("reason") or ""),
                    delay_minutes_raw=raw_delay,
                )
            ).strip()

            if needs_full_retiming:
                final_delay = int(
                    normalize_followup_delay(
                        topic=topic,
                        suggested_minutes=raw_delay,
                        source_user_text=source_user_text or str(metadata.get("reason") or ""),
                        target_window=inferred_window,
                        now=created_dt,
                    )
                )
            else:
                final_delay = int(metadata.get("delay_minutes_final") or raw_delay)
            ttl_hours = int(
                metadata.get("ttl_hours")
                or _compute_followup_ttl_hours(
                    delay_minutes=final_delay,
                    target_window=inferred_window,
                    topic=topic,
                )
            )

            due_dt = created_dt + timedelta(minutes=final_delay)
            if status == "pending" and due_dt <= now:
                due_dt = _next_occurrence_for_window(now, inferred_window, final_delay)

            expires_dt = due_dt + timedelta(hours=ttl_hours)

            metadata["target_window"] = inferred_window
            metadata["ttl_hours"] = ttl_hours
            metadata["delay_minutes_raw"] = raw_delay
            metadata["delay_minutes_final"] = final_delay

            conn.execute(
                """
                UPDATE pending_followups
                SET followup_after_ts=?,
                    expires_at=?,
                    metadata_json=?
                WHERE id=?
                """,
                (
                    due_dt.isoformat(timespec="seconds"),
                    expires_dt.isoformat(timespec="seconds"),
                    json.dumps(metadata, ensure_ascii=False),
                    followup_id,
                ),
            )
            updated += 1

        conn.commit()
        return updated
    finally:
        conn.close()


def find_followups_for_control(
    subject_query: str,
    *,
    topic: str = "",
    statuses: tuple[str, ...] = ("pending", "sent"),
) -> list[dict]:
    ensure_pending_followups_table()
    query_tokens = set(_tokenize_followup_text(subject_query))
    topic = _coerce_text_scalar(topic, "").lower()
    conn = _conn()
    try:
        placeholders = ",".join("?" for _ in statuses)
        rows = conn.execute(
            f"""
            SELECT id, topic, subject, status, followup_after_ts, expires_at,
                   source_channel, source_agent, metadata_json, arc_key
            FROM pending_followups
            WHERE status IN ({placeholders})
            ORDER BY id DESC
            """,
            tuple(statuses),
        ).fetchall()

        matches: list[tuple[int, dict]] = []
        for row in rows:
            row_topic = str(row[1] or "").strip().lower()
            row_subject = str(row[2] or "")
            if topic and row_topic != topic:
                continue

            subject_tokens = set(_tokenize_followup_text(row_subject))
            overlap = len(query_tokens & subject_tokens)

            score = overlap
            if subject_query and subject_query.strip().lower() in row_subject.lower():
                score += 3
            if topic and row_topic == topic:
                score += 1

            if score <= 0:
                continue

            try:
                metadata = json.loads(row[8] or "{}")
            except Exception:
                metadata = {}

            matches.append(
                (
                    score,
                    {
                        "id": int(row[0]),
                        "topic": row_topic,
                        "subject": row_subject,
                        "status": str(row[3] or ""),
                        "followup_after_ts": str(row[4] or ""),
                        "expires_at": str(row[5] or ""),
                        "source_channel": str(row[6] or ""),
                        "source_agent": str(row[7] or ""),
                        "metadata": metadata,
                        "arc_key": str(row[9] or ""),
                    },
                )
            )

        matches.sort(key=lambda item: (item[0], item[1]["id"]), reverse=True)
        return [item[1] for item in matches]
    finally:
        conn.close()


def _set_followup_decision(followup_id: int, decision: str, reason: str = ""):
    conn = _conn()
    try:
        conn.execute(
            """
            UPDATE pending_followups
            SET last_decision=?,
                decision_reason=?
            WHERE id=?
            """,
            (decision, reason, followup_id),
        )
        conn.commit()
    finally:
        conn.close()


def expire_old_followups(now_iso: str):
    conn = _conn()
    try:
        cur = conn.execute(
            "SELECT id FROM pending_followups WHERE status IN ('pending', 'sent') AND expires_at <= ?",
            (now_iso,)
        )
        expired_ids = [row[0] for row in cur.fetchall()]

        if expired_ids:
            conn.execute(
                """
                UPDATE pending_followups
                SET status='expired',
                    resolution_reason='ttl_expired',
                    resolved_at=?,
                    last_decision='expired'
                WHERE status IN ('pending', 'sent') AND expires_at <= ?
                """,
                (now_iso, now_iso),
            )
            conn.commit()
    finally:
        conn.close()

    for fid in expired_ids:
        record_followup_outcome(fid, -0.5, "ttl_expired")


def reanchor_pending_followups_to_target_windows(limit: int = 50) -> int:
    ensure_pending_followups_table()
    now = _local_now()
    now_iso = now.isoformat(timespec="seconds")

    conn = _conn()
    try:
        rows = conn.execute(
            """
            SELECT id, topic, source_user_text, followup_after_ts, metadata_json
            FROM pending_followups
            WHERE status='pending'
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()

        updated = 0

        for row in rows:
            followup_id = int(row[0])
            topic = str(row[1] or "")
            source_user_text = str(row[2] or "")
            current_followup_after_ts = str(row[3] or "")

            try:
                metadata = json.loads(row[4] or "{}")
            except Exception:
                metadata = {}

            target_window = str(metadata.get("target_window") or "").strip()
            if not target_window:
                continue

            raw_delay = int(metadata.get("delay_minutes_raw") or 0)
            expected_delay = normalize_followup_delay(
                topic=topic,
                suggested_minutes=raw_delay,
                source_user_text=source_user_text,
                target_window=target_window,
                now=now,
            )

            expected_followup_dt = now + timedelta(minutes=expected_delay)
            expected_followup_iso = expected_followup_dt.isoformat(timespec="seconds")

            try:
                current_dt = _coerce_local_dt(datetime.fromisoformat(current_followup_after_ts))
            except Exception:
                current_dt = None

            if current_dt is not None:
                diff_minutes = abs(int((expected_followup_dt - current_dt).total_seconds() / 60))
                if diff_minutes <= 20:
                    continue

            ttl_hours = _compute_followup_ttl_hours(
                expected_delay,
                target_window=target_window,
                topic=topic,
            )
            expires_dt = expected_followup_dt + timedelta(hours=ttl_hours)

            metadata["delay_minutes_final"] = expected_delay
            metadata["ttl_hours"] = ttl_hours
            metadata["target_window"] = target_window

            conn.execute(
                """
                UPDATE pending_followups
                SET followup_after_ts=?,
                    expires_at=?,
                    metadata_json=?,
                    last_decision=?,
                    decision_reason=?
                WHERE id=?
                """,
                (
                    expected_followup_iso,
                    expires_dt.isoformat(timespec="seconds"),
                    json.dumps(metadata, ensure_ascii=False),
                    "reanchored",
                    f"reanchored_to:{target_window}",
                    followup_id,
                ),
            )
            updated += 1

        conn.commit()
        return updated
    finally:
        conn.close()


def find_pending_followups(limit: int = 20, *, active_only: bool = True) -> list[dict]:
    ensure_pending_followups_table()
    conn = _conn()
    try:
        where_sql = "WHERE status IN ('pending', 'sent')" if active_only else ""
        query = (
            """
            SELECT
                id,
                topic,
                subject,
                status,
                followup_after_ts,
                expires_at,
                created_at,
                source_channel,
                source_agent,
                source_user_text,
                last_decision,
                decision_reason,
                outcome_score,
                times_sent,
                metadata_json,
                arc_key
            FROM pending_followups
            """
            + where_sql
            + """
            ORDER BY id DESC
            LIMIT ?
            """
        )
        rows = conn.execute(
            query,
            (limit,),
        ).fetchall()
        from datetime import datetime
        return [
            {
                "id": r[0],
                "topic": r[1],
                "subject": r[2],
                "status": r[3],
                "followup_after_ts": r[4],
                "expires_at": r[5],
                "created_at": r[6],
                "source_channel": r[7],
                "source_agent": r[8],
                "source_user_text": r[9],
                "last_decision": r[10],
                "decision_reason": r[11],
                "outcome_score": float(r[12] or 0.0),
                "times_sent": int(r[13] or 0),
                "metadata": json.loads(r[14] or "{}"),
                "arc_key": r[15] or "",
                "due_in_minutes": max(
                    0,
                    int((datetime.fromisoformat(r[4]).replace(tzinfo=FOLLOWUP_LOCAL_TZ) - _local_now()).total_seconds() / 60)
                ) if r[3] == "pending" else None,
            }
            for r in rows
        ]
    finally:
        conn.close()


def has_recent_sent_followup(within_minutes: int = 90) -> bool:
    conn = _conn()
    try:
        row = conn.execute(
            """
            SELECT sent_at
            FROM pending_followups
            WHERE status='sent' AND sent_at IS NOT NULL
            ORDER BY sent_at DESC, id DESC
            LIMIT 1
            """
        ).fetchone()

        if not row or not row[0]:
            return False

        last_sent = datetime.fromisoformat(str(row[0]).replace(" ", "T"))
        last_sent = last_sent.replace(tzinfo=FOLLOWUP_LOCAL_TZ) if last_sent.tzinfo is None else last_sent.astimezone(FOLLOWUP_LOCAL_TZ)
        return (_local_now() - last_sent) <= timedelta(minutes=within_minutes)
    finally:
        conn.close()


def has_recent_sent_followup_for_arc(arc_key: str, within_minutes: int = 240) -> bool:
    conn = _conn()
    try:
        row = conn.execute(
            """
            SELECT sent_at
            FROM pending_followups
            WHERE arc_key=? AND status='sent' AND sent_at IS NOT NULL
            ORDER BY sent_at DESC, id DESC
            LIMIT 1
            """,
            (arc_key,),
        ).fetchone()

        if not row or not row[0]:
            return False

        last_sent = datetime.fromisoformat(str(row[0]).replace(" ", "T"))
        last_sent = last_sent.replace(tzinfo=FOLLOWUP_LOCAL_TZ) if last_sent.tzinfo is None else last_sent.astimezone(FOLLOWUP_LOCAL_TZ)
        return (_local_now() - last_sent) <= timedelta(minutes=within_minutes)
    finally:
        conn.close()


def looks_like_followup_resolution_update(user_text: str) -> bool:
    text = _normalize_match_text(user_text)
    if not text:
        return False

    if len(text.split()) > 18:
        return False

    resolution_markers = (
        t("prompts.ext_str_534"),
        t("prompts.ext_str_821"),
        t("prompts.ext_str_319"),
        t("prompts.ext_str_281"),
        t("prompts.ext_str_369"),
        t("prompts.ext_str_403"),
        t("prompts.ext_str_285"),
        t("prompts.ext_str_313"),
        t("prompts.ext_str_516"),
        t("prompts.ext_str_529"),
        t("prompts.ext_str_551"),
        t("prompts.ext_str_572"),
        t("prompts.ext_str_713"),
        t("prompts.ext_str_738"),
        t("prompts.ext_str_608"),
        t("prompts.ext_str_649"),
        t("prompts.ext_str_563"),
        t("prompts.ext_str_660"),
        t("prompts.ext_str_787"),
        t("prompts.ext_str_792"),
        t("prompts.ext_str_316"),
        t("prompts.ext_str_308"),
        t("prompts.ext_str_253"),
        t("prompts.ext_str_254"),
        t("prompts.ext_str_655"),
        t("prompts.ext_str_588"),
    )
    return any(marker in text for marker in resolution_markers)


def record_followup_outcome(followup_id: int, delta: float, reason: str):
    conn = _conn()
    try:
        conn.execute(
            """
            UPDATE pending_followups
            SET outcome_score = COALESCE(outcome_score, 0.0) + ?,
                decision_reason = ?
            WHERE id=?
            """,
            (float(delta), reason, followup_id),
        )
        conn.commit()
    finally:
        conn.close()


def extract_followup_candidate_with_llm(
    user_text: str,
    ai_text: str,
    agent_name: str,
    active_followups_text: str = "",
) -> dict | None:
    import json
    from core.i18n import load_prompt, t
    from services.gemini import safe_gemini_call

    prompt_template = load_prompt("telegram_bot_followup_extract.md")
    prompt = prompt_template.format(
        example_1=t("memory.pending_followups.prompt_example_1"),
        example_2=t("memory.pending_followups.prompt_example_2"),
        example_3=t("memory.pending_followups.prompt_example_3"),
        example_4=t("memory.pending_followups.prompt_example_4"),
        example_5=t("memory.pending_followups.prompt_example_5"),
        active_followups_text=active_followups_text,
        agent_name=agent_name,
        user_text=user_text[:800],
        ai_text=ai_text[:800],
    )

    try:
        response = safe_gemini_call(prompt)
        raw = response.text if hasattr(response, "text") else str(response)
        
        start = raw.find("{")
        end = raw.rfind("}")
        if start != -1 and end != -1 and end > start:
            raw = raw[start:end+1]
            
        data = json.loads(raw)
        if not isinstance(data, dict):
            return None
        return data
    except Exception as exc:
        print(f"[FollowUpExtract Error]: {exc}")
        return None


def looks_like_messenger_draft_exchange(user_text: str, ai_text: str = "") -> bool:
    text = _normalize_match_text(f"{user_text} {ai_text}")
    if not text:
        return False

    try:
        from services.messenger_intent import classify_messenger_intent
        from core.messenger_draft import has_active_draft

        intent = classify_messenger_intent(
            user_text,
            has_active_draft=has_active_draft(),
        )
        if intent.intent in {"create_draft", "confirm_send", "clarify_draft", "clear_draft"}:
            return True
    except Exception:
        pass

    operational_markers = (
        "draft",
        t("prompts.ext_str_264"),
        t("prompts.ext_str_478"),
        "messenger",
        t("prompts.ext_str_113"),
        t("prompts.ext_str_430"),
        t("prompts.ext_str_392"),
        t("prompts.ext_str_399"),
        t("prompts.ext_str_168"),
        t("prompts.ext_str_133"),
        t("prompts.ext_str_59"),
        t("prompts.ext_draft_5"),
        t("prompts.ext_str_120"),
    )
    return any(marker in text for marker in operational_markers)


def looks_like_linkedin_post_exchange(user_text: str, ai_text: str = "") -> bool:
    text = _normalize_match_text(f"{user_text} {ai_text}")
    if not text:
        return False

    try:
        from core.utils import (
            looks_like_linkedin_request,
            looks_like_terminal_linkedin_draft_result,
        )

        if looks_like_linkedin_request(user_text):
            return True
        if looks_like_terminal_linkedin_draft_result(ai_text):
            return True
    except Exception:
        pass

    operational_markers = (
        "linkedin",
        t("prompts.ext_str_335"),
        "post",
        "publish",
        t("prompts.ext_draft_linkedin_1"),
        "linkedin post",
        t("prompts.ext_post_linkedin"),
        t("prompts.ext_linkedin_post"),
        t("prompts.ext_linkedin_post_1"),
    )
    return any(marker in text for marker in operational_markers)


def looks_like_negative_plan_update(user_text: str) -> bool:
    text = _normalize_match_text(user_text)
    if not text:
        return False

    negative_markers = (
        t("prompts.ext_str_508"),
        t("prompts.ext_str_596"),
        t("prompts.ext_str_212"),
        t("prompts.ext_str_254"),
        t("prompts.ext_str_619"),
        t("prompts.ext_str_296"),
        t("prompts.ext_str_290"),
        t("prompts.ext_str_588"),
    )
    future_context_markers = (
        t("prompts.ext_str_826"),
        t("prompts.ext_str_530"),
        t("prompts.ext_str_588"),
        t("prompts.ext_str_689"),
        t("prompts.ext_str_290"),
        t("prompts.ext_str_691"),
        t("prompts.ext_str_613"),
        t("prompts.ext_str_363"),
    )
    completion_markers = (
        t("prompts.ext_str_281"),
        t("prompts.ext_str_738"),
        t("prompts.ext_str_722"),
        t("prompts.ext_str_529"),
        t("prompts.ext_str_572"),
        t("prompts.ext_str_310"),
    )

    has_negative = any(marker in text for marker in negative_markers)
    has_future_context = any(marker in text for marker in future_context_markers)
    has_completion = any(marker in text for marker in completion_markers)

    return has_negative and has_future_context and not has_completion



def looks_like_operational_reminder_exchange(user_text: str, ai_text: str = "") -> bool:
    user_norm = _normalize_match_text(user_text)
    ai_norm = _normalize_match_text(ai_text)

    if not user_norm and not ai_norm:
        return False

    reminder_request_markers = (
        t("prompts.ext_str_200"),
        t("prompts.ext_str_141"),
        t("prompts.ext_str_124"),
        t("prompts.ext_str_118"),
        t("prompts.ext_str_90"),
        t("prompts.ext_str_360"),
        t("prompts.ext_str_256"),
        "alarm",
        t("prompts.ext_str_331"),
    )

    reminder_confirmation_markers = (
        t("prompts.ext_str_58"),
        t("prompts.ext_str_70"),
        t("prompts.ext_str_65"),
        "alarm set",
    )

    has_time_reference = (
        ":" in user_norm
        or t("prompts.ext_str_717") in user_norm
        or t("prompts.ext_str_590") in user_norm
        or t("prompts.ext_str_588") in user_norm
        or t("prompts.ext_str_820") in user_norm
    )

    user_looks_like_reminder = (
        any(marker in user_norm for marker in reminder_request_markers)
        or (
            has_time_reference
            and any(marker in user_norm for marker in (t("prompts.ext_str_360"), t("prompts.ext_str_256"), t("prompts.ext_str_455"), t("prompts.ext_str_238")))
        )
    )

    ai_looks_like_confirmation = any(
        marker in ai_norm for marker in reminder_confirmation_markers
    )

    # Classic operational pair:
    # user asks reminder/alarm + assistant confirms scheduling
    if user_looks_like_reminder and ai_looks_like_confirmation:
        return True

    # Even if there is no confirmation string, just wake-up/alarm setup
    # we do not want it to become a follow-up candidate
    if user_looks_like_reminder and any(
        marker in user_norm for marker in (t("prompts.ext_str_360"), t("prompts.ext_str_256"), "05:30", "5:30")
    ):
        return True

    return False

def maybe_create_followup_from_exchange(
    *,
    user_text: str,
    ai_text: str,
    agent_name: str,
    channel: str,
    recently_resolved: list[dict] | None = None,
):
    clean_user = str(user_text or "").strip()
    clean_ai = str(ai_text or "").strip()

    if looks_like_messenger_draft_exchange(clean_user, clean_ai):
        return None

    if looks_like_linkedin_post_exchange(clean_user, clean_ai):
        return None

    if looks_like_negative_plan_update(clean_user):
        return None

    if looks_like_operational_reminder_exchange(clean_user, clean_ai):
        return None

    if not clean_user:
        return None

    # Skip followups if the exchange is just tool output or routine system messages
    if "routine" in agent_name.lower():
        return None
    if t("prompts.ext_str_317") in clean_user.lower() or "[system]" in clean_user.lower():
        return None
    if t("prompts.ext_str_67") in clean_user.lower() or t("prompts.ext_str_69") in clean_user.lower():
        return None

    low_user = clean_user.lower()

    skip_markers = (
        "ok",
        t("prompts.ext_str_833"),
        t("prompts.ext_str_802"),
        t("prompts.ext_str_799"),
        "thanks",
        t("prompts.ext_str_280"),
        t("prompts.ext_str_55"),
        t("prompts.ext_background"),
    )
    if len(clean_user.split()) <= 1 and any(m in low_user for m in skip_markers):
        return None

    active_followups = find_pending_followups(limit=10, active_only=True)
    active_str = ""
    if active_followups:
        lines = ["[Active Pending Follow-ups]"]
        for f in active_followups:
            lines.append(f"[#{f['id']}] topic: {f['topic']}, subject: {f['subject']}")
        active_str = "\n".join(lines)

    candidate = extract_followup_candidate_with_llm(
        clean_user,
        clean_ai,
        agent_name,
        active_followups_text=active_str,
    )
    if not candidate:
        return None

    update_id = candidate.get("update_existing_id")
    if update_id:
        existing_followup = next(
            (item for item in active_followups if item["id"] == update_id),
            None,
        )

        # A sent arc is historical context, never a pending item to reopen.
        if (
            existing_followup
            and str(existing_followup.get("status") or "").strip().lower() == "sent"
        ):
            print(f"[FollowUp]: ignored merge into already-sent #{update_id}")
            return None

        topic_for_defer = (
            str(existing_followup.get("topic") or "")
            if existing_followup
            else ""
        )

        from memory.pending_followups import defer_followup
        defer_followup(
            followup_id=update_id,
            delay_minutes=candidate.get("delay_minutes", 60),
            reason=candidate.get("reason", "updated_by_deduplication"),
            target_window=candidate.get("target_window", ""),
            topic=topic_for_defer,
        )
        print(f"[FollowUp]: merged new info into existing #{update_id}")
        return update_id

    if not candidate.get("should_follow_up"):
        return None

    if recently_resolved and not candidate_is_distinct_from_recently_resolved(
        candidate,
        recently_resolved,
    ):
        print("[FollowUp]: create-skip redundant arc after resolution update")
        return None

    return create_pending_followup_from_candidate(
        candidate=candidate,
        source_channel=channel,
        source_agent=agent_name,
        source_user_text=clean_user,
        source_ai_text=clean_ai,
    )


def process_followup_exchange(
    *,
    user_text: str,
    ai_text: str,
    agent_name: str,
    channel: str,
) -> int | None:
    """Resolve an existing follow-up, then create only a distinct new arc.

    A user completion update may resolve an active arc and still describe a
    separate future need.  This shared path prevents the just-resolved arc
    from being recreated while preserving genuinely distinct candidates.
    """
    resolved_count = maybe_resolve_followups_from_user_message(user_text)
    recently_resolved = None
    if resolved_count > 0 and looks_like_followup_resolution_update(user_text):
        recently_resolved = get_recently_resolved_followups(
            limit=5,
            within_seconds=180,
        )

    return maybe_create_followup_from_exchange(
        user_text=user_text,
        ai_text=ai_text,
        agent_name=agent_name,
        channel=channel,
        recently_resolved=recently_resolved,
    )


def classify_followup_resolution_with_llm(
    *,
    user_text: str,
    topic: str,
    subject: str,
    source_user_text: str,
) -> dict | None:
    import json
    from core.i18n import load_prompt
    from services.gemini import safe_gemini_call

    prompt_template = load_prompt("telegram_bot_followup_resolve.md")
    prompt = prompt_template.format(
        topic=topic,
        subject=subject,
        source_user_text=source_user_text,
        user_text=user_text,
    )

    try:
        response = safe_gemini_call(prompt)
        raw = response.text if hasattr(response, "text") else str(response)
        start = raw.find('{')
        end = raw.rfind('}')
        if start != -1 and end != -1 and end > start:
            raw = raw[start:end+1]
        data = json.loads(raw)
        return data if isinstance(data, dict) else None
    except Exception as exc:
        print(f"[FollowUpResolve Error]: {exc}")
        return None


def classify_followup_deferral_with_llm(
    *,
    topic: str,
    subject: str,
    source_user_text: str,
    current_user_text: str,
) -> dict:
    import json
    from core.i18n import load_prompt
    from services.gemini import safe_gemini_call

    prompt_template = load_prompt("telegram_bot_followup_defer.md")
    prompt = prompt_template.format(
        topic=topic,
        subject=subject,
        source_user_text=source_user_text,
        current_user_text=current_user_text,
    )

    response = safe_gemini_call(prompt)
    raw = response.text if hasattr(response, "text") else str(response)
    
    start = raw.find('{')
    end = raw.rfind('}')
    if start != -1 and end != -1 and end > start:
        raw = raw[start:end+1]

    try:
        data = json.loads(raw)
    except Exception:
        return {
            "should_defer": False,
            "delay_minutes": 0,
            "target_window": "",
            "reason": "invalid_json",
            "confidence": 0.0,
        }

    return {
        "should_defer": bool(data.get("should_defer")),
        "delay_minutes": int(data.get("delay_minutes", 0)),
        "target_window": str(data.get("target_window", "")),
        "reason": str(data.get("reason", "")),
        "confidence": float(data.get("confidence", 0.0)),
    }


def maybe_resolve_followups_from_user_message(user_text: str) -> int:
    ensure_pending_followups_table()
    text = _normalize_match_text(user_text)
    if not text:
        return 0

    conn = _conn()
    try:
        rows = conn.execute(
            """
            SELECT id, topic, subject, source_user_text, status
            FROM pending_followups
            WHERE status IN ('pending', 'sent')
            ORDER BY CASE WHEN status='sent' THEN 0 ELSE 1 END, id DESC
            LIMIT 20
            """
        ).fetchall()

        resolution_markers = (
            t("prompts.ext_str_534"),
            t("prompts.ext_str_821"),
            t("prompts.ext_str_319"),
            t("prompts.ext_str_281"),
            t("prompts.ext_str_369"),
            t("prompts.ext_str_403"),
            t("prompts.ext_str_285"),
            t("prompts.ext_str_313"),
            t("prompts.ext_str_516"),
            t("prompts.ext_str_529"),
            t("prompts.ext_str_551"),
            t("prompts.ext_str_572"),
            t("prompts.ext_str_713"),
            t("prompts.ext_str_738"),
            t("prompts.ext_str_563"),
            t("prompts.ext_str_660"),
            t("prompts.ext_str_787"),
            t("prompts.ext_str_792"),
            t("prompts.ext_str_644"),
            t("prompts.ext_str_558"),
            t("prompts.ext_str_655"),
            t("prompts.ext_str_588"),
            t("prompts.ext_str_316"),
            t("prompts.ext_str_308"),
            t("prompts.ext_str_253"),
            t("prompts.ext_str_254"),
            t("prompts.ext_str_681"),
            t("prompts.ext_str_689"),
            t("prompts.ext_str_282"),
            t("prompts.ext_str_290"),
        )

        if not any(m in text for m in resolution_markers):
            return 0

        resolved_count = 0

        for row in rows:
            followup_id, topic, subject, source_user_text, followup_status = row
            followup_status = str(followup_status or "").strip().lower()

            shared_tokens = [
                tok for tok in _normalize_match_text(subject).split()
                if len(tok) >= 4 and tok in text
            ]

            if topic == "outing" and not shared_tokens:
                continue

            lexical_hint = bool(shared_tokens) or (
                topic == "outing" and any(x in text for x in (t("prompts.ext_str_572"), t("prompts.ext_str_239"), t("prompts.ext_str_738"), t("prompts.ext_str_529")))
            )

            if not lexical_hint and len(text.split()) < 4:
                continue

            deferral = classify_followup_deferral_with_llm(
                topic=topic,
                subject=subject,
                source_user_text=source_user_text or "",
                current_user_text=user_text,
            )

            if deferral.get("should_defer") and float(deferral.get("confidence") or 0.0) >= 0.60:
                delay_minutes = normalize_followup_delay(
                    topic=topic,
                    suggested_minutes=int(deferral.get("delay_minutes") or 0),
                    source_user_text=user_text,
                    target_window=str(deferral.get("target_window") or ""),
                    now=_local_now(),
                )
                defer_reason = deferral.get('reason') or 'user_postponed'
                defer_followup(
                    followup_id,
                    delay_minutes=delay_minutes,
                    reason=f"deferred:{defer_reason}",
                    target_window=str(deferral.get("target_window") or ""),
                    topic=topic,
                )
                print(f"[FollowUp]: deferred #{followup_id} -> {defer_reason}")
                continue

            result = classify_followup_resolution_with_llm(
                user_text=user_text,
                topic=topic,
                subject=subject,
                source_user_text=source_user_text or "",
            )

            if not result or not result.get("resolves"):
                continue

            confidence = float(result.get("confidence") or 0.0)
            if confidence < 0.55:
                continue

            resolution_type = str(result.get("resolution_type") or "resolved").strip()
            reason = str(result.get("reason") or "").strip()

            resolve_followup(
                followup_id,
                f"resolved_by_user:{resolution_type}"
            )
            _set_followup_decision(
                followup_id,
                decision="resolved",
                reason=reason or resolution_type,
            )
            print(f"[FollowUp]: resolved #{followup_id} ({resolution_type})")
            resolved_count += 1
        return resolved_count
    finally:
        conn.close()

