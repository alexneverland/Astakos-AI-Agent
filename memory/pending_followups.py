import json
import sqlite3
import unicodedata
from datetime import datetime, timedelta
from typing import Optional

from config import STATE_DB


FOLLOWUP_TTL_HOURS = 12


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


def _delay_until_next_window(now: datetime, hour: int, minute: int = 0) -> int:
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target <= now:
        target = target + timedelta(days=1)
    return max(1, int((target - now).total_seconds() / 60))


def normalize_followup_delay(
    topic: str,
    suggested_minutes: int,
    source_user_text: str = "",
    target_window: str = "",
    now: Optional[datetime] = None,
) -> int:
    text = _normalize_match_text(source_user_text or "")
    topic = (topic or "").strip().lower()
    target_window = (target_window or "").strip().lower()
    raw_value = int(suggested_minutes or 0)
    value = raw_value
    now = now or datetime.now()
    hour = int(now.hour)

    if value < 30:
        value = 30
    if value > 720:
        value = 720

    if target_window == "same_day_short_checkin":
        return max(20, min(value, 90))

    if target_window == "same_day_evening":
        if hour < 18:
            delay = _delay_until_next_window(now, 19, 30)
            return max(120, min(delay, 12 * 60))
        return max(45, min(value, 240))

    if target_window == "next_day_morning":
        delay = _delay_until_next_window(now + timedelta(days=1), 9, 30)
        return max(8 * 60, min(delay, 24 * 60))

    if target_window == "next_day_late_morning":
        delay = _delay_until_next_window(now + timedelta(days=1), 11, 30)
        return max(8 * 60, min(delay, 24 * 60))

    if target_window == "next_day_afternoon":
        delay = _delay_until_next_window(now + timedelta(days=1), 14, 30)
        return max(10 * 60, min(delay, 30 * 60))

    if target_window == "next_day_evening":
        delay = _delay_until_next_window(now + timedelta(days=1), 19, 30)
        return max(12 * 60, min(delay, 30 * 60))

    if target_window == "after_likely_completion":
        if topic == "outing":
            return max(45, min(value, 180))
        if topic == "food_purchase":
            return max(90, min(value, 360))
        return max(60, min(value, 300))

    # fallback heuristic αν το LLM δεν έδωσε usable window
    if topic == "outing":
        return max(30, min(value, 180))

    if topic == "food_purchase":
        if "αυριο" in text or "αύριο" in text:
            delay = _delay_until_next_window(now + timedelta(days=1), 11, 30)
            return max(8 * 60, min(delay, 24 * 60))
        if "αποψε" in text or "απόψε" in text or "βραδ" in text:
            return max(45, min(value, 240))
        return max(90, min(value, 360))

    return max(60, min(value, 480))


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
):
    ensure_pending_followups_table()
    conn = _conn()
    try:
        expires_at = (
            datetime.fromisoformat(followup_after_ts) + timedelta(hours=FOLLOWUP_TTL_HOURS)
        ).isoformat(timespec="seconds")

        metadata_json = json.dumps(metadata or {}, ensure_ascii=False)
        arc_key = build_followup_arc_key(topic, subject)

        existing = conn.execute(
            """
            SELECT id
            FROM pending_followups
            WHERE status='pending' AND (
                (topic=? AND subject=?)
                OR arc_key=?
            )
            ORDER BY id DESC
            LIMIT 1
            """,
            (topic, subject, arc_key),
        ).fetchone()

        if existing:
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

    now = datetime.now()
    delay_minutes = normalize_followup_delay(
        topic=topic,
        suggested_minutes=delay_minutes_raw,
        source_user_text=source_user_text,
        target_window=str(candidate.get("target_window") or ""),
        now=now,
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
        metadata={
            "reason": candidate.get("reason", ""),
            "target_window": str(candidate.get("target_window") or ""),
            "delay_minutes_raw": delay_minutes_raw,
            "delay_minutes_final": delay_minutes,
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
                created_at
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
                }
            )
        return out
    finally:
        conn.close()


def get_recently_resolved_followups(limit: int = 5, within_seconds: int = 180) -> list[dict]:
    ensure_pending_followups_table()
    conn = _conn()
    try:
        cutoff = datetime.now() - timedelta(seconds=within_seconds)
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
                resolved_at = datetime.fromisoformat(str(row[6]).replace(" ", "T"))
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
        existing_topic = str(item.get("topic") or "").strip().lower()
        existing_arc = str(item.get("arc_key") or "").strip()
        if topic == existing_topic:
            return False
        if arc_key and existing_arc and arc_key == existing_arc:
            return False
    return True


def mark_followup_sent(followup_id: int, decision_reason: str = "followup_sent"):
    conn = _conn()
    try:
        from datetime import datetime
        now_iso = datetime.now().isoformat(timespec="seconds")
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


def resolve_followup(followup_id: int, reason: str):
    conn = _conn()
    try:
        conn.execute(
            """
            UPDATE pending_followups
            SET status='resolved',
                resolution_reason=?,
                resolved_at=CURRENT_TIMESTAMP,
                last_decision='resolved',
                decision_reason=?
            WHERE id=?
            """,
            (reason, reason, followup_id),
        )
        conn.commit()
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
        conn.execute(
            """
            UPDATE pending_followups
            SET status='expired',
                resolution_reason='ttl_expired',
                resolved_at=CURRENT_TIMESTAMP,
                last_decision='expired',
                decision_reason='ttl_expired',
                outcome_score=COALESCE(outcome_score, 0.0) - 0.5
            WHERE status='pending' AND expires_at <= ?
            """,
            (now_iso,),
        )
        conn.commit()
    finally:
        conn.close()


def find_pending_followups(limit: int = 20) -> list[dict]:
    ensure_pending_followups_table()
    conn = _conn()
    try:
        rows = conn.execute(
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
            ORDER BY id DESC
            LIMIT ?
            """,
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
                    int((datetime.fromisoformat(r[4]) - datetime.now()).total_seconds() / 60)
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
            ORDER BY id DESC
            LIMIT 1
            """
        ).fetchone()

        if not row or not row[0]:
            return False

        last_sent = datetime.fromisoformat(str(row[0]).replace(" ", "T"))
        return (datetime.now() - last_sent) <= timedelta(minutes=within_minutes)
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
            ORDER BY id DESC
            LIMIT 1
            """,
            (arc_key,),
        ).fetchone()

        if not row or not row[0]:
            return False

        last_sent = datetime.fromisoformat(str(row[0]).replace(" ", "T"))
        return (datetime.now() - last_sent) <= timedelta(minutes=within_minutes)
    finally:
        conn.close()


def looks_like_followup_resolution_update(user_text: str) -> bool:
    text = _normalize_match_text(user_text)
    if not text:
        return False

    if len(text.split()) > 18:
        return False

    resolution_markers = (
        "τελικά",
        "ήδη",
        "το έκανα",
        "το εκανα",
        "το πήρα",
        "το πηρα",
        "τις πήρα",
        "τις πηρα",
        "γύρισα",
        "γυρισα",
        "βρήκα",
        "βρηκα",
        "πήγα",
        "πηγα",
        "έφυγα",
        "εφυγα",
        "φεύγω",
        "φευγω",
        "πάω",
        "παω",
        "δεν πήρα",
        "δεν πηρα",
        "δεν έγινε",
        "δεν εγινε",
        "αύριο",
        "αυριο",
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


def extract_followup_candidate_with_llm(user_text: str, ai_text: str, agent_name: str) -> dict | None:
    import json
    import re
    from services.gemini import safe_gemini_call

    prompt = f"""
Ανάλυσε το παρακάτω exchange και αποφάσισε αν αξίζει να δημιουργηθεί ένα ΜΕΛΛΟΝΤΙΚΟ conversational follow-up.

Θέλουμε follow-up μόνο όταν:
- υπάρχει φυσικό επόμενο βήμα ή outcome
- αργότερα θα είχε νόημα να ρωτήσουμε πώς πήγε
- το θέμα αφορά πράξη / γεγονός / αγορά / έξοδο / σχέδιο / οικογενειακή κίνηση / task progression

Δεν θέλουμε follow-up όταν:
- είναι απλό chit-chat
- είναι καθαρά ενημέρωση χωρίς επόμενο βήμα
- είναι pure tool result / operational reply
- είναι πολύ αόριστο

Απάντησε ΑΥΣΤΗΡΑ σε JSON:
{{
  "should_follow_up": true,
  "topic": "food_purchase | outing | task_progress | family_plan | appointment | general_progress",
  "subject": "σύντομο subject",
  "delay_minutes": 180,
  "target_window": "same_day_short_checkin | same_day_evening | next_day_morning | next_day_late_morning | next_day_afternoon | next_day_evening | after_likely_completion",
  "confidence": 0.0,
  "reason": "short reason"
}}

ή

{{
  "should_follow_up": false,
  "reason": "short reason"
}}

Κανόνες:
- subject μέχρι 4 λέξεις
- προτίμησε compact noun phrase, όχι πλήρη περιγραφή
- απόφυγε "και", "για", "ώστε", "να"
- delay_minutes integer από 30 έως 720
- confidence 0.0 έως 1.0
- μην επιστρέψεις τίποτα εκτός JSON
- target_window πρέπει να περιγράφει ΠΟΤΕ έχει φυσικό νόημα να ξαναμιλήσουμε
- Μην επιλέγεις target_window με βάση γενικά "αργότερα", αλλά με βάση το πραγματικό πιθανό outcome

Χρησιμοποίησε:
- "same_day_short_checkin" όταν ο χρήστης μόλις ξεκίνησε κάτι και σύντομα θα υπάρχει εξέλιξη
- "same_day_evening" όταν το θέμα λογικά θα κλείσει αργότερα μέσα στην ίδια μέρα
- "next_day_morning" όταν το θέμα μεταφέρεται στην επόμενη μέρα και έχει νόημα νωρίς αλλά όχι χαράματα
- "next_day_late_morning" όταν το θέμα σχετίζεται με φαγητό / έξοδο / οικογενειακή κίνηση που λογικά θα ξεκαθαρίσει πιο κοντά στο μεσημέρι
- "next_day_afternoon" όταν το θέμα αναμένεται να ξεκαθαρίσει μετά το μεσημέρι
- "next_day_evening" όταν είναι βραδινό σχέδιο / μεταγενέστερη εξέλιξη
- "after_likely_completion" όταν το follow-up πρέπει να γίνει μετά το πιθανό τέλος του γεγονότος

Παραδείγματα:
- "οι μπριζόλες αύριο" -> target_window: "next_day_late_morning"
- "πάω τώρα να τους βρω στο πάρκο" -> target_window: "same_day_short_checkin"
- "αύριο θα δούμε για το interview" -> target_window: "next_day_afternoon"
- "το βράδυ θα βγούμε" -> target_window: "same_day_evening"

Παραδείγματα καλού subject:
- "μπριζόλες λαιμού"
- "συνάντηση με Σοφία"
- "καθάρισμα κλουβιού"

Παραδείγματα κακού subject:
- "αγορά και ψήσιμο για τις μπριζόλες λαιμού"
- "να δω πώς πήγε το πράγμα αργότερα"

[Agent]: {agent_name}
[User]: {user_text[:800]}
[Assistant]: {ai_text[:800]}
"""
    try:
        response = safe_gemini_call(prompt)
        raw = response.text if hasattr(response, "text") else str(response)
        raw = re.sub(r"```json|```", "", raw.strip()).strip()
        data = json.loads(raw)
        if not isinstance(data, dict):
            return None
        return data
    except Exception as exc:
        print(f"[FollowUpExtract Error]: {exc}")
        return None


def maybe_create_followup_from_exchange(
    *,
    user_text: str,
    ai_text: str,
    agent_name: str,
    channel: str,
):
    clean_user = str(user_text or "").strip()
    clean_ai = str(ai_text or "").strip()

    if not clean_user:
        return None

    low_user = clean_user.lower()

    skip_markers = (
        "ok",
        "οκ",
        "ναι",
        "όχι",
        "thanks",
        "ευχαριστ",
        "υπενθύμιση ρυθμίστηκε",
        "αποθηκεύεται σε background",
    )
    if len(clean_user.split()) <= 3 and any(m in low_user for m in skip_markers):
        return None

    candidate = extract_followup_candidate_with_llm(clean_user, clean_ai, agent_name)
    if not candidate or not candidate.get("should_follow_up"):
        return None
    return create_pending_followup_from_candidate(
        candidate=candidate,
        source_channel=channel,
        source_agent=agent_name,
        source_user_text=clean_user,
        source_ai_text=clean_ai,
    )


def classify_followup_resolution_with_llm(
    *,
    user_text: str,
    topic: str,
    subject: str,
    source_user_text: str,
) -> dict | None:
    import json
    import re
    from services.gemini import safe_gemini_call

    prompt = f"""
Αποφάσισε αν το νέο μήνυμα του χρήστη λύνει/κλείνει ένα pending conversational follow-up.

Pending follow-up:
- topic: {topic}
- subject: {subject}
- original source message: {source_user_text}

New user message:
{user_text}

Απάντησε ΑΥΣΤΗΡΑ σε JSON:
{{
  "resolves": true,
  "resolution_type": "completed | canceled | postponed | superseded | irrelevant",
  "confidence": 0.0,
  "reason": "short reason"
}}

ή

{{
  "resolves": false,
  "confidence": 0.0,
  "reason": "short reason"
}}

Κανόνες:
- resolves=true αν ο χρήστης λέει ότι το έκανε, δεν το έκανε, πήγε για αύριο, βρήκε το πρόσωπο, γύρισε, ακυρώθηκε, μετατέθηκε
- resolves=false αν είναι άσχετο ή δεν αρκεί
- confidence 0.0 έως 1.0
- μόνο JSON
"""
    try:
        response = safe_gemini_call(prompt)
        raw = response.text if hasattr(response, "text") else str(response)
        raw = re.sub(r"```json|```", "", raw.strip()).strip()
        data = json.loads(raw)
        return data if isinstance(data, dict) else None
    except Exception as exc:
        print(f"[FollowUpResolve Error]: {exc}")
        return None


def maybe_resolve_followups_from_user_message(user_text: str) -> int:
    ensure_pending_followups_table()
    text = _normalize_match_text(user_text)
    if not text:
        return 0

    conn = _conn()
    try:
        rows = conn.execute(
            """
            SELECT id, topic, subject, source_user_text
            FROM pending_followups
            WHERE status IN ('pending', 'sent')
            ORDER BY CASE WHEN status='sent' THEN 0 ELSE 1 END, id DESC
            LIMIT 20
            """
        ).fetchall()

        resolution_markers = (
            "τελικά",
            "ήδη",
            "το έκανα",
            "το εκανα",
            "το πήρα",
            "το πηρα",
            "τις πήρα",
            "τις πηρα",
            "γύρισα",
            "γυρισα",
            "βρήκα",
            "βρηκα",
            "πήγα",
            "πηγα",
            "φεύγω",
            "φευγω",
            "πάω",
            "παω",
            "έγινε",
            "εγινε",
            "αύριο",
            "αυριο",
            "δεν πήρα",
            "δεν πηρα",
            "δεν έγινε",
            "δεν εγινε",
        )

        if not any(m in text for m in resolution_markers):
            return 0

        resolved_count = 0

        for row in rows:
            followup_id, topic, subject, source_user_text = row

            shared_tokens = [
                tok for tok in _normalize_match_text(subject).split()
                if len(tok) >= 4 and tok in text
            ]

            lexical_hint = bool(shared_tokens) or (
                topic == "outing" and any(x in text for x in ("βρηκα", "τους βρηκα", "πηγα", "γυρισα"))
            )

            if not lexical_hint and len(text.split()) < 4:
                continue

            result = classify_followup_resolution_with_llm(
                user_text=text,
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
            record_followup_outcome(
                followup_id,
                +1.0,
                "resolved_by_user_message"
            )
            print(f"[FollowUp]: resolved #{followup_id} ({resolution_type})")
            resolved_count += 1
        return resolved_count
    finally:
        conn.close()
