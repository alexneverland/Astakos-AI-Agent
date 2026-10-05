"""Offline contracts for the pinned research engine and Astakos adapter."""

import ast
import os
import re
import shutil
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
    functions = [node for node in tree.body if isinstance(node, ast.FunctionDef)]
    for function in functions:
        function.decorator_list = []
    namespace = {
        "os": os,
        "sys": sys,
        "subprocess": subprocess,
        "shutil": shutil,
        "BASE_DIR": str(ROOT),
        "t": lambda key, **kwargs: f"{key}: {kwargs}",
    }
    exec(compile(ast.Module(body=functions, type_ignores=[]), "adapter", "exec"), namespace)
    return namespace


def _run_vendor_cli(runner: str, cwd: Path, *args: str) -> subprocess.CompletedProcess:
    """Use the same verified >=3.12 launcher as production for CLI tests."""
    command = _adapter()["_research_python_command"]()
    return subprocess.run(
        [*command, "-c", runner, str(SKILL / "scripts/last30days.py"), *args],
        cwd=cwd, capture_output=True, text=True, encoding="utf-8", timeout=30,
    )


def test_release_is_pinned() -> None:
    """The shipped skill must advertise the reviewed release."""
    assert 'version: "3.26.0"' in (SKILL / "SKILL.md").read_text(encoding="utf-8")


@pytest.mark.parametrize("http_status", ["fixture-private-password", {"password": "fixture-private-password"}, True, 99, 600, 401])
def test_public_auth_http_status_is_bounded_integer(http_status) -> None:
    """The CodeQL-tainted HTTP field cannot carry provider strings or objects."""
    tree = ast.parse((SKILL / "scripts/last30days.py").read_text(encoding="utf-8"))
    function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "public_device_auth_result")
    namespace = {"re": re}
    exec(compile(ast.Module(body=[function], type_ignores=[]), "public_auth", "exec"), namespace)
    public = namespace["public_device_auth_result"]({
        "status": "error", "http_status": http_status,
        "api_key": "fixture-private-password", "detail": "fixture-private-password",
    })
    if type(http_status) is int and 100 <= http_status <= 599:
        assert public["http_status"] == http_status
    else:
        assert "http_status" not in public
    assert "fixture-private-password" not in str(public)


def test_python311_uses_verified_path_interpreter(monkeypatch) -> None:
    """A 3.11 application can still research using a compatible PATH Python."""
    monkeypatch.setattr(sys, "version_info", (3, 11, 9))
    monkeypatch.setattr(shutil, "which", lambda name: "/compatible/python" if name == "python" else None)
    calls = []

    def run(argv, **kwargs):
        calls.append(argv)
        if "-c" in argv:
            return SimpleNamespace(returncode=0, stdout="3.12", stderr="")
        return SimpleNamespace(returncode=0, stdout="research result", stderr="")

    monkeypatch.setattr(subprocess, "run", run)
    assert _adapter()["research_last30days"]("offline topic") == "research result"
    assert calls[-1][0] == "/compatible/python"


def test_python311_never_runs_research_without_compatible_python(monkeypatch) -> None:
    """Missing/old Python must fail locally before starting research."""
    monkeypatch.setattr(sys, "version_info", (3, 11, 9))
    monkeypatch.setattr(shutil, "which", lambda name: None)
    calls = []
    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: calls.append(args))
    assert "msg_unexpected_error" in _adapter()["research_last30days"]("offline topic")
    assert not calls


def test_real_cli_test_launcher_on_python311(monkeypatch, tmp_path) -> None:
    """Simulate a 3.11 test host with a real compatible Python on PATH."""
    compatible = _adapter()["_research_python_command"]()
    monkeypatch.setattr(sys, "version_info", (3, 11, 9))
    launcher_name = "py" if len(compatible) > 1 else "python"
    monkeypatch.setattr(shutil, "which", lambda name: compatible[0] if name == launcher_name else None)
    result = _run_vendor_cli("print('fixture-cli-ok')", tmp_path)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "fixture-cli-ok"


@pytest.mark.parametrize("error_kind", ["401", "503", "network"])
def test_real_setup_http_boundary_never_logs_credentials(tmp_path, error_kind) -> None:
    """Run real device-auth and profile handling, mocking only HTTP/auth I/O."""
    runner = r'''
import importlib.util, io, socket, sys
from urllib.error import HTTPError, URLError
from unittest.mock import patch
spec = importlib.util.spec_from_file_location("research_cli", sys.argv[1])
cli = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cli)
from lib import setup_wizard
kind = sys.argv[2]
sys.argv = [sys.argv[1], "setup", "--github"]
secret = "fixture-private-credential"
def http_failure(*args, **kwargs):
    if kind == "network":
        raise URLError(secret)
    raise HTTPError("https://example.invalid/profile", int(kind), secret, {}, io.BytesIO(secret.encode()))
def forbidden(*args, **kwargs):
    raise AssertionError("External I/O forbidden")
handle = {"device_code": "fixture-device-code", "user_code": "ABCD-1234", "interval": 1}
with patch.object(cli.env, "get_config", return_value={}), patch.object(cli.env, "read_secret_env", return_value=None), patch.object(setup_wizard, "_start_device_flow", return_value=({}, handle)), patch.object(setup_wizard, "poll_device_auth", return_value="fixture-access-token"), patch.object(setup_wizard, "urlopen", side_effect=http_failure), patch.object(setup_wizard.time, "sleep"), patch.object(setup_wizard, "_device_handle_path", return_value=cli.Path("missing-fixture-handle")), patch.object(socket.socket, "connect", forbidden):
    raise SystemExit(cli.main())
'''
    result = _run_vendor_cli(runner, tmp_path, error_kind)
    assert result.returncode == 0, result.stderr
    assert '"status": "error"' in result.stdout
    assert "fixture-private" not in result.stdout + result.stderr
    if error_kind != "network":
        assert error_kind in result.stdout + result.stderr


@pytest.mark.parametrize("status", ["error", "success", "already_registered", "awaiting_authorization"])
def test_device_auth_stdout_drops_provider_secrets(tmp_path, status) -> None:
    """Real CLI setup output must not echo provider error bodies or secrets."""
    runner = r'''
import importlib.util, socket, sys
from unittest.mock import patch
spec = importlib.util.spec_from_file_location("research_cli", sys.argv[1])
cli = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cli)
from lib import setup_wizard
def forbidden(*args, **kwargs):
    raise AssertionError("External I/O forbidden")
status = sys.argv[2]
sys.argv = [sys.argv[1], "setup", "--github"]
result = {"status": status, "reason": "http_error", "http_status": 401,
          "detail": "fixture-private-password", "message": "fixture-private-password",
          "password": "fixture-private-password", "api_key": "fixture-private-api-key",
          "user_code": "ABCD-1234", "verification_uri": "https://github.com/login/device"}
with patch.object(cli.env, "get_config", return_value={}), patch.object(cli.env, "read_secret_env", return_value=None), patch.object(setup_wizard, "run_github_auth", return_value=result), patch.object(setup_wizard, "write_api_key", return_value=True) as write_key, patch.object(socket.socket, "connect", forbidden):
    code = cli.main()
    if status == "success":
        write_key.assert_called_once_with(cli.env.CONFIG_FILE, "fixture-private-api-key")
    else:
        write_key.assert_not_called()
    raise SystemExit(code)
'''
    result = _run_vendor_cli(runner, tmp_path, status)
    assert result.returncode == 0, result.stderr
    assert f'"status": "{status}"' in result.stdout
    assert '"user_code": "ABCD-1234"' in result.stdout
    assert f'"persisted": {str(status in {"success", "already_registered"}).lower()}' in result.stdout
    assert "fixture-private" not in result.stdout + result.stderr


@pytest.mark.parametrize("probe_result", ["3.11", "not-a-version", "timeout"])
def test_old_or_failed_path_python_falls_back_to_windows_launcher(monkeypatch, probe_result) -> None:
    """Do not trust PATH names: validate versions and recover through py -3."""
    monkeypatch.setattr(sys, "version_info", (3, 11, 9))
    monkeypatch.setattr(shutil, "which", lambda name: {"python": "/old/python", "py": "/launcher/py"}.get(name))

    def run(argv, **kwargs):
        if argv[0] == "/old/python":
            if probe_result == "timeout":
                raise subprocess.TimeoutExpired(argv, kwargs["timeout"])
            return SimpleNamespace(returncode=0, stdout=probe_result)
        assert argv[:2] == ["/launcher/py", "-3"]
        return SimpleNamespace(returncode=0, stdout="3.13")

    monkeypatch.setattr(subprocess, "run", run)
    assert _adapter()["_research_python_command"]() == ["/launcher/py", "-3"]


@pytest.mark.parametrize("configured", [None, "3"])
def test_adapter_preserves_credit_policy(monkeypatch, configured) -> None:
    """No new paid backfill by default; an explicit process setting wins."""
    monkeypatch.setattr(sys, "version_info", (3, 12, 0))
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
    monkeypatch.setattr(sys, "version_info", (3, 12, 0))
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
    result = _run_vendor_cli(runner, tmp_path)
    assert result.returncode == 0, result.stderr
    assert "offline topic" in result.stdout
    assert len(result.stdout) > 100
