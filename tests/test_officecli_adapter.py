"""Offline adapter contracts; no application configuration or binary is loaded."""

import ast
import os
import shlex
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from typing import Any, NoReturn

import pytest


def _adapter(root: Path, run: Callable[..., SimpleNamespace]) -> dict[str, Any]:
    """Load the actual adapter with only its subprocess boundary replaced."""
    source = Path(__file__).resolve().parents[1] / "astakos_skills/officecli_skill.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    nodes = [node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.Assign))]
    for node in nodes:
        if isinstance(node, ast.FunctionDef):
            node.decorator_list = []
    namespace = {
        "os": os, "Path": Path, "shlex": shlex,
        "subprocess": SimpleNamespace(run=run), "BASE_DIR": str(root),
        "t": lambda key, **kwargs: f"{key}: {kwargs}",
        "officecli_binary_path": lambda root, **kwargs: Path(root) / "vendor/officecli/officecli.exe",
        "verified_officecli_path": lambda root: Path(root) / "vendor/officecli/officecli.exe",
    }
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(source), "exec"), namespace)
    return namespace


@pytest.mark.parametrize("suffix", ["docx", "xlsx", "pptx"])
def test_output_tag_and_quoted_arguments(tmp_path: Path, suffix: str) -> None:
    """A successful CLI creation exposes the actual output path to the UI."""
    binary = tmp_path / "vendor/officecli/officecli.exe"
    binary.parent.mkdir(parents=True)
    binary.touch()

    def run(argv: list[str], **kwargs: Any) -> SimpleNamespace:
        """Emulate CLI output creation while validating the process contract."""
        assert argv == [str(binary), "create", f"sample file.{suffix}"]
        assert kwargs["shell"] is False
        assert kwargs["timeout"] == 120
        assert Path(kwargs["cwd"]) == tmp_path / "outputs"
        (Path(kwargs["cwd"]) / f"sample file.{suffix}").write_bytes(b"fixture")
        return SimpleNamespace(returncode=0, stdout="Created", stderr="")

    response = _adapter(tmp_path, run)["run_officecli"](f'officecli create "sample file.{suffix}"')
    assert f"[CREATED_FILE: {(tmp_path / 'outputs' / f'sample file.{suffix}').resolve()}]" in response


@pytest.mark.parametrize("separator", ["&", "|", ";", ">", "<", "\n", "\r"])
def test_shell_operators_never_reach_binary(tmp_path: Path, separator: str) -> None:
    """The existing command safety boundary remains intact after upgrading."""
    binary = tmp_path / "vendor/officecli/officecli.exe"
    binary.parent.mkdir(parents=True)
    binary.touch()

    def forbidden(*args: object, **kwargs: object) -> NoReturn:
        """Fail immediately if unsafe input reaches the subprocess boundary."""
        pytest.fail("Unsafe command reached subprocess")

    result = _adapter(tmp_path, forbidden)["run_officecli"](f"create sample.docx{separator}extra")
    assert "unsafe" in result


def test_missing_binary_is_local_error(tmp_path: Path) -> None:
    """A checkout without the ignored executable fails without external I/O."""
    def forbidden(*args: object, **kwargs: object) -> NoReturn:
        """Fail if the adapter attempts to invoke a missing executable."""
        pytest.fail("Missing binary reached subprocess")

    assert "msg_not_found" in _adapter(tmp_path, forbidden)["run_officecli"]("create sample.docx")


def test_native_binary_is_used_on_linux(tmp_path: Path) -> None:
    """A provisioned Linux checkout must not look for the Windows executable."""
    binary = tmp_path / "vendor/officecli/officecli"
    binary.parent.mkdir(parents=True)
    binary.touch()

    def run(argv: list[str], **kwargs: Any) -> SimpleNamespace:
        """Confirm the chosen executable without starting any real process."""
        assert argv[0] == str(binary)
        return SimpleNamespace(returncode=0, stdout="fixture", stderr="")

    namespace = _adapter(tmp_path, run)
    namespace["officecli_binary_path"] = lambda root: binary
    namespace["verified_officecli_path"] = lambda root: binary
    assert "msg_success" in namespace["run_officecli"]("create sample.docx")


def test_unverified_binary_cannot_reach_subprocess(tmp_path: Path) -> None:
    """The real native verifier prevents execution of a damaged local artifact."""
    from services.officecli_installation import verified_officecli_path, officecli_binary_path
    binary = officecli_binary_path(tmp_path, allow_bundled=False)
    binary.parent.mkdir(parents=True)
    binary.write_bytes(b"damaged executable")

    def forbidden(*args: Any, **kwargs: Any) -> NoReturn:
        """Fail loudly if a rejected executable crosses the process boundary."""
        pytest.fail("Unverified artifact reached subprocess")

    namespace = _adapter(tmp_path, forbidden)
    namespace["verified_officecli_path"] = verified_officecli_path
    namespace["officecli_binary_path"] = officecli_binary_path
    assert "msg_not_found" in namespace["run_officecli"]("create sample.docx")
