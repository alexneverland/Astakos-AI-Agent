"""
Tests για Web UI polling: load_messages_after_rowid, get_max_rowid, notify flow.
Τρέξε: python3 tests/test_telegram_polling.py
"""
import sys, os, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import memory.conversation_history as ch
from datetime import datetime

DB = "/tmp/test_tg_polling.db"

def setup():
    if os.path.exists(DB): os.unlink(DB)
    ch.init_db(DB)

def teardown():
    if os.path.exists(DB): os.unlink(DB)

def test_max_rowid_empty():
    setup()
    assert ch.get_max_rowid(db_path=DB) == 0
    teardown()

def test_max_rowid_after_inserts():
    setup()
    for i in range(3):
        ch.append_message(role="user", content=f"m{i}", channel="telegram", db_path=DB)
    rid = ch.get_max_rowid(db_path=DB)
    assert isinstance(rid, int) and rid >= 3, f"Expected int >= 3, got {rid!r}"
    teardown()

def test_load_after_rowid_basic():
    setup()
    ch.append_message(role="user", content="A", channel="telegram", db_path=DB)
    mid = ch.get_max_rowid(db_path=DB)
    ch.append_message(role="assistant", content="B", channel="telegram", db_path=DB)
    ch.append_message(role="user",      content="C", channel="telegram", db_path=DB)
    msgs = ch.load_messages_after_rowid(after_rowid=mid, db_path=DB)
    contents = [m["content"] for m in msgs]
    assert "A" not in contents
    assert "B" in contents and "C" in contents
    teardown()

def test_channel_filter():
    setup()
    ch.append_message(role="user", content="TG", channel="telegram", db_path=DB)
    ch.append_message(role="user", content="WB", channel="web",      db_path=DB)
    msgs = ch.load_messages_after_rowid(after_rowid=0, channel="telegram", db_path=DB)
    contents = [m["content"] for m in msgs]
    assert "TG" in contents and "WB" not in contents
    teardown()

def test_rowid_in_result():
    setup()
    ch.append_message(role="user", content="X", channel="telegram", db_path=DB)
    msgs = ch.load_messages_after_rowid(after_rowid=0, db_path=DB)
    assert len(msgs) == 1
    assert "rowid" in msgs[0] and isinstance(msgs[0]["rowid"], int)
    teardown()

def test_after_rowid_zero_returns_all():
    setup()
    for i in range(4):
        ch.append_message(role="user", content=f"x{i}", channel="telegram", db_path=DB)
    msgs = ch.load_messages_after_rowid(after_rowid=0, db_path=DB)
    assert len(msgs) == 4, f"Expected 4, got {len(msgs)}"
    teardown()

def test_notify_flow():
    setup()
    broadcasts = []

    def fake_notify(role, content, agent=None):
        now = datetime.now()
        ch.append_message(role=role, content=content, channel="telegram",
                           timestamp=now, agent=agent, db_path=DB)
        msg_id = ch.get_max_rowid(db_path=DB)
        broadcasts.append({"type": "new_message", "channel": "telegram",
                            "id": msg_id, "role": role, "agent": agent})
        return msg_id

    rid = fake_notify("assistant", "Γεια!", "Chat_Agent")
    assert isinstance(rid, int) and rid > 0
    assert broadcasts[0]["type"] == "new_message"
    assert broadcasts[0]["channel"] == "telegram"
    assert broadcasts[0]["agent"] == "Chat_Agent"
    teardown()

if __name__ == "__main__":
    tests = [test_max_rowid_empty, test_max_rowid_after_inserts, test_load_after_rowid_basic,
             test_channel_filter, test_rowid_in_result, test_after_rowid_zero_returns_all,
             test_notify_flow]
    for t in tests:
        t()
        print(f"  {t.__name__}: PASS")
    print(f"\n✅ {len(tests)}/{ len(tests)} tests PASSED")
