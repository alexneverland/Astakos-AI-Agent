# ================================================================
# Project: Astakos AI Agent 🦞
# Description: Modular LLM-agnostic multi-agent framework
# Copyright (c) 2026 - All Rights Reserved
# ================================================================
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
    llm = ChatGoogleGenerativeAI(
        model=FAST_MODEL, temperature=0.7, safety_settings=custom_safety,
        vertexai=True, project=config.PROJECT_ID, location=os.getenv("LOCATION", "global")
    )
    llm_heavy = ChatGoogleGenerativeAI(
        model=HEAVY_MODEL, temperature=0.1, safety_settings=custom_safety,
        vertexai=True, project=config.PROJECT_ID, location=os.getenv("LOCATION", "global")
    )
    vertex_client = genai.Client(
        vertexai=True, project=config.PROJECT_ID, location=os.getenv("LOCATION", "global")
    )
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
