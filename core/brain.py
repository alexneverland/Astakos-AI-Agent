# ================================================================
# Project: Astakos AI Agent 🦞
# Developer: Lazaros (Piston-7)
# Description: Modular LLM-agnostic multi-agent framework
# Copyright (c) 2026 - All Rights Reserved
# ================================================================
import warnings
import os
from langchain_google_genai import ChatGoogleGenerativeAI, HarmCategory, HarmBlockThreshold
from rich.console import Console

# Αγνοούμε τα προειδοποιητικά για να είναι καθαρό το τερματικό
warnings.filterwarnings("ignore")

# 1. Κεντρικός Ορισμός Μοντέλων (Strings)
FAST_MODEL = "gemini-3.5-flash"
HEAVY_MODEL = "gemini-3.1-pro-preview"

# [MASTRO-SHIELD]: Κατεβάζουμε τελείως τις ασπίδες ασφαλείας (BLOCK_NONE)
# για να μην μπλοκάρονται αθώα/ανθρώπινα μηνύματα από false positives.
custom_safety = {
    HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
}

# 2. Αρχιτέκτονας Μοντέλων (LangChain Objects)
# Κύριο LLM (Για γρήγορες απαντήσεις, Telegram chat, απλά validations)
llm = ChatGoogleGenerativeAI(
    model=FAST_MODEL,
    temperature=0.7,
    safety_settings=custom_safety,
    vertexai=True,
    project=os.getenv("PROJECT_ID", "astakos-finall"),
    location=os.getenv("LOCATION", "global"),
)

# Βαρύ LLM (Για σκανάρισμα ChromaDB, σύνθετο Tool Use, JSON memory parsing, API design)
llm_heavy = ChatGoogleGenerativeAI(
    model=HEAVY_MODEL,
    temperature=0.1,
    safety_settings=custom_safety,
    vertexai=True,
    project=os.getenv("PROJECT_ID", "astakos-finall"),
    location=os.getenv("LOCATION", "global"),
)

console = Console()
print("\033[92m[Brain]: Gemini Engines Loaded (Vertex AI via GenAI SDK) 🦞\033[0m")