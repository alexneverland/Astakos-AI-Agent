"""
Static consistency checks for Astakos tools and skills.

These tests intentionally avoid importing runtime modules. They parse source
files with AST so they do not touch credentials, browsers, APIs, or local state.
"""
import ast
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

# Explicit non-LangGraph capabilities. These are routed by prompts, Telegram
# commands, or higher-level agents instead of being direct entries in all_tools.
CAPABILITY_ALIASES = {
    "calendar_tasks": {"google_calendar_tool", "google_tasks_tool"},
    "child_activities": {"get_weather_forecast", "search_memory"},
    "code_git": {"run_terminal_command", "github_manager", "write_code", "run_code"},
    "git_ops": {"run_terminal_command", "github_manager"},
    "drive": {"drive_manager"},
    "email": {"mail_manager"},
    "ferries": {"duckduckgo_search"},
    "flights": {"search_flights"},
    "google_fit": {"get_fit_summary"},
    "image_generation": {"generate_image_tool"},
    "linkedin_post": {"update_pending_linkedin_post", "process_and_clear_linkedin_post"},
    "long_term_goals": {"save_goal_tool", "update_goal_status_tool"},
    "maps_places": {"search_google_places", "get_navigation_info"},
    "messenger": {"relay_local_payload", "execute_local_pipeline"},
    "news": {"get_news"},
    "nutrition_analysis": set(),  # Telegram /nutrition command flow.
    "recipe": {"recipe_expert", "log_meal"},
    "shopping_list": {"manage_list"},
    "story_maker": set(),  # Telegram /story command flow.
    "vacuum": {"control_vacuum"},
    "weather": {"get_weather_forecast"},
}

def _parse(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8", errors="ignore"), filename=str(path))


def _assigned_value(tree: ast.Module, name: str):
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            if any(isinstance(t, ast.Name) and t.id == name for t in node.targets):
                return node.value
        if isinstance(node, ast.AnnAssign):
            if isinstance(node.target, ast.Name) and node.target.id == name:
                return node.value
    raise AssertionError(f"Assignment not found: {name}")


def _dict_string_values(path: Path, name: str) -> dict[str, str]:
    value = _assigned_value(_parse(path), name)
    assert isinstance(value, ast.Dict)
    result = {}
    for key, val in zip(value.keys, value.values):
        if isinstance(key, ast.Constant) and isinstance(val, ast.Constant):
            result[str(key.value)] = str(val.value)
    return result


def _list_names(path: Path, name: str) -> list[str]:
    value = _assigned_value(_parse(path), name)
    assert isinstance(value, ast.List)
    return [elt.id for elt in value.elts if isinstance(elt, ast.Name)]


def _tool_functions(path: Path) -> set[str]:
    tools = set()
    for node in _parse(path).body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for dec in node.decorator_list:
            if isinstance(dec, ast.Name) and dec.id == "tool":
                tools.add(node.name)
            elif isinstance(dec, ast.Call) and isinstance(dec.func, ast.Name) and dec.func.id == "tool":
                tools.add(node.name)
    return tools


def _all_skill_tool_functions() -> set[str]:
    tools = set()
    for path in (ROOT / "astakos_skills").glob("*.py"):
        tools.update(_tool_functions(path))
    return tools


def test_all_graph_tools_have_matching_risk_entries():
    all_tools = set(_list_names(ROOT / "tools" / "system.py", "all_tools"))
    risk = set(_dict_string_values(ROOT / "core" / "tool_risk.py", "TOOL_RISK"))

    assert all_tools - risk == set()
    assert risk - all_tools == set()


def test_decorated_skill_tools_are_registered_or_explicitly_documented():
    all_tools = set(_list_names(ROOT / "tools" / "system.py", "all_tools"))
    skill_tools = _all_skill_tool_functions()
    unregistered = skill_tools - all_tools

    assert unregistered == set()


def test_capability_registry_entries_point_to_known_tools_or_documented_flows():
    all_tools = set(_list_names(ROOT / "tools" / "system.py", "all_tools"))
    registry = json.loads((ROOT / "core" / "capability_registry.json").read_text(encoding="utf-8"))

    unknown_capabilities = []
    missing_alias_tools = {}
    for entry in registry:
        name = entry["name"]
        if name in all_tools:
            continue
        if name not in CAPABILITY_ALIASES:
            unknown_capabilities.append(name)
            continue
        missing = CAPABILITY_ALIASES[name] - all_tools
        if missing:
            missing_alias_tools[name] = sorted(missing)

    assert unknown_capabilities == []
    assert missing_alias_tools == {}
