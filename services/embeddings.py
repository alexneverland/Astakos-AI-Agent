# ================================================================
# Project: Astakos AI Agent
# Module:  Embeddings Cache - SQLite backend
# L1: in-memory dict (session, resets on restart)
# L2: SQLite (persistent, WAL, per-row writes - no full rewrites)
# ================================================================

import hashlib
import json
import sqlite3
import threading
from datetime import datetime
from time import perf_counter

from langchain_core.embeddings import Embeddings
from config import EMBEDDINGS_CACHE_DB
from core.ai_provider import EmbeddingsAdapter, get_embeddings_adapter


# -- DB helpers --------------------------------------------------

def _db_connect() -> sqlite3.Connection:
    conn = sqlite3.connect(EMBEDDINGS_CACHE_DB, timeout=10)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def _init_db() -> int:
    """Creates table if missing. Returns count of cached entries."""
    with _db_connect() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS embeddings_cache (
                key        TEXT PRIMARY KEY,
                embedding  TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
        """)
        count = conn.execute("SELECT COUNT(*) FROM embeddings_cache").fetchone()[0]
    return count


# -- Base Embeddings Model -------------------------------------------

class ProviderEmbeddings(Embeddings):
    """LangChain adapter that resolves the semantic-memory provider lazily.

    Delaying resolution keeps normal application startup available when a user
    has selected a chat provider without native embeddings.  The first semantic
    operation then returns one clear setup error instead of silently falling
    back to another provider or downloading a local model.
    """

    def __init__(
        self,
        provider_name: str | None = None,
        chat_provider_name: str | None = None,
    ) -> None:
        self.provider_name = provider_name
        self.chat_provider_name = chat_provider_name
        self._adapter: EmbeddingsAdapter | None = None
        self._adapter_lock = threading.Lock()

    def _get_adapter(self) -> EmbeddingsAdapter:
        if self._adapter is None:
            with self._adapter_lock:
                if self._adapter is None:
                    self._adapter = get_embeddings_adapter(
                        self.provider_name,
                        self.chat_provider_name,
                    )
        return self._adapter

    def embed_query(self, text: str) -> list[float]:
        return self._get_adapter().embed_text(text, is_query=True)[0]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self._get_adapter().embed_text(texts, is_query=False)


base_embeddings = ProviderEmbeddings()


# -- Cache class -------------------------------------------------

class MastroEmbeddingsCache(Embeddings):
    """
    Two-layer embeddings cache:
      L1 - in-memory dict  (fast, resets on restart)
      L2 - SQLite          (persistent, single-row INSERT per miss)
    """

    def __init__(self, base: Embeddings):
        self.base = base
        self._lock = threading.Lock()
        self._l1: dict = {}  # key -> embedding

        count = _init_db()
        print(f"\033[92m[EmbeddingsCache]: SQLite primed - {count} cached vectors.\033[0m")

    # -- internal ------------------------------------------------

    @staticmethod
    def _key(text: str) -> str:
        return hashlib.md5(text.strip().encode("utf-8")).hexdigest()

    def _l2_get(self, key: str):
        try:
            with _db_connect() as conn:
                row = conn.execute(
                    "SELECT embedding FROM embeddings_cache WHERE key = ?", (key,)
                ).fetchone()
            if row:
                return json.loads(row[0])
        except Exception as e:
            print(f"\033[91m[EmbeddingsCache]: L2 read error: {e}\033[0m")
        return None

    def _l2_put(self, key: str, emb: list) -> None:
        try:
            with _db_connect() as conn:
                conn.execute(
                    "INSERT OR IGNORE INTO embeddings_cache (key, embedding, created_at) VALUES (?, ?, ?)",
                    (key, json.dumps(emb), datetime.now().isoformat(timespec="seconds")),
                )
        except Exception as e:
            print(f"\033[91m[EmbeddingsCache]: L2 write error: {e}\033[0m")

    # -- public API ----------------------------------------------

    def embed_query(self, text: str) -> list:
        started = perf_counter()
        key = self._key(text)

        # L1
        with self._lock:
            if key in self._l1:
                return self._l1[key]

        # L2
        emb = self._l2_get(key)
        if emb is not None:
            with self._lock:
                self._l1[key] = emb
            self._report_slow_query("l2", text, started)
            return emb

        # API call
        emb = self.base.embed_query(text)
        with self._lock:
            self._l1[key] = emb
        self._l2_put(key, emb)
        self._report_slow_query("provider", text, started)
        return emb

    @staticmethod
    def _report_slow_query(source: str, text: str, started: float) -> None:
        elapsed_ms = int((perf_counter() - started) * 1000)
        if elapsed_ms >= 1000:
            print(
                "[EmbeddingsCachePerf]: "
                f"query_source={source} elapsed={elapsed_ms}ms chars={len(text)}"
            )

    def embed_documents(self, texts: list) -> list:
        results = [None] * len(texts)
        missing_texts = []
        missing_idx = []

        for i, text in enumerate(texts):
            key = self._key(text)
            # L1
            with self._lock:
                if key in self._l1:
                    results[i] = self._l1[key]
                    continue
            # L2
            emb = self._l2_get(key)
            if emb is not None:
                with self._lock:
                    self._l1[key] = emb
                results[i] = emb
            else:
                missing_texts.append(text)
                missing_idx.append(i)

        if missing_texts:
            new_embs = self.base.embed_documents(missing_texts)
            for j, text in enumerate(missing_texts):
                key = self._key(text)
                emb = new_embs[j]
                with self._lock:
                    self._l1[key] = emb
                self._l2_put(key, emb)
                results[missing_idx[j]] = emb

        return results


embeddings = MastroEmbeddingsCache(base_embeddings)
