# ================================================================
# Project: Astakos AI Agent 🦞
# Module:  Test Provider Mocks
# Description: Deterministic offline mock adapters for contract testing
# Copyright (c) 2026 - All Rights Reserved
# ================================================================

from __future__ import annotations

from typing import Sequence
from core.ai_provider import (
    AIProviderAdapter,
    CapabilityNotSupportedError,
    normalize_embedding_texts,
    ProviderAuthError,
    RateLimitError,
)


import io
from PIL import Image

def _make_mock_jpeg() -> bytes:
    img = Image.new("RGB", (16, 16), color=(0, 128, 255))
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()

def _make_mock_png() -> bytes:
    img = Image.new("RGBA", (16, 16), color=(255, 100, 50, 180))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()

MOCK_JPEG_BYTES: bytes = _make_mock_jpeg()
MOCK_PNG_BYTES: bytes = _make_mock_png()


class MockOpenAIAdapter(AIProviderAdapter):
    provider_name = "openai"
    supported_capabilities = {"text", "vision", "audio_stt", "image_gen", "embeddings"}

    def __init__(self, should_fail_auth: bool = False, should_rate_limit: bool = False):
        self.should_fail_auth = should_fail_auth
        self.should_rate_limit = should_rate_limit

    def _check_faults(self):
        if self.should_fail_auth:
            raise ProviderAuthError("openai", "Invalid OpenAI API key.")
        if self.should_rate_limit:
            raise RateLimitError("openai", "OpenAI rate limit exceeded (429).", retry_after=5.0)

    def generate_text(self, prompt: str, model_type: str = "fast", system_prompt: str | None = None, temperature: float | None = None) -> str:
        self._check_faults()
        return f"[OpenAI Mock Text]: {prompt}"

    def analyze_vision(self, prompt: str, image_bytes: bytes, mime_type: str = "image/jpeg") -> str:
        self._check_faults()
        return f"[OpenAI Mock Vision ({len(image_bytes)} bytes)]: {prompt}"

    def transcribe_audio(self, audio_bytes: bytes, mime_type: str = "audio/ogg") -> str:
        self._check_faults()
        return "[OpenAI Mock Audio]: Transcribed test voice"

    def generate_image(self, prompt: str, aspect_ratio: str = "1:1") -> bytes:
        self._check_faults()
        return MOCK_PNG_BYTES


    def embed_text(self, texts: str | Sequence[str], is_query: bool = False) -> list[list[float]]:
        self._check_faults()
        # Returns 1536-dimensional mock vectors
        return [[0.01 * (i + 1) for i in range(1536)] for _ in normalize_embedding_texts(texts)]


class MockGeminiAPIAdapter(AIProviderAdapter):
    provider_name = "gemini"
    supported_capabilities = {"text", "vision", "audio_stt", "image_gen", "embeddings"}

    def __init__(self, should_fail_auth: bool = False, should_rate_limit: bool = False):
        self.should_fail_auth = should_fail_auth
        self.should_rate_limit = should_rate_limit

    def _check_faults(self):
        if self.should_fail_auth:
            raise ProviderAuthError("gemini", "Invalid Gemini API key.")
        if self.should_rate_limit:
            raise RateLimitError("gemini", "Gemini quota exceeded (429).", retry_after=10.0)

    def generate_text(self, prompt: str, model_type: str = "fast", system_prompt: str | None = None, temperature: float | None = None) -> str:
        self._check_faults()
        return f"[Gemini Mock Text]: {prompt}"

    def analyze_vision(self, prompt: str, image_bytes: bytes, mime_type: str = "image/jpeg") -> str:
        self._check_faults()
        return f"[Gemini Mock Vision ({len(image_bytes)} bytes)]: {prompt}"

    def transcribe_audio(self, audio_bytes: bytes, mime_type: str = "audio/ogg") -> str:
        self._check_faults()
        return "[Gemini Mock Audio]: Transcribed test voice"

    def generate_image(self, prompt: str, aspect_ratio: str = "1:1") -> bytes:
        self._check_faults()
        return MOCK_JPEG_BYTES

    def embed_text(self, texts: str | Sequence[str], is_query: bool = False) -> list[list[float]]:
        self._check_faults()
        # Returns 768-dimensional mock vectors
        return [[0.02 * (i + 1) for i in range(768)] for _ in normalize_embedding_texts(texts)]


class MockVertexAIAdapter(AIProviderAdapter):
    provider_name = "vertex"
    supported_capabilities = {"text", "vision", "audio_stt", "image_gen", "embeddings"}

    def __init__(self, should_fail_auth: bool = False, should_rate_limit: bool = False):
        self.should_fail_auth = should_fail_auth
        self.should_rate_limit = should_rate_limit

    def _check_faults(self):
        if self.should_fail_auth:
            raise ProviderAuthError("vertex", "Vertex AI permission denied (403).")
        if self.should_rate_limit:
            raise RateLimitError("vertex", "Vertex AI resource exhausted (429).", retry_after=15.0)

    def generate_text(self, prompt: str, model_type: str = "fast", system_prompt: str | None = None, temperature: float | None = None) -> str:
        self._check_faults()
        return f"[Vertex Mock Text]: {prompt}"

    def analyze_vision(self, prompt: str, image_bytes: bytes, mime_type: str = "image/jpeg") -> str:
        self._check_faults()
        return f"[Vertex Mock Vision ({len(image_bytes)} bytes)]: {prompt}"

    def transcribe_audio(self, audio_bytes: bytes, mime_type: str = "audio/ogg") -> str:
        self._check_faults()
        return "[Vertex Mock Audio]: Transcribed test voice"

    def generate_image(self, prompt: str, aspect_ratio: str = "1:1") -> bytes:
        self._check_faults()
        return MOCK_JPEG_BYTES


    def embed_text(self, texts: str | Sequence[str], is_query: bool = False) -> list[list[float]]:
        self._check_faults()
        # Returns 768-dimensional mock vectors
        return [[0.03 * (i + 1) for i in range(768)] for _ in normalize_embedding_texts(texts)]


class MockAnthropicAdapter(AIProviderAdapter):
    provider_name = "anthropic"
    supported_capabilities = {"text", "vision"}

    def __init__(self, should_fail_auth: bool = False, should_rate_limit: bool = False):
        self.should_fail_auth = should_fail_auth
        self.should_rate_limit = should_rate_limit

    def _check_faults(self):
        if self.should_fail_auth:
            raise ProviderAuthError("anthropic", "Invalid Anthropic API key.")
        if self.should_rate_limit:
            raise RateLimitError("anthropic", "Anthropic rate limit exceeded (429).", retry_after=8.0)

    def generate_text(self, prompt: str, model_type: str = "fast", system_prompt: str | None = None, temperature: float | None = None) -> str:
        self._check_faults()
        return f"[Anthropic Mock Text]: {prompt}"

    def analyze_vision(self, prompt: str, image_bytes: bytes, mime_type: str = "image/jpeg") -> str:
        self._check_faults()
        return f"[Anthropic Mock Vision ({len(image_bytes)} bytes)]: {prompt}"

    def transcribe_audio(self, audio_bytes: bytes, mime_type: str = "audio/ogg") -> str:
        raise CapabilityNotSupportedError(
            provider="anthropic",
            capability="audio_stt",
            message="Audio transcription is not supported natively by Anthropic.",
        )

    def generate_image(self, prompt: str, aspect_ratio: str = "1:1") -> bytes:
        raise CapabilityNotSupportedError(
            provider="anthropic",
            capability="image_gen",
            message="Image generation is not supported by Anthropic.",
        )

    def embed_text(self, texts: str | Sequence[str], is_query: bool = False) -> list[list[float]]:
        raise CapabilityNotSupportedError(
            provider="anthropic",
            capability="embeddings",
            message="Embeddings are not supported natively by Anthropic.",
        )
