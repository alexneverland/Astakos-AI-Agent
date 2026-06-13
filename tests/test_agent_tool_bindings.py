import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _function_source(name: str) -> str:
    source = (ROOT / "core" / "agents.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return ast.get_source_segment(source, node) or ""
    raise AssertionError(f"Function not found: {name}")


def test_git_agent_uses_terminal_not_read_local_file():
    source = _function_source("git_agent_node")

    assert "run_terminal_command" in source
    assert "read_local_file" not in source


def test_dev_agent_binds_register_tool():
    source = _function_source("dev_agent_node")

    assert "write_custom_tool" in source
    assert "register_tool" in source


def test_tech_agent_binds_observability_tools():
    source = _function_source("tech_agent_node")

    assert "tool_stats" in source
    assert "system_doctor" in source
    assert "memory_review" in source
