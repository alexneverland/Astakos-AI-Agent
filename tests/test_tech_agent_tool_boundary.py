from langchain_core.messages import HumanMessage, AIMessage
from unittest.mock import patch
from pathlib import Path
import json
import socket
import pytest

from core.tool_loop_guard import inspect_tool_loop


@pytest.fixture(autouse=True)
def isolated_tech_agent(monkeypatch, tmp_path, mock_dbs):
    """Keep agent tests away from live memory, registries, and transports."""
    network_attempts = []

    def deny_network(*args, **kwargs):
        network_attempts.append(True)
        raise AssertionError("Unexpected network call in offline Tech_Agent test")

    monkeypatch.setattr(socket.socket, "connect", deny_network)
    monkeypatch.setattr(socket, "create_connection", deny_network)
    from core import agents
    from core import agent_tools

    monkeypatch.setattr(agents, "build_prompt", lambda history, prompt, **kwargs: prompt)
    monkeypatch.setattr("core.utils.build_prompt", lambda history, prompt, **kwargs: prompt)
    registry = tmp_path / "capabilities.json"
    registry.write_text("[]", encoding="utf-8")
    monkeypatch.setattr(agent_tools, "_registry_path", lambda: str(registry))
    monkeypatch.setattr(agent_tools, "_load_trusted_all_tools", lambda: [])
    yield agents.tech_agent_node
    assert not network_attempts, "An offline test attempted an outbound call"

def _ai_with_tool(name, args):
    msg = AIMessage(content="")
    msg.tool_calls = [{"name": name, "args": args, "id": f"{name}-1"}]
    return msg

def test_tech_agent_tool_boundary(isolated_tech_agent):
    state = {"messages": [HumanMessage(content="Hello tech agent")], "channel": "web"}

    with patch("core.agents.llm_heavy") as mock_llm_heavy:
        mock_llm_heavy.bind_tools.return_value.invoke.return_value = AIMessage(content="Mocked response")
        isolated_tech_agent(state)

        assert mock_llm_heavy.bind_tools.called
        bound_tools = mock_llm_heavy.bind_tools.call_args[0][0]
        tool_names = [t.name for t in bound_tools]

        # 1. Prove it includes duckduckgo_search and bounded diagnostics
        assert "duckduckgo_search" in tool_names
        assert "grep_project_files" in tool_names
        assert "list_recent_files" in tool_names
        assert "list_project_files" in tool_names
        assert "read_project_file" in tool_names

        # 2. Prove it excludes the unsafe tools
        assert "run_terminal_command" not in tool_names
        assert "write_code" not in tool_names
        assert "run_code" not in tool_names
        assert "grant_project_access" not in tool_names
        assert "edit_project_file" not in tool_names
        assert "write_project_file" not in tool_names


@pytest.mark.parametrize("allowed", [True, False])
def test_tech_agent_reads_only_granted_project_code(
    isolated_tech_agent, monkeypatch, tmp_path, allowed
):
    """Exercise real file reads through the tools offered to the Tech model."""
    from tools import project_tools

    project = tmp_path / "Μαθηματικα"
    source = project / "lib" / "challenge.ts"
    source.parent.mkdir(parents=True)
    source.write_text("export const maxNumber = 10;\n", encoding="utf-8")
    access = tmp_path / "project_access.json"
    access.write_text(json.dumps({
        str(project): {"read": allowed, "edit": False, "label": "Μαθηματικα"},
    }), encoding="utf-8")
    monkeypatch.setattr(project_tools, "PROJECT_ACCESS_FILE", str(access))
    state = {"messages": [HumanMessage(content=f"{project} δεσ και πεσ μου πωσ σου φαινετε")], "channel": "web"}

    with patch("core.agents.llm_heavy") as model:
        model.bind_tools.return_value.invoke.return_value = AIMessage(content="offline")
        isolated_tech_agent(state)
        bound = {tool.name: tool for tool in model.bind_tools.call_args.args[0]}

    result = bound["read_project_file"].invoke({"file_path": str(source)})
    if allowed:
        listing = bound["list_project_files"].invoke({"folder_path": str(project), "pattern": "**/*.ts"})
        assert "challenge.ts" in listing
        assert "export const maxNumber = 10;" in result
    else:
        assert "❌" in result
        assert "export const" not in result

    outside = tmp_path / "private.ts"
    outside.write_text("private marker", encoding="utf-8")
    denied = bound["read_project_file"].invoke({"file_path": str(project / ".." / "private.ts")})
    assert "❌" in denied
    assert "private marker" not in denied


def test_tech_review_prompt_distinguishes_evidence_and_incomplete_access():
    """Pin the review policy without pretending to test a live model's judgment."""
    prompt = (Path(__file__).parents[1] / "core" / "prompts.md").read_text(encoding="utf-8")
    tech = prompt.split("## Tech_Agent")[1].split("## Dev_Agent")[0]
    assert "read_project_file" in tech
    assert "README-only" in tech
    assert "tests passed" in tech
    assert "access fails" in tech

def test_repeated_native_search_is_bounded():
    # 3. Prove repeated native-search calls are bounded before graph recursion
    messages = [
        HumanMessage(content="search for display brands"),
        _ai_with_tool("duckduckgo_search", {"query": "best display brands"}),
        _ai_with_tool("duckduckgo_search", {"query": "best display brands"}),
        _ai_with_tool("duckduckgo_search", {"query": "best display brands"}),
        _ai_with_tool("duckduckgo_search", {"query": "best display brands"}),
    ]
    allowed, _ = inspect_tool_loop(messages)
    assert allowed is False

def test_tech_agent_prompt_no_terminal_hallucination():
    import os
    from config import BASE_DIR

    prompt_path = os.path.join(BASE_DIR, "core", "prompts.md")
    with open(prompt_path, "r", encoding="utf-8") as f:
        content = f.read()

    tech_section = content.split("## Tech_Agent")[1].split("## Dev_Agent")[0].lower()

    assert "terminal commands" not in tech_section
    assert "powershell" not in tech_section
    assert "shell commands" not in tech_section
