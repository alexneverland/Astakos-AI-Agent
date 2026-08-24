# ================================================================
# Project: Astakos AI Agent 🦞
# Module:  Tests for AI Provider Capability Adapter Contract
# Description: Validates typed contracts, errors, and adapter behavior
# Copyright (c) 2026 - All Rights Reserved
# ================================================================

import pytest
from unittest.mock import MagicMock, patch

from core.ai_provider import (
    AIProviderAdapter,
    AIProviderError,
    CapabilityNotSupportedError,
    ProviderAuthError,
    RateLimitError,
    OpenAIAdapter,
    GeminiAPIAdapter,
    VertexAIAdapter,
    AnthropicAdapter,
    get_provider_adapter,
)
from tests.fixtures.provider_mocks import (
    MockOpenAIAdapter,
    MockGeminiAPIAdapter,
    MockVertexAIAdapter,
    MockAnthropicAdapter,
)


class TestAIProviderContract:
    """Verifies that all adapters strictly conform to the AIProviderAdapter contract."""

    @pytest.mark.parametrize(
        "adapter_cls,expected_name,expected_caps",
        [
            (OpenAIAdapter, "openai", {"text", "vision", "audio_stt", "image_gen", "embeddings"}),
            (GeminiAPIAdapter, "gemini", {"text", "vision", "audio_stt", "image_gen", "embeddings"}),
            (VertexAIAdapter, "vertex", {"text", "vision", "audio_stt", "image_gen", "embeddings"}),
            (AnthropicAdapter, "anthropic", {"text", "vision"}),
        ],
    )
    def test_adapter_attributes_and_capabilities(self, adapter_cls, expected_name, expected_caps):
        adapter = adapter_cls()
        assert issubclass(adapter_cls, AIProviderAdapter)
        assert adapter.provider_name == expected_name
        assert adapter.supported_capabilities == expected_caps
        for cap in expected_caps:
            assert adapter.is_capability_supported(cap) is True
        assert adapter.is_capability_supported("non_existent_capability") is False

    def test_factory_resolves_all_known_providers(self):
        openai_adapter = get_provider_adapter("openai", api_key="test-key")
        assert isinstance(openai_adapter, OpenAIAdapter)
        assert openai_adapter.provider_name == "openai"

        gemini_adapter = get_provider_adapter("gemini", api_key="test-key")
        assert isinstance(gemini_adapter, GeminiAPIAdapter)
        assert gemini_adapter.provider_name == "gemini"

        vertex_adapter = get_provider_adapter("vertex", project_id="test-proj", location="global")
        assert isinstance(vertex_adapter, VertexAIAdapter)
        assert vertex_adapter.provider_name == "vertex"

        anthropic_adapter = get_provider_adapter("anthropic", api_key="test-key")
        assert isinstance(anthropic_adapter, AnthropicAdapter)
        assert anthropic_adapter.provider_name == "anthropic"

    def test_factory_raises_for_unknown_provider(self):
        with pytest.raises(AIProviderError) as exc_info:
            get_provider_adapter("unsupported_provider_xyz")
        assert "Unknown AI provider" in str(exc_info.value)

    def test_mock_adapters_conform_to_contract(self):
        adapters = [
            MockOpenAIAdapter(),
            MockGeminiAPIAdapter(),
            MockVertexAIAdapter(),
            MockAnthropicAdapter(),
        ]
        for adapter in adapters:
            assert isinstance(adapter, AIProviderAdapter)
            text_out = adapter.generate_text("Hello Astakos")
            assert isinstance(text_out, str)
            assert "Hello Astakos" in text_out

            vision_out = adapter.analyze_vision("Describe image", b"fake_image_bytes")
            assert isinstance(vision_out, str)
            assert "Describe image" in vision_out


class TestAnthropicUnsupportedCapabilities:
    """Verifies that unsupported operations on Anthropic raise typed, informative errors."""

    def setup_method(self):
        self.adapter = AnthropicAdapter(api_key="test-anthropic-key")

    def test_transcribe_audio_raises_capability_not_supported(self):
        with pytest.raises(CapabilityNotSupportedError) as exc_info:
            self.adapter.transcribe_audio(b"audio_bytes", mime_type="audio/ogg")
        err = exc_info.value
        assert err.provider == "anthropic"
        assert err.capability == "audio_stt"
        assert "Audio transcription is not natively supported by Anthropic" in err.user_message

    def test_generate_image_raises_capability_not_supported(self):
        with pytest.raises(CapabilityNotSupportedError) as exc_info:
            self.adapter.generate_image("A cute robot lobster", aspect_ratio="1:1")
        err = exc_info.value
        assert err.provider == "anthropic"
        assert err.capability == "image_gen"
        assert "Image generation is not supported by Anthropic" in err.user_message

    def test_embed_text_raises_capability_not_supported(self):
        with pytest.raises(CapabilityNotSupportedError) as exc_info:
            self.adapter.embed_text(["Text to embed"])
        err = exc_info.value
        assert err.provider == "anthropic"
        assert err.capability == "embeddings"
        assert "Embeddings are not natively supported by Anthropic" in err.user_message


class TestTypedErrorMapping:
    """Verifies that authentication and rate-limit faults map to typed exceptions."""

    def test_mock_fault_injection(self):
        # Auth fault
        auth_adapter = MockOpenAIAdapter(should_fail_auth=True)
        with pytest.raises(ProviderAuthError) as exc_info:
            auth_adapter.generate_text("test")
        assert exc_info.value.provider == "openai"

        # Rate limit fault
        rate_adapter = MockGeminiAPIAdapter(should_rate_limit=True)
        with pytest.raises(RateLimitError) as exc_info:
            rate_adapter.generate_text("test")
        assert exc_info.value.provider == "gemini"
        assert exc_info.value.retry_after == 10.0

    def test_missing_api_key_raises_auth_error(self):
        openai_adapter = OpenAIAdapter(api_key="")
        with pytest.raises(ProviderAuthError) as exc_info:
            openai_adapter.generate_text("test")
        assert exc_info.value.provider == "openai"

        gemini_adapter = GeminiAPIAdapter(api_key="")
        with pytest.raises(ProviderAuthError) as exc_info:
            gemini_adapter.generate_text("test")
        assert exc_info.value.provider == "gemini"

        anthropic_adapter = AnthropicAdapter(api_key="")
        with pytest.raises(ProviderAuthError) as exc_info:
            anthropic_adapter.generate_text("test")
        assert exc_info.value.provider == "anthropic"


class TestBrainBackwardCompatibility:
    """Verifies that core/brain.py retains backward-compatible symbols and integration."""

    def test_brain_symbols_exist(self):
        from core import brain
        assert hasattr(brain, "llm")
        assert hasattr(brain, "llm_heavy")
        assert hasattr(brain, "FAST_MODEL")
        assert hasattr(brain, "HEAVY_MODEL")
        assert hasattr(brain, "safe_llm_invoke")
        assert hasattr(brain, "get_active_provider_adapter")

    def test_get_active_provider_adapter_returns_singleton(self):
        from core.brain import get_active_provider_adapter
        adapter1 = get_active_provider_adapter()
        adapter2 = get_active_provider_adapter()
        assert adapter1 is adapter2
        assert isinstance(adapter1, AIProviderAdapter)
