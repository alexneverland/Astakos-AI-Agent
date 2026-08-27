# ================================================================
# Project: Astakos AI Agent 🦞
# Module:  Tests for AI Provider Capability Adapter Contract
# Description: Validates typed contracts, errors, thread-safety, and real adapter boundaries (offline)
# Copyright (c) 2026 - All Rights Reserved
# ================================================================

import base64
from concurrent.futures import ThreadPoolExecutor
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
    AUDIO_TRANSCRIPTION_PROMPT,
    get_provider_adapter,
    get_gemini_safety_settings,
    resolve_gemini_safety_threshold,
    resolve_provider_models,
    resolve_vertex_location,
    normalize_embedding_texts,
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

    def test_factory_resolves_all_known_providers(self, monkeypatch):
        """Verify factory defaults independently of supported model overrides."""
        monkeypatch.delenv("ASTAKOS_GEMINI_FAST_MODEL", raising=False)
        monkeypatch.delenv("ASTAKOS_GEMINI_HEAVY_MODEL", raising=False)

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

    def test_shared_gemini_safety_settings_resolution(self, monkeypatch):
        from langchain_google_genai import HarmBlockThreshold, HarmCategory
        monkeypatch.setenv("ASTAKOS_GEMINI_SAFETY_THRESHOLD", "BLOCK_ONLY_HIGH")
        threshold = resolve_gemini_safety_threshold()
        assert threshold == HarmBlockThreshold.BLOCK_ONLY_HIGH

        settings = get_gemini_safety_settings()
        assert settings[HarmCategory.HARM_CATEGORY_HARASSMENT] == HarmBlockThreshold.BLOCK_ONLY_HIGH
        assert settings[HarmCategory.HARM_CATEGORY_CIVIC_INTEGRITY] == HarmBlockThreshold.BLOCK_ONLY_HIGH

    def test_vertex_location_resolution_matches_legacy_environment_rule(self, monkeypatch):
        monkeypatch.delenv("LOCATION", raising=False)
        assert resolve_vertex_location() == "global"
        monkeypatch.setenv("LOCATION", "europe-west4")
        assert resolve_vertex_location() == "europe-west4"
        assert resolve_vertex_location("us-central1") == "us-central1"

    def test_scalar_embedding_text_normalizes_to_one_item(self):
        assert normalize_embedding_texts("hello") == ["hello"]


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

    @pytest.mark.parametrize(
        ("mime_type", "expected_filename"),
        [
            ("audio/ogg", "audio.ogg"),
            ("audio/webm", "audio.webm"),
            ("audio/wav", "audio.wav"),
            ("audio/mpeg", "audio.mp3"),
            ("audio/mp4", "audio.mp4"),
            ("audio/flac", "audio.flac"),
        ],
    )
    @patch("requests.post")
    def test_transcribe_audio_preserves_matching_filename_extension(
        self,
        mock_post,
        mime_type,
        expected_filename,
    ):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"text": "Transcribed test audio"}
        mock_post.return_value = mock_resp

        result = self.adapter.transcribe_audio(b"audio_bytes", mime_type=mime_type)
        assert result == "Transcribed test audio"
        uploaded_filename, _, uploaded_mime = mock_post.call_args.kwargs["files"]["file"]
        assert uploaded_filename == expected_filename
        assert uploaded_mime == mime_type

    @patch("requests.post")
    def test_transcribe_audio_rejects_unknown_mime_type(self, mock_post):
        with pytest.raises(CapabilityNotSupportedError) as exc_info:
            self.adapter.transcribe_audio(b"audio_bytes", mime_type="audio/unknown")
        assert exc_info.value.provider == "openai"
        assert exc_info.value.capability == "audio_stt"
        mock_post.assert_not_called()

    @patch("requests.post")
    def test_generate_image_aspect_ratios(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        raw_bytes = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00dalle_image"
        mock_resp.json.return_value = {"data": [{"b64_json": base64.b64encode(raw_bytes).decode("utf-8")}]}
        mock_post.return_value = mock_resp

        # Square 1:1 -> 1024x1024
        img1 = self.adapter.generate_image("A cute lobster", aspect_ratio="1:1")
        assert img1 == raw_bytes
        call_json1 = mock_post.call_args_list[-1][1]["json"]
        assert call_json1["size"] == "1024x1024"

        # Landscape 16:9 -> 1792x1024
        img2 = self.adapter.generate_image("A wide landscape", aspect_ratio="16:9")
        assert img2 == raw_bytes
        call_json2 = mock_post.call_args_list[-1][1]["json"]
        assert call_json2["size"] == "1792x1024"

        # Portrait 9:16 -> 1024x1792
        img3 = self.adapter.generate_image("A tall skyscraper", aspect_ratio="9:16")
        assert img3 == raw_bytes
        call_json3 = mock_post.call_args_list[-1][1]["json"]
        assert call_json3["size"] == "1024x1792"

    @patch("requests.post")
    def test_generate_image_unsupported_aspect_ratio_raises(self, mock_post):
        with pytest.raises(CapabilityNotSupportedError) as exc_info:
            self.adapter.generate_image("A portrait photo", aspect_ratio="4:3")
        assert exc_info.value.provider == "openai"
        assert exc_info.value.capability == "image_gen"
        assert "4:3" in str(exc_info.value)
        # Ensure no HTTP request was made
        mock_post.assert_not_called()

    @patch("langchain_openai.OpenAIEmbeddings.embed_documents")
    def test_embed_text_success(self, mock_embed):
        mock_embed.return_value = [[0.1] * 1536, [0.2] * 1536]
        vecs = self.adapter.embed_text(["doc 1", "doc 2"])
        assert len(vecs) == 2
        assert len(vecs[0]) == 1536

    @patch("langchain_openai.OpenAIEmbeddings.embed_documents")
    def test_embed_text_scalar_is_one_document(self, mock_embed):
        mock_embed.return_value = [[0.1] * 1536]
        vecs = self.adapter.embed_text("one document")
        assert len(vecs) == 1
        mock_embed.assert_called_once_with(["one document"])

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

    @patch("requests.post")
    def test_explicit_empty_api_key_raises_auth_error(self, mock_post):
        empty_adapter = OpenAIAdapter(api_key="")
        with pytest.raises(ProviderAuthError) as exc_text:
            empty_adapter.generate_text("test")
        assert exc_text.value.provider == "openai"

        with pytest.raises(ProviderAuthError) as exc_audio:
            empty_adapter.transcribe_audio(b"audio")
        assert exc_audio.value.provider == "openai"

        with pytest.raises(ProviderAuthError) as exc_img:
            empty_adapter.generate_image("prompt")
        assert exc_img.value.provider == "openai"

        with pytest.raises(ProviderAuthError) as exc_emb:
            empty_adapter.embed_text(["text"])
        assert exc_emb.value.provider == "openai"

        mock_post.assert_not_called()


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

    def test_gemini_adapter_passes_resolved_safety_settings(self):
        llm = self.adapter._get_llm()
        assert hasattr(llm, "safety_settings")
        assert llm.safety_settings is not None

    @patch("google.genai.Client")
    def test_transcribe_audio_dedicated_success(self, mock_client_cls):
        mock_client = MagicMock()
        mock_file = MagicMock(name="files/sample_audio_file", uri="https://generativelanguage.googleapis.com/v1beta/files/sample_audio_file")
        mock_file.name = "files/sample_audio_file"
        mock_client.files.upload.return_value = mock_file

        mock_interaction = MagicMock(output_text="Gemini transcribed voice verbatim")
        mock_client.interactions.create.return_value = mock_interaction
        mock_client_cls.return_value = mock_client

        out = self.adapter.transcribe_audio(b"sample_audio_bytes", mime_type="audio/ogg")
        assert out == "Gemini transcribed voice verbatim"

        # 1. Verify Files API upload was called with in-memory stream and mime_type
        upload_kwargs = mock_client.files.upload.call_args.kwargs
        upload_file_obj = upload_kwargs["file"]
        assert upload_file_obj.read() == b"sample_audio_bytes"
        assert upload_kwargs["config"].mime_type == "audio/ogg"

        # 2. Verify Interactions API create call
        create_kwargs = mock_client.interactions.create.call_args.kwargs
        assert create_kwargs["model"] == "gemini-3.5-transcribe"
        assert create_kwargs["input"] == [
            {
                "type": "audio",
                "uri": "https://generativelanguage.googleapis.com/v1beta/files/sample_audio_file",
                "mime_type": "audio/ogg",
            }
        ]
        assert create_kwargs["generation_config"] == {
            "transcription_config": {
                "mode": {
                    "type": "verbatim",
                },
            },
        }

        # 3. Verify remote file deletion
        mock_client.files.delete.assert_called_once_with(name="files/sample_audio_file")

    @patch("google.genai.Client")
    def test_transcribe_audio_silence_returns_silence_token(self, mock_client_cls):
        mock_client = MagicMock()
        mock_file = MagicMock()
        mock_file.name = "files/silent_audio_file"
        mock_file.uri = "files/silent_audio_file"
        mock_client.files.upload.return_value = mock_file

        mock_interaction = MagicMock(output_text="")  # Empty output indicates silence
        mock_client.interactions.create.return_value = mock_interaction
        mock_client_cls.return_value = mock_client

        out = self.adapter.transcribe_audio(b"silent_bytes", mime_type="audio/webm")
        assert out == "[ΣΙΩΠΗ]"
        mock_client.files.delete.assert_called_once_with(name="files/silent_audio_file")

    @patch("google.genai.Client")
    def test_transcribe_audio_deletion_failure_preserves_successful_transcript(self, mock_client_cls, caplog):
        mock_client = MagicMock()
        mock_file = MagicMock()
        mock_file.name = "files/audio_file_del_fail"
        mock_file.uri = "files/audio_file_del_fail"
        mock_client.files.upload.return_value = mock_file

        mock_interaction = MagicMock(output_text="Valid transcript text")
        mock_client.interactions.create.return_value = mock_interaction
        mock_client.files.delete.side_effect = Exception("Remote file delete network failure")
        mock_client_cls.return_value = mock_client

        import logging
        with caplog.at_level(logging.WARNING):
            out = self.adapter.transcribe_audio(b"audio_bytes", mime_type="audio/ogg")

        assert out == "Valid transcript text"
        assert "Failed to delete temporary uploaded audio file" in caplog.text

    @patch("google.genai.Client")
    def test_transcribe_audio_remote_file_deleted_on_transcription_failure(self, mock_client_cls):
        mock_client = MagicMock()
        mock_file = MagicMock()
        mock_file.name = "files/fail_audio_file"
        mock_file.uri = "files/fail_audio_file"
        mock_client.files.upload.return_value = mock_file

        mock_client.interactions.create.side_effect = Exception("403 PERMISSION_DENIED: API key not valid")
        mock_client_cls.return_value = mock_client

        with pytest.raises(ProviderAuthError) as exc_info:
            self.adapter.transcribe_audio(b"audio_bytes", mime_type="audio/ogg")

        assert exc_info.value.provider == "gemini"
        mock_client.files.delete.assert_called_once_with(name="files/fail_audio_file")

    @patch("google.genai.Client")
    def test_transcribe_audio_fallback_on_unsupported_model(self, mock_client_cls, caplog):
        mock_client = MagicMock()
        mock_file = MagicMock()
        mock_file.name = "files/fallback_audio_file"
        mock_file.uri = "files/fallback_audio_file"
        mock_client.files.upload.return_value = mock_file

        # Interactions create raises 404 model not found
        mock_client.interactions.create.side_effect = Exception("404 NOT_FOUND: Publisher Model gemini-3.5-transcribe not found")
        mock_resp_fallback = MagicMock()
        mock_resp_fallback.text = "Fallback Gemini Flash transcribed voice"
        mock_client.models.generate_content.return_value = mock_resp_fallback
        mock_client_cls.return_value = mock_client

        import logging
        with caplog.at_level(logging.WARNING):
            out = self.adapter.transcribe_audio(b"audio_bytes", mime_type="audio/ogg")

        assert out == "Fallback Gemini Flash transcribed voice"
        mock_client.models.generate_content.assert_called_once()
        fallback_kwargs = mock_client.models.generate_content.call_args.kwargs
        assert fallback_kwargs["model"] == self.adapter.fast_model
        assert fallback_kwargs["contents"][1] == AUDIO_TRANSCRIPTION_PROMPT
        mock_client.files.delete.assert_called_once_with(name="files/fallback_audio_file")
        assert "Falling back to generic Flash transcription" in caplog.text

        # Second scenario: Model unavailable phrase triggers Flash fallback
        caplog.clear()
        mock_client.models.generate_content.reset_mock()
        mock_client.files.delete.reset_mock()
        mock_client.interactions.create.side_effect = Exception("Model 'gemini-3.5-transcribe' is unavailable")
        with caplog.at_level(logging.WARNING):
            out_unavail = self.adapter.transcribe_audio(b"audio_bytes", mime_type="audio/ogg")

        assert out_unavail == "Fallback Gemini Flash transcribed voice"
        mock_client.models.generate_content.assert_called_once()
        mock_client.files.delete.assert_called_once_with(name="files/fallback_audio_file")
        assert "Falling back to generic Flash transcription" in caplog.text

    @patch("google.genai.Client")
    def test_transcribe_audio_auth_and_quota_errors_never_fallback(self, mock_client_cls):
        mock_client = MagicMock()
        mock_file = MagicMock()
        mock_file.name = "files/test_file"
        mock_file.uri = "files/test_file"
        mock_client.files.upload.return_value = mock_file
        mock_client_cls.return_value = mock_client

        # 1. Auth error -> raises ProviderAuthError, no fallback to models.generate_content
        mock_client.interactions.create.side_effect = Exception("403 PERMISSION_DENIED: API key not valid")
        with pytest.raises(ProviderAuthError) as exc_auth:
            self.adapter.transcribe_audio(b"audio_bytes")
        assert exc_auth.value.provider == "gemini"
        assert mock_client.models.generate_content.call_count == 0

        # 2. Quota error -> raises RateLimitError, no fallback to models.generate_content
        mock_client.interactions.create.side_effect = Exception("429 RESOURCE_EXHAUSTED: Daily quota exceeded")
        with pytest.raises(RateLimitError) as exc_rate:
            self.adapter.transcribe_audio(b"audio_bytes")
        assert exc_rate.value.provider == "gemini"
        assert mock_client.models.generate_content.call_count == 0

    @patch("google.genai.Client")
    def test_transcribe_audio_validation_and_transient_errors_never_fallback(self, mock_client_cls):
        mock_client = MagicMock()
        mock_file = MagicMock()
        mock_file.name = "files/test_file"
        mock_file.uri = "files/test_file"
        mock_client.files.upload.return_value = mock_file
        mock_client_cls.return_value = mock_client

        # 1. 400 Bad Request / Invalid Audio format -> raises AIProviderError, no fallback
        mock_client.interactions.create.side_effect = Exception("400 INVALID_ARGUMENT: Unsupported audio codec")
        with pytest.raises(AIProviderError) as exc_val:
            self.adapter.transcribe_audio(b"audio_bytes")
        assert exc_val.value.provider == "gemini"
        assert mock_client.models.generate_content.call_count == 0

        # 2. 503 Transient Service Unavailable -> raises AIProviderError, no fallback
        mock_client.interactions.create.side_effect = Exception("503 UNAVAILABLE: Service temporarily overloaded")
        with pytest.raises(AIProviderError) as exc_503:
            self.adapter.transcribe_audio(b"audio_bytes")
        assert exc_503.value.provider == "gemini"
        assert mock_client.models.generate_content.call_count == 0

        # 3. Timeout / Connection error -> raises AIProviderError, no fallback
        mock_client.interactions.create.side_effect = TimeoutError("Connection timed out")
        with pytest.raises(AIProviderError) as exc_to:
            self.adapter.transcribe_audio(b"audio_bytes")
        assert exc_to.value.provider == "gemini"
        assert mock_client.models.generate_content.call_count == 0

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

    @patch("langchain_google_genai.GoogleGenerativeAIEmbeddings.embed_documents")
    def test_embed_text_scalar_is_one_document(self, mock_embed):
        mock_embed.return_value = [[0.05] * 768]
        vecs = self.adapter.embed_text("one document")
        assert len(vecs) == 1
        mock_embed.assert_called_once_with(["one document"])

    @patch("langchain_google_genai.GoogleGenerativeAIEmbeddings.embed_query")
    def test_embed_query_batch_uses_query_mode_for_every_text(self, mock_query):
        mock_query.side_effect = [[0.1] * 768, [0.2] * 768]
        vecs = self.adapter.embed_text(["query one", "query two"], is_query=True)
        assert vecs == [[0.1] * 768, [0.2] * 768]
        assert mock_query.call_args_list[0].args == ("query one",)
        assert mock_query.call_args_list[1].args == ("query two",)

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

        # Symbolic-only RATE_LIMIT_EXCEEDED without numeric 429
        mock_invoke.side_effect = Exception("RATE_LIMIT_EXCEEDED: Too many requests per minute")
        with pytest.raises(RateLimitError) as exc_rate_sym:
            self.adapter.generate_text("test")
        assert exc_rate_sym.value.provider == "gemini"

    @patch("langchain_google_genai.ChatGoogleGenerativeAI.invoke")
    def test_invalid_api_key_error_maps_to_auth_error(self, mock_invoke):
        mock_invoke.side_effect = Exception("400 API_KEY_INVALID: API key not valid")
        with pytest.raises(ProviderAuthError) as exc_info:
            self.adapter.generate_text("test")
        assert exc_info.value.provider == "gemini"

    def test_explicit_empty_api_key_raises_auth_error(self):
        empty_adapter = GeminiAPIAdapter(api_key="")
        with pytest.raises(ProviderAuthError) as exc_text:
            empty_adapter.generate_text("test")
        assert exc_text.value.provider == "gemini"

        with pytest.raises(ProviderAuthError) as exc_audio:
            empty_adapter.transcribe_audio(b"audio")
        assert exc_audio.value.provider == "gemini"

        with pytest.raises(ProviderAuthError) as exc_img:
            empty_adapter.generate_image("prompt")
        assert exc_img.value.provider == "gemini"

        with pytest.raises(ProviderAuthError) as exc_emb:
            empty_adapter.embed_text(["text"])
        assert exc_emb.value.provider == "gemini"


class TestRealVertexAIAdapterBoundary:
    """Offline SDK boundary tests for VertexAIAdapter."""

    def setup_method(self):
        self.adapter = VertexAIAdapter(project_id="test-proj", location="europe-west1")

    @patch("langchain_google_genai.ChatGoogleGenerativeAI.invoke")
    def test_generate_text_and_vision_success(self, mock_invoke):
        mock_resp = MagicMock()
        mock_resp.content = "Vertex AI response"
        mock_invoke.return_value = mock_resp

        text_out = self.adapter.generate_text("Hello Vertex")
        assert text_out == "Vertex AI response"
        assert self.adapter.location == "europe-west1"

        vision_out = self.adapter.analyze_vision("Analyze blueprint", b"fake_blueprint_bytes")
        assert vision_out == "Vertex AI response"

    def test_vertex_adapter_passes_resolved_safety_settings(self):
        llm = self.adapter._get_llm()
        assert hasattr(llm, "safety_settings")
        assert llm.safety_settings is not None
        assert self.adapter.location == "europe-west1"

    @patch("google.genai.Client")
    def test_transcribe_audio_dedicated_success(self, mock_client_cls):
        mock_client = MagicMock()
        mock_resp = MagicMock()
        mock_resp.text = "Vertex transcribed audio verbatim"
        mock_client.models.generate_content.return_value = mock_resp
        mock_client_cls.return_value = mock_client

        out = self.adapter.transcribe_audio(b"audio_bytes", mime_type="audio/ogg")
        assert out == "Vertex transcribed audio verbatim"

        # 1. Verify dedicated transcription client is initialized with location='global'
        assert mock_client_cls.call_args.kwargs["location"] == "global"
        assert mock_client_cls.call_args.kwargs["project"] == "test-proj"
        assert mock_client_cls.call_args.kwargs["vertexai"] is True
        # 2. Verify normal adapter location is unchanged
        assert self.adapter.location == "europe-west1"

        # 3. Verify request uses dedicated model with raw audio and relies on default transcription behavior
        kwargs = mock_client.models.generate_content.call_args.kwargs
        assert kwargs["model"] == "gemini-3.5-transcribe-preview"
        assert kwargs["contents"] == [{"inline_data": {"mime_type": "audio/ogg", "data": b"audio_bytes"}}]
        # No artificial config fields or prompts are passed
        assert kwargs.get("config") is None
        assert AUDIO_TRANSCRIPTION_PROMPT not in str(kwargs["contents"])

    @patch("google.genai.Client")
    def test_transcribe_audio_silence_returns_silence_token(self, mock_client_cls):
        mock_client = MagicMock()
        mock_resp = MagicMock()
        mock_resp.text = ""  # Empty text indicates silence
        mock_client.models.generate_content.return_value = mock_resp
        mock_client_cls.return_value = mock_client

        out = self.adapter.transcribe_audio(b"silent_audio_bytes", mime_type="audio/ogg")
        assert out == "[ΣΙΩΠΗ]"

    @patch("google.genai.Client")
    def test_transcribe_audio_fallback_on_unsupported_model(self, mock_client_cls, caplog):
        mock_dedicated_client = MagicMock()
        mock_fallback_client = MagicMock()

        # 1. First scenario: 404 NOT_FOUND on dedicated global client -> falls back to Flash
        mock_dedicated_client.models.generate_content.side_effect = Exception("404 NOT_FOUND: Publisher Model gemini-3.5-transcribe-preview not found")
        mock_resp_fallback = MagicMock()
        mock_resp_fallback.text = "Fallback Flash transcribed voice"
        mock_fallback_client.models.generate_content.return_value = mock_resp_fallback

        def _client_factory(**kwargs):
            if kwargs.get("location") == "global":
                return mock_dedicated_client
            return mock_fallback_client

        mock_client_cls.side_effect = _client_factory

        import logging
        with caplog.at_level(logging.WARNING):
            out = self.adapter.transcribe_audio(b"audio_bytes", mime_type="audio/ogg")

        assert out == "Fallback Flash transcribed voice"
        assert mock_dedicated_client.models.generate_content.call_count == 1
        assert mock_fallback_client.models.generate_content.call_count == 1

        # Verify fallback call uses fast_model, normal location, and AUDIO_TRANSCRIPTION_PROMPT
        fallback_kwargs = mock_fallback_client.models.generate_content.call_args.kwargs
        assert fallback_kwargs["model"] == self.adapter.fast_model
        assert fallback_kwargs["contents"][1] == AUDIO_TRANSCRIPTION_PROMPT
        assert "Falling back to generic Flash transcription" in caplog.text

        # 2. Second scenario: Model unavailable phrasing -> also triggers Flash fallback
        caplog.clear()
        mock_dedicated_client.models.generate_content.side_effect = Exception("Model 'gemini-3.5-transcribe-preview' is unavailable in region global")
        with caplog.at_level(logging.WARNING):
            out_unavail = self.adapter.transcribe_audio(b"audio_bytes", mime_type="audio/ogg")

        assert out_unavail == "Fallback Flash transcribed voice"
        assert mock_dedicated_client.models.generate_content.call_count == 2
        assert mock_fallback_client.models.generate_content.call_count == 2
        assert "Falling back to generic Flash transcription" in caplog.text

    @patch("google.genai.Client")
    def test_transcribe_audio_auth_and_quota_errors_never_fallback(self, mock_client_cls):
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client

        # 1. Auth Error -> raises ProviderAuthError and never attempts fallback
        mock_client.models.generate_content.side_effect = Exception("403 PERMISSION_DENIED: Vertex AI IAM permission denied")
        with pytest.raises(ProviderAuthError) as exc_auth:
            self.adapter.transcribe_audio(b"audio_bytes")
        assert exc_auth.value.provider == "vertex"
        assert mock_client.models.generate_content.call_count == 1

        # 2. Invalid Scope -> raises ProviderAuthError and never attempts fallback
        mock_client.models.generate_content.side_effect = Exception("invalid_scope: Invalid OAuth scope")
        with pytest.raises(ProviderAuthError) as exc_scope:
            self.adapter.transcribe_audio(b"audio_bytes")
        assert exc_scope.value.provider == "vertex"
        assert mock_client.models.generate_content.call_count == 2

        # 3. Quota Error -> raises RateLimitError and never attempts fallback
        mock_client.models.generate_content.side_effect = Exception("429 RESOURCE_EXHAUSTED: Vertex AI quota exceeded")
        with pytest.raises(RateLimitError) as exc_rate:
            self.adapter.transcribe_audio(b"audio_bytes")
        assert exc_rate.value.provider == "vertex"
        assert mock_client.models.generate_content.call_count == 3

    @patch("google.genai.Client")
    def test_transcribe_audio_validation_and_transient_errors_never_fallback(self, mock_client_cls):
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client

        # 1. 400 Bad Request / Invalid Audio format -> raises AIProviderError, no fallback
        mock_client.models.generate_content.side_effect = Exception("400 INVALID_ARGUMENT: Unsupported MIME type audio/invalid")
        with pytest.raises(AIProviderError) as exc_val:
            self.adapter.transcribe_audio(b"audio_bytes")
        assert exc_val.value.provider == "vertex"
        assert mock_client.models.generate_content.call_count == 1

        # 2. 503 Transient Service Unavailable -> raises AIProviderError, no fallback
        mock_client.models.generate_content.side_effect = Exception("503 UNAVAILABLE: Service temporarily overloaded")
        with pytest.raises(AIProviderError) as exc_503:
            self.adapter.transcribe_audio(b"audio_bytes")
        assert exc_503.value.provider == "vertex"
        assert mock_client.models.generate_content.call_count == 2

        # 3. General service unavailable phrase -> raises AIProviderError, no fallback
        mock_client.models.generate_content.side_effect = Exception("503: Backend service unavailable")
        with pytest.raises(AIProviderError) as exc_srv:
            self.adapter.transcribe_audio(b"audio_bytes")
        assert exc_srv.value.provider == "vertex"
        assert mock_client.models.generate_content.call_count == 3

        # 4. Timeout / Connection error -> raises AIProviderError, no fallback
        mock_client.models.generate_content.side_effect = TimeoutError("Connection timed out")
        with pytest.raises(AIProviderError) as exc_to:
            self.adapter.transcribe_audio(b"audio_bytes")
        assert exc_to.value.provider == "vertex"
        assert mock_client.models.generate_content.call_count == 4

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

    @patch("langchain_google_genai.GoogleGenerativeAIEmbeddings.embed_documents")
    def test_embed_text_scalar_is_one_document(self, mock_embed):
        mock_embed.return_value = [[0.03] * 768]
        vecs = self.adapter.embed_text("one document")
        assert len(vecs) == 1
        mock_embed.assert_called_once_with(["one document"])

    @patch("langchain_google_genai.GoogleGenerativeAIEmbeddings.embed_query")
    def test_embed_query_success(self, mock_query):
        mock_query.return_value = [0.09] * 768
        vecs = self.adapter.embed_text(["single query"], is_query=True)
        assert len(vecs) == 1
        assert len(vecs[0]) == 768

    @patch("langchain_google_genai.GoogleGenerativeAIEmbeddings.embed_query")
    def test_embed_query_batch_uses_query_mode_for_every_text(self, mock_query):
        mock_query.side_effect = [[0.1] * 768, [0.2] * 768]
        vecs = self.adapter.embed_text(["query one", "query two"], is_query=True)
        assert vecs == [[0.1] * 768, [0.2] * 768]
        assert mock_query.call_args_list[0].args == ("query one",)
        assert mock_query.call_args_list[1].args == ("query two",)

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

        # Symbolic-only RATE_LIMIT_EXCEEDED without numeric 429
        mock_invoke.side_effect = Exception("RATE_LIMIT_EXCEEDED: Vertex project rate limit exceeded")
        with pytest.raises(RateLimitError) as exc_rate_sym:
            self.adapter.generate_text("test")
        assert exc_rate_sym.value.provider == "vertex"

    @patch("langchain_google_genai.ChatGoogleGenerativeAI.invoke")
    def test_google_credential_errors_map_to_auth_error(self, mock_invoke):
        from google.auth.exceptions import DefaultCredentialsError, RefreshError

        for error in (DefaultCredentialsError("Application Default Credentials unavailable"), RefreshError("Token refresh failed")):
            mock_invoke.side_effect = error
            with pytest.raises(ProviderAuthError) as exc_info:
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

    def test_explicit_empty_api_key_raises_auth_error(self):
        empty_adapter = AnthropicAdapter(api_key="")
        with pytest.raises(ProviderAuthError) as exc_text:
            empty_adapter.generate_text("test")
        assert exc_text.value.provider == "anthropic"

        with pytest.raises(ProviderAuthError) as exc_vis:
            empty_adapter.analyze_vision("look", b"fake_bytes")
        assert exc_vis.value.provider == "anthropic"


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
        assert hasattr(brain, "custom_safety")
        assert hasattr(brain, "safe_llm_invoke")
        assert hasattr(brain, "get_active_provider_adapter")

    def test_get_active_provider_adapter_returns_singleton(self):
        from core.brain import get_active_provider_adapter
        adapter1 = get_active_provider_adapter()
        adapter2 = get_active_provider_adapter()
        assert adapter1 is adapter2
        assert isinstance(adapter1, AIProviderAdapter)

    def test_get_active_provider_adapter_thread_safety(self):
        import core.brain as brain
        orig_adapter = brain._active_provider_adapter
        try:
            brain._active_provider_adapter = None
            results = []
            with ThreadPoolExecutor(max_workers=10) as executor:
                futures = [executor.submit(brain.get_active_provider_adapter) for _ in range(20)]
                for f in futures:
                    results.append(f.result())

            # All 20 threads must obtain the exact same singleton instance
            assert len(results) == 20
            first_instance = results[0]
            for inst in results:
                assert inst is first_instance
        finally:
            brain._active_provider_adapter = orig_adapter

    def test_unknown_provider_in_brain_defaults_to_vertex_adapter(self):
        import core.brain as brain
        orig_adapter = brain._active_provider_adapter
        orig_provider = brain._provider
        try:
            effective_provider = brain._effective_provider("completely_unknown_provider_xyz")
            assert effective_provider == "vertex"
            expected_fast, expected_heavy = brain.resolve_provider_models("vertex")
            assert (expected_fast, expected_heavy) == brain.resolve_provider_models(
                effective_provider,
            )

            brain._provider = "completely_unknown_provider_xyz"
            brain._active_provider_adapter = None
            adapter = brain.get_active_provider_adapter()
            assert isinstance(adapter, VertexAIAdapter)
            assert adapter.provider_name == "vertex"
        finally:
            brain._provider = orig_provider
            brain._active_provider_adapter = orig_adapter
