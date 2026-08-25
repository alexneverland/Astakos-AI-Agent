"""Offline tests for independent semantic-memory provider selection."""

from __future__ import annotations

import sys

import pytest

from core.ai_provider import (
    EmbeddingsProviderSetupRequired,
    LocalE5EmbeddingsAdapter,
    OpenAIAdapter,
    get_embeddings_adapter,
    resolve_embeddings_provider,
)


class TestEmbeddingsProviderResolution:
    """Ensure chat and embeddings providers remain independently selectable."""

    def test_auto_uses_vertex_when_vertex_is_the_chat_provider(self) -> None:
        assert resolve_embeddings_provider("auto", "vertex") == "vertex"

    def test_explicit_openai_embeddings_can_be_used_with_anthropic_chat(self) -> None:
        assert resolve_embeddings_provider("openai", "anthropic") == "openai"

    def test_auto_anthropic_never_silently_falls_back(self) -> None:
        with pytest.raises(EmbeddingsProviderSetupRequired, match="Semantic memory needs an embeddings provider"):
            resolve_embeddings_provider("auto", "anthropic")

    def test_unknown_provider_has_a_clear_setup_error(self) -> None:
        with pytest.raises(EmbeddingsProviderSetupRequired, match="Unknown embeddings provider"):
            resolve_embeddings_provider("unknown", "vertex")

    def test_factory_returns_explicit_native_embeddings_provider(self) -> None:
        adapter = get_embeddings_adapter("openai", api_key="test-key")
        assert isinstance(adapter, OpenAIAdapter)

    def test_local_backend_does_not_install_or_download_missing_dependencies(self, monkeypatch) -> None:
        monkeypatch.setitem(sys.modules, "sentence_transformers", None)
        adapter = LocalE5EmbeddingsAdapter()

        with pytest.raises(EmbeddingsProviderSetupRequired, match="not installed"):
            adapter.embed_text("δοκιμή", is_query=True)
