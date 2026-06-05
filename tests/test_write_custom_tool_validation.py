import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_write_custom_tool_rejects_function_name_only_in_string():
    from tools.system import write_custom_tool

    code = '''
from langchain_core.tools import tool

TEXT = "def my_tool(value): return value"

@tool
def other_tool(value: str) -> str:
    """Echo text."""
    return value
'''

    result = write_custom_tool.func("my_tool", code)

    assert "exactly one top-level function" in result


def test_write_custom_tool_rejects_missing_tool_decorator():
    from tools.system import write_custom_tool

    code = '''
def my_tool(value: str) -> str:
    """Echo text."""
    return value
'''

    result = write_custom_tool.func("my_tool", code)

    assert "@tool decorator" in result


def test_write_custom_tool_rejects_extra_tool_functions():
    from tools.system import write_custom_tool

    code = '''
from langchain_core.tools import tool

@tool
def my_tool(value: str) -> str:
    """Echo text."""
    return value

@tool
def other_tool(value: str) -> str:
    """Echo text."""
    return value
'''

    result = write_custom_tool.func("my_tool", code)

    assert "only one @tool function is allowed" in result
    assert "other_tool" in result


def test_write_custom_tool_accepts_valid_tool(tmp_path, monkeypatch):
    import tools.system as system

    monkeypatch.setattr(system, "WORKSPACE_DIR", str(tmp_path))
    code = '''
from langchain_core.tools import tool

@tool
def my_tool(value: str) -> str:
    """Uppercase text."""
    return value.upper()
'''

    result = system.write_custom_tool.func("my_tool", code)

    assert "Tool 'my_tool'" in result
    assert "TEST_OK: TEST" in result
    assert not (tmp_path / "_test_my_tool.py").exists()
