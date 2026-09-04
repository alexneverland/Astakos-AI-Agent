import re
from pathlib import Path
from typing import Any

from core.utils import (
    looks_like_web_tool_error,
    filter_recent_web_tool_results,
    build_web_failure_reply,
    looks_like_terminal_linkedin_draft_result,
    build_linkedin_draft_ready_reply,
    should_attach_linkedin_draft_reply,
    looks_like_terminal_messenger_draft_result,
    build_messenger_draft_ready_reply,
)
from langchain_core.messages import HumanMessage, ToolMessage, AIMessage, SystemMessage
from core.i18n import t


# 1. Detect web error sentinel
def test_looks_like_web_tool_error_detects_structured_prefix():
    assert looks_like_web_tool_error("[WEB_TOOL_ERROR][duckduckgo_search][reason=timeout] ...") is True

# 2. Detect legacy human failure text
def test_looks_like_web_tool_error_detects_legacy_failure_text():
    assert looks_like_web_tool_error("⚠️ Η αναζήτηση απέτυχε σε 2 backends ...") is True

# 3. Success result is not failure
def test_looks_like_web_tool_error_ignores_real_search_result():
    assert looks_like_web_tool_error("Τίτλος: ... URL: ... Περίληψη: ...") is False

# 4. Guard blocks hallucinated web answer
def test_guard_blocks_hallucinated_web_answer():
    # Simulate history with one failed web tool
    history = [
        HumanMessage(content="Πόσα άτομα χωράει το Θέατρο Γης;"),
        AIMessage(content="", tool_calls=[{"name": "duckduckgo_search", "args": {}, "id": "t1"}]),
        ToolMessage(tool_call_id="t1", name="duckduckgo_search", content="[WEB_TOOL_ERROR][duckduckgo_search] error")
    ]
    recent = filter_recent_web_tool_results(history)
    web_errors = [(name, text) for name, text in recent if looks_like_web_tool_error(text)]
    web_successes = [(name, text) for name, text in recent if not looks_like_web_tool_error(text)]
    
    assert len(web_errors) == 1
    assert len(web_successes) == 0
    
    reply = build_web_failure_reply("Πόσα άτομα χωράει το Θέατρο Γης;", recent)
    assert "νούμερο/στοιχείο" in reply

# 5. Guard does not block when there is at least one successful tool result
def test_guard_allows_if_partial_success():
    history = [
        HumanMessage(content="Πόσα άτομα χωράει;"),
        AIMessage(content="", tool_calls=[
            {"name": "duckduckgo_search", "args": {}, "id": "t1"},
            {"name": "browse_url", "args": {}, "id": "t2"}
        ]),
        ToolMessage(tool_call_id="t1", name="duckduckgo_search", content="[WEB_TOOL_ERROR] failed"),
        ToolMessage(tool_call_id="t2", name="browse_url", content="Το θέατρο χωράει 4000 άτομα.")
    ]
    recent = filter_recent_web_tool_results(history)
    web_errors = [(n, t) for n, t in recent if looks_like_web_tool_error(t)]
    web_successes = [(n, t) for n, t in recent if not looks_like_web_tool_error(t)]
    
    assert len(web_errors) == 1
    assert len(web_successes) == 1

# 6. Current-turn isolation
def test_guard_ignores_old_failures():
    history = [
        HumanMessage(content="παλιό query"),
        AIMessage(content="", tool_calls=[{"name": "duckduckgo_search", "args": {}, "id": "old_t"}]),
        ToolMessage(tool_call_id="old_t", name="duckduckgo_search", content="[WEB_TOOL_ERROR] old fail"),
        AIMessage(content="Δεν το βρήκα."),
        HumanMessage(content="νέο query"),
        AIMessage(content="", tool_calls=[{"name": "duckduckgo_search", "args": {}, "id": "new_t"}]),
        ToolMessage(tool_call_id="new_t", name="duckduckgo_search", content="Επιτυχία! Βρήκα αποτελέσματα.")
    ]
    recent = filter_recent_web_tool_results(history)
    web_errors = [(n, t) for n, t in recent if looks_like_web_tool_error(t)]
    web_successes = [(n, t) for n, t in recent if not looks_like_web_tool_error(t)]
    
    assert len(web_errors) == 0
    assert len(web_successes) == 1


from core.agents import web_agent_node

def test_web_agent_node_overrides_hallucinated_answer_when_all_web_tools_fail(monkeypatch):
    class FakeBoundLLM:
        def invoke(self, messages):
            return AIMessage(content="Το Θέατρο Γης χωράει περίπου 4.300 άτομα")

    class FakeLLM:
        def bind_tools(self, tools):
            return FakeBoundLLM()

    monkeypatch.setattr("core.agents.llm", FakeLLM())
    monkeypatch.setattr("core.agents.load_agent_prompt", lambda *a, **k: "test prompt", raising=False)

    state = {
        "messages": [
            HumanMessage(content="Πόσα άτομα χωράει το Θέατρο Γης;"),
            AIMessage(content="", tool_calls=[{"name": "duckduckgo_search", "args": {}, "id": "t1"}]),
            ToolMessage(
                tool_call_id="t1",
                name="duckduckgo_search",
                content="[WEB_TOOL_ERROR][duckduckgo_search][reason=no_results] Η αναζήτηση απέτυχε."
            ),
        ],
        "channel": "telegram",
    }

    result = web_agent_node(state)
    reply = result["messages"][-1].content

    assert "4.300" not in reply
    assert "δεν θέλω να σου πω" in reply
    assert "αξιόπιστο αποτέλεσμα" in reply

def test_web_agent_node_does_not_override_when_one_web_tool_succeeds(monkeypatch):
    class FakeBoundLLM:
        def invoke(self, messages):
            return AIMessage(content="Το Θέατρο Γης χωράει περίπου 4.300 άτομα.")

    class FakeLLM:
        def bind_tools(self, tools):
            return FakeBoundLLM()

    monkeypatch.setattr("core.agents.llm", FakeLLM())
    monkeypatch.setattr("core.agents.load_agent_prompt", lambda *a, **k: "test prompt", raising=False)

    state = {
        "messages": [
            HumanMessage(content="Πόσα άτομα χωράει το Θέατρο Γης;"),
            AIMessage(content="", tool_calls=[
                {"name": "duckduckgo_search", "args": {}, "id": "t1"},
                {"name": "browse_url", "args": {}, "id": "t2"}
            ]),
            ToolMessage(
                tool_call_id="t1",
                name="duckduckgo_search",
                content="[WEB_TOOL_ERROR][duckduckgo_search][reason=no_results] Η αναζήτηση απέτυχε."
            ),
            ToolMessage(
                tool_call_id="t2",
                name="browse_url",
                content="Το θέατρο χωράει 4.300 άτομα."
            ),
        ],
        "channel": "telegram",
    }

    result = web_agent_node(state)
    reply = result["messages"][-1].content

    assert "4.300" in reply
    assert "δεν θέλω να σου πω" not in reply

def test_linkedin_terminal_result_detection():
    text = "SUCCESS: Το draft είναι έτοιμο και παρκαρισμένο. STOP calling tools and report to the user that the draft is ready for their approval."
    assert looks_like_terminal_linkedin_draft_result(text) is True


def test_linkedin_terminal_reply_builder():
    reply = build_linkedin_draft_ready_reply([
        "SUCCESS: Το draft είναι έτοιμο και παρκαρισμένο. STOP calling tools and report to the user that the draft is ready for their approval."
    ])
    assert "LinkedIn" in reply
    assert "Το αποθήκευσα" in reply
    assert "ανεβάσω" in reply


def test_web_agent_node_short_circuits_after_linkedin_draft_success(monkeypatch):
    class FakeBoundLLM:
        def invoke(self, messages):
            raise AssertionError("LLM should not run after terminal LinkedIn draft tool result")

    class FakeLLM:
        def bind_tools(self, tools):
            return FakeBoundLLM()

    monkeypatch.setattr("core.agents.llm", FakeLLM())

    state = {
        "messages": [
            HumanMessage(content="Γράψε post για το LinkedIn"),
            AIMessage(content="", tool_calls=[{"name": "update_pending_linkedin_post", "args": {}, "id": "t1"}]),
            ToolMessage(
                tool_call_id="t1",
                name="update_pending_linkedin_post",
                content="SUCCESS: Το draft είναι έτοιμο και παρκαρισμένο. STOP calling tools and report to the user that the draft is ready for their approval."
            ),
        ],
        "channel": "web",
    }

    result = web_agent_node(state)
    reply = result["messages"][-1].content

    assert "LinkedIn" in reply
    assert "Το αποθήκευσα" in reply


def test_web_agent_node_does_not_short_circuit_linkedin_reply_for_messenger_request(monkeypatch):
    from core.agents import web_agent_node

    class FakeBoundLLM:
        def invoke(self, messages):
            return AIMessage(content="Έτοιμο το προσχέδιο για Messenger.")

    class FakeLLM:
        def bind_tools(self, tools):
            return FakeBoundLLM()

    monkeypatch.setattr("core.agents.llm", FakeLLM())
    monkeypatch.setattr("core.agents.load_agent_prompt", lambda *a, **k: "test prompt", raising=False)

    state = {
        "messages": [
            HumanMessage(content="Φτιάξε νέο Messenger draft για τη Partner. Μόνο Messenger μήνυμα, όχι LinkedIn post."),
            AIMessage(content="", tool_calls=[{"name": "update_pending_linkedin_post", "args": {}, "id": "t1"}]),
            ToolMessage(
                tool_call_id="t1",
                name="update_pending_linkedin_post",
                content="SUCCESS: Το draft είναι έτοιμο και παρκαρισμένο. STOP calling tools and report to the user that the draft is ready for their approval."
            ),
        ],
        "channel": "telegram",
    }

    result = web_agent_node(state)
    reply = result["messages"][-1].content

    assert "Messenger" in reply
    assert "LinkedIn" not in reply


def test_should_attach_linkedin_reply_skips_messenger_turn():
    tool_results = [
        "SUCCESS: draft ready and parked. STOP calling tools and report to the user that the draft is ready for approval."
    ]
    assert should_attach_linkedin_draft_reply(
        "Messenger μηνύματα για τη Partner ετοίμασε όχι linkedin",
        tool_results,
        recent_linkedin_prompt_active=False,
    ) is False


def test_should_attach_linkedin_reply_allows_short_confirm_with_recent_context():
    tool_results = [
        "SUCCESS: draft ready and parked. STOP calling tools and report to the user that the draft is ready for approval."
    ]
    assert should_attach_linkedin_draft_reply(
        "Στείλε",
        tool_results,
        recent_linkedin_prompt_active=True,
    ) is True


def test_messenger_terminal_result_detection():
    text = "✅ DRAFT ΑΠΟΘΗΚΕΥΤΗΚΕ.\nmessage: Καλημέρα αγάπη μου"
    assert looks_like_terminal_messenger_draft_result(text) is True


def test_messenger_terminal_reply_builder():
    reply = build_messenger_draft_ready_reply([
        "✅ DRAFT ΑΠΟΘΗΚΕΥΤΗΚΕ.\nmessage: Καλημέρα αγάπη μου"
    ])
    assert "Το αποθήκευσα" in reply
    assert "στείλω" in reply
    assert "Καλημέρα αγάπη μου" in reply

def test_build_linkedin_draft_ready_reply_uses_real_draft_payload():
    import json
    from core.utils import build_linkedin_draft_ready_reply
    payload = {
        "status": "success",
        "kind": "linkedin_draft_saved",
        "draft_text": "Hello LinkedIn from Astakos",
        "photo_path": "C:/astakos_v2/outputs/test_image.jpg",
    }
    raw = "SUCCESS_JSON:" + json.dumps(payload, ensure_ascii=False)

    reply = build_linkedin_draft_ready_reply([raw])

    assert "Hello LinkedIn from Astakos" in reply
    assert "Το αποθήκευσα" in reply
    assert "ανεβάσω" in reply
    assert "[SEND_PHOTO: C:/astakos_v2/outputs/test_image.jpg]" in reply

def test_parse_linkedin_draft_result_detects_json_payload():
    import json
    from core.utils import looks_like_terminal_linkedin_draft_result
    payload = {
        "status": "success",
        "kind": "linkedin_draft_saved",
        "draft_text": "hello",
        "photo_path": "",
    }
    raw = "SUCCESS_JSON:" + json.dumps(payload, ensure_ascii=False)

    assert looks_like_terminal_linkedin_draft_result(raw) is True


def test_web_agent_returns_inactive_draft_reply_without_retrying_stale_send(monkeypatch, tmp_path):
    import config
    from core.agents import web_agent_node
    from langchain_core.messages import AIMessage, HumanMessage

    monkeypatch.setattr(
        config,
        "MESSENGER_DRAFT_FILE",
        str(tmp_path / "missing_messenger_draft.json"),
    )
    monkeypatch.setattr(
        "core.agents.load_agent_prompt",
        lambda *args, **kwargs: "test prompt",
        raising=False,
    )

    class FakeBoundLLM:
        def invoke(self, messages):
            return AIMessage(
                content="",
                tool_calls=[{
                    "name": "execute_local_pipeline",
                    "id": "stale-send",
                    "args": {},
                }],
            )

    class FakeLLM:
        def bind_tools(self, tools):
            return FakeBoundLLM()

        def invoke(self, messages):
            raise AssertionError("stale Messenger send must not retry the LLM")

    fake_llm = FakeLLM()
    monkeypatch.setattr("core.agents.llm", fake_llm)

    result = web_agent_node({
        "messages": [HumanMessage(content="Είμαστε έτοιμοι, βγαίνουμε για ποτό.")],
        "channel": "telegram",
    })

    reply = result["messages"][-1]
    assert reply.content == t("prompts.ext_str_14")
    assert not getattr(reply, "tool_calls", [])


def test_web_agent_retries_empty_synthesis_before_returning_to_user(monkeypatch):
    class FakeBoundLLM:
        def invoke(self, messages):
            return AIMessage(content="")

    class FakeLLM:
        def __init__(self):
            self.retry_calls = 0

        def bind_tools(self, tools):
            return FakeBoundLLM()

        def invoke(self, messages):
            self.retry_calls += 1
            return AIMessage(content="Βρήκα νωπό κοτόπουλο στον Μασούτη.")

    fake_llm = FakeLLM()
    monkeypatch.setattr("core.agents.llm", fake_llm)
    monkeypatch.setattr(
        "core.agents.load_agent_prompt",
        lambda *args, **kwargs: "test prompt",
        raising=False,
    )

    result = web_agent_node({
        "messages": [
            HumanMessage(content="Πού έχει νωπό κοτόπουλο;"),
            AIMessage(
                content="",
                tool_calls=[{"name": "search_supermarket_prices", "args": {}, "id": "t1"}],
            ),
            ToolMessage(
                tool_call_id="t1",
                name="search_supermarket_prices",
                content="RAW_TOOL_RESULT_MUST_NOT_REACH_USER",
            ),
        ],
        "channel": "web",
    })

    reply = result["messages"][-1].content

    assert fake_llm.retry_calls == 1
    assert reply
    assert reply != t("tools.web.empty_synthesis")
    assert "RAW_TOOL_RESULT_MUST_NOT_REACH_USER" not in reply


def test_web_agent_never_returns_raw_results_after_empty_retries(monkeypatch):
    class FakeBoundLLM:
        def invoke(self, messages):
            return AIMessage(content="")

    class FakeLLM:
        def __init__(self):
            self.retry_calls = 0

        def bind_tools(self, tools):
            return FakeBoundLLM()

        def invoke(self, messages):
            self.retry_calls += 1
            return AIMessage(content="")

    fake_llm = FakeLLM()
    monkeypatch.setattr("core.agents.llm", fake_llm)
    monkeypatch.setattr(
        "core.agents.load_agent_prompt",
        lambda *args, **kwargs: "test prompt",
        raising=False,
    )

    result = web_agent_node({
        "messages": [
            HumanMessage(content="Πού έχει νωπό κοτόπουλο;"),
            AIMessage(
                content="",
                tool_calls=[{"name": "search_supermarket_prices", "args": {}, "id": "t1"}],
            ),
            ToolMessage(
                tool_call_id="t1",
                name="search_supermarket_prices",
                content="RAW_TOOL_RESULT_MUST_NOT_REACH_USER",
            ),
        ],
        "channel": "web",
    })

    reply = result["messages"][-1].content

    assert fake_llm.retry_calls == 3
    assert reply == t("tools.web.empty_synthesis")
    assert result["messages"][-1]._astakos_phase_timings[
        "web_empty_synthesis_fallback"
    ] == 1
    assert "RAW_TOOL_RESULT_MUST_NOT_REACH_USER" not in reply


def test_web_agent_skips_empty_retries_when_all_web_tools_failed(monkeypatch):
    class FakeBoundLLM:
        def invoke(self, messages):
            return AIMessage(content="")

    class FakeLLM:
        def __init__(self):
            self.retry_calls = 0

        def bind_tools(self, tools):
            return FakeBoundLLM()

        def invoke(self, messages):
            self.retry_calls += 1
            return AIMessage(content="should not be used")

    fake_llm = FakeLLM()
    monkeypatch.setattr("core.agents.llm", fake_llm)
    monkeypatch.setattr(
        "core.agents.load_agent_prompt",
        lambda *args, **kwargs: "test prompt",
        raising=False,
    )

    result = web_agent_node({
        "messages": [
            HumanMessage(content="Πού έχει νωπό κοτόπουλο;"),
            AIMessage(
                content="",
                tool_calls=[{"name": "search_supermarket_prices", "args": {}, "id": "t1"}],
            ),
            ToolMessage(
                tool_call_id="t1",
                name="search_supermarket_prices",
                content="[WEB_TOOL_ERROR][search_supermarket_prices][reason=timeout]",
            ),
        ],
        "channel": "web",
    })

    assert fake_llm.retry_calls == 0
    assert result["messages"][-1].content != t("tools.web.empty_synthesis")


def test_web_research_budget_is_exhausted_after_three_generic_research_calls():
    from core.agents import _has_exhausted_web_research_budget

    history = [
        HumanMessage(content="Research this topic."),
        AIMessage(content="", tool_calls=[
            {"name": "duckduckgo_search", "args": {"query": "first"}, "id": "t1"},
        ]),
        ToolMessage(tool_call_id="t1", name="duckduckgo_search", content="first source"),
        AIMessage(content="", tool_calls=[
            {"name": "browse_url", "args": {"url": "https://example.com/1"}, "id": "t2"},
        ]),
        ToolMessage(tool_call_id="t2", name="browse_url", content="second source"),
        AIMessage(content="", tool_calls=[
            {"name": "duckduckgo_search", "args": {"query": "third"}, "id": "t3"},
        ]),
        ToolMessage(tool_call_id="t3", name="duckduckgo_search", content="third source"),
    ]

    assert _has_exhausted_web_research_budget(history) is True


def test_web_research_budget_ignores_non_research_tools():
    from core.agents import _has_exhausted_web_research_budget

    history = [
        HumanMessage(content="Find supermarket prices."),
        AIMessage(content="", tool_calls=[
            {"name": "search_supermarket_prices", "args": {"query": "chicken"}, "id": "t1"},
        ]),
        AIMessage(content="", tool_calls=[
            {"name": "search_supermarket_prices", "args": {"query": "milk"}, "id": "t2"},
        ]),
        AIMessage(content="", tool_calls=[
            {"name": "get_weather_forecast", "args": {}, "id": "t3"},
        ]),
    ]

    assert _has_exhausted_web_research_budget(history) is False


def test_web_agent_trims_parallel_research_calls_to_remaining_budget(monkeypatch):
    from core.agents import clean_orphan_tool_calls, web_agent_node

    class FakeBoundLLM:
        def invoke(self, messages):
            return AIMessage(
                content=[
                    {
                        "type": "function_call",
                        "name": "duckduckgo_search",
                        "args": {"query": "third"},
                        "id": "t3",
                    },
                    {
                        "type": "function_call",
                        "name": "browse_url",
                        "args": {"url": "https://example.com/2"},
                        "id": "t4",
                    },
                ],
                tool_calls=[
                    {
                        "name": "duckduckgo_search",
                        "args": {"query": "third"},
                        "id": "t3",
                    },
                    {
                        "name": "browse_url",
                        "args": {"url": "https://example.com/2"},
                        "id": "t4",
                    },
                ],
            )

    class FakeLLM:
        def __init__(self):
            self.bound_calls = 0

        def bind_tools(self, tools):
            self.bound_calls += 1
            return FakeBoundLLM()

        def invoke(self, messages):
            raise AssertionError("synthesis should not run before the budget is reached")

    monkeypatch.setattr("core.agents.llm", FakeLLM())
    monkeypatch.setattr(
        "core.utils.load_agent_prompt",
        lambda *args, **kwargs: "test prompt",
    )

    result = web_agent_node({
        "messages": [
            HumanMessage(content="Research this topic."),
            AIMessage(content="", tool_calls=[
                {
                    "name": "duckduckgo_search",
                    "args": {"query": "first"},
                    "id": "t1",
                },
            ]),
            ToolMessage(
                tool_call_id="t1",
                name="duckduckgo_search",
                content="first source",
            ),
            AIMessage(content="", tool_calls=[
                {
                    "name": "browse_url",
                    "args": {"url": "https://example.com/1"},
                    "id": "t2",
                },
            ]),
            ToolMessage(
                tool_call_id="t2",
                name="browse_url",
                content="second source",
            ),
        ],
        "channel": "web",
    })

    calls = result["messages"][-1].tool_calls

    assert [call["id"] for call in calls] == ["t3"]
    inline_ids = [
        part.get("id")
        for part in result["messages"][-1].content
        if isinstance(part, dict)
        and part.get("type") in ("function_call", "tool_use")
    ]
    assert inline_ids == ["t3"]

    cleaned = clean_orphan_tool_calls([
        result["messages"][-1],
        ToolMessage(
            tool_call_id="t3",
            name="duckduckgo_search",
            content="third source",
        ),
    ])

    assert len(cleaned) == 2
    assert cleaned[0].tool_calls == calls

def test_web_agent_synthesizes_without_tools_after_research_budget(monkeypatch):
    from core.agents import web_agent_node

    class FakeBoundLLM:
        def invoke(self, messages):
            return AIMessage(content="TOOL_PATH_MUST_NOT_RUN")

    class FakeLLM:
        def __init__(self):
            self.bound_calls = 0
            self.synthesis_calls = 0
            self.synthesis_messages = []

        def bind_tools(self, tools):
            self.bound_calls += 1
            return FakeBoundLLM()

        def invoke(self, messages):
            self.synthesis_calls += 1
            self.synthesis_messages.append(messages)
            return AIMessage(content="Research synthesis from verified sources.")

    fake_llm = FakeLLM()
    monkeypatch.setattr("core.agents.llm", fake_llm)
    loaded_prompt_names = []

    def fake_load_agent_prompt(name: str, *_args, **_kwargs) -> str:
        loaded_prompt_names.append(name)
        return {
            "Web_Agent": "test prompt",
            "Web_Research_Synthesis": "[TEST RESEARCH SYNTHESIS CONTRACT]",
        }.get(name, "")

    monkeypatch.setattr(
        "core.utils.load_agent_prompt",
        fake_load_agent_prompt,
    )

    result = web_agent_node({
        "messages": [
            HumanMessage(content="Research this topic."),
            AIMessage(content="", tool_calls=[
                {"name": "duckduckgo_search", "args": {"query": "first"}, "id": "t1"},
            ]),
            ToolMessage(tool_call_id="t1", name="duckduckgo_search", content="first source"),
            AIMessage(content="", tool_calls=[
                {"name": "browse_url", "args": {"url": "https://example.com/1"}, "id": "t2"},
            ]),
            ToolMessage(tool_call_id="t2", name="browse_url", content="second source"),
            AIMessage(content="", tool_calls=[
                {"name": "duckduckgo_search", "args": {"query": "third"}, "id": "t3"},
            ]),
            ToolMessage(tool_call_id="t3", name="duckduckgo_search", content="third source"),
        ],
        "channel": "web",
    })

    reply = result["messages"][-1].content

    assert fake_llm.bound_calls == 0
    assert fake_llm.synthesis_calls == 1
    assert reply == "Research synthesis from verified sources."
    assert "TOOL_PATH_MUST_NOT_RUN" not in reply
    assert "Web_Research_Synthesis" in loaded_prompt_names
    synthesis_system_messages = [
        message.content
        for message in fake_llm.synthesis_messages[0]
        if getattr(message, "type", "") == "system"
    ]
    assert any(
        "[TEST RESEARCH SYNTHESIS CONTRACT]" in content
        for content in synthesis_system_messages
    )


def test_web_research_budget_resets_for_a_new_user_turn():
    from core.agents import _has_exhausted_web_research_budget

    history = [
        HumanMessage(content="Research the first topic."),
        AIMessage(content="", tool_calls=[
            {"name": "duckduckgo_search", "args": {"query": "first"}, "id": "t1"},
        ]),
        AIMessage(content="", tool_calls=[
            {"name": "browse_url", "args": {"url": "https://example.com/1"}, "id": "t2"},
        ]),
        AIMessage(content="", tool_calls=[
            {"name": "duckduckgo_search", "args": {"query": "third"}, "id": "t3"},
        ]),
        HumanMessage(content="Research a new topic."),
    ]

    assert _has_exhausted_web_research_budget(history) is False


def test_web_research_trim_supports_object_calls_without_model_copy():
    from core.agents import _trim_web_research_tool_calls

    class ToolCall:
        def __init__(self, name, call_id):
            self.name = name
            self.id = call_id

    class LegacyResponse:
        def __init__(self):
            self.content = []
            self.tool_calls = [
                ToolCall("duckduckgo_search", "t3"),
                ToolCall("browse_url", "t4"),
            ]

    history = [
        HumanMessage(content="Research this topic."),
        AIMessage(content="", tool_calls=[
            {"name": "duckduckgo_search", "args": {}, "id": "t1"},
        ]),
        AIMessage(content="", tool_calls=[
            {"name": "browse_url", "args": {}, "id": "t2"},
        ]),
    ]

    response = LegacyResponse()
    trimmed = _trim_web_research_tool_calls(response, history)

    assert trimmed is not response
    assert [call.id for call in trimmed.tool_calls] == ["t3"]


def test_web_agent_hides_messenger_draft_tool_for_ordinary_turn(monkeypatch: Any) -> None:
    """An ordinary Web turn cannot create a Messenger draft from conversational context."""
    from core.agents import web_agent_node

    bound_tool_names: list[str] = []

    class FakeBoundLLM:
        """Return a plain reply without issuing tool calls."""

        def invoke(self, messages: Any) -> AIMessage:
            """Return a deterministic assistant response for the bound tool set."""
            return AIMessage(content="plain reply")

    class FakeLLM:
        """Capture the tools exposed to the Web agent."""

        def bind_tools(self, tools: list[Any]) -> FakeBoundLLM:
            """Record the tool names and return the deterministic bound model."""
            bound_tool_names.extend(tool.name for tool in tools)
            return FakeBoundLLM()

    monkeypatch.setattr("core.agents.llm", FakeLLM())
    monkeypatch.setattr("core.agents.load_agent_prompt", lambda *_args: "test prompt")

    web_agent_node({
        "messages": [HumanMessage(content="Ο Πασσιάς έχει και κρέας εκτός από αλλαντικά.")],
        "channel": "telegram",
    })

    assert "relay_local_payload" not in bound_tool_names


def test_web_agent_exposes_messenger_draft_tool_for_explicit_request(monkeypatch: Any) -> None:
    """A direct request to compose a message retains the Messenger draft flow."""
    from core.agents import web_agent_node

    bound_tool_names: list[str] = []

    class FakeBoundLLM:
        """Return a plain reply without issuing tool calls."""

        def invoke(self, messages: Any) -> AIMessage:
            """Return a deterministic assistant response for the bound tool set."""
            return AIMessage(content="plain reply")

    class FakeLLM:
        """Capture the tools exposed to the Web agent."""

        def bind_tools(self, tools: list[Any]) -> FakeBoundLLM:
            """Record the tool names and return the deterministic bound model."""
            bound_tool_names.extend(tool.name for tool in tools)
            return FakeBoundLLM()

    monkeypatch.setattr("core.agents.llm", FakeLLM())
    monkeypatch.setattr("core.agents.load_agent_prompt", lambda *_args: "test prompt")

    web_agent_node({
        "messages": [HumanMessage(content="Γράψε ένα μήνυμα στη Σοφία.")],
        "channel": "telegram",
    })

    assert "relay_local_payload" in bound_tool_names
    assert "execute_local_pipeline" not in bound_tool_names


def test_web_agent_exposes_messenger_draft_tool_for_accepted_routine_offer(monkeypatch: Any) -> None:
    """A trusted accepted routine offer allows drafting after a bare affirmative."""
    from core.agents import web_agent_node
    from services.messenger_intent import MESSENGER_ROUTINE_DRAFT_OFFER_MARKER

    bound_tool_names: list[str] = []

    class FakeBoundLLM:
        """Return a plain reply without issuing tool calls."""

        def invoke(self, messages: Any) -> AIMessage:
            """Return a deterministic assistant response for the bound tool set."""
            return AIMessage(content="plain reply")

    class FakeLLM:
        """Capture the tools exposed to the Web agent."""

        def bind_tools(self, tools: list[Any]) -> FakeBoundLLM:
            """Record the tool names and return the deterministic bound model."""
            bound_tool_names.extend(tool.name for tool in tools)
            return FakeBoundLLM()

    monkeypatch.setattr("core.agents.llm", FakeLLM())
    monkeypatch.setattr("core.agents.load_agent_prompt", lambda *_args: "test prompt")

    web_agent_node({
        "messages": [
            SystemMessage(content=MESSENGER_ROUTINE_DRAFT_OFFER_MARKER),
            HumanMessage(content="ναι"),
        ],
        "channel": "telegram",
    })

    assert "relay_local_payload" in bound_tool_names
    assert "execute_local_pipeline" not in bound_tool_names


def test_web_agent_exposes_messenger_draft_tool_for_active_draft_edit(monkeypatch: Any) -> None:
    """An active draft keeps the persistence tool available for a natural edit request."""
    from core.agents import web_agent_node

    bound_tool_names: list[str] = []

    class FakeBoundLLM:
        """Return a plain reply without issuing tool calls."""

        def invoke(self, messages: Any) -> AIMessage:
            """Return a deterministic assistant response for the bound tool set."""
            return AIMessage(content="plain reply")

    class FakeLLM:
        """Capture the tools exposed to the Web agent."""

        def bind_tools(self, tools: list[Any]) -> FakeBoundLLM:
            """Record the tool names and return the deterministic bound model."""
            bound_tool_names.extend(tool.name for tool in tools)
            return FakeBoundLLM()

    monkeypatch.setattr("core.agents.llm", FakeLLM())
    monkeypatch.setattr("core.agents.load_agent_prompt", lambda *_args: "test prompt")
    monkeypatch.setattr(
        "core.messenger_draft.active_draft_status",
        lambda: (True, "active", {"message": "Initial draft"}),
    )

    web_agent_node({
        "messages": [
            HumanMessage(content="Γράψε ένα μήνυμα"),
            AIMessage(
                content=(
                    "Έτοιμο το προσχέδιο, μάστορα:\n\n"
                    "«Initial draft»\n\n"
                    "Το αποθήκευσα. Θέλεις αλλαγές ή να το στείλω;"
                ),
            ),
            HumanMessage(content="Κάν' το πιο ζεστό."),
        ],
        "channel": "telegram",
    })

    assert "relay_local_payload" in bound_tool_names


def test_web_agent_hides_messenger_draft_tool_for_unrelated_active_draft_turn(monkeypatch: Any) -> None:
    """An active draft must not expose persistence during unrelated conversation."""
    from core.agents import web_agent_node

    bound_tool_names: list[str] = []

    class FakeBoundLLM:
        """Return a plain reply without issuing tool calls."""

        def invoke(self, messages: Any) -> AIMessage:
            """Return a deterministic assistant response for the bound tool set."""
            return AIMessage(content="plain reply")

    class FakeLLM:
        """Capture the tools exposed to the Web agent."""

        def bind_tools(self, tools: list[Any]) -> FakeBoundLLM:
            """Record the tool names and return the deterministic bound model."""
            bound_tool_names.extend(tool.name for tool in tools)
            return FakeBoundLLM()

    monkeypatch.setattr("core.agents.llm", FakeLLM())
    monkeypatch.setattr("core.agents.load_agent_prompt", lambda *_args: "test prompt")
    monkeypatch.setattr(
        "core.messenger_draft.active_draft_status",
        lambda: (True, "active", {"message": "Initial draft"}),
    )

    web_agent_node({
        "messages": [HumanMessage(content="Σε τρεις μέρες φεύγουμε Γεωργία")],
        "channel": "web",
    })

    assert "relay_local_payload" not in bound_tool_names


def test_chat_agent_hides_messenger_draft_tool_for_unrelated_active_draft_turn(monkeypatch: Any) -> None:
    """Chat routing cannot expose draft persistence for unrelated active-draft text."""
    from core.agents import chat_agent_node

    bound_tool_names: list[str] = []

    class FakeBoundLLM:
        """Return a plain reply without issuing tool calls."""

        def invoke(self, messages: Any) -> AIMessage:
            """Return a deterministic assistant response for the bound tool set."""
            return AIMessage(content="plain reply")

    class FakeLLM:
        """Capture the tools exposed to the Chat agent."""

        def bind_tools(self, tools: list[Any]) -> FakeBoundLLM:
            """Record the tool names and return the deterministic bound model."""
            bound_tool_names.extend(tool.name for tool in tools)
            return FakeBoundLLM()

    monkeypatch.setattr("core.agents.llm", FakeLLM())
    monkeypatch.setattr("core.agents.load_agent_prompt", lambda *_args: "test prompt")
    monkeypatch.setattr(
        "core.messenger_draft.active_draft_status",
        lambda: (True, "active", {"message": "Initial draft"}),
    )

    chat_agent_node({
        "messages": [HumanMessage(content="Σε τρεις μέρες φεύγουμε Γεωργία")],
        "channel": "web",
    })

    assert "relay_local_payload" not in bound_tool_names


def test_chat_agent_hides_direct_memory_write_for_external_context(monkeypatch: Any) -> None:
    """A trusted user update must not issue a direct write from tainted context."""
    from core.agents import chat_agent_node
    from core.untrusted_content import external_content_history_metadata

    bound_tool_names: list[str] = []

    class FakeBoundLLM:
        """Return a plain reply without issuing tool calls."""

        def invoke(self, messages: Any) -> AIMessage:
            """Return a deterministic assistant response for the bound tool set."""
            return AIMessage(content="plain reply")

    class FakeLLM:
        """Capture the tools exposed to the Chat agent."""

        def bind_tools(self, tools: list[Any]) -> FakeBoundLLM:
            """Record the tool names and return the deterministic bound model."""
            bound_tool_names.extend(tool.name for tool in tools)
            return FakeBoundLLM()

    monkeypatch.setattr("core.agents.llm", FakeLLM())
    monkeypatch.setattr("core.agents.load_agent_prompt", lambda *_args: "test prompt")

    chat_agent_node({
        "messages": [
            AIMessage(
                content="External summary.",
                additional_kwargs=external_content_history_metadata(["browse_url"]),
            ),
            HumanMessage(content="Σε τρεις μέρες φεύγουμε Γεωργία"),
        ],
        "channel": "web",
    })

    assert "save_to_memory" not in bound_tool_names


def test_chat_agent_hides_stale_research_tools_for_unrelated_new_turn(
    monkeypatch: Any,
) -> None:
    """A home update must not re-run an older Web research request."""
    from core.agents import chat_agent_node
    from core.untrusted_content import external_content_history_metadata

    bound_tool_names: list[str] = []

    class FakeBoundLLM:
        """Return a plain reply without issuing tool calls."""

        def invoke(self, messages: Any) -> AIMessage:
            """Return a deterministic assistant response for the bound tool set."""
            return AIMessage(content="plain reply")

    class FakeLLM:
        """Capture the tools exposed to the Chat agent."""

        def bind_tools(self, tools: list[Any]) -> FakeBoundLLM:
            """Record the tool names and return the deterministic bound model."""
            bound_tool_names.extend(tool.name for tool in tools)
            return FakeBoundLLM()

    monkeypatch.setattr("core.agents.llm", FakeLLM())
    monkeypatch.setattr("core.agents.load_agent_prompt", lambda *_args: "test prompt")

    chat_agent_node({
        "messages": [
            HumanMessage(content="Τι καιρό θα έχει στο Rustavi;"),
            AIMessage(
                content="External weather summary.",
                additional_kwargs=external_content_history_metadata(["get_weather_forecast"]),
            ),
            HumanMessage(content="Γύρισα σπίτι φίλε."),
        ],
        "channel": "telegram",
    })

    assert "duckduckgo_search" not in bound_tool_names
    assert "search_supermarket_prices" not in bound_tool_names


def test_chat_agent_keeps_research_tools_for_current_direct_web_request(
    monkeypatch: Any,
) -> None:
    """A current direct Web request may still use research tools."""
    from core.agents import chat_agent_node
    from core.untrusted_content import external_content_history_metadata

    bound_tool_names: list[str] = []

    class FakeBoundLLM:
        """Return a plain reply without issuing tool calls."""

        def invoke(self, messages: Any) -> AIMessage:
            """Return a deterministic assistant response for the bound tool set."""
            return AIMessage(content="plain reply")

    class FakeLLM:
        """Capture the tools exposed to the Chat agent."""

        def bind_tools(self, tools: list[Any]) -> FakeBoundLLM:
            """Record the tool names and return the deterministic bound model."""
            bound_tool_names.extend(tool.name for tool in tools)
            return FakeBoundLLM()

    monkeypatch.setattr("core.agents.llm", FakeLLM())
    monkeypatch.setattr("core.agents.load_agent_prompt", lambda *_args: "test prompt")

    chat_agent_node({
        "messages": [
            HumanMessage(content="Τι καιρό θα έχει στο Rustavi;"),
            AIMessage(
                content="External weather summary.",
                additional_kwargs=external_content_history_metadata(["get_weather_forecast"]),
            ),
            HumanMessage(content="Ψάξε στο web τι καιρό θα έχει στη Γεωργία."),
        ],
        "channel": "telegram",
    })

    assert "duckduckgo_search" in bound_tool_names
    assert "search_supermarket_prices" in bound_tool_names


def test_chat_agent_keeps_explicit_memory_save_for_external_context(
    monkeypatch: Any,
) -> None:
    """An explicit save request must reach the provenance-aware approval path."""
    from core.agents import chat_agent_node
    from core.untrusted_content import external_content_history_metadata

    bound_tool_names: list[str] = []

    class FakeBoundLLM:
        """Return a plain reply without issuing tool calls."""

        def invoke(self, messages: Any) -> AIMessage:
            """Return a deterministic assistant response for the bound tool set."""
            return AIMessage(content="plain reply")

    class FakeLLM:
        """Capture the tools exposed to the Chat agent."""

        def bind_tools(self, tools: list[Any]) -> FakeBoundLLM:
            """Record the tool names and return the deterministic bound model."""
            bound_tool_names.extend(tool.name for tool in tools)
            return FakeBoundLLM()

    monkeypatch.setattr("core.agents.llm", FakeLLM())
    monkeypatch.setattr("core.agents.load_agent_prompt", lambda *_args: "test prompt")

    chat_agent_node({
        "messages": [
            AIMessage(
                content="External deadline summary.",
                additional_kwargs=external_content_history_metadata(["browse_url"]),
            ),
            HumanMessage(content="Save that deadline to my memory."),
        ],
        "channel": "web",
    })

    assert "save_to_memory" in bound_tool_names


def test_chat_agent_ignores_routine_tool_text_for_messenger_draft_gate(
    monkeypatch: Any,
) -> None:
    """Routine-search output mentioning a message must not authorize a draft."""
    from core.agents import chat_agent_node

    bound_tool_names: list[str] = []

    class FakeBoundLLM:
        """Return a plain reply without issuing tool calls."""

        def invoke(self, messages: Any) -> AIMessage:
            """Return a deterministic assistant response for the bound tool set."""
            return AIMessage(content="plain reply")

    class FakeLLM:
        """Capture the tools exposed to the Chat agent."""

        def bind_tools(self, tools: list[Any]) -> FakeBoundLLM:
            """Record the tool names and return the deterministic bound model."""
            bound_tool_names.extend(tool.name for tool in tools)
            return FakeBoundLLM()

    monkeypatch.setattr("core.agents.llm", FakeLLM())
    monkeypatch.setattr("core.agents.load_agent_prompt", lambda *_args: "test prompt")

    chat_agent_node({
        "messages": [
            HumanMessage(content="Σε τρεις μέρες φεύγουμε Γεωργία."),
            AIMessage(
                content="",
                tool_calls=[{
                    "name": "search_routines",
                    "args": {"query": "*"},
                    "id": "routine-search",
                }],
            ),
            ToolMessage(
                content="11:00 — Σύνταξη πρωινού μηνύματος στη Σοφία στο Messenger",
                name="search_routines",
                tool_call_id="routine-search",
            ),
        ],
        "channel": "web",
    })

    assert "relay_local_payload" not in bound_tool_names


def test_proactive_prompt_requires_message_routines_to_request_draft_first() -> None:
    """Message routines must ask before generating a Messenger draft or message body."""
    prompt_path = Path(__file__).resolve().parents[1] / "prompts" / "telegram_bot_craft_proactive.md"
    prompt = prompt_path.read_text(encoding="utf-8")

    assert re.search(
        r"routine.*(?:composing|sending).*message.*ask whether.*draft first",
        prompt,
        flags=re.IGNORECASE,
    )
    assert re.search(
        r"Do not generate.*message text.*until the user explicitly asks",
        prompt,
        flags=re.IGNORECASE,
    )
