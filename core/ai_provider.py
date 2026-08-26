# ================================================================
# Project: Astakos AI Agent 🦞
# Module:  Core AI Provider Adapter Contract & Implementations
# Description: Central provider capability abstraction layer
# Copyright (c) 2026 - All Rights Reserved
# ================================================================

from __future__ import annotations

import base64
import hashlib
import os
from abc import ABC, abstractmethod
from typing import Any, Protocol, Sequence

import config


# ────────────────────────────────────────────────────────────────
# 1. SHARED MODEL & SAFETY RESOLUTION (Single Source of Truth)
# ────────────────────────────────────────────────────────────────

DEFAULT_GEMINI_FAST_MODEL = "gemini-3.5-flash"
DEFAULT_GEMINI_HEAVY_MODEL = "gemini-3.1-pro-preview"
DEFAULT_VERTEX_EMBEDDING_MODEL = "text-embedding-004"
DEFAULT_GEMINI_EMBEDDING_MODEL = "models/text-embedding-004"
DEFAULT_OPENAI_EMBEDDING_MODEL = "text-embedding-3-small"
DEFAULT_LOCAL_EMBEDDING_MODEL = "intfloat/multilingual-e5-small"
VERTEX_OAUTH_SCOPES: tuple[str, ...] = ("https://www.googleapis.com/auth/cloud-platform",)
AUDIO_TRANSCRIPTION_PROMPT = (
    "You are exclusively a speech-to-text tool. Transcribe only the spoken audio "
    "accurately and verbatim, without commentary or a reply. If no intelligible "
    "speech is audible, return exactly: [ΣΙΩΠΗ]."
)


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


def find_offline_adc_credentials_path() -> str | None:
    """
    Discovers standard local Application Default Credentials (ADC) file path without network calls.
    Returns path if file exists on disk, otherwise None.
    """
    gac = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    if gac and os.path.exists(gac):
        return gac

    if os.name == "nt":
        app_data = os.environ.get("APPDATA")
        if app_data:
            win_adc = os.path.join(app_data, "gcloud", "application_default_credentials.json")
            if os.path.exists(win_adc):
                return win_adc
    else:
        xdg_config = os.environ.get("XDG_CONFIG_HOME")
        if xdg_config:
            xdg_adc = os.path.join(xdg_config, "gcloud", "application_default_credentials.json")
            if os.path.exists(xdg_adc):
                return xdg_adc
        unix_adc = os.path.expanduser("~/.config/gcloud/application_default_credentials.json")
        if os.path.exists(unix_adc):
            return unix_adc

    return None


def resolve_vertex_credentials_path(explicit_path: str | None = None) -> str:
    """Discovers configured Vertex AI credentials file path without mutating environment."""
    if explicit_path and os.path.exists(explicit_path):
        return explicit_path
    env_cred = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    if env_cred and os.path.exists(env_cred):
        return env_cred
    config_cred = getattr(config, "CREDENTIALS_PATH", "")
    if config_cred and os.path.exists(config_cred):
        return config_cred
    base_dir = getattr(config, "BASE_DIR", os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    root_cred = os.path.join(base_dir, "credentials.json")
    if os.path.exists(root_cred):
        return root_cred
    nested_cred = os.path.join(base_dir, "credentials", "credentials.json")
    if os.path.exists(nested_cred):
        return nested_cred
    adc_path = find_offline_adc_credentials_path()
    if adc_path and os.path.exists(adc_path):
        return adc_path
    return ""


def get_vertex_credentials(credentials_path: str | None = None) -> Any:
    """
    Loads Google auth credentials for Vertex AI if a credentials file is configured or discovered.
    Explicit service-account credentials are scoped with VERTEX_OAUTH_SCOPES ('https://www.googleapis.com/auth/cloud-platform').
    Returns google.auth.credentials.Credentials or None.
    """
    import json
    cred_file = resolve_vertex_credentials_path(credentials_path)
    if cred_file and os.path.exists(cred_file):
        try:
            with open(cred_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                cred_type = data.get("type")
                if cred_type == "service_account":
                    from google.oauth2 import service_account
                    return service_account.Credentials.from_service_account_info(
                        data,
                        scopes=list(VERTEX_OAUTH_SCOPES),
                    )
                elif cred_type == "authorized_user":
                    from google.oauth2 import credentials as user_credentials
                    return user_credentials.Credentials.from_authorized_user_info(data)
        except Exception:
            pass
    return None


def resolve_vertex_project_id(explicit_project: str | None = None, cred_file: str | None = None) -> str:
    """
    Resolves the Google Cloud project ID for Vertex AI.
    Prefers explicit_project or configured PROJECT_ID. If configured PROJECT_ID is empty
    or the default placeholder 'your-gcp-project-id', falls back to discovering the project ID
    from configured/ambient credentials files.
    """
    import json
    # 1. Explicit project if non-placeholder and non-empty
    if explicit_project and explicit_project.strip().lower() != "your-gcp-project-id":
        return explicit_project.strip()

    # 2. Configured PROJECT_ID or env PROJECT_ID if non-placeholder and non-empty
    proj = (getattr(config, "PROJECT_ID", "") or os.environ.get("PROJECT_ID", "")).strip()
    if proj and proj.lower() != "your-gcp-project-id":
        return proj

    # 3. Fallback to credentials JSON (service account project_id or ADC quota_project_id)
    target_cred = resolve_vertex_credentials_path(cred_file)
    if target_cred and os.path.exists(target_cred):
        try:
            with open(target_cred, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                discovered = (data.get("project_id") or data.get("quota_project_id") or "").strip()
                if discovered and discovered.lower() != "your-gcp-project-id":
                    return discovered
        except Exception:
            pass

    return "your-gcp-project-id"




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


class EmbeddingsProviderSetupRequired(AIProviderError):
    """Raised when semantic memory has no explicitly usable embeddings backend."""


class EmbeddingsAdapter(Protocol):
    """Minimal contract required by the semantic-memory embeddings layer."""

    provider_name: str

    def embed_text(
        self,
        texts: str | Sequence[str],
        is_query: bool = False,
    ) -> list[list[float]]:
        """Generate dense vector embeddings for texts."""


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
        self.embedding_model = DEFAULT_OPENAI_EMBEDDING_MODEL

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
        self.embedding_model = DEFAULT_GEMINI_EMBEDDING_MODEL

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
                    AUDIO_TRANSCRIPTION_PROMPT,
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
            emb_client = GoogleGenerativeAIEmbeddings(model=self.embedding_model, google_api_key=self.api_key)
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
        credentials_path: str | None = None,
    ):
        self.credentials_path = resolve_vertex_credentials_path(credentials_path)
        self.project_id = resolve_vertex_project_id(project_id, cred_file=self.credentials_path)
        self.location = resolve_vertex_location(location)
        self.fast_model, self.heavy_model = resolve_provider_models("vertex", fast_model, heavy_model)
        self.embedding_model = DEFAULT_VERTEX_EMBEDDING_MODEL
        self._credentials = get_vertex_credentials(self.credentials_path)

    def _get_llm(self, model_type: str = "fast", temperature: float | None = None):
        from langchain_google_genai import ChatGoogleGenerativeAI
        model = self.heavy_model if model_type == "heavy" else self.fast_model
        temp = temperature if temperature is not None else (0.1 if model_type == "heavy" else 0.7)
        safety_settings = get_gemini_safety_settings()
        kwargs = {
            "model": model,
            "temperature": temp,
            "safety_settings": safety_settings,
            "vertexai": True,
            "project": self.project_id,
            "location": self.location,
        }
        if self._credentials is not None:
            kwargs["credentials"] = self._credentials
        return ChatGoogleGenerativeAI(**kwargs)

    def _get_genai_client(self):
        from google import genai
        kwargs = {
            "vertexai": True,
            "project": self.project_id,
            "location": self.location,
        }
        if self._credentials is not None:
            kwargs["credentials"] = self._credentials
        return genai.Client(**kwargs)

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
                    AUDIO_TRANSCRIPTION_PROMPT,
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
            kwargs = {
                "model": self.embedding_model,
                "vertexai": True,
                "project": self.project_id,
                "location": self.location,
            }
            if self._credentials is not None:
                kwargs["credentials"] = self._credentials
            emb_client = GoogleGenerativeAIEmbeddings(**kwargs)
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
            message="Embeddings are not natively supported by Anthropic API alone. Configure a separate Vertex, Gemini, OpenAI, or optional local embeddings provider.",
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

_EMBEDDINGS_PROVIDER_NAMES = frozenset({"vertex", "gemini", "openai", "local"})


def resolve_embeddings_provider(
    provider_name: str | None = None,
    chat_provider_name: str | None = None,
) -> str:
    """Resolve the embeddings backend independently from the chat provider.

    ``auto`` deliberately uses the chat provider only when it exposes native
    embeddings.  It never silently selects OpenAI or downloads a local model
    for providers such as Anthropic.
    """
    configured = provider_name
    if configured is None:
        configured = os.getenv("EMBEDDINGS_PROVIDER", "auto")
    resolved = configured.strip().lower()
    if resolved == "auto":
        chat_provider = (
            chat_provider_name
            or getattr(config, "LLM_PROVIDER", "vertex")
        ).strip().lower()
        adapter = get_provider_adapter(chat_provider)
        if adapter.is_capability_supported("embeddings"):
            return adapter.provider_name
        raise EmbeddingsProviderSetupRequired(
            "Semantic memory needs an embeddings provider. Configure "
            "EMBEDDINGS_PROVIDER as vertex, gemini, openai, or local; "
            "Anthropic does not provide native embeddings.",
            provider=chat_provider,
        )
    if resolved not in _EMBEDDINGS_PROVIDER_NAMES:
        valid = ", ".join(sorted(_EMBEDDINGS_PROVIDER_NAMES | {"auto"}))
        raise EmbeddingsProviderSetupRequired(
            f"Unknown embeddings provider '{resolved}'. Valid options: {valid}.",
            provider=resolved,
        )
    return resolved


class LocalE5EmbeddingsAdapter:
    """Optional local multilingual E5 backend with no install or download side effects."""

    provider_name = "local"
    model_name = DEFAULT_LOCAL_EMBEDDING_MODEL

    def __init__(self, model_name: str | None = None):
        self.model_name = model_name or os.getenv("ASTAKOS_LOCAL_EMBEDDING_MODEL", self.model_name)
        self._model: Any | None = None

    def _get_model(self) -> Any:
        if self._model is not None:
            return self._model
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            raise EmbeddingsProviderSetupRequired(
                "Local embeddings are selected but sentence-transformers is not installed. "
                "Install sentence-transformers before selecting local embeddings.",
                provider="local",
                original_error=exc,
            ) from exc
        try:
            # Local-only prevents a background model download during normal use.
            self._model = SentenceTransformer(self.model_name, local_files_only=True)
            return self._model
        except FileNotFoundError as exc:
            raise EmbeddingsProviderSetupRequired(
                f"Local embeddings model '{self.model_name}' is not installed locally. "
                "Download it explicitly during setup before selecting local embeddings.",
                provider="local",
                original_error=exc,
            ) from exc
        except Exception as exc:
            raise EmbeddingsProviderSetupRequired(
                f"Could not initialize local embeddings model '{self.model_name}': {exc}. "
                "Repair or reinstall the local model before selecting local embeddings.",
                provider="local",
                original_error=exc,
            ) from exc

    def embed_text(
        self,
        texts: str | Sequence[str],
        is_query: bool = False,
    ) -> list[list[float]]:
        normalized_texts = normalize_embedding_texts(texts)
        prefix = "query: " if is_query else "passage: "
        vectors = self._get_model().encode(
            [f"{prefix}{text}" for text in normalized_texts],
            normalize_embeddings=True,
        )
        return [vector.tolist() for vector in vectors]


def get_provider_adapter(provider_name: str | None = None, **kwargs: Any) -> AIProviderAdapter:
    """Factory function returning the configured AIProviderAdapter instance."""
    resolved_name = (provider_name or getattr(config, "LLM_PROVIDER", "vertex")).strip().lower()
    adapter_cls = _ADAPTER_REGISTRY.get(resolved_name)
    if not adapter_cls:
        raise AIProviderError(f"Unknown AI provider: '{resolved_name}'. Valid options: {list(_ADAPTER_REGISTRY.keys())}")
    return adapter_cls(**kwargs)


def get_embeddings_adapter(
    provider_name: str | None = None,
    chat_provider_name: str | None = None,
    **kwargs: Any,
) -> EmbeddingsAdapter:
    """Return the explicitly resolved backend used only for semantic embeddings."""
    resolved = resolve_embeddings_provider(provider_name, chat_provider_name)
    if resolved == "local":
        return LocalE5EmbeddingsAdapter(**kwargs)
    adapter = get_provider_adapter(resolved, **kwargs)
    if not adapter.is_capability_supported("embeddings"):
        raise EmbeddingsProviderSetupRequired(
            f"Provider '{resolved}' does not support embeddings.",
            provider=resolved,
        )
    return adapter


def get_embeddings_backend_identity(
    provider_name: str | None = None,
    chat_provider_name: str | None = None,
) -> str:
    """Return a stable identity for cache and Chroma namespace selection."""
    adapter = get_embeddings_adapter(provider_name, chat_provider_name)
    model = getattr(adapter, "embedding_model", getattr(adapter, "model_name", "default"))
    return f"{adapter.provider_name}:{model}"


def build_embeddings_cache_key(backend_identity: str, role: str, text: str) -> str:
    """Build a provider/model/role-scoped cache key for one embedding input."""
    payload = f"{backend_identity}\0{role}\0{text.strip()}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def get_embeddings_collection_name(
    provider_name: str | None = None,
    chat_provider_name: str | None = None,
) -> str:
    """Return the isolated Chroma collection for the selected embeddings backend.

    The long-standing Vertex collection keeps its legacy name so existing
    installations retain semantic retrieval. Every other backend begins in an
    empty namespace; historical semantic memories can be re-indexed later by
    an explicit user action.
    """
    identity = get_embeddings_backend_identity(provider_name, chat_provider_name)
    if identity == f"vertex:{DEFAULT_VERTEX_EMBEDDING_MODEL}":
        return "astakos_long_term"
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:12]
    return f"astakos_vec_{digest}"
