# ================================================================
# Project: Astakos AI Agent 🦞
# Developer: Lazaros (Piston-7)
# Description: Modular LLM-agnostic multi-agent framework
# Copyright (c) 2026 - All Rights Reserved
# ================================================================

import os
import json
import hashlib
import threading
from langchain_core.embeddings import Embeddings
from langchain_google_genai import GoogleGenerativeAIEmbeddings  # [MASTRO-FIX]: VertexAI → GenAI
from config import EMBEDDINGS_CACHE_FILE

emb_cache_lock = threading.Lock()

# [MASTRO-FIX]: Χρησιμοποιούμε το μοντέλο που "παίζει" με όλα τα κλειδιά
base_embeddings = GoogleGenerativeAIEmbeddings(
    model="models/embedding-001", # Το standard stable μοντέλο
    task_type="retrieval_document"
)

class MastroEmbeddingsCache(Embeddings):
    def __init__(self, base):
        self.base = base
        self.cache = {}
        if os.path.exists(EMBEDDINGS_CACHE_FILE):
            try:
                with open(EMBEDDINGS_CACHE_FILE, "r", encoding="utf-8") as f:
                    self.cache = json.load(f)
                print(f"\033[92m[Cache]: Φορτώθηκαν {len(self.cache)} embeddings από το δίσκο!\033[0m")
            except:
                pass

    def _get_key(self, text: str):
        return hashlib.md5(text.strip().encode('utf-8')).hexdigest()

    def embed_query(self, text: str) -> list[float]:
        key = self._get_key(text)
        with emb_cache_lock:
            if key in self.cache:
                return self.cache[key]
        emb = self.base.embed_query(text)
        with emb_cache_lock:
            self.cache[key] = emb
            self._save()
        return emb

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        results = [None] * len(texts)
        missing_texts = []
        missing_indices = []

        with emb_cache_lock:
            for i, text in enumerate(texts):
                key = self._get_key(text)
                if key in self.cache:
                    results[i] = self.cache[key]
                else:
                    missing_texts.append(text)
                    missing_indices.append(i)

        if missing_texts:
            new_embs = self.base.embed_documents(missing_texts)
            with emb_cache_lock:
                for i, text in enumerate(missing_texts):
                    key = self._get_key(text)
                    self.cache[key] = new_embs[i]
                    results[missing_indices[i]] = new_embs[i]
                self._save()
        return results

    def _save(self):
        cache_copy = self.cache.copy()
        def write_file():
            try:
                with open(EMBEDDINGS_CACHE_FILE, "w", encoding="utf-8") as f:
                    json.dump(cache_copy, f, ensure_ascii=False)
            except Exception:
                pass
        threading.Thread(target=write_file, daemon=True).start()

embeddings = MastroEmbeddingsCache(base_embeddings)