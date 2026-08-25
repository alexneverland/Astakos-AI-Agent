"""Regression coverage for historical capability-memory presentation."""

from collections.abc import Iterator
from unittest.mock import MagicMock, patch

import pytest

import core.i18n
import core.utils as utils
from core.ai_provider import EmbeddingsProviderSetupRequired, ProviderAuthError
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


def test_prompt_surfaces_embeddings_setup_once_without_blocking_chat(monkeypatch) -> None:
    """Provider setup failures become one clear user-facing prompt status."""
    utils._embedding_setup_notifications.clear()
    setup_error = EmbeddingsProviderSetupRequired(
        "Configure an embeddings provider.",
        provider="anthropic",
    )
    monkeypatch.setattr(
        "memory.context_builder.build_memory_context",
        MagicMock(side_effect=setup_error),
    )

    first_prompt = build_prompt(
        state_messages=[MockMessage("Πες μου κάτι χρήσιμο")],
        agent_role="Chat_Agent",
        channel="telegram",
    )
    second_prompt = build_prompt(
        state_messages=[MockMessage("Πες μου κάτι χρήσιμο")],
        agent_role="Chat_Agent",
        channel="telegram",
    )

    assert "SEMANTIC MEMORY SETUP REQUIRED" in first_prompt
    assert "Configure an embeddings provider." in first_prompt
    assert "SEMANTIC MEMORY SETUP REQUIRED" not in second_prompt


def test_prompt_surfaces_embeddings_authentication_once_without_blocking_chat(monkeypatch) -> None:
    """Invalid embeddings credentials get one clear status instead of a silent empty search."""
    utils._embedding_setup_notifications.clear()
    auth_error = ProviderAuthError("openai", "OPENAI_API_KEY is not configured.")
    monkeypatch.setattr(
        "memory.context_builder.build_memory_context",
        MagicMock(side_effect=auth_error),
    )

    first_prompt = build_prompt(
        state_messages=[MockMessage("Πες μου κάτι χρήσιμο")],
        agent_role="Chat_Agent",
        channel="telegram",
    )
    second_prompt = build_prompt(
        state_messages=[MockMessage("Πες μου κάτι χρήσιμο")],
        agent_role="Chat_Agent",
        channel="telegram",
    )

    assert "SEMANTIC MEMORY AUTHENTICATION REQUIRED" in first_prompt
    assert "OPENAI_API_KEY is not configured." in first_prompt
    assert "SEMANTIC MEMORY AUTHENTICATION REQUIRED" not in second_prompt
