# ================================================================
# Project: Astakos AI Agent 🦞
# Developer: Lazaros (Piston-7)
# Description: Modular LLM-agnostic multi-agent framework
# Copyright (c) 2026 - All Rights Reserved
# ================================================================
import warnings
import os
import time
from langchain_google_genai import ChatGoogleGenerativeAI, HarmCategory, HarmBlockThreshold
from rich.console import Console
from google import genai

# Ignore warnings to keep the terminal clean
warnings.filterwarnings("ignore")

# 1. Central Model Definition (Strings)
FAST_MODEL = "gemini-3.5-flash"
HEAVY_MODEL = "gemini-3.1-pro-preview"

# [MASTRO-SHIELD v3]: We keep only the safety categories it accepts
# the Gemini text generation endpoint. Extra categories such as JAILBREAK/IMAGE_*
# may raise INVALID_ARGUMENT on certain model paths.
_BN = HarmBlockThreshold.BLOCK_NONE
custom_safety = {
    HarmCategory.HARM_CATEGORY_HARASSMENT:         _BN,
    HarmCategory.HARM_CATEGORY_HATE_SPEECH:        _BN,
    HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT:  _BN,
    HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT:  _BN,
    HarmCategory.HARM_CATEGORY_CIVIC_INTEGRITY:    _BN,
}

# 2. Model Architect (LangChain Objects)
# Main LLM (For fast responses, Telegram chat, simple validations)
llm = ChatGoogleGenerativeAI(
    model=FAST_MODEL,
    temperature=0.7,
    safety_settings=custom_safety,
    vertexai=True,
    project=os.getenv("PROJECT_ID", "astakos-finall"),
    location=os.getenv("LOCATION", "global"),
)

# Heavy LLM (For ChromaDB scanning, complex Tool Use, JSON memory parsing, API design)
llm_heavy = ChatGoogleGenerativeAI(
    model=HEAVY_MODEL,
    temperature=0.1,
    safety_settings=custom_safety,
    vertexai=True,
    project=os.getenv("PROJECT_ID", "astakos-finall"),
    location=os.getenv("LOCATION", "global"),
)

# 3. Shared Vertex AI raw client (for multimodal: images, audio, documents)
# The entire codebase pulls from here — a single point of initialization.
vertex_client = genai.Client(
    vertexai=True,
    project=os.getenv("PROJECT_ID", "astakos-finall"),
    location=os.getenv("LOCATION", "global"),
)

console = Console()
print("\033[92m[Brain]: Gemini Engines Loaded (Vertex AI via GenAI SDK)\033[0m")


def safe_llm_invoke(llm_obj, input_, retries: int = 3, base_delay: float = 2.0):
    from time import perf_counter
    """
    Mastro-Shield for main LLM calls: exponential backoff on
    network/transport errors (OAuth token refresh timeout, connection reset, etc.).

    Usage:
        from core.brain import safe_llm_invoke, llm
        response = safe_llm_invoke(llm, [HumanMessage(content=prompt)])

    Catches:
        - google.auth.exceptions.TransportError  (OAuth refresh timeout)
        - requests.exceptions.ConnectTimeout
        - any error with "timeout" / "transport" / "connection" in the msg
    Does not retry:
        - 400/401/403 (auth/param errors — retry does not help)
        - 429 quota (left to safe_gemini_call for sidecar calls)
    """
    _TRANSIENT = ("timeout", "transport", "connection refused",
                  "connection reset", "remote disconnected", "eof occurred",
                  "10060", "10054")  # WinError codes

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
            is_fatal     = any(c in err for c in ("400", "401", "403", "invalid"))

            if is_fatal or not is_transient:
                raise

            if attempt >= retries - 1:
                print(f"\033[91m[Brain]: LLM fatal after {retries} attempts: {e}\033[0m")
                raise

            wait = base_delay * (2 ** attempt)
            print(f"\033[93m[Brain]: Network error (attempt {attempt+1}/{retries}), "
                  f"retry σε {wait:.0f}s — {type(e).__name__}\033[0m")
            time.sleep(wait)
