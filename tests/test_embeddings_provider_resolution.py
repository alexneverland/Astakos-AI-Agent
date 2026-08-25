"""Offline tests for independent semantic-memory provider selection."""

from __future__ import annotations

import sys

import pytest

from core.ai_provider import (
    EmbeddingsProviderSetupRequired,
    LocalE5EmbeddingsAdapter,
    OpenAIAdapter,
    build_embeddings_cache_key,
    get_embeddings_backend_identity,
    get_embeddings_adapter,
    get_embeddings_collection_name,
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

    def test_vertex_keeps_legacy_collection_and_other_backends_are_isolated(self) -> None:
        assert get_embeddings_backend_identity("vertex") == "vertex:text-embedding-004"
        assert get_embeddings_collection_name("vertex") == "astakos_long_term"
        assert get_embeddings_collection_name("openai") != "astakos_long_term"
        assert get_embeddings_collection_name("openai") == get_embeddings_collection_name("openai")

    def test_cache_key_isolated_by_backend_and_embedding_role(self) -> None:
        vertex_query = build_embeddings_cache_key("vertex:text-embedding-004", "query", "same text")
        vertex_document = build_embeddings_cache_key("vertex:text-embedding-004", "document", "same text")
        openai_query = build_embeddings_cache_key("openai:text-embedding-3-small", "query", "same text")

        assert vertex_query != vertex_document
        assert vertex_query != openai_query

    def test_local_backend_does_not_install_or_download_missing_dependencies(self, monkeypatch) -> None:
        monkeypatch.setitem(sys.modules, "sentence_transformers", None)
        adapter = LocalE5EmbeddingsAdapter()

        with pytest.raises(EmbeddingsProviderSetupRequired, match="not installed"):
            adapter.embed_text("δοκιμή", is_query=True)

    def test_local_initialization_errors_keep_their_actual_cause(self, monkeypatch) -> None:
        class _BrokenSentenceTransformer:
            def __init__(self, *args, **kwargs) -> None:
                raise RuntimeError("corrupt local model")

        fake_module = type("_Module", (), {"SentenceTransformer": _BrokenSentenceTransformer})
        monkeypatch.setitem(sys.modules, "sentence_transformers", fake_module)

        with pytest.raises(EmbeddingsProviderSetupRequired, match="corrupt local model") as error:
            LocalE5EmbeddingsAdapter().embed_text("δοκιμή")

        assert isinstance(error.value.original_error, RuntimeError)
