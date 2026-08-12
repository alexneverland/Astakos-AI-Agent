"""Regression coverage for navigation ETA requests and web-search failures."""

from collections.abc import Iterator

import pytest

import core.i18n
from core.capability_lookup import lookup_agent, reload_registry
from core.i18n import load_locale, t
from core.utils import load_agent_prompt


@pytest.fixture(autouse=True)
def restore_locale() -> Iterator[None]:
    """Restore the configured locale after each assertion."""
    original_locale = core.i18n.LANG
    yield
    load_locale(original_locale)


def test_eta_question_routes_to_web_agent() -> None:
    """Route a direct arrival-time question to the navigation-capable agent."""
    reload_registry()

    assert lookup_agent("Σε πόση ώρα φτάνουμε στο χωριό;") == "Web_Agent"


def test_short_arrival_follow_up_routes_to_web_agent() -> None:
    """Keep the user's natural arrival follow-up on the navigation path."""
    reload_registry()

    assert lookup_agent("Φτάνουμε, για δες.") == "Web_Agent"


def test_plain_arrival_statement_does_not_force_navigation() -> None:
    """Keep an ordinary arrival update in normal conversation routing."""
    reload_registry()

    assert lookup_agent("Φτάνουμε σπίτι.") is None


def test_web_prompt_prioritizes_navigation_for_eta_questions() -> None:
    """Keep ETA and distance requests on the native navigation path."""
    prompt = load_agent_prompt("Web_Agent")

    assert "[NAVIGATION PRIORITY]" in prompt
    assert "get_navigation_info" in prompt
    assert "φτάνουμε, για δες" in prompt


@pytest.mark.parametrize("locale", ["el", "en"])
def test_search_failure_payload_is_descriptive_not_an_instruction(locale: str) -> None:
    """Do not put tool-control directives inside untrusted search failures."""
    load_locale(locale)

    message = t("tools.web.search_all_failed", last_error="timeout", count=2)

    assert "WEB_TOOL_ERROR" in message
    assert "ΜΗΝ ξαναδοκιμάσεις" not in message
    assert "ενημέρωσε τον χρήστη" not in message
