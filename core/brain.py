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

warnings.filterwarnings("ignore")

FAST_MODEL = "gemini-3.5-flash"
HEAVY_MODEL = "gemini-3.1-pro"

# [MASTRO-SHIELD]: Χαλαρώνουμε τα φίλτρα ασφαλείας για να μην κόβει καθημερινά μηνύματα (π.χ. θυμό, ζήλια, αστεία)
custom_safety = {
    HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
}

# 2. Τα περνάς στο LangChain με τα νέα safety settings
llm = ChatGoogleGenerativeAI(
    model=FAST_MODEL, 
    temperature=0.7,
    safety_settings=custom_safety
)

llm_heavy = ChatGoogleGenerativeAI(
    model=HEAVY_MODEL, 
    temperature=0.1,
    safety_settings=custom_safety
)

console = Console()
print("\033[92m[Brain]: Gemini Engines Loaded (AI Studio Mode - Custom Safety) 🦞\033[0m")