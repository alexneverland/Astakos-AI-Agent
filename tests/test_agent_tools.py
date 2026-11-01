"""Focused coverage for dynamic registered-tool binding."""

import json
from pathlib import Path
from typing import Any

import pytest

import core.agent_tools
from core.agent_tools import get_registered_tools_for_agent


class DummyTool:
    """Minimal valid tool stand-in."""

    def __init__(self, name: str) -> None:
        self.name = name

    def invoke(self, *_args: Any, **_kwargs: Any) -> None:
        """Provide the callable tool surface required by the helper."""


def _write_registry(path: Path, entries: Any) -> None:
    """Write a temporary capability registry for one test."""
    path.write_text(json.dumps(entries), encoding="utf-8")


def test_registered_tool_is_bound_only_to_owning_agent(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Bind a valid trusted export only to the registry-declared agent."""
    registry_path = tmp_path / "capability_registry.json"
    _write_registry(registry_path, [{"name": "world_clock", "agent": "Chat_Agent"}])
    world_clock = DummyTool("world_clock")
    monkeypatch.setattr(core.agent_tools, "_registry_path", lambda: str(registry_path))
    monkeypatch.setattr(core.agent_tools, "_load_trusted_all_tools", lambda: [world_clock])

    static = [DummyTool("static_tool")]
    assert [tool.name for tool in get_registered_tools_for_agent("Chat_Agent", static)] == [
        "static_tool",
        "world_clock",
    ]
    assert [tool.name for tool in get_registered_tools_for_agent("Web_Agent", static)] == ["static_tool"]


def test_registered_tool_binding_fails_closed_for_invalid_inputs(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Ignore malformed entries, missing exports, and non-invokable objects."""
    registry_path = tmp_path / "capability_registry.json"
    _write_registry(
        registry_path,
        [
            {"name": "not an identifier", "agent": "Chat_Agent"},
            {"name": "missing_export", "agent": "Chat_Agent"},
            {"name": "wrong_agent", "agent": "Web_Agent"},
            "not-an-entry",
        ],
    )
    monkeypatch.setattr(core.agent_tools, "_registry_path", lambda: str(registry_path))
    monkeypatch.setattr(core.agent_tools, "_load_trusted_all_tools", lambda: [DummyTool("wrong_agent")])

    static = [DummyTool("static_tool")]
    assert [tool.name for tool in get_registered_tools_for_agent("Chat_Agent", static)] == ["static_tool"]


def test_registered_tool_binding_preserves_static_tools_on_loader_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Return static tools unchanged if trusted exports cannot be loaded."""
    static = [DummyTool("static_tool")]
    monkeypatch.setattr(core.agent_tools, "_load_trusted_all_tools", lambda: object())

    assert get_registered_tools_for_agent("Chat_Agent", static) == static


def test_registry_path_uses_runtime_base_dir(monkeypatch: pytest.MonkeyPatch) -> None:
    """Read config.BASE_DIR at call time rather than at module import time."""
    import config

    monkeypatch.setattr(config, "BASE_DIR", "C:/temporary-astakos")
    assert core.agent_tools._registry_path().replace("\\", "/").endswith(
        "temporary-astakos/core/capability_registry.json"
    )
