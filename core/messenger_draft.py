import json
import os
import hashlib
from uuid import uuid4
from filelock import FileLock
from datetime import datetime, timedelta


def _settings():
    import config

    draft_file = getattr(
        config,
        "MESSENGER_DRAFT_FILE",
        os.path.join(config.BASE_DIR, "messenger_draft.json"),
    )
    ttl_seconds = int(getattr(config, "MESSENGER_DRAFT_TTL_SECONDS", 1800))
    return draft_file, ttl_seconds


def _parse_datetime(value: str):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def build_draft(target_name: str, message: str, *, image_path: str = "", now: datetime | None = None) -> dict:
    _, ttl_seconds = _settings()
    now = now or datetime.now()
    expires_at = now + timedelta(seconds=ttl_seconds)
    draft = {
        "revision": uuid4().hex,
        "target_name": target_name,
        "message": message,
        "status": "pending",
        "created_at": now.isoformat(timespec="seconds"),
        "expires_at": expires_at.isoformat(timespec="seconds"),
    }
    if image_path:
        draft["image_path"] = image_path
    return draft


def _draft_fingerprint() -> str:
    """Fingerprint exact persisted contents, including malformed existing data."""
    from pathlib import Path
    draft_file, _ = _settings()
    try:
        return hashlib.sha256(Path(draft_file).read_bytes()).hexdigest()
    except FileNotFoundError:
        return "missing"


def capture_draft_write_guard(messages: list) -> dict:
    """Anchor a graph turn to its native owner history and shared draft revision."""
    import config
    from memory.conversation_history import get_latest_trusted_user_rowid, load_messages_after_rowid
    from core.untrusted_content import is_direct_user_message
    from core.utils import strip_transport_metadata
    try:
        path = config.CONVERSATION_DB_FILE
        version = get_latest_trusted_user_rowid(db_path=path)
        latest = next((row for row in reversed(messages) if is_direct_user_message(row)), None)
        if latest is None:
            return {"valid": False}
        if version:
            rows = load_messages_after_rowid(after_rowid=version-1, limit=1, db_path=path)
            if not rows or strip_transport_metadata(rows[0]["content"]) != strip_transport_metadata(str(latest.content)):
                return {"valid": False}
        draft_file, _ = _settings()
        with FileLock(draft_file + ".lock", timeout=10):
            return {"valid": True, "history_version": version, "history_path": path,
                    "draft_fingerprint": _draft_fingerprint()}
    except Exception:
        return {"valid": False}


def save_draft(target_name: str, message: str, *, image_path: str = "", write_guard: dict | None = None) -> dict:
    """Save atomically; guarded graph writes cannot replace newer draft/history."""
    draft_file, _ = _settings()
    with FileLock(draft_file + ".lock", timeout=10):
        if write_guard is not None:
            from memory.conversation_history import get_latest_trusted_user_rowid
            if (write_guard.get("valid") is not True
                    or _draft_fingerprint() != write_guard.get("draft_fingerprint")
                    or get_latest_trusted_user_rowid(db_path=write_guard["history_path"]) != write_guard["history_version"]):
                raise ValueError("Draft preparation cancelled: a newer turn or draft superseded this request.")
        draft = build_draft(target_name, message, image_path=image_path)
        temporary = draft_file + "." + uuid4().hex + ".tmp"
        try:
            with open(temporary, "w", encoding="utf-8") as f:
                json.dump(draft, f, ensure_ascii=False, indent=4)
            os.replace(temporary, draft_file)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        return draft


def load_draft() -> dict | None:
    draft_file, _ = _settings()
    if not os.path.exists(draft_file):
        return None
    try:
        with open(draft_file, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def active_draft_status(*, now: datetime | None = None) -> tuple[bool, str, dict | None]:
    draft = load_draft()
    if not draft:
        return False, "missing", None

    if draft.get("status", "pending") != "pending":
        return False, "not_pending", draft

    if not draft.get("target_name") or not draft.get("message"):
        return False, "incomplete", draft

    expires_at = _parse_datetime(draft.get("expires_at", ""))
    if expires_at and (now or datetime.now()) > expires_at:
        return False, "expired", draft

    return True, "active", draft


def has_active_draft() -> bool:
    active, _, _ = active_draft_status()
    return active


def inactive_draft_message(reason: str) -> str:
    from core.i18n import t
    if reason == "expired":
        return t("core.messenger_draft.draft_expired")
    if reason == "incomplete":
        return t("prompts.ext_str_11")
    if reason == "not_pending":
        return t("prompts.ext_str_4")
    return t("prompts.ext_str_14")


def _seconds_between(start: datetime | None, end: datetime | None) -> int | None:
    if not start or not end:
        return None
    return int((end - start).total_seconds())


def debug_draft_state(*, now: datetime | None = None) -> dict:
    now = now or datetime.now()
    active, reason, draft = active_draft_status(now=now)
    if not draft:
        return {
            "exists": False,
            "active": False,
            "reason": reason,
            "status": None,
            "target_name": None,
            "created_at": None,
            "expires_at": None,
            "age_seconds": None,
            "expires_in_seconds": None,
            "message_chars": 0,
        }

    created_at = _parse_datetime(draft.get("created_at", ""))
    expires_at = _parse_datetime(draft.get("expires_at", ""))
    expires_in = _seconds_between(now, expires_at)
    if expires_in is not None:
        expires_in = max(0, expires_in)

    return {
        "exists": True,
        "active": active,
        "reason": reason,
        "status": draft.get("status", "pending"),
        "target_name": draft.get("target_name") or None,
        "created_at": draft.get("created_at"),
        "expires_at": draft.get("expires_at"),
        "age_seconds": _seconds_between(created_at, now),
        "expires_in_seconds": expires_in,
        "message_chars": len(draft.get("message") or ""),
    }


def clear_draft() -> bool:
    draft_file, _ = _settings()
    if not os.path.exists(draft_file):
        return False
    try:
        with open(draft_file, "w", encoding="utf-8") as f:
            json.dump({}, f, ensure_ascii=False, indent=4)
        return True
    except Exception:
        return False

