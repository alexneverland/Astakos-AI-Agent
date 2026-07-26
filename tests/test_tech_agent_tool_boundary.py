from langchain_core.messages import HumanMessage, AIMessage
from unittest.mock import patch

from core.agents import tech_agent_node
from core.tool_loop_guard import inspect_tool_loop

def _ai_with_tool(name, args):
    msg = AIMessage(content="")
    msg.tool_calls = [{"name": name, "args": args, "id": f"{name}-1"}]
    return msg

def test_tech_agent_tool_boundary():
    state = {"messages": [HumanMessage(content="Hello tech agent")], "channel": "web"}

    with patch("core.agents.llm_heavy") as mock_llm_heavy:
        mock_llm_heavy.bind_tools.return_value.invoke.return_value = AIMessage(content="Mocked response")
        tech_agent_node(state)

        assert mock_llm_heavy.bind_tools.called
        bound_tools = mock_llm_heavy.bind_tools.call_args[0][0]
        tool_names = [t.name for t in bound_tools]

        # 1. Prove it includes duckduckgo_search and bounded diagnostics
        assert "duckduckgo_search" in tool_names
        assert "grep_project_files" in tool_names
        assert "list_recent_files" in tool_names

        # 2. Prove it excludes the unsafe tools
        assert "run_terminal_command" not in tool_names
        assert "write_code" not in tool_names
        assert "run_code" not in tool_names

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
