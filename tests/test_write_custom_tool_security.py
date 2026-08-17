"""Tests for write_custom_tool AST security validation and approval risk.
Run: python -m pytest tests/test_write_custom_tool_security.py -v
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tools.system import _validate_custom_tool_ast, write_custom_tool
from core.tool_risk import get_risk
from core.approval import requires_plan_per_action_approval, _effective_risk


# ── 1. Valid Tools Pass AST Validation ──────────────────────────

def test_valid_pure_math_tool_passes():
    code = """
from langchain_core.tools import tool
import math

@tool
def calculate_vat(amount: float, rate: float = 0.24) -> float:
    \"\"\"Calculate VAT on amount.\"\"\"
    return round(amount * rate, 2)
"""
    valid, err, caps = _validate_custom_tool_ast(code, "calculate_vat")
    assert valid is True
    assert err == ""
    assert caps == set()


def test_valid_datetime_json_tool_passes():
    code = """
from langchain_core.tools import tool
import json
import datetime
from typing import Dict, Any

@tool
def format_event(title: str, days_ahead: int = 1) -> str:
    \"\"\"Format an event JSON payload.\"\"\"
    target_date = datetime.datetime.now() + datetime.timedelta(days=days_ahead)
    return json.dumps({"title": title, "date": target_date.isoformat()})
"""
    valid, err, caps = _validate_custom_tool_ast(code, "format_event")
    assert valid is True
    assert err == ""
    assert caps == set()


def test_valid_network_tool_detects_capability():
    code = """
from langchain_core.tools import tool
import httpx

@tool
def fetch_crypto_price(coin: str) -> str:
    \"\"\"Fetch current crypto price.\"\"\"
    return f"Price for {coin}"
"""
    valid, err, caps = _validate_custom_tool_ast(code, "fetch_crypto_price")
    assert valid is True
    assert err == ""
    assert "httpx" in caps


def test_valid_requests_and_bs4_tool_passes():
    code = """
from langchain_core.tools import tool
import requests
from bs4 import BeautifulSoup

@tool
def scrape_headlines(url: str) -> str:
    \"\"\"Scrape headline titles.\"\"\"
    return "headlines"
"""
    valid, err, caps = _validate_custom_tool_ast(code, "scrape_headlines")
    assert valid is True
    assert err == ""
    assert "requests" in caps
    assert "bs4" in caps


# ── 2. Malicious Imports are Blocked ────────────────────────────

def test_forbidden_os_import_is_blocked():
    code = """
from langchain_core.tools import tool
import os

@tool
def bad_tool() -> str:
    return "bad"
"""
    valid, err, _ = _validate_custom_tool_ast(code, "bad_tool")
    assert valid is False
    assert "forbidden module import: `os`" in err


def test_forbidden_subprocess_import_is_blocked():
    code = """
from langchain_core.tools import tool
from subprocess import Popen

@tool
def bad_tool() -> str:
    return "bad"
"""
    valid, err, _ = _validate_custom_tool_ast(code, "bad_tool")
    assert valid is False
    assert "forbidden module import: `subprocess`" in err


def test_forbidden_ctypes_import_is_blocked():
    code = """
from langchain_core.tools import tool
import ctypes

@tool
def bad_tool() -> str:
    return "bad"
"""
    valid, err, _ = _validate_custom_tool_ast(code, "bad_tool")
    assert valid is False
    assert "forbidden module import: `ctypes`" in err


def test_unapproved_third_party_import_is_blocked():
    code = """
from langchain_core.tools import tool
import evil_package

@tool
def bad_tool() -> str:
    return "bad"
"""
    valid, err, _ = _validate_custom_tool_ast(code, "bad_tool")
    assert valid is False
    assert "unapproved module import: `evil_package`" in err


# ── 3. Malicious Calls, Aliases and Dunder Access are Blocked ──

def test_eval_call_is_blocked():
    code = """
from langchain_core.tools import tool

@tool
def bad_tool(expr: str) -> str:
    return eval(expr)
"""
    valid, err, _ = _validate_custom_tool_ast(code, "bad_tool")
    assert valid is False
    assert "forbidden identifier: `eval`" in err


def test_eval_alias_is_blocked():
    code = """
from langchain_core.tools import tool

@tool
def bad_tool(expr: str) -> str:
    x = eval
    return x(expr)
"""
    valid, err, _ = _validate_custom_tool_ast(code, "bad_tool")
    assert valid is False
    assert "forbidden identifier: `eval`" in err


def test_exec_call_is_blocked():
    code = """
from langchain_core.tools import tool

@tool
def bad_tool(stmt: str) -> str:
    exec(stmt)
    return "done"
"""
    valid, err, _ = _validate_custom_tool_ast(code, "bad_tool")
    assert valid is False
    assert "forbidden identifier: `exec`" in err


def test_open_call_is_blocked():
    code = """
from langchain_core.tools import tool

@tool
def bad_tool(path: str) -> str:
    with open(path) as f:
        return f.read()
"""
    valid, err, _ = _validate_custom_tool_ast(code, "bad_tool")
    assert valid is False
    assert "forbidden identifier: `open`" in err


def test_getattr_call_is_blocked():
    code = """
from langchain_core.tools import tool
import math

@tool
def bad_tool() -> str:
    func = getattr(math, "__builtins__")
    return str(func)
"""
    valid, err, _ = _validate_custom_tool_ast(code, "bad_tool")
    assert valid is False
    assert "forbidden identifier: `getattr`" in err or "forbidden dunder attribute" in err


def test_dunder_builtins_access_is_blocked():
    code = """
from langchain_core.tools import tool

@tool
def bad_tool() -> str:
    b = ().__class__.__bases__[0].__subclasses__()
    return str(b)
"""
    valid, err, _ = _validate_custom_tool_ast(code, "bad_tool")
    assert valid is False
    assert "forbidden dunder" in err


def test_dunder_getattribute_access_is_blocked():
    code = """
from langchain_core.tools import tool

@tool
def bad_tool() -> str:
    f = ().__getattribute__("__class__")
    return str(f)
"""
    valid, err, _ = _validate_custom_tool_ast(code, "bad_tool")
    assert valid is False
    assert "forbidden dunder" in err


def test_module_attribute_access_is_blocked():
    code = """
from langchain_core.tools import tool
import math

@tool
def bad_tool() -> str:
    return str(math.sys)
"""
    valid, err, _ = _validate_custom_tool_ast(code, "bad_tool")
    assert valid is False
    assert "forbidden module access: `sys`" in err


def test_vars_builtin_is_blocked():
    code = """
from langchain_core.tools import tool

@tool
def bad_tool() -> str:
    return str(vars())
"""
    valid, err, _ = _validate_custom_tool_ast(code, "bad_tool")
    assert valid is False
    assert "forbidden identifier: `vars`" in err


# ── 4. Structure and Decorator Validation ───────────────────────

def test_missing_tool_decorator_is_rejected():
    code = """
def plain_function(x: int) -> int:
    return x * 2
"""
    valid, err, _ = _validate_custom_tool_ast(code, "plain_function")
    assert valid is False
    assert "must have the @tool decorator" in err


def test_multiple_tools_in_one_file_is_rejected():
    code = """
from langchain_core.tools import tool

@tool
def tool_one() -> str:
    return "one"

@tool
def tool_two() -> str:
    return "two"
"""
    valid, err, _ = _validate_custom_tool_ast(code, "tool_one")
    assert valid is False
    assert "only one @tool function is allowed" in err


# ── 5. Tool Risk & Plan Mode Boundary ───────────────────────────

def test_write_custom_tool_risk_is_critical():
    assert get_risk("write_custom_tool") == "CRITICAL"
    tc = {"name": "write_custom_tool", "args": {"tool_name": "calc", "tool_code": "..."}}
    assert _effective_risk(tc) == "CRITICAL"


def test_write_custom_tool_requires_plan_per_action_approval():
    tc = {"name": "write_custom_tool", "args": {"tool_name": "calc", "tool_code": "..."}}
    assert requires_plan_per_action_approval(tc) is True


def test_write_custom_tool_rejects_bad_code_without_executing():
    bad_code = """
from langchain_core.tools import tool
import os

@tool
def exploit_tool() -> str:
    return "exploit"
"""
    result = write_custom_tool.invoke({"tool_name": "exploit_tool", "tool_code": bad_code})
    assert "System Error: Rejected" in result
