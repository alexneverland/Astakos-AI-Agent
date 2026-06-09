"""
Tests για memory/execution_trace.py
Τρέξε: pytest tests/test_execution_trace.py -v
"""
import os
import sys
import json
import time
import tempfile
import shutil

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import memory.execution_trace as et_module
from memory.execution_trace import ExecutionTrace, load_traces, _truncate


# ── Fixture helper (χωρίς pytest tmp_path — FUSE permission issues) ───────────
def _tmpdir():
    return tempfile.mkdtemp(dir="/tmp", prefix="astakos_trace_test_")


# ═══════════════════════════════════════════════════════════════
# _truncate
# ═══════════════════════════════════════════════════════════════

def test_truncate_short_string():
    assert _truncate("hello", 10) == "hello"

def test_truncate_long_string():
    s = "a" * 400
    result = _truncate(s, 300)
    assert len(result) == 301  # 300 + "…"
    assert result.endswith("…")

def test_truncate_converts_non_string():
    assert _truncate(42, 50) == "42"


# ═══════════════════════════════════════════════════════════════
# ExecutionTrace — init
# ═══════════════════════════════════════════════════════════════

def test_init_fields():
    t = ExecutionTrace(channel="web", user_message="γεια σου")
    assert t.channel == "web"
    assert t.user_message == "γεια σου"
    assert t.agent is None
    assert t.tool_calls == []
    assert t.response is None
    assert t.error is None
    assert t.loop_guard is False
    assert len(t.trace_id) == 8

def test_long_user_message_truncated():
    msg = "x" * 500
    t = ExecutionTrace(channel="telegram", user_message=msg)
    assert len(t.user_message) <= 201  # 200 + "…"


# ═══════════════════════════════════════════════════════════════
# process_event — agent detection
# ═══════════════════════════════════════════════════════════════

class _ToolMsg:
    def __init__(self, tool_call_id, name, content):
        self.type = "tool"
        self.tool_call_id = tool_call_id
        self.name = name
        self.content = content
        self.tool_calls = None

class _AIMsg:
    def __init__(self, tool_calls):
        self.tool_calls = tool_calls
        self.type = "ai"
        self.tool_call_id = None
        self.name = None
        self.content = ""

def test_process_event_sets_agent():
    t = ExecutionTrace("web", "test")
    t.process_event({"Chat_Agent": {"messages": []}})
    assert t.agent == "Chat_Agent"

def test_process_event_skips_supervisor():
    t = ExecutionTrace("web", "test")
    t.process_event({"supervisor": {"messages": []}})
    assert t.agent is None

def test_process_event_skips_tools_node():
    t = ExecutionTrace("web", "test")
    t.process_event({"tools": {"messages": []}})
    assert t.agent is None

def test_process_event_last_agent_wins():
    t = ExecutionTrace("web", "test")
    t.process_event({"Chat_Agent": {"messages": []}})
    t.process_event({"Dev_Agent": {"messages": []}})
    assert t.agent == "Dev_Agent"


# ═══════════════════════════════════════════════════════════════
# process_event — tool call recording
# ═══════════════════════════════════════════════════════════════

def test_tool_call_recorded():
    t = ExecutionTrace("telegram", "test")
    ai_msg = _AIMsg(tool_calls=[{"id": "tc1", "name": "web_search", "args": {"query": "q"}}])
    t._process_message("Web_Agent", ai_msg)
    tool_msg = _ToolMsg(tool_call_id="tc1", name="web_search", content="some result")
    t._process_message("tools", tool_msg)
    assert len(t.tool_calls) == 1
    tc = t.tool_calls[0]
    assert tc["tool"] == "web_search"
    assert "q" in tc["args"]
    assert tc["result"] == "some result"
    assert tc["duration_ms"] is not None
    assert tc["error"] is False

def test_tool_call_duration_positive():
    t = ExecutionTrace("telegram", "test")
    ai_msg = _AIMsg(tool_calls=[{"id": "tc2", "name": "slow_tool", "args": {}}])
    t._process_message("Dev_Agent", ai_msg)
    time.sleep(0.05)
    tool_msg = _ToolMsg(tool_call_id="tc2", name="slow_tool", content="ok")
    t._process_message("tools", tool_msg)
    assert t.tool_calls[0]["duration_ms"] >= 40

def test_error_tool_detected():
    t = ExecutionTrace("telegram", "test")
    ai_msg = _AIMsg(tool_calls=[{"id": "tc3", "name": "bad_tool", "args": {}}])
    t._process_message("Dev_Agent", ai_msg)
    tool_msg = _ToolMsg(tool_call_id="tc3", name="bad_tool", content="❌ Κάτι πήγε στραβά")
    t._process_message("tools", tool_msg)
    assert t.tool_calls[0]["error"] is True

def test_loop_guard_detected():
    t = ExecutionTrace("telegram", "test")
    ai_msg = _AIMsg(tool_calls=[{"id": "tc4", "name": "some_tool", "args": {}}])
    t._process_message("Dev_Agent", ai_msg)
    tool_msg = _ToolMsg(tool_call_id="tc4", name="some_tool",
                        content="Tool loop stopped after 8 tool rounds. Last tool(s): some_tool.")
    t._process_message("tools", tool_msg)
    assert t.loop_guard is True

def test_multiple_tools_recorded():
    t = ExecutionTrace("web", "test")
    for i in range(3):
        ai_msg = _AIMsg(tool_calls=[{"id": f"tc{i}", "name": f"tool_{i}", "args": {}}])
        t._process_message("Web_Agent", ai_msg)
        tool_msg = _ToolMsg(tool_call_id=f"tc{i}", name=f"tool_{i}", content=f"result_{i}")
        t._process_message("tools", tool_msg)
    assert len(t.tool_calls) == 3
    assert [tc["tool"] for tc in t.tool_calls] == ["tool_0", "tool_1", "tool_2"]


# ═══════════════════════════════════════════════════════════════
# finalize
# ═══════════════════════════════════════════════════════════════

def test_finalize_sets_response():
    t = ExecutionTrace("web", "test")
    t.finalize(response="Ορίστε η απάντηση")
    assert t.response == "Ορίστε η απάντηση"
    assert t.duration_ms >= 0

def test_finalize_sets_error():
    t = ExecutionTrace("web", "test")
    t.finalize(error="SomeException")
    assert t.error == "SomeException"

def test_finalize_truncates_long_response():
    t = ExecutionTrace("web", "test")
    t.finalize(response="r" * 500)
    assert len(t.response) <= 201

def test_finalize_duration_accumulates():
    t = ExecutionTrace("web", "test")
    time.sleep(0.05)
    t.finalize()
    assert t.duration_ms >= 40


# ═══════════════════════════════════════════════════════════════
# save + load_traces  (χρησιμοποιεί /tmp για να αποφύγει FUSE perms)
# ═══════════════════════════════════════════════════════════════

def test_save_creates_file():
    d = _tmpdir()
    try:
        old_dir = et_module._TRACES_DIR
        et_module._TRACES_DIR = d
        t = ExecutionTrace("web", "save test")
        t.finalize(response="ok")
        t.save()
        from datetime import datetime
        today = datetime.now().strftime("%Y-%m-%d")
        log_file = os.path.join(d, f"{today}.json")
        assert os.path.exists(log_file)
        data = json.loads(open(log_file, encoding="utf-8").read())
        assert data[0]["channel"] == "web"
        assert data[0]["user_message"] == "save test"
        assert data[0]["response"] == "ok"
        assert data[0]["trace_id"] == t.trace_id
    finally:
        et_module._TRACES_DIR = old_dir
        shutil.rmtree(d, ignore_errors=True)

def test_save_appends_multiple():
    d = _tmpdir()
    try:
        old_dir = et_module._TRACES_DIR
        et_module._TRACES_DIR = d
        for i in range(3):
            t = ExecutionTrace("telegram", f"msg {i}")
            t.finalize(response=f"resp {i}")
            t.save()
        from datetime import datetime
        today = datetime.now().strftime("%Y-%m-%d")
        data = json.loads(open(os.path.join(d, f"{today}.json"), encoding="utf-8").read())
        assert len(data) == 3
        assert [x["user_message"] for x in data] == ["msg 0", "msg 1", "msg 2"]
    finally:
        et_module._TRACES_DIR = old_dir
        shutil.rmtree(d, ignore_errors=True)

def test_load_traces_empty():
    d = _tmpdir()
    try:
        old_dir = et_module._TRACES_DIR
        et_module._TRACES_DIR = d
        assert load_traces() == []
    finally:
        et_module._TRACES_DIR = old_dir
        shutil.rmtree(d, ignore_errors=True)

def test_load_traces_returns_saved():
    d = _tmpdir()
    try:
        old_dir = et_module._TRACES_DIR
        et_module._TRACES_DIR = d
        t = ExecutionTrace("web", "hello")
        t.finalize(response="world")
        t.save()
        result = load_traces()
        assert len(result) == 1
        assert result[0]["response"] == "world"
    finally:
        et_module._TRACES_DIR = old_dir
        shutil.rmtree(d, ignore_errors=True)

def test_load_traces_limit():
    d = _tmpdir()
    try:
        old_dir = et_module._TRACES_DIR
        et_module._TRACES_DIR = d
        for i in range(10):
            t = ExecutionTrace("web", f"m{i}")
            t.finalize()
            t.save()
        assert len(load_traces(limit=5)) == 5
    finally:
        et_module._TRACES_DIR = old_dir
        shutil.rmtree(d, ignore_errors=True)

def test_load_traces_specific_date():
    d = _tmpdir()
    try:
        old_dir = et_module._TRACES_DIR
        et_module._TRACES_DIR = d
        fake_date = "2025-01-01"
        fake_data = [{"trace_id": "abc12345", "channel": "telegram", "user_message": "past"}]
        with open(os.path.join(d, f"{fake_date}.json"), "w", encoding="utf-8") as f:
            json.dump(fake_data, f)
        result = load_traces(date=fake_date)
        assert len(result) == 1
        assert result[0]["user_message"] == "past"
    finally:
        et_module._TRACES_DIR = old_dir
        shutil.rmtree(d, ignore_errors=True)

def test_save_atomic_on_corrupt_file():
    d = _tmpdir()
    try:
        old_dir = et_module._TRACES_DIR
        et_module._TRACES_DIR = d
        from datetime import datetime
        today = datetime.now().strftime("%Y-%m-%d")
        with open(os.path.join(d, f"{today}.json"), "w") as f:
            f.write("CORRUPT{{{")
        t = ExecutionTrace("web", "after corrupt")
        t.finalize()
        t.save()
        data = json.loads(open(os.path.join(d, f"{today}.json"), encoding="utf-8").read())
        assert len(data) == 1
        assert data[0]["user_message"] == "after corrupt"
    finally:
        et_module._TRACES_DIR = old_dir
        shutil.rmtree(d, ignore_errors=True)
