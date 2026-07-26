"""Regression coverage for historical capability-memory presentation."""

from collections.abc import Iterator
from unittest.mock import MagicMock, patch

import pytest

import core.i18n
from core.i18n import load_locale, t
from core.utils import build_prompt, load_agent_prompt


class MockMessage:
    """Minimal message object accepted by the prompt builder."""

    def __init__(self, content: str) -> None:
        self.content = content


@pytest.fixture(autouse=True)
def restore_locale() -> Iterator[None]:
    """Restore the active locale after each prompt assertion."""
    original_locale = core.i18n.LANG
    yield
    load_locale(original_locale)


def test_prompt_includes_draft_verification_rule_for_historical_memory() -> None:
    """Require a current verification before agents claim a draft exists."""
    load_locale("en")
    with patch("memory.context_builder.build_memory_context") as build_memory_context:
        context = MagicMock()
        context.render.return_value = "[CAPABILITY] Historical world-time draft"
        build_memory_context.return_value = context

        prompt = build_prompt(state_messages=[MockMessage("hello")], agent_role="Chat_Agent")

    assert "[CAPABILITY]" in prompt
    assert t("core.approval.draft_verification_rule") in prompt


def test_dev_prompt_requires_prefix_and_no_tools_during_proposal() -> None:
    """Keep the capability proposal turn deterministic and non-executing."""
    load_locale("en")
    prompt = build_prompt(state_messages=[MockMessage("hello")], agent_role="Dev_Agent")

    dev_prompt = load_agent_prompt("Dev_Agent")
    assert "You MUST start your response EXACTLY with the localized proposal prefix" in dev_prompt
    assert "CRITICAL: You must NOT call ANY tools during this proposal turn." in prompt
