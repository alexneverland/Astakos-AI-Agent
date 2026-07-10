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

    yes_exact = {"ναι", "nai", "yes", "ok", "οκ"}
    no_exact = {"όχι", "οχι", "oxi", "no"}

    no_phrases = (
        "μην το αποθηκευσεις",
        "μην την αποθηκευσεις",
        "μην αποθηκευσεις",
        "μην το αρχειοθετησεις",
        "μην την αρχειοθετησεις",
        "δεν θελω να το αποθηκευσεις",
        "δεν θελω να την αποθηκευσεις",
        "αστο",
        "αφησε το",
        "μην το κρατησεις",
        "μην την κρατησεις",
    )
    yes_phrases = (
        "αποθηκευσε το",
        "αποθηκευσε την",
        "αρχειοθετησε το",
        "αρχειοθετησε την",
        "κρατα το",
        "κρατα την",
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
    txt = _normalize_gr(text)
    markers = (
        "να την αποθηκευσω μονιμα στη μνημη μου",
        "να το αποθηκευσω μονιμα στη μνημη μου",
        "να την αρχειοθετησω μονιμα",
        "να το αρχειοθετησω μονιμα",
        "απαντησε μου μονο με",
        "ναι η οχι",
        "ναι ή οχι",
        "να την αποθηκευσω",
        "να το αποθηκευσω",
        "να τη σωσω",
        "να το σωσω",
        "να την αρχειοθετησω",
    )
    return any(m in txt for m in markers)


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
                status TEXT NOT NULL DEFAULT 'pending',
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL
            )
            """
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
        return dict(row) if row else None
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


def create_pending_asset_archive(
    channel: str,
    asset_type: str,
    file_path: str,
    filename: str,
    analysis: str,
    caption: str = "",
    ttl_minutes: int = 30,
):
    now = datetime.now()
    expires_at = now + timedelta(minutes=ttl_minutes)

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
                analysis, caption, status, created_at, expires_at
            )
            VALUES (?, ?, ?, ?, ?, ?, 'pending', ?, ?)
            """,
            (
                channel,
                asset_type,
                file_path,
                filename,
                analysis,
                caption,
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
        return dict(row) if row else None
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
