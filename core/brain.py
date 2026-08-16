# ================================================================
# Project: Astakos AI Agent 🦞
# Description: Modular LLM-agnostic multi-agent framework
# Copyright (c) 2026 - All Rights Reserved
# ================================================================
import config
import warnings
import os
import time
from langchain_google_genai import ChatGoogleGenerativeAI, HarmCategory, HarmBlockThreshold
from rich.console import Console
from google import genai

# Ignore warnings to keep the terminal clean
warnings.filterwarnings("ignore")

# 1. Base Model Definitions
_provider = getattr(config, "LLM_PROVIDER", "vertex").lower()

DEFAULT_GEMINI_FAST_MODEL = "gemini-3.5-flash"
DEFAULT_GEMINI_HEAVY_MODEL = "gemini-3.1-pro-preview"


def _google_model_from_environment(variable_name: str, default_model: str) -> str:
    """Return an optional Google-model override, falling back to the stable default."""
    configured_model = os.getenv(variable_name, "").strip()
    return configured_model or default_model

# [MASTRO-SHIELD v3]: Safety for Google models
_BN = HarmBlockThreshold.BLOCK_NONE
custom_safety = {
    HarmCategory.HARM_CATEGORY_HARASSMENT:         _BN,
    HarmCategory.HARM_CATEGORY_HATE_SPEECH:        _BN,
    HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT:  _BN,
    HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT:  _BN,
    HarmCategory.HARM_CATEGORY_CIVIC_INTEGRITY:    _BN,
}

vertex_client = None
console = Console()

if _provider == "openai":
    from langchain_openai import ChatOpenAI
    FAST_MODEL = "gpt-4o-mini"
    HEAVY_MODEL = "gpt-4o"
    llm = ChatOpenAI(model=FAST_MODEL, temperature=0.7, api_key=config.OPENAI_API_KEY)
    llm_heavy = ChatOpenAI(model=HEAVY_MODEL, temperature=0.1, api_key=config.OPENAI_API_KEY)
    print("\033[92m[Brain]: OpenAI Engines Loaded\033[0m")

elif _provider == "anthropic":
    from langchain_anthropic import ChatAnthropic
    FAST_MODEL = "claude-3-5-haiku-latest"
    HEAVY_MODEL = "claude-3-5-sonnet-latest"
    llm = ChatAnthropic(model=FAST_MODEL, temperature=0.7, api_key=config.ANTHROPIC_API_KEY)
    llm_heavy = ChatAnthropic(model=HEAVY_MODEL, temperature=0.1, api_key=config.ANTHROPIC_API_KEY)
    print("\033[92m[Brain]: Anthropic Engines Loaded\033[0m")

elif _provider == "gemini":
    FAST_MODEL = _google_model_from_environment(
        "ASTAKOS_GEMINI_FAST_MODEL", DEFAULT_GEMINI_FAST_MODEL,
    )
    HEAVY_MODEL = _google_model_from_environment(
        "ASTAKOS_GEMINI_HEAVY_MODEL", DEFAULT_GEMINI_HEAVY_MODEL,
    )
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
    FAST_MODEL = _google_model_from_environment(
        "ASTAKOS_GEMINI_FAST_MODEL", DEFAULT_GEMINI_FAST_MODEL,
    )
    HEAVY_MODEL = _google_model_from_environment(
        "ASTAKOS_GEMINI_HEAVY_MODEL", DEFAULT_GEMINI_HEAVY_MODEL,
    )
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
