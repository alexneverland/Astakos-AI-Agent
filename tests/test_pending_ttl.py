"""
Tests για TTL cleanup των stale pending approvals.
"""
import sys, os, json, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime, timedelta
from unittest.mock import patch
import pytest
import core.approval as ap


def _pending_file_with(tmp_path, entries: dict) -> str:
    p = tmp_path / "pending.json"
    p.write_text(json.dumps(entries, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(p)


def _item(tool: str, minutes_ago: int, status: str = "pending") -> dict:
    created = (datetime.now() - timedelta(minutes=minutes_ago)).isoformat(timespec="seconds")
    return {
        "tool_name":    tool,
        "tool_call_id": f"id_{tool}",
        "tool_args":    {},
        "created_at":   created,
        "status":       status,
    }


# ── TTL = 60 min ──────────────────────────────────────────────────

def test_stale_entry_gets_expired(tmp_path):
    """Pending action 70 λεπτών → expired."""
    entries = {"old": _item("mail_manager", 70)}
    pfile = _pending_file_with(tmp_path, entries)

    with patch.object(ap, "PENDING_FILE", pfile):
        expired = ap.expire_stale_pending()

    assert "old" in expired
    data = json.loads(open(pfile).read())
    assert data["old"]["status"] == "expired"
    assert "expired_at" in data["old"]


def test_fresh_entry_not_expired(tmp_path):
    """Pending action 10 λεπτών → παραμένει pending."""
    entries = {"fresh": _item("drive_manager", 10)}
    pfile = _pending_file_with(tmp_path, entries)

    with patch.object(ap, "PENDING_FILE", pfile):
        expired = ap.expire_stale_pending()

    assert expired == []
    data = json.loads(open(pfile).read())
    assert data["fresh"]["status"] == "pending"


def test_already_resolved_not_touched(tmp_path):
    """Approved/rejected entries δεν αγγίζονται ακόμα και αν είναι παλιές."""
    entries = {
        "approved_old": _item("github_manager", 120, status="approved"),
        "rejected_old": _item("mail_manager",   90,  status="rejected"),
    }
    pfile = _pending_file_with(tmp_path, entries)

    with patch.object(ap, "PENDING_FILE", pfile):
        expired = ap.expire_stale_pending()

    assert expired == []
    data = json.loads(open(pfile).read())
    assert data["approved_old"]["status"] == "approved"
    assert data["rejected_old"]["status"] == "rejected"


def test_mixed_entries(tmp_path):
    """Μόνο τα stale pending γίνονται expired, τα υπόλοιπα ανέπαφα."""
    entries = {
        "stale1":    _item("mail_manager",   65),
        "stale2":    _item("github_manager", 120),
        "fresh":     _item("drive_manager",  5),
        "approved":  _item("run_code",       80, status="approved"),
    }
    pfile = _pending_file_with(tmp_path, entries)

    with patch.object(ap, "PENDING_FILE", pfile):
        expired = ap.expire_stale_pending()

    assert set(expired) == {"stale1", "stale2"}
    data = json.loads(open(pfile).read())
    assert data["fresh"]["status"] == "pending"
    assert data["approved"]["status"] == "approved"
    assert data["stale1"]["status"] == "expired"
    assert data["stale2"]["status"] == "expired"


def test_no_pending_file(tmp_path):
    """Αν δεν υπάρχει αρχείο, επιστρέφει άδεια λίστα χωρίς crash."""
    missing = str(tmp_path / "nonexistent.json")
    with patch.object(ap, "PENDING_FILE", missing):
        expired = ap.expire_stale_pending()
    assert expired == []


def test_load_pending_auto_expires(tmp_path):
    """_load_pending() καλεί expire_stale_pending() αυτόματα."""
    entries = {
        "stale": _item("mail_manager", 90),
        "fresh": _item("drive_manager", 5),
    }
    pfile = _pending_file_with(tmp_path, entries)

    with patch.object(ap, "PENDING_FILE", pfile):
        result = ap._load_pending()

    # Μετά το load, το stale έχει γίνει expired στο αρχείο
    data = json.loads(open(pfile).read())
    assert data["stale"]["status"] == "expired"
    # Αλλά στο επιστρεφόμενο dict το expired entry μπορεί να υπάρχει — αυτό που μετράει
    # είναι ότι το list_pending() δεν το επιστρέφει
    with patch.object(ap, "PENDING_FILE", pfile):
        active = ap.list_pending()
    names = [x["tool_name"] for x in active]
    assert "mail_manager" not in names
    assert "drive_manager" in names


def test_expired_entry_cannot_execute(tmp_path):
    """Expired pending action must not execute from a stale approve callback."""
    entries = {"stale": _item("dangerous_tool", 90)}
    pfile = _pending_file_with(tmp_path, entries)

    class Tool:
        name = "dangerous_tool"

        def invoke(self, args):
            raise AssertionError("expired tool should not execute")

    with patch.object(ap, "PENDING_FILE", pfile):
        result = ap.execute_approved_pending("stale", [Tool()])

    assert result["ok"] is False
    assert result["status"] == "expired"
    data = json.loads(open(pfile, encoding="utf-8").read())
    assert data["stale"]["status"] == "expired"


def test_ttl_constant_is_3600():
    """Το PENDING_TTL_SECONDS είναι 3600 (60 λεπτά)."""
    assert ap.PENDING_TTL_SECONDS == 3600
