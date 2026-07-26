"""Resolve registered Astakos tools for the agent that owns them."""

import json
import logging
import os
from typing import Any


logger = logging.getLogger(__name__)


def _registry_path() -> str:
    """Return the capability-registry path using the runtime base directory."""
    import config

    return os.path.join(config.BASE_DIR, "core", "capability_registry.json")


def _load_trusted_all_tools() -> list[Any]:
    """Load the explicit, trusted export list from the system-tools module."""
    from tools.system import all_tools

    return all_tools


def get_registered_tools_for_agent(agent_name: str, static_tools: list[Any]) -> list[Any]:
    """Merge valid registry-owned tools into an agent's static tool list.

    The capability registry is advisory: a dynamic entry is bound only when its
    name is valid, belongs to ``agent_name``, and resolves to a trusted tool
    export with a callable ``invoke`` method. Any loading failure preserves the
    static list unchanged.
    """
    try:
        system_all_tools = _load_trusted_all_tools()
    except Exception as error:
        logger.warning("Could not load trusted tools: %s", error)
        return list(static_tools)

    if not isinstance(system_all_tools, (list, tuple)):
        logger.warning("Trusted tools loader returned a non-sequence value.")
        return list(static_tools)

    try:
        with open(_registry_path(), "r", encoding="utf-8") as registry_file:
            registry = json.load(registry_file)
    except Exception as error:
        logger.warning("Could not load capability registry: %s", error)
        return list(static_tools)

    if not isinstance(registry, list):
        return list(static_tools)

    trusted_exports: dict[str, Any] = {}
    for tool in system_all_tools:
        name = getattr(tool, "name", getattr(tool, "__name__", None))
        if isinstance(name, str) and name.isidentifier() and callable(getattr(tool, "invoke", None)):
            trusted_exports[name] = tool

    merged_tools = list(static_tools)
    seen_names = {
        name
        for tool in static_tools
        if isinstance((name := getattr(tool, "name", getattr(tool, "__name__", None))), str)
    }

    for entry in registry:
        if not isinstance(entry, dict) or entry.get("agent") != agent_name:
            continue

        name = entry.get("name")
        if not isinstance(name, str) or not name.isidentifier() or name in seen_names:
            continue

        tool = trusted_exports.get(name)
        if tool is not None:
            merged_tools.append(tool)
            seen_names.add(name)

    return merged_tools
