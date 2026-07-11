from types import SimpleNamespace


def test_tool_results_fallback_uses_no_tools_synthesis(monkeypatch):
    import clients.telegram_bot as bot

    captured = []

    def fake_safe_llm(llm, messages):
        captured.append(messages[0].content)
        return SimpleNamespace(content="Σύνθεση από εργαλεία")

    monkeypatch.setattr(bot, "safe_llm_invoke", fake_safe_llm)

    result = bot._tool_results_fallback_response("τι βρήκες;", ["snippet 1", "snippet 2"])

    assert result == "Σύνθεση από εργαλεία"
    assert "Do not call tools" in captured[0]
    assert "snippet 1" in captured[0]


def test_tool_results_fallback_returns_raw_snippets_when_synthesis_fails(monkeypatch):
    import clients.telegram_bot as bot

    def fake_safe_llm(llm, messages):
        raise RuntimeError("blocked")

    monkeypatch.setattr(bot, "safe_llm_invoke", fake_safe_llm)

    result = bot._tool_results_fallback_response("τι βρήκες;", ["snippet raw"])

    assert "snippet raw" in result
    assert "δεν μπόρεσα να τα συνθέσω" in result


def test_tool_results_fallback_ignores_empty_results():
    import clients.telegram_bot as bot

    assert bot._tool_results_fallback_response("τι βρήκες;", ["", "   "]) == ""
