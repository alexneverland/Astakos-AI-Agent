import json
import os
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


def build_draft(target_name: str, message: str, *, now: datetime | None = None) -> dict:
    _, ttl_seconds = _settings()
    now = now or datetime.now()
    expires_at = now + timedelta(seconds=ttl_seconds)
    return {
        "target_name": target_name,
        "message": message,
        "status": "pending",
        "created_at": now.isoformat(timespec="seconds"),
        "expires_at": expires_at.isoformat(timespec="seconds"),
    }


def save_draft(target_name: str, message: str) -> dict:
    draft_file, _ = _settings()
    draft = build_draft(target_name, message)
    with open(draft_file, "w", encoding="utf-8") as f:
        json.dump(draft, f, ensure_ascii=False, indent=4)
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
    if reason == "expired":
        return "❌ Σφάλμα: Το προσχέδιο έχει λήξει. Φτιάξε νέο draft πριν στείλω."
    if reason == "incomplete":
        return "❌ Σφάλμα: Το προσχέδιο είναι ελλιπές."
    if reason == "not_pending":
        return "❌ Σφάλμα: Δεν υπάρχει ενεργό προσχέδιο για αποστολή."
    return "❌ Σφάλμα: Δεν βρέθηκε προσχέδιο!"


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
