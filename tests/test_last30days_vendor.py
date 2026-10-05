"""Offline contracts for the pinned research engine and Astakos adapter."""

import ast
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "vendor/last30days-skill/skills/last30days"


def _adapter() -> dict:
    """Load the adapter without importing credentials or application runtime."""
    tree = ast.parse((ROOT / "astakos_skills/research_last30days.py").read_text())
    function = next(node for node in tree.body if isinstance(node, ast.FunctionDef))
    function.decorator_list = []
    namespace = {
        "os": os,
        "sys": sys,
        "subprocess": subprocess,
        "BASE_DIR": str(ROOT),
        "t": lambda key, **kwargs: f"{key}: {kwargs}",
    }
    exec(compile(ast.Module(body=[function], type_ignores=[]), "adapter", "exec"), namespace)
    return namespace


def test_release_is_pinned() -> None:
    """The shipped skill must advertise the reviewed release."""
    assert 'version: "3.26.0"' in (SKILL / "SKILL.md").read_text(encoding="utf-8")


@pytest.mark.parametrize("configured", [None, "3"])
def test_adapter_preserves_credit_policy(monkeypatch, configured) -> None:
    """No new paid backfill by default; an explicit process setting wins."""
    if configured is None:
        monkeypatch.delenv("LAST30DAYS_REDDIT_SC_MIN_ITEMS", raising=False)
    else:
        monkeypatch.setenv("LAST30DAYS_REDDIT_SC_MIN_ITEMS", configured)
    calls = []

    def run(argv, **kwargs):
        calls.append((argv, kwargs))
        return SimpleNamespace(returncode=0, stdout=" research result ", stderr="")

    monkeypatch.setattr(subprocess, "run", run)
    assert _adapter()["research_last30days"]("offline topic") == "research result"
    argv, kwargs = calls[0]
    assert argv == [sys.executable, str(SKILL / "scripts/last30days.py"), "--emit", "md", "offline topic"]
    assert kwargs["timeout"] == 120
    assert kwargs["env"]["LAST30DAYS_REDDIT_SC_MIN_ITEMS"] == (configured or "0")
    assert os.environ.get("LAST30DAYS_REDDIT_SC_MIN_ITEMS") == configured


@pytest.mark.parametrize("mode", ["failure", "timeout"])
def test_adapter_keeps_error_handling(monkeypatch, mode) -> None:
    """An engine failure cannot be reported as a successful result."""
    def run(argv, **kwargs):
        if mode == "timeout":
            raise subprocess.TimeoutExpired(argv, kwargs["timeout"])
        return SimpleNamespace(returncode=1, stdout="", stderr="offline failure")

    monkeypatch.setattr(subprocess, "run", run)
    result = _adapter()["research_last30days"]("offline topic")
    expected = "timeout" if mode == "timeout" else "msg_exec_error"
    assert expected in result


def test_real_engine_accepts_astakos_markdown_contract(tmp_path) -> None:
    """Exercise the real engine with fixtures and fail closed on network I/O."""
    runner = r'''
import importlib.util, socket, sys
from unittest.mock import patch
spec = importlib.util.spec_from_file_location("research_cli", sys.argv[1])
cli = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cli)
def forbidden(*args, **kwargs):
    raise AssertionError("Live network is forbidden in vendor contract tests")
sys.argv = [sys.argv[1], "--emit", "md", "offline topic", "--mock", "--save-dir", ""]
with patch.object(cli.env, "get_config", return_value={}), patch.object(cli.env, "read_secret_env", return_value=None), patch.object(socket, "create_connection", forbidden), patch.object(socket.socket, "connect", forbidden), patch.object(socket.socket, "connect_ex", forbidden):
    raise SystemExit(cli.main())
'''
    result = subprocess.run(
        [sys.executable, "-c", runner, str(SKILL / "scripts/last30days.py")],
        cwd=tmp_path, capture_output=True, text=True, encoding="utf-8", timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert "offline topic" in result.stdout
    assert len(result.stdout) > 100
