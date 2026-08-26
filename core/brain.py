# ================================================================
# Project: Astakos AI Agent 🦞
# Description: Modular LLM-agnostic multi-agent framework
# Copyright (c) 2026 - All Rights Reserved
# ================================================================
from typing import Any, Callable, TypeVar
import config
import warnings
import os
import time
import threading
from langchain_google_genai import ChatGoogleGenerativeAI, HarmCategory, HarmBlockThreshold
from rich.console import Console
from google import genai


# Ignore warnings to keep the terminal clean
warnings.filterwarnings("ignore")

from core.ai_provider import (
    AIProviderAdapter,
    DEFAULT_GEMINI_FAST_MODEL,
    DEFAULT_GEMINI_HEAVY_MODEL,
    get_gemini_safety_settings,
    get_provider_adapter,
    google_model_from_environment,
    resolve_gemini_safety_threshold,
    resolve_provider_models,
    resolve_vertex_location,
)

# 1. Base Model Definitions
_KNOWN_PROVIDERS = frozenset({"openai", "gemini", "anthropic", "vertex"})


def _effective_provider(provider_name: str) -> str:
    """Resolve unknown configured providers to the legacy Vertex fallback."""
    return provider_name if provider_name in _KNOWN_PROVIDERS else "vertex"


def _google_model_from_environment(variable_name: str, default_model: str) -> str:
    """Compatibility wrapper retaining the legacy override-warning behavior."""
    return google_model_from_environment(variable_name, default_model, emit_warning=True)


_provider = getattr(config, "LLM_PROVIDER", "vertex").lower()
_effective_provider_name = _effective_provider(_provider)
FAST_MODEL, HEAVY_MODEL = resolve_provider_models(
    _effective_provider_name,
    emit_warnings=True,
)
_resolve_gemini_safety_threshold = resolve_gemini_safety_threshold

# [MASTRO-SHIELD v3]: Safety for Google models
custom_safety = get_gemini_safety_settings()
VERTEX_LOCATION = resolve_vertex_location()

vertex_client = None
console = Console()

if _provider == "openai":
    from langchain_openai import ChatOpenAI
    llm = ChatOpenAI(model=FAST_MODEL, temperature=0.7, api_key=config.OPENAI_API_KEY)
    llm_heavy = ChatOpenAI(model=HEAVY_MODEL, temperature=0.1, api_key=config.OPENAI_API_KEY)
    print("\033[92m[Brain]: OpenAI Engines Loaded\033[0m")

elif _provider == "anthropic":
    from langchain_anthropic import ChatAnthropic
    llm = ChatAnthropic(model=FAST_MODEL, temperature=0.7, api_key=config.ANTHROPIC_API_KEY)
    llm_heavy = ChatAnthropic(model=HEAVY_MODEL, temperature=0.1, api_key=config.ANTHROPIC_API_KEY)
    print("\033[92m[Brain]: Anthropic Engines Loaded\033[0m")

elif _provider == "gemini":
    llm = ChatGoogleGenerativeAI(
        model=FAST_MODEL, temperature=0.7, safety_settings=custom_safety, api_key=config.GEMINI_API_KEY
    )
    llm_heavy = ChatGoogleGenerativeAI(
        model=HEAVY_MODEL, temperature=0.1, safety_settings=custom_safety, api_key=config.GEMINI_API_KEY
    )
    # Temporary fallback for un-refactored scripts
    vertex_client = genai.Client(api_key=config.GEMINI_API_KEY)
    print("\033[92m[Brain]: Gemini Engines Loaded (API Key)\033[0m")

else:  # default to vertex
    from core.ai_provider import (
        get_vertex_credentials,
        resolve_vertex_credentials_path,
        resolve_vertex_project_id,
    )

    _vertex_cred_path = resolve_vertex_credentials_path()
    _vertex_project = resolve_vertex_project_id(cred_file=_vertex_cred_path)
    _vertex_creds = get_vertex_credentials(_vertex_cred_path)

    _chat_kwargs = {
        "model": FAST_MODEL,
        "temperature": 0.7,
        "safety_settings": custom_safety,
        "vertexai": True,
        "project": _vertex_project,
        "location": VERTEX_LOCATION,
    }
    _heavy_kwargs = {
        "model": HEAVY_MODEL,
        "temperature": 0.1,
        "safety_settings": custom_safety,
        "vertexai": True,
        "project": _vertex_project,
        "location": VERTEX_LOCATION,
    }
    _client_kwargs = {
        "vertexai": True,
        "project": _vertex_project,
        "location": VERTEX_LOCATION,
    }
    if _vertex_creds is not None:
        _chat_kwargs["credentials"] = _vertex_creds
        _heavy_kwargs["credentials"] = _vertex_creds
        _client_kwargs["credentials"] = _vertex_creds

    llm = ChatGoogleGenerativeAI(**_chat_kwargs)
    llm_heavy = ChatGoogleGenerativeAI(**_heavy_kwargs)
    vertex_client = genai.Client(**_client_kwargs)
    print("\033[92m[Brain]: Gemini Engines Loaded (Vertex AI)\033[0m")

_active_provider_adapter: AIProviderAdapter | None = None
_adapter_lock = threading.Lock()


def get_active_provider_adapter() -> AIProviderAdapter:
    """Return the active AIProviderAdapter singleton instance, defaulting unknown providers to vertex (thread-safe)."""
    global _active_provider_adapter
    if _active_provider_adapter is None:
        with _adapter_lock:
            if _active_provider_adapter is None:
                _active_provider_adapter = get_provider_adapter(_effective_provider(_provider))
    return _active_provider_adapter


def safe_llm_invoke(llm_obj, input_, retries: int = 3, base_delay: float = 2.0):
    from time import perf_counter
    """
    Mastro-Shield override: exponential backoff on network, quota,
    and transient server-side model failures.
    """
    _TRANSIENT = (
        "timeout",
        "transport",
        "connection refused",
        "connection reset",
        "remote disconnected",
        "eof occurred",
        "10060",
        "10054",
    )

    for attempt in range(retries):
        try:
            attempt_started = perf_counter()
            response = llm_obj.invoke(input_)
            attempt_ms = int((perf_counter() - attempt_started) * 1000)

            try:
                existing = dict(getattr(response, "_astakos_phase_timings", {}) or {})
                existing["safe_llm_invoke_ms"] = attempt_ms
                existing["safe_llm_attempt"] = attempt + 1
                setattr(response, "_astakos_phase_timings", existing)
            except Exception:
                pass

            return response
        except Exception as e:
            err = str(e).lower()
            is_transient = any(t in err for t in _TRANSIENT)
            is_quota = "429" in err or "quota" in err or "resource exhausted" in err
            is_server = any(code in err for code in ("500", "502", "503"))
            is_fatal = any(c in err for c in ("400", "401", "403", "invalid"))

            if is_fatal or not (is_transient or is_quota or is_server):
                raise

            if attempt >= retries - 1:
                print(f"\033[91m[Brain]: LLM fatal after {retries} attempts: {e}\033[0m")
                raise

            if is_quota:
                wait = base_delay * (4 ** attempt)
                print(
                    f"\033[93m[Brain]: Quota limit (attempt {attempt+1}/{retries}), "
                    f"retrying in {wait:.1f}s - {type(e).__name__}\033[0m"
                )
            else:
                wait = base_delay * (2 ** attempt)
                print(
                    f"\033[93m[Brain]: Network/server error (attempt {attempt+1}/{retries}), "
                    f"retrying in {wait:.0f}s - {type(e).__name__}\033[0m"
                )
            time.sleep(wait)


_T = TypeVar("_T")


def safe_adapter_call(
    func: Callable[..., _T],
    *args: Any,
    retries: int = 3,
    base_delay: float = 2.0,
    **kwargs: Any,
) -> _T:
    """
    Mastro-Shield provider adapter executor: exponential backoff on network, quota,
    and transient server-side model failures.
    """

    from core.ai_provider import (
        CapabilityNotSupportedError,
        ProviderAuthError,
        RateLimitError,
    )

    _TRANSIENT = (
        "timeout",
        "transport",
        "connection refused",
        "connection reset",
        "remote disconnected",
        "eof occurred",
        "10060",
        "10054",
    )

    for attempt in range(retries):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            err = str(e).lower()
            is_transient = any(t in err for t in _TRANSIENT)
            is_quota = isinstance(e, RateLimitError) or "429" in err or "quota" in err or "resource exhausted" in err
            is_server = any(code in err for code in ("500", "502", "503"))
            is_fatal = isinstance(e, (CapabilityNotSupportedError, ProviderAuthError)) or any(
                c in err for c in ("400", "401", "403", "invalid")
            )

            if is_fatal or not (is_transient or is_quota or is_server):
                raise

            if attempt >= retries - 1:
                print(f"\033[91m[Brain]: Provider operation fatal after {retries} attempts: {e}\033[0m")
                raise

            if is_quota:
                retry_after = getattr(e, "retry_after", None)
                wait = float(retry_after) if retry_after is not None else base_delay * (4 ** attempt)
                print(
                    f"\033[93m[Brain]: Quota limit (attempt {attempt+1}/{retries}), "
                    f"retrying in {wait:.1f}s - {type(e).__name__}\033[0m"
                )
            else:
                wait = base_delay * (2 ** attempt)
                print(
                    f"\033[93m[Brain]: Network/server error (attempt {attempt+1}/{retries}), "
                    f"retrying in {wait:.0f}s - {type(e).__name__}\033[0m"
                )
            time.sleep(wait)
