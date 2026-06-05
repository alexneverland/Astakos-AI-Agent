import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from langchain_core.messages import AIMessage

from core.tool_loop_guard import inspect_tool_loop


def _ai_tool_call(name: str, args: dict):
    return AIMessage(
        content="",
        tool_calls=[{"name": name, "args": args, "id": f"call-{name}"}],
    )


def test_repeated_same_tool_call_is_blocked():
    messages = [
        _ai_tool_call("run_terminal_command", {"command": "git status"}),
        _ai_tool_call("run_terminal_command", {"command": "git status"}),
        _ai_tool_call("run_terminal_command", {"command": "git status"}),
    ]

    allowed, reason = inspect_tool_loop(messages, max_repeated_calls=2)

    assert allowed is False
    assert "Repeated tool call" in reason


def test_many_tool_rounds_are_blocked():
    messages = [
        _ai_tool_call("run_terminal_command", {"command": f"git log -n {i}"})
        for i in range(9)
    ]

    allowed, reason = inspect_tool_loop(messages, max_tool_rounds=8)

    assert allowed is False
    assert "Tool loop stopped" in reason


def test_small_tool_sequence_is_allowed():
    messages = [
        _ai_tool_call("run_terminal_command", {"command": "git status"}),
        _ai_tool_call("run_terminal_command", {"command": "git log -n 1"}),
    ]

    allowed, reason = inspect_tool_loop(messages)

    assert allowed is True
    assert reason == ""
