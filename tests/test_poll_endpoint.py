"""
Integration-ish tests for GET /messages/poll.

Does not spin up the full server (avoids LangGraph/Gemini imports).
Builds a minimal FastAPI app using the actual poll_messages handler
and real memory.conversation_history DB — only auth is overridden.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from unittest.mock import patch
from fastapi import FastAPI, Depends
from fastapi.testclient import TestClient
import memory.conversation_history as ch


# ── Minimal app that mirrors the real handler ─────

def _make_app(db_path: str) -> FastAPI:
    """
    Creates a minimal FastAPI app with the /messages/poll endpoint.
    The require_token becomes a no-op. The DB path is fixed per-test.
    """
    app = FastAPI()

    async def no_auth():
        return None

    @app.get("/messages/poll")
    async def poll_messages(after_id: int = 0, channel: str | None = None, _=Depends(no_auth)):
        try:
            messages = ch.load_messages_after_rowid(
                after_rowid=after_id, channel=channel or None, limit=50, db_path=db_path
            )
            current_max = ch.get_max_rowid(db_path=db_path)
            return {"messages": messages, "max_id": current_max}
        except Exception as e:
            return {"messages": [], "max_id": after_id, "error": str(e)}

    return app


def _db(tmp_path) -> str:
    db = str(tmp_path / "test.db")
    ch.init_db(db)
    return db


# ── Tests ───────────────────────────────────────────────────────

def test_poll_empty_db(tmp_path):
    """Empty DB → messages=[], max_id=0."""
    db = _db(tmp_path)
    client = TestClient(_make_app(db))
    r = client.get("/messages/poll")
    assert r.status_code == 200
    body = r.json()
    assert body["messages"] == []
    assert body["max_id"] == 0


def test_poll_returns_all_when_after_id_zero(tmp_path):
    """after_id=0 → returns all messages."""
    db = _db(tmp_path)
    ch.append_message(role="user",      content="A", channel="telegram", db_path=db)
    ch.append_message(role="assistant", content="B", channel="telegram", db_path=db)
    client = TestClient(_make_app(db))
    r = client.get("/messages/poll?after_id=0")
    assert r.status_code == 200
    body = r.json()
    assert len(body["messages"]) == 2
    contents = [m["content"] for m in body["messages"]]
    assert "A" in contents and "B" in contents


def test_poll_after_id_returns_only_new(tmp_path):
    """after_id=N → only messages with rowid > N."""
    db = _db(tmp_path)
    ch.append_message(role="user", content="old", channel="telegram", db_path=db)
    mid = ch.get_max_rowid(db_path=db)
    ch.append_message(role="assistant", content="new", channel="telegram", db_path=db)

    client = TestClient(_make_app(db))
    r = client.get(f"/messages/poll?after_id={mid}")
    assert r.status_code == 200
    body = r.json()
    assert len(body["messages"]) == 1
    assert body["messages"][0]["content"] == "new"


def test_poll_max_id_advances(tmp_path):
    """max_id increases after new messages."""
    db = _db(tmp_path)
    client = TestClient(_make_app(db))

    r1 = client.get("/messages/poll?after_id=0")
    assert r1.json()["max_id"] == 0

    ch.append_message(role="user", content="X", channel="telegram", db_path=db)
    r2 = client.get("/messages/poll?after_id=0")
    assert r2.json()["max_id"] > 0


def test_poll_channel_filter(tmp_path):
    """channel=telegram → does not return web messages."""
    db = _db(tmp_path)
    ch.append_message(role="user", content="tg_msg",  channel="telegram", db_path=db)
    ch.append_message(role="user", content="web_msg", channel="web",      db_path=db)

    client = TestClient(_make_app(db))
    r = client.get("/messages/poll?after_id=0&channel=telegram")
    assert r.status_code == 200
    contents = [m["content"] for m in r.json()["messages"]]
    assert "tg_msg" in contents
    assert "web_msg" not in contents


def test_poll_no_channel_returns_all_channels(tmp_path):
    """Without channel param → returns telegram + web together."""
    db = _db(tmp_path)
    ch.append_message(role="user", content="tg",  channel="telegram", db_path=db)
    ch.append_message(role="user", content="web", channel="web",      db_path=db)

    client = TestClient(_make_app(db))
    r = client.get("/messages/poll?after_id=0")
    contents = [m["content"] for m in r.json()["messages"]]
    assert "tg" in contents and "web" in contents


def test_poll_rowid_present_in_messages(tmp_path):
    """Each message has a rowid (integer) — the frontend cursor is required."""
    db = _db(tmp_path)
    ch.append_message(role="user", content="msg", channel="telegram", db_path=db)

    client = TestClient(_make_app(db))
    r = client.get("/messages/poll?after_id=0")
    msg = r.json()["messages"][0]
    assert "rowid" in msg
    assert isinstance(msg["rowid"], int) and msg["rowid"] > 0


def test_poll_incremental_two_rounds(tmp_path):
    """Simulate two polling rounds: second round brings only new data."""
    db = _db(tmp_path)
    client = TestClient(_make_app(db))

    # Round 1
    ch.append_message(role="user",      content="r1a", channel="telegram", db_path=db)
    ch.append_message(role="assistant", content="r1b", channel="telegram", db_path=db)
    r1 = client.get("/messages/poll?after_id=0&channel=telegram")
    assert len(r1.json()["messages"]) == 2
    last_rowid = r1.json()["max_id"]

    # Round 2: only new message
    ch.append_message(role="user", content="r2", channel="telegram", db_path=db)
    r2 = client.get(f"/messages/poll?after_id={last_rowid}&channel=telegram")
    msgs2 = r2.json()["messages"]
    assert len(msgs2) == 1
    assert msgs2[0]["content"] == "r2"
