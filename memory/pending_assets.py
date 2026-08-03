from core.i18n import t
import sqlite3
import json
import unicodedata
from datetime import datetime, timedelta
from typing import Dict, Any, Optional

from config import STATE_DB


def _normalize_gr(text: str) -> str:
    normalized = unicodedata.normalize("NFD", str(text or ""))
    return "".join(ch for ch in normalized if not unicodedata.combining(ch)).lower().strip()


def classify_pending_asset_reply(text: str) -> str | None:
    txt = _normalize_gr(text)
    words = txt.replace(",", " ").replace(".", " ").replace("!", " ").replace(";", " ").split()

    yes_exact = {t("prompts.ext_str_802"), "nai", "yes", "ok", t("prompts.ext_str_833")}
    no_exact = {t("prompts.ext_str_799"), t("prompts.ext_str_816"), "oxi", "no"}

    no_phrases = (
        t("prompts.ext_str_80"),
        t("prompts.ext_str_66"),
        t("prompts.ext_str_109"),
        t("prompts.ext_str_57"),
        t("prompts.ext_str_48"),
        t("prompts.ext_str_25"),
        t("prompts.ext_str_20"),
        t("prompts.ext_str_692"),
        t("prompts.ext_str_321"),
        t("prompts.ext_str_104"),
        t("prompts.ext_str_92"),
    )
    yes_phrases = (
        t("prompts.ext_str_160"),
        t("prompts.ext_str_138"),
        t("prompts.ext_str_131"),
        t("prompts.ext_str_122"),
        t("prompts.ext_str_330"),
        t("prompts.ext_str_266"),
        "save it",
    )

    if txt in no_exact or (words and words[0] in no_exact):
        return "no"
    if txt in yes_exact or (words and words[0] in yes_exact):
        return "yes"

    # Negation must always win.
    if any(phrase in txt for phrase in no_phrases):
        return "no"
    if any(phrase in txt for phrase in yes_phrases):
        return "yes"

    return None


def looks_like_asset_confirmation_prompt(text: str) -> bool:
    import re
    txt_raw = _normalize_gr(text)
    txt_clean = re.sub(r'[\W_]+', '', txt_raw)

    markers = (
        t("prompts.ext_str_8"),
        t("prompts.ext_str_10"),
        t("prompts.ext_str_30"),
        t("prompts.ext_str_38"),
        t("prompts.ext_str_60"),
        t("prompts.ext_str_260"),
        t("prompts.ext_str_262"),
        t("prompts.ext_str_96"),
        t("prompts.ext_str_112"),
        t("prompts.ext_str_202"),
        t("prompts.ext_str_206"),
        t("prompts.ext_str_76"),
    )

    for m in markers:
        m_clean = re.sub(r'[\W_]+', '', _normalize_gr(m))
        if m_clean and m_clean in txt_clean:
            return True
    return False


def _get_conn():
    return sqlite3.connect(STATE_DB)


def init_pending_assets_table():
    conn = _get_conn()
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS pending_asset_archives (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                channel TEXT NOT NULL,
                asset_type TEXT NOT NULL,
                file_path TEXT NOT NULL,
                filename TEXT NOT NULL,
                analysis TEXT,
                caption TEXT,
                external_content_sources_json TEXT NOT NULL DEFAULT '[]',
                status TEXT NOT NULL DEFAULT 'pending',
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL
            )
            """
        )
        columns = {row[1] for row in conn.execute("PRAGMA table_info(pending_asset_archives)")}
        if "external_content_sources_json" not in columns:
            conn.execute(
                "ALTER TABLE pending_asset_archives "
                "ADD COLUMN external_content_sources_json TEXT NOT NULL DEFAULT '[]'"
            )
        conn.commit()
    finally:
        conn.close()

def get_latest_recent_asset(channel: str, max_age_minutes: int = 20):
    cutoff_iso = (datetime.now() - timedelta(minutes=max_age_minutes)).isoformat()
    conn = _get_conn()
    try:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            """
            SELECT *
            FROM pending_asset_archives
            WHERE channel = ?
              AND created_at >= ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (channel, cutoff_iso),
        ).fetchone()
        return _pending_asset_row(row)
    finally:
        conn.close()


def clear_expired_pending_assets():
    now_iso = datetime.now().isoformat()
    conn = _get_conn()
    try:
        conn.execute(
            """
            UPDATE pending_asset_archives
            SET status = 'cancelled'
            WHERE status = 'pending'
              AND expires_at <= ?
            """,
            (now_iso,),
        )
        conn.commit()
    finally:
        conn.close()


def _pending_asset_row(row: sqlite3.Row | None) -> dict[str, Any] | None:
    """Return a pending asset row with validated external provenance names."""
    if row is None:
        return None
    asset = dict(row)
    try:
        raw_sources = json.loads(asset.get("external_content_sources_json") or "[]")
    except (TypeError, ValueError):
        raw_sources = []
    from core.untrusted_content import external_content_history_metadata

    asset["external_content_sources"] = external_content_history_metadata(
        raw_sources if isinstance(raw_sources, list) else [],
    ).get("untrusted_external_tool_names", [])
    return asset


def create_pending_asset_archive(
    channel: str,
    asset_type: str,
    file_path: str,
    filename: str,
    analysis: str,
    caption: str = "",
    ttl_minutes: int = 30,
    external_content_sources: list[str] | None = None,
):
    """Create a pending archive while retaining validated source provenance."""
    now = datetime.now()
    expires_at = now + timedelta(minutes=ttl_minutes)
    from core.untrusted_content import external_content_history_metadata

    source_names = external_content_history_metadata(external_content_sources or []).get(
        "untrusted_external_tool_names",
        [],
    )

    conn = _get_conn()
    try:
        conn.execute(
            """
            UPDATE pending_asset_archives
            SET status = 'cancelled'
            WHERE channel = ?
              AND asset_type = ?
              AND status = 'pending'
            """,
            (channel, asset_type),
        )

        cursor = conn.execute(
            """
            INSERT INTO pending_asset_archives (
                channel, asset_type, file_path, filename,
                analysis, caption, external_content_sources_json, status, created_at, expires_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?)
            """,
            (
                channel,
                asset_type,
                file_path,
                filename,
                analysis,
                caption,
                json.dumps(source_names),
                now.isoformat(),
                expires_at.isoformat(),
            ),
        )
        conn.commit()
        return cursor.lastrowid
    finally:
        conn.close()


def get_latest_pending_asset(channel: str, asset_type: str = "photo"):
    clear_expired_pending_assets()

    now_iso = datetime.now().isoformat()
    conn = _get_conn()
    try:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            """
            SELECT *
            FROM pending_asset_archives
            WHERE channel = ?
              AND asset_type = ?
              AND status = 'pending'
              AND expires_at > ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (channel, asset_type, now_iso),
        ).fetchone()
        return _pending_asset_row(row)
    finally:
        conn.close()


def mark_pending_asset_confirmed(asset_id: int):
    conn = _get_conn()
    try:
        conn.execute(
            """
            UPDATE pending_asset_archives
            SET status = 'confirmed'
            WHERE id = ?
            """,
            (asset_id,),
        )
        conn.commit()
    finally:
        conn.close()


def mark_pending_asset_cancelled(asset_id: int):
    conn = _get_conn()
    try:
        conn.execute(
            """
            UPDATE pending_asset_archives
            SET status = 'cancelled'
            WHERE id = ?
            """,
            (asset_id,),
        )
        conn.commit()
    finally:
        conn.close()


def is_reply_to_recent_asset_prompt(channel: str, limit: int = 3) -> bool:
    from memory.conversation_history import load_recent_context

    entries = load_recent_context(
        channel=channel,
        global_limit=limit,
        channel_limit=limit,
        total_limit=limit,
    )

    for entry in reversed(entries):
        if entry.get("role") != "assistant":
            continue

        content = str(entry.get("content") or "").strip()
        if not content:
            continue

        return looks_like_asset_confirmation_prompt(content)

    return False

