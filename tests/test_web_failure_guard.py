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
from langchain_core.messages import HumanMessage, ToolMessage, AIMessage

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
    assert "αποθήκευσα" in reply
    assert "Θέλεις αλλαγές ή να το ανεβάσω;" in reply


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
    assert "αποθήκευσα" in reply


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
            HumanMessage(content="Φτιάξε νέο Messenger draft για τη Σοφία. Μόνο Messenger μήνυμα, όχι LinkedIn post."),
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
        "Messenger μηνύματα για τη Σοφία ετοίμασε όχι linkedin",
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
    assert "Το αποθήκευσα." in reply
    assert "να το στείλω" in reply
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
    assert "Το αποθήκευσα. Θέλεις αλλαγές ή να το ανεβάσω;" in reply
    assert "[CREATED_FILE: C:/astakos_v2/outputs/test_image.jpg]" in reply

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
