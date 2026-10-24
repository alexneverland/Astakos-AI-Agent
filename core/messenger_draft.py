import json
import os
import hashlib
from uuid import uuid4
from filelock import FileLock
from datetime import datetime, timedelta
from contextlib import nullcontext


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


def capture_draft_write_guard(messages: list, *, db_path: str | None = None) -> dict:
    """Anchor a graph turn to its native owner history and shared draft revision."""
    import config
    from memory.conversation_history import get_latest_trusted_user_rowid
    from core.untrusted_content import is_direct_user_message
    try:
        path = db_path or config.CONVERSATION_DB_FILE
        version = get_latest_trusted_user_rowid(db_path=path)
        latest = next((row for row in reversed(messages) if is_direct_user_message(row)), None)
        if latest is None:
            return {"valid": False}
        if version:
            owner_rowid = latest.additional_kwargs.get("astakos_owner_rowid")
            if type(owner_rowid) is not int or owner_rowid != version:
                return {"valid": False}
        draft_file, _ = _settings()
        with FileLock(draft_file + ".lock", timeout=10):
            return {"valid": True, "history_version": version, "history_path": path,
                    "draft_fingerprint": _draft_fingerprint()}
    except Exception:
        return {"valid": False, "unavailable": True}


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


def clear_draft(*, write_guard: dict | None = None) -> bool:
    """Clear under the writer lock, optionally bound to an observed owner/revision."""
    draft_file, _ = _settings()
    try:
        with FileLock(draft_file + ".lock", timeout=10):
            if not os.path.exists(draft_file):
                return False
            if write_guard is not None:
                from memory.conversation_history import guard_owner_history_version
                if (write_guard.get("valid") is not True
                        or _draft_fingerprint() != write_guard.get("draft_fingerprint")):
                    return False
            history_guard = (guard_owner_history_version(write_guard["history_version"],
                             db_path=write_guard["history_path"]) if write_guard is not None else nullcontext(True))
            with history_guard as current:
                if not current:
                    return False
                _replace_draft({})
            return True
    except (OSError, TimeoutError):
        return False


def _replace_draft(data: dict) -> None:
    """Atomically replace the draft while the caller holds its writer lock."""
    draft_file, _ = _settings()
    temporary = draft_file + "." + uuid4().hex + ".tmp"
    try:
        with open(temporary, "w", encoding="utf-8") as stream:
            json.dump(data, stream, ensure_ascii=False, indent=4)
        os.replace(temporary, draft_file)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def claim_draft_send(expected_revision: str = "") -> dict:
    """Claim one pending revision durably before touching the transport.

    An interrupted or failed send stays non-pending because delivery may have
    occurred. Owner preparation can replace it; retries cannot send it twice.
    """
    draft_file, _ = _settings()
    with FileLock(draft_file + ".lock", timeout=10):
        active, reason, draft = active_draft_status()
        if not active:
            raise ValueError(inactive_draft_message(reason))
        if expected_revision and draft.get("revision") != expected_revision:
            from core.i18n import t
            raise ValueError(t("core.messenger_draft.request_superseded"))
        draft = {**draft, "revision": draft.get("revision") or uuid4().hex,
                 "status": "sending"}
        _replace_draft(draft)
        return draft


def finish_draft_send(revision: str, *, succeeded: bool) -> None:
    """Retain a terminal/uncertain claim without deleting a replacement draft."""
    draft_file, _ = _settings()
    with FileLock(draft_file + ".lock", timeout=10):
        draft = load_draft()
        if draft and draft.get("revision") == revision and draft.get("status") == "sending":
            _replace_draft({**draft, "status": "sent" if succeeded else "uncertain"})

