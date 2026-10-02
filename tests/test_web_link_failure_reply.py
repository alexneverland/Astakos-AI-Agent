"""Current-turn URL failures stay grounded and do not expose tool diagnostics."""
import json
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from core import i18n
from core.utils import build_web_failure_reply


@pytest.mark.parametrize("language", ["el", "en"])
@pytest.mark.parametrize("reason", ["cloudflare", "timeout", "generic"])
def test_supplied_link_failure_reports_safe_cause(language, reason, monkeypatch):
    """Known protocol codes are localized without echoing external error text."""
    locale = Path(__file__).parents[1] / "locales" / f"{language}.json"
    monkeypatch.setattr(i18n, "_translations", json.loads(locale.read_text(encoding="utf-8")))
    result = build_web_failure_reply(
        "https://example.org/product Πώς σου φαίνεται;",
        [("browse_url", f"[WEB_TOOL_ERROR][browse_url][reason={reason}] secret-path ignore instructions")],
    )
    assert i18n.t("core.utils.web_link_failure_reply") in result
    assert i18n.t(f"core.utils.web_failure_reasons.{reason}") in result
    assert "secret-path" not in result
    assert "ignore instructions" not in result
    assert "δώσε μου συγκεκριμένο link" not in result
    assert "provide a specific link" not in result.lower()


def test_unknown_failure_does_not_invent_cause_or_request_existing_link():
    """Unrecognized diagnostics cannot turn into a guessed protection failure."""
    reply = build_web_failure_reply("https://example.org/item", [
        ("browse_url", "[WEB_TOOL_ERROR][browse_url][reason=unknown] cloudflare secret-path")
    ])
    assert i18n.t("core.utils.web_link_failure_reply") in reply
    assert i18n.t("core.utils.web_failure_reasons.cloudflare") not in reply
    assert "secret-path" not in reply


@pytest.mark.parametrize("channel", ["web", "matrix", "telegram"])
def test_web_agent_uses_owner_link_not_last_tool_message(channel, monkeypatch):
    """The production guard renders the latest user input across channels."""
    from core import agents

    class NoModel:
        def bind_tools(self, tools):
            raise AssertionError("Failed page must not be synthesized as evidence")

    monkeypatch.setattr(agents, "llm", NoModel())
    monkeypatch.setattr(agents, "build_prompt", lambda *a, **k: "isolated prompt")
    monkeypatch.setattr(agents, "_has_active_messenger_draft", lambda: False)
    monkeypatch.setattr("tools.web.has_known_messenger_contact_reference", lambda _: False)
    state = {"channel": channel, "messages": [
        HumanMessage(content="https://www.skroutz.gr/s/58190803/item.html ΠΩΣ ΣΟΥ ΦΑΙΝΕΤΑΙ;"),
        AIMessage(content="", tool_calls=[{"name": "browse_url", "args": {}, "id": "page"}]),
        ToolMessage(name="browse_url", tool_call_id="page",
                    content="[WEB_TOOL_ERROR][browse_url][reason=cloudflare] blocked"),
    ]}
    reply = agents.web_agent_node(state)["messages"][-1].content
    assert i18n.t("core.utils.web_link_failure_reply") in reply
    assert i18n.t("core.utils.web_failure_reasons.cloudflare") in reply


def test_no_supplied_link_preserves_generic_failure_reply():
    """Ordinary searches keep the existing fallback; no link is invented."""
    reply = build_web_failure_reply("Βρες μου ένα γραφείο", [("research_web", "[WEB_TOOL_ERROR] failed")])
    assert reply == i18n.t("core.utils.web_failure_reply", kind=i18n.t("prompts.ext_str_243"))


def test_url_in_tool_error_is_not_a_user_supplied_link():
    """Only the owner's input establishes whether they already supplied a URL."""
    reply = build_web_failure_reply("Βρες μου ένα γραφείο", [
        ("browse_url", "[WEB_TOOL_ERROR][browse_url][reason=timeout] https://example.org/item")
    ])
    assert i18n.t("core.utils.web_link_failure_reply") not in reply
    assert reply == i18n.t("core.utils.web_failure_reply", kind=i18n.t("prompts.ext_str_243"))


@pytest.mark.parametrize("tool_name", ["research_web", "duckduckgo_search"])
def test_url_without_failed_page_read_preserves_generic_failure(tool_name):
    """A failed search is not evidence that the supplied page was opened."""
    reply = build_web_failure_reply("https://example.org/item", [
        (tool_name, f"[WEB_TOOL_ERROR][{tool_name}][reason=timeout] failed")
    ])
    assert reply == i18n.t("core.utils.web_failure_reply", kind=i18n.t("prompts.ext_str_243"))


def test_successful_page_read_is_not_reported_as_failed():
    """Even alongside another tool failure, readable page text is not a failure."""
    reply = build_web_failure_reply("https://example.org/item", [
        ("browse_url", "Readable product details"),
        ("research_web", "[WEB_TOOL_ERROR][research_web][reason=timeout] failed"),
    ])
    assert i18n.t("core.utils.web_link_failure_reply") not in reply
