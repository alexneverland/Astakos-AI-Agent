"""
Tests for Web UI polling: load_messages_after_rowid, get_max_rowid, notify flow.
Each test gets its own tmp_path — they do not share a DB file.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from datetime import datetime
import memory.conversation_history as ch


def _db(tmp_path) -> str:
    db = str(tmp_path / "test.db")
    ch.init_db(db)
    return db


def _msg(role, content, channel="telegram"):
    return {"role": role, "content": content, "channel": channel}


# ── Tests ───────────────────────────────────────────────────────

def test_max_rowid_empty(tmp_path):
    assert ch.get_max_rowid(db_path=_db(tmp_path)) == 0


def test_max_rowid_after_inserts(tmp_path):
    db = _db(tmp_path)
    for i in range(3):
        ch.append_message(role="user", content=f"m{i}", channel="telegram", db_path=db)
    rid = ch.get_max_rowid(db_path=db)
    assert isinstance(rid, int) and rid >= 3, f"Expected int >= 3, got {rid!r}"


def test_load_after_rowid_basic(tmp_path):
    db = _db(tmp_path)
    ch.append_message(role="user", content="A", channel="telegram", db_path=db)
    mid = ch.get_max_rowid(db_path=db)
    ch.append_message(role="assistant", content="B", channel="telegram", db_path=db)
    ch.append_message(role="user",      content="C", channel="telegram", db_path=db)
    msgs = ch.load_messages_after_rowid(after_rowid=mid, db_path=db)
    contents = [m["content"] for m in msgs]
    assert "A" not in contents
    assert "B" in contents and "C" in contents


def test_channel_filter(tmp_path):
    db = _db(tmp_path)
    ch.append_message(role="user", content="TG", channel="telegram", db_path=db)
    ch.append_message(role="user", content="WB", channel="web",      db_path=db)
    msgs = ch.load_messages_after_rowid(after_rowid=0, channel="telegram", db_path=db)
    contents = [m["content"] for m in msgs]
    assert "TG" in contents and "WB" not in contents


def test_rowid_in_result(tmp_path):
    db = _db(tmp_path)
    ch.append_message(role="user", content="X", channel="telegram", db_path=db)
    msgs = ch.load_messages_after_rowid(after_rowid=0, db_path=db)
    assert len(msgs) == 1
    assert "rowid" in msgs[0] and isinstance(msgs[0]["rowid"], int)


def test_after_rowid_zero_returns_all(tmp_path):
    db = _db(tmp_path)
    for i in range(4):
        ch.append_message(role="user", content=f"x{i}", channel="telegram", db_path=db)
    msgs = ch.load_messages_after_rowid(after_rowid=0, db_path=db)
    assert len(msgs) == 4, f"Expected 4, got {len(msgs)}"


def test_notify_flow(tmp_path):
    db = _db(tmp_path)
    broadcasts = []

    def fake_notify(role, content, agent=None):
        now = datetime.now()
        ch.append_message(role=role, content=content, channel="telegram",
                           timestamp=now, agent=agent, db_path=db)
        msg_id = ch.get_max_rowid(db_path=db)
        broadcasts.append({"type": "new_message", "channel": "telegram",
                            "id": msg_id, "role": role, "agent": agent})
        return msg_id

    rid = fake_notify("assistant", "Γεια!", "Chat_Agent")
    assert isinstance(rid, int) and rid > 0
    assert broadcasts[0]["type"] == "new_message"
    assert broadcasts[0]["channel"] == "telegram"
    assert broadcasts[0]["agent"] == "Chat_Agent"


def test_polling_cursor_advances(tmp_path):
    """Simulate Web UI: lastKnownMsgId (rowid) advances correctly across polls."""
    db = _db(tmp_path)
    last_rowid = 0

    # Round 1: 2 messages
    ch.append_message(role="user",      content="msg1", channel="telegram", db_path=db)
    ch.append_message(role="assistant", content="msg2", channel="telegram", db_path=db)
    msgs1 = ch.load_messages_after_rowid(after_rowid=last_rowid, db_path=db)
    assert len(msgs1) == 2
    last_rowid = ch.get_max_rowid(db_path=db)

    # Round 2: 1 new message — only it should appear
    ch.append_message(role="user", content="msg3", channel="telegram", db_path=db)
    msgs2 = ch.load_messages_after_rowid(after_rowid=last_rowid, db_path=db)
    assert len(msgs2) == 1
    assert msgs2[0]["content"] == "msg3"
