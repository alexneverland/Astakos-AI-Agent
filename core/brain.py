# ================================================================
# Project: Astakos AI Agent 🦞
# Developer: Lazaros (Piston-7)
# Description: Modular LLM-agnostic multi-agent framework
# Copyright (c) 2026 - All Rights Reserved
# ================================================================
import warnings
import os
from langchain_google_genai import ChatGoogleGenerativeAI
from rich.console import Console

# Αγνοούμε τα προειδοποιητικά για να είναι καθαρό το τερματικό
warnings.filterwarnings("ignore")

# 1. Δηλώνεις τα ονόματα (strings) μια και έξω στην κορυφή
FAST_MODEL = "gemini-3.5-flash"
HEAVY_MODEL = "gemini-3.1-pro"

# 2. Τα περνάς στο LangChain
llm = ChatGoogleGenerativeAI(
    model=FAST_MODEL, 
    temperature=0.7
)

llm_heavy = ChatGoogleGenerativeAI(
    model=HEAVY_MODEL, 
    temperature=0.1  
)

console = Console()
print("\033[92m[Brain]: Gemini Engines Loaded (AI Studio Mode) 🦞\033[0m")