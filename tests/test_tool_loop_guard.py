from langchain_core.messages import HumanMessage, AIMessage

from core.tool_loop_guard import inspect_tool_loop


def _ai_with_tool(name, args):
    msg = AIMessage(content="")
    msg.tool_calls = [{"name": name, "args": args, "id": f"{name}-1"}]
    return msg


def test_repeated_tool_calls_allowed_after_new_human_update():
    messages = [
        HumanMessage(content="ψαξε για φωτια στο ωραιοκαστρο"),
        _ai_with_tool("duckduckgo_search", {"query": "φωτια ωραιοκαστρο"}),
        HumanMessage(content="τωρα ηρθε μηνυμα 112"),
        _ai_with_tool("duckduckgo_search", {"query": "φωτια ωραιοκαστρο 112"}),
    ]
    allowed, _ = inspect_tool_loop(messages)
    assert allowed is True


def test_true_same_window_tool_loop_is_blocked():
    messages = [
        HumanMessage(content="ψαξε για φωτια στο ωραιοκαστρο"),
        _ai_with_tool("duckduckgo_search", {"query": "φωτια ωραιοκαστρο"}),
        _ai_with_tool("duckduckgo_search", {"query": "φωτια ωραιοκαστρο"}),
        _ai_with_tool("duckduckgo_search", {"query": "φωτια ωραιοκαστρο"}),
        _ai_with_tool("duckduckgo_search", {"query": "φωτια ωραιοκαστρο"}),
    ]
    allowed, reason = inspect_tool_loop(messages)
    assert allowed is False
    assert "Repeated tool call blocked" in reason

def test_small_mixed_tool_sequence_is_allowed():
    messages = [
        HumanMessage(content="ψαξε και δες"),
        _ai_with_tool("duckduckgo_search", {"query": "καιρος θεσσαλονικη"}),
        _ai_with_tool("browse_url", {"url": "https://example.com"}),
    ]
    allowed, reason = inspect_tool_loop(messages)
    assert allowed is True
    assert reason == ""
