# ================================================================
# Project: Astakos AI Agent 🦞
# Module:  Core AI Provider Adapter Contract & Implementations
# Description: Central provider capability abstraction layer
# Copyright (c) 2026 - All Rights Reserved
# ================================================================

from __future__ import annotations

import base64
import os
from abc import ABC, abstractmethod
from typing import Any, Sequence

import config


# ────────────────────────────────────────────────────────────────
# 1. SHARED MODEL & SAFETY RESOLUTION (Single Source of Truth)
# ────────────────────────────────────────────────────────────────

DEFAULT_GEMINI_FAST_MODEL = "gemini-3.5-flash"
DEFAULT_GEMINI_HEAVY_MODEL = "gemini-3.1-pro-preview"


def google_model_from_environment(variable_name: str, default_model: str, emit_warning: bool = False) -> str:
    """Return an optional Google-model override, surfacing active overrides at startup if requested."""
    configured_model = os.getenv(variable_name, "").strip()
    if not configured_model:
        return default_model
    if emit_warning and configured_model != default_model:
        print(
            "\033[93m[Brain]: Google model override active "
            f"({variable_name}={configured_model!r}; default={default_model!r}). "
            "Verify that the configured Gemini model is available.\033[0m",
        )
    return configured_model


def resolve_provider_models(
    provider_name: str,
    fast_override: str | None = None,
    heavy_override: str | None = None,
    emit_warnings: bool = False,
) -> tuple[str, str]:
    """Return (fast_model, heavy_model) for the given provider without hardcoded divergence."""
    provider = (provider_name or "").strip().lower()
    if provider == "openai":
        return (fast_override or "gpt-4o-mini", heavy_override or "gpt-4o")
    elif provider == "anthropic":
        return (fast_override or "claude-3-5-haiku-latest", heavy_override or "claude-3-5-sonnet-latest")
    elif provider in ("gemini", "vertex"):
        fast = fast_override or google_model_from_environment(
            "ASTAKOS_GEMINI_FAST_MODEL", DEFAULT_GEMINI_FAST_MODEL, emit_warning=emit_warnings
        )
        heavy = heavy_override or google_model_from_environment(
            "ASTAKOS_GEMINI_HEAVY_MODEL", DEFAULT_GEMINI_HEAVY_MODEL, emit_warning=emit_warnings
        )
        return (fast, heavy)
    return (fast_override or "fast-model", heavy_override or "heavy-model")


def resolve_vertex_location(location: str | None = None) -> str:
    """Return the legacy Vertex location, allowing an explicit adapter override."""
    return os.getenv("LOCATION", "global") if location is None else location


def normalize_embedding_texts(texts: str | Sequence[str]) -> list[str]:
    """Normalize one text or a sequence of texts into provider-safe embedding input."""
    normalized = [texts] if isinstance(texts, str) else list(texts)
    if not all(isinstance(text, str) for text in normalized):
        raise TypeError("Embedding input must contain only strings.")
    return normalized


def resolve_gemini_safety_threshold() -> Any:
    """Return the configured HarmBlockThreshold, defaulting to BLOCK_NONE."""
    from langchain_google_genai import HarmBlockThreshold
    raw = os.getenv("ASTAKOS_GEMINI_SAFETY_THRESHOLD", "").strip().upper()
    if not raw:
        return HarmBlockThreshold.BLOCK_NONE
    mapping = {
        "BLOCK_NONE": HarmBlockThreshold.BLOCK_NONE,
        "BLOCK_ONLY_HIGH": HarmBlockThreshold.BLOCK_ONLY_HIGH,
        "BLOCK_MEDIUM_AND_ABOVE": HarmBlockThreshold.BLOCK_MEDIUM_AND_ABOVE,
        "BLOCK_LOW_AND_ABOVE": HarmBlockThreshold.BLOCK_LOW_AND_ABOVE,
    }
    if raw in mapping:
        if raw != "BLOCK_NONE":
            print(f"\033[93m[Brain]: Gemini safety threshold active ({raw}).\033[0m")
        return mapping[raw]
    print(
        f"\033[93m[Brain]: Unknown safety threshold {raw!r}, falling back to BLOCK_NONE.\033[0m"
    )
    return HarmBlockThreshold.BLOCK_NONE


def get_gemini_safety_settings() -> dict[Any, Any]:
    """Return the dictionary of safety categories mapped to the resolved threshold."""
    from langchain_google_genai import HarmCategory
    threshold = resolve_gemini_safety_threshold()
    return {
        HarmCategory.HARM_CATEGORY_HARASSMENT:         threshold,
        HarmCategory.HARM_CATEGORY_HATE_SPEECH:        threshold,
        HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT:  threshold,
        HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT:  threshold,
        HarmCategory.HARM_CATEGORY_CIVIC_INTEGRITY:    threshold,
    }


# ────────────────────────────────────────────────────────────────
# 2. TYPED EXCEPTIONS & ERROR TAXONOMY
# ────────────────────────────────────────────────────────────────

class AIProviderError(Exception):
    """Base exception for all AI provider operations."""

    def __init__(self, message: str, provider: str | None = None, original_error: Exception | None = None):
        self.provider = provider or "unknown"
        self.original_error = original_error
        super().__init__(message)


class CapabilityNotSupportedError(AIProviderError):
    """Raised when an operation is not supported by the active provider."""

    def __init__(self, provider: str, capability: str, message: str | None = None):
        self.capability = capability
        self.user_message = message or f"Capability '{capability}' is not supported by provider '{provider}'."
        super().__init__(self.user_message, provider=provider)


class ProviderAuthError(AIProviderError):
    """Raised when authentication with the provider fails."""

    def __init__(self, provider: str, message: str | None = None, original_error: Exception | None = None):
        user_msg = message or f"Authentication failed for provider '{provider}'. Please verify your credentials."
        super().__init__(user_msg, provider=provider, original_error=original_error)


class RateLimitError(AIProviderError):
    """Raised when rate limits or quotas are exceeded."""

    def __init__(self, provider: str, message: str | None = None, retry_after: float | None = None, original_error: Exception | None = None):
        self.retry_after = retry_after
        user_msg = message or f"Rate limit or quota exceeded for provider '{provider}'."
        super().__init__(user_msg, provider=provider, original_error=original_error)


# ────────────────────────────────────────────────────────────────
# 3. ABSTRACT BASE ADAPTER CONTRACT
# ────────────────────────────────────────────────────────────────

class AIProviderAdapter(ABC):
    """Abstract interface defining the 5 standard provider operations."""

    provider_name: str = "base"
    supported_capabilities: set[str] = set()

    def is_capability_supported(self, capability: str) -> bool:
        """Return True if the capability is natively supported by this adapter."""
        return capability in self.supported_capabilities

    @abstractmethod
    def generate_text(
        self,
        prompt: str,
        model_type: str = "fast",
        system_prompt: str | None = None,
        temperature: float | None = None,
    ) -> str:
        """Generate text response from the provider."""

    @abstractmethod
    def analyze_vision(
        self,
        prompt: str,
        image_bytes: bytes,
        mime_type: str = "image/jpeg",
    ) -> str:
        """Analyze an image with multimodal prompt."""

    @abstractmethod
    def transcribe_audio(
        self,
        audio_bytes: bytes,
        mime_type: str = "audio/ogg",
    ) -> str:
        """Transcribe speech audio bytes to text."""

    @abstractmethod
    def generate_image(
        self,
        prompt: str,
        aspect_ratio: str = "1:1",
    ) -> bytes:
        """Generate an image and return raw image bytes."""

    @abstractmethod
    def embed_text(
        self,
        texts: str | Sequence[str],
        is_query: bool = False,
    ) -> list[list[float]]:
        """Generate dense vector embeddings for texts."""


# ────────────────────────────────────────────────────────────────
# 4. CONCRETE PROVIDER ADAPTERS
# ────────────────────────────────────────────────────────────────

class OpenAIAdapter(AIProviderAdapter):
    """Adapter for OpenAI (GPT-4o, Whisper, DALL-E, Embeddings)."""

    provider_name = "openai"
    supported_capabilities = {"text", "vision", "audio_stt", "image_gen", "embeddings"}

    def __init__(self, api_key: str | None = None, fast_model: str | None = None, heavy_model: str | None = None):
        self.api_key = getattr(config, "OPENAI_API_KEY", "") if api_key is None else api_key
        self.fast_model, self.heavy_model = resolve_provider_models("openai", fast_model, heavy_model)
        self.embedding_model = "text-embedding-3-small"

    def _get_llm(self, model_type: str = "fast", temperature: float | None = None):
        if not self.api_key:
            raise ProviderAuthError("openai", "OPENAI_API_KEY is not configured.")
        from langchain_openai import ChatOpenAI
        model = self.heavy_model if model_type == "heavy" else self.fast_model
        temp = temperature if temperature is not None else (0.1 if model_type == "heavy" else 0.7)
        return ChatOpenAI(model=model, temperature=temp, api_key=self.api_key)

    def generate_text(
        self,
        prompt: str,
        model_type: str = "fast",
        system_prompt: str | None = None,
        temperature: float | None = None,
    ) -> str:
        try:
            llm = self._get_llm(model_type=model_type, temperature=temperature)
            messages = []
            if system_prompt:
                from langchain_core.messages import SystemMessage
                messages.append(SystemMessage(content=system_prompt))
            from langchain_core.messages import HumanMessage
            messages.append(HumanMessage(content=prompt))
            response = llm.invoke(messages)
            return getattr(response, "content", "") or ""
        except Exception as e:
            self._handle_exception(e)

    def analyze_vision(
        self,
        prompt: str,
        image_bytes: bytes,
        mime_type: str = "image/jpeg",
    ) -> str:
        try:
            llm = self._get_llm(model_type="fast")
            b64_data = base64.b64encode(image_bytes).decode("utf-8")
            from langchain_core.messages import HumanMessage
            message = HumanMessage(
                content=[
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{b64_data}"}},
                ]
            )
            response = llm.invoke([message])
            return getattr(response, "content", "") or ""
        except Exception as e:
            self._handle_exception(e)

    def transcribe_audio(
        self,
        audio_bytes: bytes,
        mime_type: str = "audio/ogg",
    ) -> str:
        if not self.api_key:
            raise ProviderAuthError("openai", "OPENAI_API_KEY is not configured.")

        extension_by_mime = {
            "audio/aac": "aac",
            "audio/flac": "flac",
            "audio/m4a": "m4a",
            "audio/mp3": "mp3",
            "audio/mp4": "mp4",
            "audio/mpeg": "mp3",
            "audio/mpga": "mpga",
            "audio/ogg": "ogg",
            "audio/wav": "wav",
            "audio/webm": "webm",
            "audio/x-m4a": "m4a",
            "audio/x-wav": "wav",
        }
        normalized_mime_type = mime_type.strip().lower()
        extension = extension_by_mime.get(normalized_mime_type)
        if extension is None:
            raise CapabilityNotSupportedError(
                provider="openai",
                capability="audio_stt",
                message=f"Audio MIME type '{mime_type}' is not supported by OpenAI transcription.",
            )

        try:
            import requests
            headers = {"Authorization": f"Bearer {self.api_key}"}
            files = {"file": (f"audio.{extension}", audio_bytes, normalized_mime_type)}
            data = {"model": "whisper-1"}
            resp = requests.post("https://api.openai.com/v1/audio/transcriptions", headers=headers, files=files, data=data, timeout=30)
            if resp.status_code in (401, 403):
                raise ProviderAuthError("openai", f"OpenAI Whisper auth failed: {resp.text}")
            if resp.status_code == 429:
                raise RateLimitError("openai", "OpenAI Whisper quota exceeded.")
            resp_json = resp.json()
            if "error" in resp_json:
                raise AIProviderError(str(resp_json["error"]), provider="openai")
            return resp_json.get("text", "").strip()
        except AIProviderError:
            raise
        except Exception as e:
            self._handle_exception(e)

    def generate_image(
        self,
        prompt: str,
        aspect_ratio: str = "1:1",
    ) -> bytes:
        if not self.api_key:
            raise ProviderAuthError("openai", "OPENAI_API_KEY is not configured.")

        ratio_map = {
            "1:1": "1024x1024",
            "16:9": "1792x1024",
            "1792:1024": "1792x1024",
            "9:16": "1024x1792",
            "1024:1792": "1024x1792",
        }
        normalized_ratio = (aspect_ratio or "1:1").strip()
        if normalized_ratio not in ratio_map:
            raise CapabilityNotSupportedError(
                provider="openai",
                capability="image_gen",
                message=(
                    f"Aspect ratio '{aspect_ratio}' is not supported by OpenAI DALL-E 3. "
                    f"Supported ratios are '1:1' (1024x1024), '16:9' (1792x1024), and '9:16' (1024x1792)."
                ),
            )
        size = ratio_map[normalized_ratio]

        try:
            import requests
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            }
            data = {
                "model": "dall-e-3",
                "prompt": prompt,
                "n": 1,
                "size": size,
                "response_format": "b64_json",
            }
            resp = requests.post("https://api.openai.com/v1/images/generations", headers=headers, json=data, timeout=60)
            if resp.status_code in (401, 403):
                raise ProviderAuthError("openai", f"OpenAI DALL-E auth failed: {resp.text}")
            if resp.status_code == 429:
                raise RateLimitError("openai", "OpenAI DALL-E rate limit exceeded.")
            resp_json = resp.json()
            if "error" in resp_json:
                raise AIProviderError(str(resp_json["error"]), provider="openai")
            b64_str = resp_json["data"][0]["b64_json"]
            return base64.b64decode(b64_str)
        except AIProviderError:
            raise
        except Exception as e:
            self._handle_exception(e)

    def embed_text(
        self,
        texts: str | Sequence[str],
        is_query: bool = False,
    ) -> list[list[float]]:
        if not self.api_key:
            raise ProviderAuthError("openai", "OPENAI_API_KEY is not configured.")
        try:
            normalized_texts = normalize_embedding_texts(texts)
            from langchain_openai import OpenAIEmbeddings
            embeddings_client = OpenAIEmbeddings(model=self.embedding_model, api_key=self.api_key)
            if is_query:
                return [embeddings_client.embed_query(text) for text in normalized_texts]
            return embeddings_client.embed_documents(normalized_texts)
        except Exception as e:
            self._handle_exception(e)

    def _handle_exception(self, e: Exception) -> None:
        if isinstance(e, AIProviderError):
            raise e
        err_msg = str(e).lower()
        if "401" in err_msg or "unauthorized" in err_msg or "invalid api key" in err_msg or "forbidden" in err_msg:
            raise ProviderAuthError("openai", str(e), original_error=e) from e
        if "429" in err_msg or "quota" in err_msg or "rate limit" in err_msg or "resource exhausted" in err_msg:
            raise RateLimitError("openai", str(e), original_error=e) from e
        raise AIProviderError(str(e), provider="openai", original_error=e) from e


class GeminiAPIAdapter(AIProviderAdapter):
    """Adapter for Google AI Studio Gemini (API Key)."""

    provider_name = "gemini"
    supported_capabilities = {"text", "vision", "audio_stt", "image_gen", "embeddings"}

    def __init__(self, api_key: str | None = None, fast_model: str | None = None, heavy_model: str | None = None):
        if api_key is None:
            self.api_key = getattr(config, "GEMINI_API_KEY", "") or getattr(config, "GOOGLE_API_KEY", "")
        else:
            self.api_key = api_key
        self.fast_model, self.heavy_model = resolve_provider_models("gemini", fast_model, heavy_model)

    def _get_llm(self, model_type: str = "fast", temperature: float | None = None):
        if not self.api_key:
            raise ProviderAuthError("gemini", "GEMINI_API_KEY is not configured.")
        from langchain_google_genai import ChatGoogleGenerativeAI
        model = self.heavy_model if model_type == "heavy" else self.fast_model
        temp = temperature if temperature is not None else (0.1 if model_type == "heavy" else 0.7)
        safety_settings = get_gemini_safety_settings()
        return ChatGoogleGenerativeAI(model=model, temperature=temp, safety_settings=safety_settings, api_key=self.api_key)

    def _get_genai_client(self):
        if not self.api_key:
            raise ProviderAuthError("gemini", "GEMINI_API_KEY is not configured.")
        from google import genai
        return genai.Client(api_key=self.api_key)

    def generate_text(
        self,
        prompt: str,
        model_type: str = "fast",
        system_prompt: str | None = None,
        temperature: float | None = None,
    ) -> str:
        try:
            llm = self._get_llm(model_type=model_type, temperature=temperature)
            messages = []
            if system_prompt:
                from langchain_core.messages import SystemMessage
                messages.append(SystemMessage(content=system_prompt))
            from langchain_core.messages import HumanMessage
            messages.append(HumanMessage(content=prompt))
            response = llm.invoke(messages)
            return getattr(response, "content", "") or ""
        except Exception as e:
            self._handle_exception(e)

    def analyze_vision(
        self,
        prompt: str,
        image_bytes: bytes,
        mime_type: str = "image/jpeg",
    ) -> str:
        try:
            llm = self._get_llm(model_type="fast")
            b64_data = base64.b64encode(image_bytes).decode("utf-8")
            from langchain_core.messages import HumanMessage
            message = HumanMessage(
                content=[
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{b64_data}"}},
                ]
            )
            response = llm.invoke([message])
            return getattr(response, "content", "") or ""
        except Exception as e:
            self._handle_exception(e)

    def transcribe_audio(
        self,
        audio_bytes: bytes,
        mime_type: str = "audio/ogg",
    ) -> str:
        try:
            client = self._get_genai_client()
            response = client.models.generate_content(
                model=self.fast_model,
                contents=[
                    {"inline_data": {"mime_type": mime_type, "data": audio_bytes}},
                    "Transcribe the spoken audio accurately into text without extra commentary.",
                ],
            )
            return getattr(response, "text", "").strip() if getattr(response, "text", None) else ""
        except Exception as e:
            self._handle_exception(e)

    def generate_image(
        self,
        prompt: str,
        aspect_ratio: str = "1:1",
    ) -> bytes:
        try:
            client = self._get_genai_client()
            from google.genai import types
            response = client.models.generate_images(
                model="imagen-3.0-generate-001",
                prompt=prompt,
                config=types.GenerateImagesConfig(number_of_images=1, aspect_ratio=aspect_ratio),
            )
            if not response.generated_images:
                raise AIProviderError("Gemini Imagen returned no generated images.", provider="gemini")
            img_obj = response.generated_images[0].image
            if hasattr(img_obj, "image_bytes"):
                return img_obj.image_bytes
            import io
            buf = io.BytesIO()
            img_obj.save(buf, format="JPEG")
            return buf.getvalue()
        except Exception as e:
            self._handle_exception(e)

    def embed_text(
        self,
        texts: str | Sequence[str],
        is_query: bool = False,
    ) -> list[list[float]]:
        if not self.api_key:
            raise ProviderAuthError("gemini", "GEMINI_API_KEY is not configured.")
        try:
            normalized_texts = normalize_embedding_texts(texts)
            from langchain_google_genai import GoogleGenerativeAIEmbeddings
            emb_client = GoogleGenerativeAIEmbeddings(model="models/text-embedding-004", google_api_key=self.api_key)
            if is_query:
                return [emb_client.embed_query(text) for text in normalized_texts]
            return emb_client.embed_documents(normalized_texts)
        except Exception as e:
            self._handle_exception(e)

    def _handle_exception(self, e: Exception) -> None:
        if isinstance(e, AIProviderError):
            raise e
        err_msg = str(e).lower()
        if (
            "401" in err_msg
            or "unauthorized" in err_msg
            or "permission_denied" in err_msg
            or "403" in err_msg
            or "api_key_invalid" in err_msg
            or "api key not valid" in err_msg
            or "invalid api key" in err_msg
        ):
            raise ProviderAuthError("gemini", str(e), original_error=e) from e
        if "429" in err_msg or "quota" in err_msg or "resource_exhausted" in err_msg:
            raise RateLimitError("gemini", str(e), original_error=e) from e
        raise AIProviderError(str(e), provider="gemini", original_error=e) from e


class VertexAIAdapter(AIProviderAdapter):
    """Adapter for Google Cloud Vertex AI (Service Account)."""

    provider_name = "vertex"
    supported_capabilities = {"text", "vision", "audio_stt", "image_gen", "embeddings"}

    def __init__(
        self,
        project_id: str | None = None,
        location: str | None = None,
        fast_model: str | None = None,
        heavy_model: str | None = None,
    ):
        self.project_id = project_id or getattr(config, "PROJECT_ID", "your-gcp-project-id")
        self.location = resolve_vertex_location(location)
        self.fast_model, self.heavy_model = resolve_provider_models("vertex", fast_model, heavy_model)

    def _get_llm(self, model_type: str = "fast", temperature: float | None = None):
        from langchain_google_genai import ChatGoogleGenerativeAI
        model = self.heavy_model if model_type == "heavy" else self.fast_model
        temp = temperature if temperature is not None else (0.1 if model_type == "heavy" else 0.7)
        safety_settings = get_gemini_safety_settings()
        return ChatGoogleGenerativeAI(
            model=model,
            temperature=temp,
            safety_settings=safety_settings,
            vertexai=True,
            project=self.project_id,
            location=self.location,
        )

    def _get_genai_client(self):
        from google import genai
        return genai.Client(
            vertexai=True,
            project=self.project_id,
            location=self.location,
        )

    def generate_text(
        self,
        prompt: str,
        model_type: str = "fast",
        system_prompt: str | None = None,
        temperature: float | None = None,
    ) -> str:
        try:
            llm = self._get_llm(model_type=model_type, temperature=temperature)
            messages = []
            if system_prompt:
                from langchain_core.messages import SystemMessage
                messages.append(SystemMessage(content=system_prompt))
            from langchain_core.messages import HumanMessage
            messages.append(HumanMessage(content=prompt))
            response = llm.invoke(messages)
            return getattr(response, "content", "") or ""
        except Exception as e:
            self._handle_exception(e)

    def analyze_vision(
        self,
        prompt: str,
        image_bytes: bytes,
        mime_type: str = "image/jpeg",
    ) -> str:
        try:
            llm = self._get_llm(model_type="fast")
            b64_data = base64.b64encode(image_bytes).decode("utf-8")
            from langchain_core.messages import HumanMessage
            message = HumanMessage(
                content=[
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{b64_data}"}},
                ]
            )
            response = llm.invoke([message])
            return getattr(response, "content", "") or ""
        except Exception as e:
            self._handle_exception(e)

    def transcribe_audio(
        self,
        audio_bytes: bytes,
        mime_type: str = "audio/ogg",
    ) -> str:
        try:
            client = self._get_genai_client()
            response = client.models.generate_content(
                model=self.fast_model,
                contents=[
                    {"inline_data": {"mime_type": mime_type, "data": audio_bytes}},
                    "Transcribe the spoken audio accurately into text without extra commentary.",
                ],
            )
            return getattr(response, "text", "").strip() if getattr(response, "text", None) else ""
        except Exception as e:
            self._handle_exception(e)

    def generate_image(
        self,
        prompt: str,
        aspect_ratio: str = "1:1",
    ) -> bytes:
        try:
            client = self._get_genai_client()
            from google.genai import types
            response = client.models.generate_images(
                model="imagen-3.0-generate-001",
                prompt=prompt,
                config=types.GenerateImagesConfig(number_of_images=1, aspect_ratio=aspect_ratio),
            )
            if not response.generated_images:
                raise AIProviderError("Vertex AI Imagen returned no generated images.", provider="vertex")
            img_obj = response.generated_images[0].image
            if hasattr(img_obj, "image_bytes"):
                return img_obj.image_bytes
            import io
            buf = io.BytesIO()
            img_obj.save(buf, format="JPEG")
            return buf.getvalue()
        except Exception as e:
            self._handle_exception(e)

    def embed_text(
        self,
        texts: str | Sequence[str],
        is_query: bool = False,
    ) -> list[list[float]]:
        try:
            normalized_texts = normalize_embedding_texts(texts)
            from langchain_google_genai import GoogleGenerativeAIEmbeddings
            emb_client = GoogleGenerativeAIEmbeddings(
                model="text-embedding-004",
                vertexai=True,
                project=self.project_id,
                location=self.location,
            )
            if is_query:
                return [emb_client.embed_query(text) for text in normalized_texts]
            return emb_client.embed_documents(normalized_texts)
        except Exception as e:
            self._handle_exception(e)

    def _handle_exception(self, e: Exception) -> None:
        if isinstance(e, AIProviderError):
            raise e
        from google.auth.exceptions import DefaultCredentialsError, RefreshError
        if isinstance(e, (DefaultCredentialsError, RefreshError)):
            raise ProviderAuthError("vertex", str(e), original_error=e) from e
        err_msg = str(e).lower()
        if "permission_denied" in err_msg or "403" in err_msg or "401" in err_msg or "unauthenticated" in err_msg:
            raise ProviderAuthError("vertex", str(e), original_error=e) from e
        if "429" in err_msg or "quota" in err_msg or "resource_exhausted" in err_msg:
            raise RateLimitError("vertex", str(e), original_error=e) from e
        raise AIProviderError(str(e), provider="vertex", original_error=e) from e


class AnthropicAdapter(AIProviderAdapter):
    """Adapter for Anthropic Claude with explicit capability guardrails."""

    provider_name = "anthropic"
    supported_capabilities = {"text", "vision"}

    def __init__(self, api_key: str | None = None, fast_model: str | None = None, heavy_model: str | None = None):
        self.api_key = getattr(config, "ANTHROPIC_API_KEY", "") if api_key is None else api_key
        self.fast_model, self.heavy_model = resolve_provider_models("anthropic", fast_model, heavy_model)

    def _get_llm(self, model_type: str = "fast", temperature: float | None = None):
        if not self.api_key:
            raise ProviderAuthError("anthropic", "ANTHROPIC_API_KEY is not configured.")
        from langchain_anthropic import ChatAnthropic
        model = self.heavy_model if model_type == "heavy" else self.fast_model
        temp = temperature if temperature is not None else (0.1 if model_type == "heavy" else 0.7)
        return ChatAnthropic(model=model, temperature=temp, api_key=self.api_key)

    def generate_text(
        self,
        prompt: str,
        model_type: str = "fast",
        system_prompt: str | None = None,
        temperature: float | None = None,
    ) -> str:
        try:
            llm = self._get_llm(model_type=model_type, temperature=temperature)
            messages = []
            if system_prompt:
                from langchain_core.messages import SystemMessage
                messages.append(SystemMessage(content=system_prompt))
            from langchain_core.messages import HumanMessage
            messages.append(HumanMessage(content=prompt))
            response = llm.invoke(messages)
            return getattr(response, "content", "") or ""
        except Exception as e:
            self._handle_exception(e)

    def analyze_vision(
        self,
        prompt: str,
        image_bytes: bytes,
        mime_type: str = "image/jpeg",
    ) -> str:
        try:
            llm = self._get_llm(model_type="fast")
            b64_data = base64.b64encode(image_bytes).decode("utf-8")
            from langchain_core.messages import HumanMessage
            message = HumanMessage(
                content=[
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{b64_data}"}},
                ]
            )
            response = llm.invoke([message])
            return getattr(response, "content", "") or ""
        except Exception as e:
            self._handle_exception(e)

    def transcribe_audio(
        self,
        audio_bytes: bytes,
        mime_type: str = "audio/ogg",
    ) -> str:
        raise CapabilityNotSupportedError(
            provider="anthropic",
            capability="audio_stt",
            message="Audio transcription is not natively supported by Anthropic API alone. Multilingual local STT fallback will be configured in PR 3A.",
        )

    def generate_image(
        self,
        prompt: str,
        aspect_ratio: str = "1:1",
    ) -> bytes:
        raise CapabilityNotSupportedError(
            provider="anthropic",
            capability="image_gen",
            message="Image generation is not supported by Anthropic. Configure an OpenAI (DALL-E) or Google (Imagen) provider to generate images.",
        )

    def embed_text(
        self,
        texts: str | Sequence[str],
        is_query: bool = False,
    ) -> list[list[float]]:
        raise CapabilityNotSupportedError(
            provider="anthropic",
            capability="embeddings",
            message="Embeddings are not natively supported by Anthropic API alone. Multilingual local E5 embeddings fallback will be configured in PR 2.",
        )

    def _handle_exception(self, e: Exception) -> None:
        if isinstance(e, AIProviderError):
            raise e
        err_msg = str(e).lower()
        if "401" in err_msg or "unauthorized" in err_msg or "invalid api key" in err_msg or "authentication_error" in err_msg:
            raise ProviderAuthError("anthropic", str(e), original_error=e) from e
        if "429" in err_msg or "rate_limit" in err_msg:
            raise RateLimitError("anthropic", str(e), original_error=e) from e
        raise AIProviderError(str(e), provider="anthropic", original_error=e) from e


# ────────────────────────────────────────────────────────────────
# 5. PROVIDER ADAPTER FACTORY
# ────────────────────────────────────────────────────────────────

_ADAPTER_REGISTRY: dict[str, type[AIProviderAdapter]] = {
    "openai": OpenAIAdapter,
    "gemini": GeminiAPIAdapter,
    "vertex": VertexAIAdapter,
    "anthropic": AnthropicAdapter,
}


def get_provider_adapter(provider_name: str | None = None, **kwargs: Any) -> AIProviderAdapter:
    """Factory function returning the configured AIProviderAdapter instance."""
    resolved_name = (provider_name or getattr(config, "LLM_PROVIDER", "vertex")).strip().lower()
    adapter_cls = _ADAPTER_REGISTRY.get(resolved_name)
    if not adapter_cls:
        raise AIProviderError(f"Unknown AI provider: '{resolved_name}'. Valid options: {list(_ADAPTER_REGISTRY.keys())}")
    return adapter_cls(**kwargs)
