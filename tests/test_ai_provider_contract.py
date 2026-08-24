# ================================================================
# Project: Astakos AI Agent 🦞
# Module:  Tests for AI Provider Capability Adapter Contract
# Description: Validates typed contracts, errors, and real adapter boundaries (offline)
# Copyright (c) 2026 - All Rights Reserved
# ================================================================

import base64
import os
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
    resolve_provider_models,
)
from tests.fixtures.provider_mocks import (
    MockOpenAIAdapter,
    MockGeminiAPIAdapter,
    MockVertexAIAdapter,
    MockAnthropicAdapter,
)


class TestAIProviderContractAndResolution:
    """Verifies adapter metadata, factory instantiation, and shared model resolution."""

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
        assert adapter.is_capability_supported("unsupported_xyz") is False

    def test_factory_resolves_all_known_providers(self):
        openai_adapter = get_provider_adapter("openai", api_key="test-key")
        assert isinstance(openai_adapter, OpenAIAdapter)
        assert openai_adapter.fast_model == "gpt-4o-mini"
        assert openai_adapter.heavy_model == "gpt-4o"

        gemini_adapter = get_provider_adapter("gemini", api_key="test-key")
        assert isinstance(gemini_adapter, GeminiAPIAdapter)
        assert gemini_adapter.fast_model == "gemini-3.5-flash"
        assert gemini_adapter.heavy_model == "gemini-3.1-pro-preview"

        vertex_adapter = get_provider_adapter("vertex", project_id="test-proj", location="global")
        assert isinstance(vertex_adapter, VertexAIAdapter)
        assert vertex_adapter.fast_model == "gemini-3.5-flash"
        assert vertex_adapter.heavy_model == "gemini-3.1-pro-preview"

        anthropic_adapter = get_provider_adapter("anthropic", api_key="test-key")
        assert isinstance(anthropic_adapter, AnthropicAdapter)
        assert anthropic_adapter.fast_model == "claude-3-5-haiku-latest"
        assert anthropic_adapter.heavy_model == "claude-3-5-sonnet-latest"

    def test_factory_raises_for_unknown_provider(self):
        with pytest.raises(AIProviderError) as exc_info:
            get_provider_adapter("unsupported_provider_xyz")
        assert "Unknown AI provider" in str(exc_info.value)

    def test_shared_model_resolution_env_overrides(self, monkeypatch):
        monkeypatch.setenv("ASTAKOS_GEMINI_FAST_MODEL", "gemini-custom-fast")
        monkeypatch.setenv("ASTAKOS_GEMINI_HEAVY_MODEL", "gemini-custom-heavy")

        fast_g, heavy_g = resolve_provider_models("gemini")
        assert fast_g == "gemini-custom-fast"
        assert heavy_g == "gemini-custom-heavy"

        gemini_adapter = GeminiAPIAdapter(api_key="test-key")
        assert gemini_adapter.fast_model == "gemini-custom-fast"
        assert gemini_adapter.heavy_model == "gemini-custom-heavy"


class TestRealOpenAIAdapterBoundary:
    """Offline SDK boundary tests for OpenAIAdapter."""

    def setup_method(self):
        self.adapter = OpenAIAdapter(api_key="sk-test-openai-key")

    @patch("langchain_openai.ChatOpenAI.invoke")
    def test_generate_text_and_vision_success(self, mock_invoke):
        mock_resp = MagicMock()
        mock_resp.content = "OpenAI offline response"
        mock_invoke.return_value = mock_resp

        text_out = self.adapter.generate_text("Hello OpenAI")
        assert text_out == "OpenAI offline response"

        vision_out = self.adapter.analyze_vision("Describe image", b"fake_bytes")
        assert vision_out == "OpenAI offline response"

    @patch("requests.post")
    def test_transcribe_audio_success(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"text": "Transcribed test audio"}
        mock_post.return_value = mock_resp

        result = self.adapter.transcribe_audio(b"audio_bytes", mime_type="audio/ogg")
        assert result == "Transcribed test audio"

    @patch("requests.post")
    def test_generate_image_success(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        raw_bytes = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00dalle_image"
        mock_resp.json.return_value = {"data": [{"b64_json": base64.b64encode(raw_bytes).decode("utf-8")}]}
        mock_post.return_value = mock_resp

        img_bytes = self.adapter.generate_image("A cute lobster")
        assert img_bytes == raw_bytes

    @patch("langchain_openai.OpenAIEmbeddings.embed_documents")
    def test_embed_text_success(self, mock_embed):
        mock_embed.return_value = [[0.1] * 1536, [0.2] * 1536]
        vecs = self.adapter.embed_text(["doc 1", "doc 2"])
        assert len(vecs) == 2
        assert len(vecs[0]) == 1536

    @patch("langchain_openai.ChatOpenAI.invoke")
    def test_auth_and_rate_limit_errors(self, mock_invoke):
        # 401 Auth Error
        mock_invoke.side_effect = Exception("401 Unauthorized: Invalid API key")
        with pytest.raises(ProviderAuthError) as exc_info:
            self.adapter.generate_text("test")
        assert exc_info.value.provider == "openai"

        # 429 Rate Limit Error
        mock_invoke.side_effect = Exception("429 Rate limit reached for requests")
        with pytest.raises(RateLimitError) as exc_info:
            self.adapter.generate_text("test")
        assert exc_info.value.provider == "openai"


class TestRealGeminiAPIAdapterBoundary:
    """Offline SDK boundary tests for GeminiAPIAdapter."""

    def setup_method(self):
        self.adapter = GeminiAPIAdapter(api_key="ai-studio-test-key")

    @patch("langchain_google_genai.ChatGoogleGenerativeAI.invoke")
    def test_generate_text_and_vision_success(self, mock_invoke):
        mock_resp = MagicMock()
        mock_resp.content = "Gemini offline response"
        mock_invoke.return_value = mock_resp

        text_out = self.adapter.generate_text("Hello Gemini")
        assert text_out == "Gemini offline response"

        vision_out = self.adapter.analyze_vision("Look at this", b"fake_bytes")
        assert vision_out == "Gemini offline response"

    @patch("google.genai.Client")
    def test_transcribe_audio_success(self, mock_client_cls):
        mock_client = MagicMock()
        mock_resp = MagicMock()
        mock_resp.text = "Gemini transcribed voice"
        mock_client.models.generate_content.return_value = mock_resp
        mock_client_cls.return_value = mock_client

        out = self.adapter.transcribe_audio(b"audio_bytes", mime_type="audio/ogg")
        assert out == "Gemini transcribed voice"

    @patch("google.genai.Client")
    def test_generate_image_success(self, mock_client_cls):
        mock_client = MagicMock()
        mock_resp = MagicMock()
        mock_img = MagicMock()
        mock_img.image_bytes = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00imagen_bytes"
        mock_resp.generated_images = [MagicMock(image=mock_img)]
        mock_client.models.generate_images.return_value = mock_resp
        mock_client_cls.return_value = mock_client

        out = self.adapter.generate_image("A scenic sunset")
        assert out == b"\xff\xd8\xff\xe0\x00\x10JFIF\x00imagen_bytes"

    @patch("google.genai.Client")
    def test_generate_image_auth_and_rate_limit_errors(self, mock_client_cls):
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client

        # Auth Error
        mock_client.models.generate_images.side_effect = Exception("403 PERMISSION_DENIED: Imagen API access denied")
        with pytest.raises(ProviderAuthError) as exc_auth:
            self.adapter.generate_image("prompt")
        assert exc_auth.value.provider == "gemini"

        # Rate Limit Error
        mock_client.models.generate_images.side_effect = Exception("429 RESOURCE_EXHAUSTED: Daily quota exceeded")
        with pytest.raises(RateLimitError) as exc_rate:
            self.adapter.generate_image("prompt")
        assert exc_rate.value.provider == "gemini"

    @patch("langchain_google_genai.GoogleGenerativeAIEmbeddings.embed_documents")
    def test_embed_text_success(self, mock_embed):
        mock_embed.return_value = [[0.05] * 768]
        vecs = self.adapter.embed_text(["test text"])
        assert len(vecs) == 1
        assert len(vecs[0]) == 768

    @patch("langchain_google_genai.ChatGoogleGenerativeAI.invoke")
    def test_auth_and_rate_limit_errors(self, mock_invoke):
        # 403 Permission Denied
        mock_invoke.side_effect = Exception("403 PERMISSION_DENIED: API key not valid")
        with pytest.raises(ProviderAuthError) as exc_info:
            self.adapter.generate_text("test")
        assert exc_info.value.provider == "gemini"

        # 429 Quota Exceeded
        mock_invoke.side_effect = Exception("429 RESOURCE_EXHAUSTED: Quota exceeded")
        with pytest.raises(RateLimitError) as exc_info:
            self.adapter.generate_text("test")
        assert exc_info.value.provider == "gemini"


class TestRealVertexAIAdapterBoundary:
    """Offline SDK boundary tests for VertexAIAdapter."""

    def setup_method(self):
        self.adapter = VertexAIAdapter(project_id="test-proj", location="global")

    @patch("langchain_google_genai.ChatGoogleGenerativeAI.invoke")
    def test_generate_text_and_vision_success(self, mock_invoke):
        mock_resp = MagicMock()
        mock_resp.content = "Vertex AI response"
        mock_invoke.return_value = mock_resp

        text_out = self.adapter.generate_text("Hello Vertex")
        assert text_out == "Vertex AI response"

        vision_out = self.adapter.analyze_vision("Analyze blueprint", b"fake_blueprint_bytes")
        assert vision_out == "Vertex AI response"

    @patch("google.genai.Client")
    def test_transcribe_audio_success(self, mock_client_cls):
        mock_client = MagicMock()
        mock_resp = MagicMock()
        mock_resp.text = "Vertex transcribed audio"
        mock_client.models.generate_content.return_value = mock_resp
        mock_client_cls.return_value = mock_client

        out = self.adapter.transcribe_audio(b"audio_bytes", mime_type="audio/ogg")
        assert out == "Vertex transcribed audio"

    @patch("google.genai.Client")
    def test_generate_image_success(self, mock_client_cls):
        mock_client = MagicMock()
        mock_resp = MagicMock()
        mock_img = MagicMock()
        mock_img.image_bytes = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00vertex_imagen_bytes"
        mock_resp.generated_images = [MagicMock(image=mock_img)]
        mock_client.models.generate_images.return_value = mock_resp
        mock_client_cls.return_value = mock_client

        out = self.adapter.generate_image("A futuristic city")
        assert out == b"\xff\xd8\xff\xe0\x00\x10JFIF\x00vertex_imagen_bytes"

    @patch("langchain_google_genai.GoogleGenerativeAIEmbeddings.embed_documents")
    def test_embed_text_success(self, mock_embed):
        mock_embed.return_value = [[0.03] * 768, [0.04] * 768]
        vecs = self.adapter.embed_text(["doc a", "doc b"])
        assert len(vecs) == 2
        assert len(vecs[0]) == 768

    @patch("langchain_google_genai.GoogleGenerativeAIEmbeddings.embed_query")
    def test_embed_query_success(self, mock_query):
        mock_query.return_value = [0.09] * 768
        vecs = self.adapter.embed_text(["single query"], is_query=True)
        assert len(vecs) == 1
        assert len(vecs[0]) == 768

    @patch("langchain_google_genai.GoogleGenerativeAIEmbeddings.embed_documents")
    def test_embed_text_auth_error(self, mock_embed):
        mock_embed.side_effect = Exception("403 PERMISSION_DENIED: Vertex Embeddings API disabled")
        with pytest.raises(ProviderAuthError) as exc_auth:
            self.adapter.embed_text(["test text"])
        assert exc_auth.value.provider == "vertex"

    @patch("langchain_google_genai.ChatGoogleGenerativeAI.invoke")
    def test_auth_and_rate_limit_errors(self, mock_invoke):
        # 403 Permission Denied
        mock_invoke.side_effect = Exception("403 Permission denied on project test-proj")
        with pytest.raises(ProviderAuthError) as exc_info:
            self.adapter.generate_text("test")
        assert exc_info.value.provider == "vertex"

        # 429 Quota Exceeded
        mock_invoke.side_effect = Exception("429 Resource exhausted: Rate limit reached")
        with pytest.raises(RateLimitError) as exc_info:
            self.adapter.generate_text("test")
        assert exc_info.value.provider == "vertex"


class TestRealAnthropicAdapterBoundary:
    """Offline SDK boundary tests for AnthropicAdapter."""

    def setup_method(self):
        self.adapter = AnthropicAdapter(api_key="sk-ant-test-key")

    @patch("langchain_anthropic.ChatAnthropic.invoke")
    def test_generate_text_and_vision_success(self, mock_invoke):
        mock_resp = MagicMock()
        mock_resp.content = "Claude offline response"
        mock_invoke.return_value = mock_resp

        text_out = self.adapter.generate_text("Hello Claude")
        assert text_out == "Claude offline response"

        vision_out = self.adapter.analyze_vision("Analyze chart", b"chart_bytes")
        assert vision_out == "Claude offline response"

    def test_unsupported_operations_raise_typed_errors(self):
        with pytest.raises(CapabilityNotSupportedError) as exc_audio:
            self.adapter.transcribe_audio(b"audio", mime_type="audio/ogg")
        assert exc_audio.value.provider == "anthropic"
        assert exc_audio.value.capability == "audio_stt"

        with pytest.raises(CapabilityNotSupportedError) as exc_img:
            self.adapter.generate_image("A robot")
        assert exc_img.value.provider == "anthropic"
        assert exc_img.value.capability == "image_gen"

        with pytest.raises(CapabilityNotSupportedError) as exc_emb:
            self.adapter.embed_text(["some text"])
        assert exc_emb.value.provider == "anthropic"
        assert exc_emb.value.capability == "embeddings"

    @patch("langchain_anthropic.ChatAnthropic.invoke")
    def test_auth_and_rate_limit_errors(self, mock_invoke):
        mock_invoke.side_effect = Exception("401 authentication_error: invalid x-api-key")
        with pytest.raises(ProviderAuthError) as exc_info:
            self.adapter.generate_text("test")
        assert exc_info.value.provider == "anthropic"

        mock_invoke.side_effect = Exception("429 rate_limit_error: request limit exceeded")
        with pytest.raises(RateLimitError) as exc_info:
            self.adapter.generate_text("test")
        assert exc_info.value.provider == "anthropic"


class TestBrainBackwardCompatibility:
    """Verifies that core/brain.py retains backward-compatible symbols and integration."""

    def test_brain_symbols_exist(self):
        from core import brain
        assert hasattr(brain, "llm")
        assert hasattr(brain, "llm_heavy")
        assert hasattr(brain, "FAST_MODEL")
        assert hasattr(brain, "HEAVY_MODEL")
        assert hasattr(brain, "DEFAULT_GEMINI_FAST_MODEL")
        assert hasattr(brain, "DEFAULT_GEMINI_HEAVY_MODEL")
        assert hasattr(brain, "_google_model_from_environment")
        assert hasattr(brain, "safe_llm_invoke")
        assert hasattr(brain, "get_active_provider_adapter")

    def test_get_active_provider_adapter_returns_singleton(self):
        from core.brain import get_active_provider_adapter
        adapter1 = get_active_provider_adapter()
        adapter2 = get_active_provider_adapter()
        assert adapter1 is adapter2
        assert isinstance(adapter1, AIProviderAdapter)

    def test_unknown_provider_in_brain_defaults_to_vertex_adapter(self):
        import core.brain as brain
        orig_adapter = brain._active_provider_adapter
        orig_provider = brain._provider
        try:
            brain._provider = "completely_unknown_provider_xyz"
            brain._active_provider_adapter = None
            adapter = brain.get_active_provider_adapter()
            assert isinstance(adapter, VertexAIAdapter)
            assert adapter.provider_name == "vertex"
        finally:
            brain._provider = orig_provider
            brain._active_provider_adapter = orig_adapter
