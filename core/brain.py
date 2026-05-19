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

# [MASTRO-STRATEGY]: 
# llm -> Το οικονομικό και ταχύτατο για το 90% των κλήσεων
# llm_heavy -> Το "σκεπτόμενο" για summaries και μνήμες

# Κύριο LLM
llm = ChatGoogleGenerativeAI(
    model="gemini-3.1-flash-lite-preview", 
    temperature=0.7
)

# Βαρύ LLM
llm_heavy = ChatGoogleGenerativeAI(
    model="gemini-3-flash-preview", 
    temperature=0.2
)

console = Console()
print("\033[92m[Brain]: Gemini 3.1 & 3.0 Engines Loaded (AI Studio Mode) 🦞\033[0m")