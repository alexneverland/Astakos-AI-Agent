import json
import sqlite3
from datetime import datetime, timedelta
from typing import Optional

from config import STATE_DB


FOLLOWUP_TTL_HOURS = 12


def _conn():
    return sqlite3.connect(STATE_DB)


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


def normalize_followup_delay(topic: str, suggested_minutes: int, source_user_text: str = "") -> int:
    text = (source_user_text or "").lower()
    topic = (topic or "").strip().lower()
    value = int(suggested_minutes or 0)

    if value < 30:
        value = 30
    if value > 720:
        value = 720

    if topic == "outing":
        return max(45, min(value, 180))

    if topic == "food_purchase":
        if "βράδυ" in text or "βραδυ" in text or "απόψε" in text or "αποψε" in text:
            return max(60, min(value, 240))
        return max(90, min(value, 300))

    if topic == "appointment":
        return max(180, min(value, 720))

    if topic == "task_progress":
        return max(120, min(value, 480))

    if topic == "family_plan":
        return max(60, min(value, 360))

    return value


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


def mark_followup_sent(followup_id: int):
    conn = _conn()
    try:
        conn.execute(
            """
            UPDATE pending_followups
            SET status='sent',
                sent_at=CURRENT_TIMESTAMP,
                resolved_at=CURRENT_TIMESTAMP,
                times_sent=COALESCE(times_sent, 0) + 1,
                last_decision='sent'
            WHERE id=?
            """,
            (followup_id,),
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
    from datetime import datetime, timedelta

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

    topic = str(candidate.get("topic") or "").strip().lower()
    subject = str(candidate.get("subject") or "").strip()
    delay_minutes_raw = int(candidate.get("delay_minutes") or 0)
    confidence = float(candidate.get("confidence") or 0.0)

    if not topic or not subject:
        return None
    if confidence < 0.45:
        return None

    delay_minutes = normalize_followup_delay(
        topic=topic,
        suggested_minutes=delay_minutes_raw,
        source_user_text=clean_user,
    )

    followup_after_ts = (
        datetime.now() + timedelta(minutes=delay_minutes)
    ).isoformat(timespec="seconds")

    followup_id = create_pending_followup(
        source_channel=channel,
        source_agent=agent_name,
        topic=topic,
        subject=subject,
        source_user_text=clean_user,
        source_ai_text=clean_ai,
        followup_after_ts=followup_after_ts,
        confidence=confidence,
        metadata={
            "reason": candidate.get("reason", ""),
            "delay_minutes_raw": delay_minutes_raw,
            "delay_minutes_final": delay_minutes,
        },
    )

    if followup_id:
        print(f"[FollowUp]: created #{followup_id} ({topic}) -> {subject} [{delay_minutes_raw}m -> {delay_minutes}m]")
    return followup_id


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


def maybe_resolve_followups_from_user_message(user_text: str):
    ensure_pending_followups_table()
    text = str(user_text or "").strip().lower()
    if not text:
        return

    conn = _conn()
    try:
        rows = conn.execute(
            """
            SELECT id, topic, subject, source_user_text
            FROM pending_followups
            WHERE status='pending'
            ORDER BY id DESC
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
            return

        for row in rows:
            followup_id, topic, subject, source_user_text = row

            shared_tokens = [
                tok for tok in subject.lower().split()
                if len(tok) >= 4 and tok in text
            ]

            lexical_hint = bool(shared_tokens) or (
                topic == "outing" and any(x in text for x in ("βρήκα", "τους βρήκα", "πήγα", "γύρισα"))
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
    finally:
        conn.close()
