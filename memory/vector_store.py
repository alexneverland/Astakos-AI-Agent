# ================================================================
# Project: Astakos AI Agent 🦞
# Description: Modular LLM-agnostic multi-agent framework
# Copyright (c) 2026 - All Rights Reserved
# ================================================================

from core.i18n import t
import os
import json
import threading
import time
import uuid
import contextlib
from datetime import datetime
import sqlite3
from langchain_chroma import Chroma
from config import CHROMA_DB_DIR, PHOTOS_INDEX_FILE, SIM_THRESHOLD_DISTANCE, MEMORY_AUDIT_DIR, STATE_DB
from services.embeddings import embeddings
from core.ai_provider import (
    EmbeddingsProviderSetupRequired,
    ProviderAuthError,
    get_embeddings_collection_name,
)

_audit_lock = threading.Lock()


def _audit_log(op: str, **kwargs):
    """Writes an entry to the daily memory audit log (logs/memory_audit/YYYY-MM-DD.json)."""
    try:
        today    = datetime.now().strftime("%Y-%m-%d")
        log_file = os.path.join(MEMORY_AUDIT_DIR, f"{today}.json")
        tmp_file = f"{log_file}.{os.getpid()}.{uuid.uuid4().hex[:8]}.tmp"
        entry    = {"ts": datetime.now().strftime("%H:%M:%S"), "op": op, **kwargs}
        os.makedirs(MEMORY_AUDIT_DIR, exist_ok=True)
        with _audit_lock:
            entries = []
            if os.path.exists(log_file):
                with open(log_file, "r", encoding="utf-8") as f:
                    try:
                        loaded = json.load(f)
                        entries = loaded if isinstance(loaded, list) else []
                    except Exception:
                        entries = []
            entries.append(entry)
            with open(tmp_file, "w", encoding="utf-8") as f:
                json.dump(entries, f, ensure_ascii=False, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_file, log_file)
    except Exception as _e:
        print(f"\033[90m[AuditLog]: {_e}\033[0m")

vector_lock = threading.Lock()
memory_lock = threading.Lock()

# ================================================================
# CROSS-PROCESS LOCK
# Same pattern as memory/event_log.py: vector_lock/memory_lock only
# serialize threads inside ONE process. api/server.py (web) and
# clients/telegram_bot.py run as 2 separate OS processes and both
# write to the same ChromaDB persist_directory - without a
# cross-process lock, concurrent writes from the two processes could
# race against the same SQLite-backed Chroma store.
# ================================================================

def _acquire_cross_process_lock():
    if os.name != "nt":
        return None
    try:
        import msvcrt
        os.makedirs(CHROMA_DB_DIR, exist_ok=True)
        lock_path = os.path.join(CHROMA_DB_DIR, ".vector_store.lock")
        f = open(lock_path, "w")
        for _attempt in range(40):  # ~2s max before giving up
            try:
                msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
                return f
            except OSError:
                time.sleep(0.05)
        f.close()
        return None  # could not get the lock - proceed anyway (in-process lock is still a safety net)
    except Exception:
        return None


def _release_cross_process_lock(f):
    if f is None:
        return
    try:
        import msvcrt
        f.seek(0)
        msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
    except Exception:
        pass
    try:
        f.close()
    except Exception:
        pass


@contextlib.contextmanager
def _cross_process_lock():
    f = _acquire_cross_process_lock()
    try:
        yield
    finally:
        _release_cross_process_lock(f)


def _resolve_collection_name() -> str:
    """Choose an isolated collection without preventing startup on incomplete setup."""
    try:
        name = get_embeddings_collection_name()
    except EmbeddingsProviderSetupRequired as exc:
        # The actual semantic request re-raises this typed error.  An empty
        # placeholder namespace lets chat and structured memory still start.
        print(f"\033[93m[MemoryManager]: {exc}\033[0m")
        return "astakos_vec_unconfigured"
    if name != "astakos_long_term":
        print(
            "\033[93m[MemoryManager]: Semantic memory uses a new embeddings namespace "
            f"({name}); existing semantic memories remain untouched and require "
            "an optional re-index to be searched again.\033[0m"
        )
    return name


_collection_name = _resolve_collection_name()

vector_store = Chroma(
    collection_name=_collection_name,
    embedding_function=embeddings,
    persist_directory=CHROMA_DB_DIR
)

_EMPTY_QUERY_RESULT = {
    "ids": [[]],
    "documents": [[]],
    "metadatas": [[]],
    "distances": [[]],
}


def _refresh_vector_store(reason: str = "") -> bool:
    """Reopen the Chroma handle when the in-process collection goes stale."""
    global vector_store
    try:
        vector_store = Chroma(
            collection_name=_collection_name,
            embedding_function=embeddings,
            persist_directory=CHROMA_DB_DIR,
        )
        suffix = f" ({reason})" if reason else ""
        print(f"\033[90m[MemoryManager]: Chroma handle refreshed{suffix}\033[0m")
        return True
    except Exception as e:
        print(f"\033[93m[MemoryManager]: Chroma refresh failed: {e}\033[0m")
        return False


def close_vector_store():
    """Properly close ChromaDB client to ensure HNSW vectors are flushed."""
    acquired = vector_lock.acquire(timeout=5)
    if not acquired:
        print("\033[93m[VectorStore]: Timeout acquiring lock during shutdown. Skipping close to prevent corruption.\033[0m")
        return

    try:
        if vector_store is not None and hasattr(vector_store, "_client"):
            try:
                vector_store._client.close()
                print("\033[90m[VectorStore]: ChromaDB client closed gracefully.\033[0m")
            except Exception as e:
                print(f"\033[91m[VectorStore]: Error closing ChromaDB: {e}\033[0m")
    finally:
        vector_lock.release()


def get_collections_inventory(chroma_dir: str | None = None) -> dict[str, int] | None:
    """
    Safely inspects Chroma database collections and their document counts in read-only mode,
    reusing the existing managed Chroma handle and thread lock when active.
    """
    if vector_store is not None and hasattr(vector_store, "_client") and vector_store._client is not None:
        try:
            with vector_lock:
                collections = vector_store._client.list_collections()
                inventory: dict[str, int] = {}
                for col in collections:
                    try:
                        inventory[col.name] = col.count()
                    except Exception:
                        inventory[col.name] = 0
                return inventory
        except Exception:
            pass

    return None




def _should_retry_chroma_error(exc: Exception) -> bool:
    text = str(exc or "")
    lowered = text.lower()
    return "error finding id" in lowered or "collection" in lowered and "stale" in lowered

def _safe_chroma_query(*, query_embeddings, n_results, where=None, include=None):
    kwargs = {
        "query_embeddings": query_embeddings,
        "n_results": n_results,
        "include": include or ["documents", "metadatas", "distances"],
    }
    if where is not None:
        kwargs["where"] = where

    for attempt in range(2):
        try:
            return vector_store._collection.query(**kwargs)
        except (EmbeddingsProviderSetupRequired, ProviderAuthError):
            raise
        except Exception as e:
            if attempt == 0 and _should_retry_chroma_error(e) and _refresh_vector_store("query retry"):
                continue
            print(f"\033[93m[MemoryManager]: Chroma query error (graceful skip): {e}\033[0m")
            return {
                "ids": [[]],
                "documents": [[]],
                "metadatas": [[]],
                "distances": [[]],
                "_error": str(e),
            }


def safe_similarity_search(query: str, *, k: int, filter: dict | None = None) -> list:
    """Search Chroma through the current handle and retry once after a refresh.

    Consumers must use this helper instead of retaining an imported ``vector_store``
    reference: a refresh replaces that module-level handle after a recoverable
    Chroma error.
    """
    for attempt in range(2):
        try:
            kwargs = {"k": k}
            if filter is not None:
                kwargs["filter"] = filter
            return vector_store.similarity_search(query, **kwargs)
        except (EmbeddingsProviderSetupRequired, ProviderAuthError):
            raise
        except Exception as e:
            if attempt == 0 and _should_retry_chroma_error(e) and _refresh_vector_store("similarity retry"):
                continue
            print(f"\033[93m[MemoryManager]: Chroma similarity error (graceful skip): {e}\033[0m")
            return []

def _safe_chroma_delete(ids: list[str]) -> bool:
    if not ids:
        return False
    try:
        vector_store._collection.delete(ids=ids)
        return True
    except Exception as e:
        print(f"\033[90m[MemoryManager]: Chroma delete skip: {e}\033[0m")
        return False

def _safe_chroma_get(*, ids=None, where=None, include=None):
    kwargs = {
        "include": include or ["documents", "metadatas"],
    }
    if ids is not None:
        kwargs["ids"] = ids
    if where is not None:
        kwargs["where"] = where

    for attempt in range(2):
        try:
            return vector_store._collection.get(**kwargs)
        except Exception as e:
            if attempt == 0 and _should_retry_chroma_error(e) and _refresh_vector_store("get retry"):
                continue
            print(f"\033[93m[MemoryManager]: Chroma get error (graceful skip): {e}\033[0m")
            return {"ids": [], "documents": [], "metadatas": [], "_error": str(e)}


def _json_meta_list(values) -> str:
    if not values:
        return "[]"
    try:
        return json.dumps(list(values), ensure_ascii=False)
    except Exception:
        return "[]"


def _ensure_profile_fact_schema(cursor) -> None:
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS profile_facts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            category TEXT NOT NULL,
            fact TEXT NOT NULL,
            photo_path TEXT,
            date TEXT,
            metadata_json TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cursor.execute("PRAGMA table_info(profile_facts)")
    cols = {row[1] for row in cursor.fetchall()}
    if "metadata_json" not in cols:
        cursor.execute("ALTER TABLE profile_facts ADD COLUMN metadata_json TEXT")


def is_semantically_duplicate(new_text: str, existing_list: list, threshold: float = 0.88) -> bool:
    """Checks if the meaning of new_text already exists in existing_list."""
    text_list = []
    for item in existing_list:
        if isinstance(item, str):
            text_list.append(item)
        elif isinstance(item, dict) and "fact" in item:
            text_list.append(item["fact"])

    if not text_list:
        return False

    try:
        new_emb = embeddings.embed_query(new_text)
        existing_embs = embeddings.embed_documents(text_list)

        norm_a = sum(a * a for a in new_emb) ** 0.5
        if norm_a == 0:
            return False

        for emb in existing_embs:
            dot_product = sum(a * b for a, b in zip(new_emb, emb))
            norm_b = sum(b * b for b in emb) ** 0.5
            if norm_b == 0:
                continue
            similarity = dot_product / (norm_a * norm_b)
            if similarity >= threshold:
                return True

    except Exception as e:
        print(f"⚠️ [Similarity Check Error]: {e}")

    return False


CORRECTION_MARKERS = (
    t("prompts.ext_str_541"), t("prompts.ext_str_451"), t("prompts.ext_str_602"), t("prompts.ext_str_640"), t("prompts.ext_str_291"), t("prompts.ext_str_286"),
    t("prompts.ext_str_210"), t("prompts.ext_str_188"), t("prompts.ext_str_512"), t("prompts.ext_str_534"), t("prompts.ext_str_543"),
    t("prompts.ext_str_205"), t("prompts.ext_str_215"), t("prompts.ext_str_491"), t("prompts.ext_str_519"), t("prompts.ext_str_229"),
    t("prompts.ext_str_191"), t("prompts.ext_str_414"), t("prompts.ext_str_384"),
    "correction", "update", "actually",
)

MEMORY_ENTITY_MARKERS = (
    t("prompts.ext_str_604"), t("prompts.ext_str_561"), t("prompts.ext_str_334"), t("prompts.ext_str_323"), t("prompts.ext_str_552"), t("prompts.ext_str_559"),
    "mastroapp", "praxis", "shiftmaster", "paletes", "astakos", t("prompts.ext_str_533"),
)
MEMORY_LINK_MARKERS = ("http", "https", "/", "\\", ".py", ".json", ".md", ".db")
MEMORY_EVENT_MARKERS = (
    t("prompts.ext_str_486"), t("prompts.ext_str_459"), t("prompts.ext_str_625"), t("prompts.ext_str_567"), t("prompts.ext_str_558"), t("prompts.ext_str_644"),
    t("prompts.ext_str_768"), t("prompts.ext_str_739"), t("prompts.ext_str_628"), t("prompts.ext_str_595"), t("prompts.ext_str_358"), t("prompts.ext_str_375"),
    t("prompts.ext_str_507"), t("prompts.ext_str_511"), t("prompts.ext_str_462"), t("prompts.ext_str_447"),
)


def looks_like_memory_correction(fact: str) -> bool:
    return any(marker in str(fact).lower() for marker in CORRECTION_MARKERS)


def memory_age_days(metadata: dict | None, *, now: datetime | None = None) -> int | None:
    try:
        old_ts = float((metadata or {}).get("timestamp") or 0)
        if old_ts > 0:
            current = now or datetime.now()
            return max(0, (current - datetime.fromtimestamp(old_ts)).days)
    except (TypeError, ValueError, OSError):
        pass
    return None


def memory_has_date(text: str) -> bool:
    import re
    text_str = str(text)
    low = text_str.lower()
    if t("prompts.ext_str_730") in low:
        return True

    # We are looking for years e.g. 2024, 1998
    if re.search(r"\b(19|20)\d{2}\b", text_str):
        return True

    # Looking for dates e.g. 12/05, 12/05/2024, 12-05
    if re.search(r"\b\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?\b", text_str):
        return True

    # Keywords
    if any(word in low for word in [t("prompts.ext_str_524"), t("prompts.ext_str_588"), t("prompts.ext_str_655"), t("prompts.ext_str_727"), t("prompts.ext_str_679"), t("prompts.ext_str_565"), t("prompts.ext_str_606"), t("prompts.ext_str_627"), t("prompts.ext_str_443")]):
        return True

    return False


def memory_richness(text: str, metadata: dict | None) -> float:
    low = str(text).lower()
    score = 0.0
    if memory_has_date(text):
        score += 1
    if any(marker in low for marker in MEMORY_ENTITY_MARKERS):
        score += 1
    if any(marker in low for marker in MEMORY_LINK_MARKERS):
        score += 1
    if any(marker in low for marker in MEMORY_EVENT_MARKERS):
        score += 1
    try:
        score += float((metadata or {}).get("confidence", 0) or 0)
    except (TypeError, ValueError):
        pass
    return score


MEMORY_TOKEN_STOPWORDS = {
    "user_fact", "lesson", t("prompts.ext_str_730"), t("prompts.ext_str_724"), t("prompts.ext_str_685"), t("prompts.ext_str_772"), t("prompts.ext_str_804"), t("prompts.ext_str_776"), t("prompts.ext_str_824"),
    t("prompts.ext_str_806"), t("prompts.ext_str_807"), t("prompts.ext_str_786"), t("prompts.ext_str_809"), t("prompts.ext_str_801"), t("prompts.ext_str_795"), t("prompts.ext_str_823"), t("prompts.ext_str_796"), t("prompts.ext_str_568"), t("prompts.ext_str_703"),
    "user_name", t("prompts.ext_str_351"), t("prompts.ext_str_411"), "kid1_name", t("prompts.ext_str_213"), t("prompts.ext_str_214"),
    "partner_name", t("prompts.ext_str_604"), t("prompts.ext_str_561"),
}


def memory_content_tokens(text: str) -> set[str]:
    tokens = []
    current = []
    for ch in str(text).lower():
        if ch.isalnum() or ch == "_":
            current.append(ch)
        elif current:
            tokens.append("".join(current))
            current = []
    if current:
        tokens.append("".join(current))

    return {
        token
        for token in tokens
        if len(token) >= 4
        and not any(ch.isdigit() for ch in token)
        and token not in MEMORY_TOKEN_STOPWORDS
    }


def memory_overlap_ratio(new_fact: str, old_content: str) -> float:
    new_tokens = memory_content_tokens(new_fact)
    old_tokens = memory_content_tokens(old_content)
    if not new_tokens or not old_tokens:
        return 0.0
    return len(new_tokens & old_tokens) / min(len(new_tokens), len(old_tokens))


def memory_token_overlap_count(new_fact: str, old_content: str) -> int:
    new_tokens = memory_content_tokens(new_fact)
    old_tokens = memory_content_tokens(old_content)
    if not new_tokens or not old_tokens:
        return 0
    return len(new_tokens & old_tokens)


def memory_has_meaningful_overlap(new_fact: str, old_content: str, *, min_shared_tokens: int = 2) -> bool:
    return memory_token_overlap_count(new_fact, old_content) >= min_shared_tokens


def _first_literal_date(text: str) -> str | None:
    """Returns the first explicit date YYYY-MM-DD within the text itself
    (e.g., "On 2026-06-17, ..."). It intentionally does NOT read metadata — the deterministic
    extractors in session_memory.py always prepend this format to the text,
    making it a more reliable signal than the metadata time_scope (which defaults to
    "today" even for timeless facts without any explicit date)."""
    import re
    match = re.search(r"\b(19|20)\d{2}-\d{2}-\d{2}\b", str(text))
    return match.group(0) if match else None


def memory_looks_episodic(
    new_fact: str,
    old_content: str,
    *,
    new_relation_type: str = "",
    old_relation_type: str = "",
    new_state_markers: list | None = None,
    old_state_markers: list | None = None,
) -> bool:
    """True if the new fact likely describes a DIFFERENT incident/day or
    state evolution compared to the old one — not a simple repetition of a
    timeless/static fact (e.g., permanent preference). In this case, the
    overlap-based dedup should not silently delete the new fact just because
    it shares vocabulary with an older, day-unrelated fact.

    Signals, in order of priority:
      1. relation_type explicitly indicates state evolution (follow_up/state_update/
         temporary_state) — by design, NEVER a simple repetition.
      2. state_markers in the new fact (started/stopped/away/returned/...) —
         specific incident/state change, not a permanent statement.
      3. Explicit, different date within the text of both
         facts (e.g., "On 2026-06-13" vs "On 2026-05-20") — two separate
         days/incidents, not the same event rephrased.
    """
    if str(new_relation_type or "").strip() in ("follow_up", "state_update", "temporary_state"):
        return True

    if new_state_markers:
        return True

    new_date = _first_literal_date(new_fact)
    old_date = _first_literal_date(old_content)
    if new_date and old_date and new_date != old_date:
        return True

    return False


def decide_memory_storage_action(
    decision: dict,
    new_fact: str,
    old_content: str,
    *,
    distance: float | None,
    duplicate_overlap: float = 0.55,
    new_relation_type: str = "",
    old_relation_type: str = "",
    new_state_markers: list | None = None,
    old_state_markers: list | None = None,
) -> dict:
    """Choose keep/overwrite/add-alongside after a close same-category match.

    Embedding distance alone is too broad for personal/family memories: two
    different family events can be close enough to look related. Only explicit
    corrections are allowed to delete old memories automatically.

    [MASTRO-FIX]: The old overlap>=duplicate_overlap -> "keep_old" silently
    deleted EVERY new fact that shared vocabulary with an older one, BEFORE even
    comparing the detail (richness) — a problem especially for close, repetitive
    family events (e.g., walks in the park), which were lost without a trace.
    Now we first check if the pair "looks episodic" (memory_looks_episodic,
    based on the already existing relation_type/state_markers metadata + explicit
    date in the text) — if yes, we keep BOTH (add_alongside) even
    with high overlap. The keep_old/grouping still applies normally
    for permanent/timeless facts that were simply rephrased.
    """
    overlap = memory_overlap_ratio(new_fact, old_content)
    episodic = memory_looks_episodic(
        new_fact,
        old_content,
        new_relation_type=new_relation_type,
        old_relation_type=old_relation_type,
        new_state_markers=new_state_markers,
        old_state_markers=old_state_markers,
    )
    if decision.get("looks_like_correction"):
        action = "overwrite"
    elif overlap >= duplicate_overlap:
        action = "add_alongside" if episodic else "keep_old"
    elif decision.get("keep_old") and float(decision.get("new_richness") or 0) < 1.5:
        action = "keep_old"
    else:
        action = "add_alongside"

    return {
        "action": action,
        "overlap": overlap,
        "distance": distance,
        "episodic": episodic,
    }


def decide_memory_overwrite(
    new_fact: str,
    old_content: str,
    old_metadata: dict | None,
    *,
    new_confidence: float = 0.7,
    stale_days: int = 30,
    now: datetime | None = None,
) -> dict:
    """Return the same keep/overwrite decision used by _save_fact."""
    looks_like_correction = looks_like_memory_correction(new_fact)
    old_age = memory_age_days(old_metadata, now=now)
    stale = old_age is not None and old_age > stale_days
    new_richness = memory_richness(new_fact, {"confidence": new_confidence})
    old_richness = memory_richness(old_content, old_metadata)
    much_longer = len(str(old_content)) > len(str(new_fact)) * 1.3
    keep_old = (
        not looks_like_correction
        and not stale
        and (old_richness > new_richness or (old_richness == new_richness and much_longer))
    )
    return {
        "keep_old": keep_old,
        "looks_like_correction": looks_like_correction,
        "stale": stale,
        "old_age_days": old_age,
        "new_richness": new_richness,
        "old_richness": old_richness,
        "much_longer": much_longer,
    }


class AstakosMemoryManager:
    """Central Memory Manager — the ONE and ONLY write point."""

    def save(self, memory_type: str, **kwargs):
        with vector_lock, memory_lock, _cross_process_lock():
            try:
                if memory_type == "fact":
                    return self._save_fact(**kwargs)
                elif memory_type == "photo":
                    return self._save_photo(**kwargs)
                elif memory_type == "document":
                    return self._save_document(**kwargs)
                elif memory_type == "session":
                    return self._save_session(**kwargs)
                elif memory_type == "working":
                    return self._save_working(**kwargs)
                elif memory_type == "reflection":
                    return self._save_reflection(**kwargs)
                elif memory_type == "event":
                    return self._save_event(**kwargs)
                else:
                    print(f"⚠️ [MemoryManager]: Unknown memory type '{memory_type}'")
            except (EmbeddingsProviderSetupRequired, ProviderAuthError) as exc:
                if memory_type == "fact":
                    print(
                        "\033[93m[MemoryManager]: Semantic save unavailable; "
                        f"preserving structured fact only ({exc})\033[0m",
                    )
                    saved = self._save_fact_profile_only(**kwargs)
                    self._trigger_routine_reconciler(
                        kwargs["fact"],
                        kwargs["category"],
                        kwargs.get("reason", "agent_inferred"),
                        external_content_sources=kwargs.get("external_content_sources"),
                    )
                    return saved
                if memory_type == "photo":
                    print(
                        "\033[93m[MemoryManager]: Semantic photo indexing unavailable; "
                        f"preserving photo archive only ({exc})\033[0m",
                    )
                    return self._append_photo_archive(**kwargs)
                if memory_type == "document":
                    print(
                        "\033[93m[MemoryManager]: Semantic document indexing unavailable; "
                        f"preserving document archive only ({exc})\033[0m",
                    )
                    return self._append_document_archive(**kwargs)
                raise
            except Exception as e:
                import traceback
                print(f"\033[91m[MemoryManager Error]: {e}\033[0m")
                traceback.print_exc()
                return False

    def _save_working(self, new_tags: str):
        from config import WORKING_MEMORY_FILE
        data = []
        if os.path.exists(WORKING_MEMORY_FILE):
            with open(WORKING_MEMORY_FILE, "r", encoding="utf-8") as f:
                try:
                    data = json.load(f)
                except:
                    data = []

        data.append({"tag": new_tags, "time": datetime.now().strftime("%H:%M")})
        data = data[-15:]

        # Atomic write: .tmp -> fsync -> os.replace (no partial/corrupted JSON on crash mid-write)
        tmp_file = WORKING_MEMORY_FILE + ".tmp"
        with open(tmp_file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.flush()
            try:
                os.fsync(f.fileno())
            except OSError:
                pass
        os.replace(tmp_file, WORKING_MEMORY_FILE)
        return True

    def _save_fact_profile_only(
        self,
        *,
        fact: str,
        category: str,
        agent_name: str,
        photo_path: str = None,
        source: str = "unknown",
        reason: str = "agent_inferred",
        confidence: float = 0.7,
        tags: list[str] | None = None,
        entities: list[str] | None = None,
        topic: str = "",
        topic_detail: str = "",
        state_markers: list[str] | None = None,
        time_scope: str = "",
        relation_type: str = "",
        external_content_sources: list[str] | None = None,
        replace_old_fact_text: str | None = None,
    ) -> bool:
        """Persist a fact in structured storage when semantic indexing is unavailable."""
        if category == "photos":
            return False

        from config import PROFILE_DB

        tags = tags or []
        entities = entities or []
        state_markers = state_markers or []
        external_content_sources = external_content_sources or []
        conn = None
        try:
            conn = sqlite3.connect(PROFILE_DB)
            cursor = conn.cursor()
            _ensure_profile_fact_schema(cursor)
            date_str = datetime.now().strftime("%Y-%m-%d")
            profile_metadata = {
                "tags": tags,
                "entities": entities,
                "topic": topic or "",
                "topic_detail": topic_detail or "",
                "state_markers": state_markers,
                "time_scope": time_scope or "",
                "relation_type": relation_type or "",
                "confidence": confidence,
                "source": source,
                "reason": reason,
                "agent_name": agent_name,
            }
            if external_content_sources:
                from core.untrusted_content import EXTERNAL_CONTENT_HISTORY_METADATA_KEY

                profile_metadata[EXTERNAL_CONTENT_HISTORY_METADATA_KEY] = external_content_sources
            metadata_json = json.dumps(profile_metadata, ensure_ascii=False)

            if replace_old_fact_text is not None:
                cursor.execute(
                    "SELECT id FROM profile_facts WHERE category=? AND fact=?",
                    (category, replace_old_fact_text),
                )
                row = cursor.fetchone()
                if not row:
                    normalized_old_fact = replace_old_fact_text.strip().lower()
                    cursor.execute(
                        "SELECT id, fact FROM profile_facts WHERE category=?",
                        (category,),
                    )
                    for candidate_id, candidate_fact in cursor.fetchall():
                        if candidate_fact.strip().lower() == normalized_old_fact:
                            row = (candidate_id,)
                            break
                if row:
                    cursor.execute(
                        "UPDATE profile_facts SET fact=?, photo_path=?, date=?, metadata_json=?, "
                        "created_at=CURRENT_TIMESTAMP WHERE id=?",
                        (fact, photo_path, date_str, metadata_json, row[0]),
                    )
                    print("\033[94m[DB Profile]: Replacing old entry (same as Chroma)\033[0m")
                else:
                    cursor.execute(
                        "INSERT INTO profile_facts (category, fact, photo_path, date, metadata_json) "
                        "VALUES (?, ?, ?, ?, ?)",
                        (category, fact, photo_path, date_str, metadata_json),
                    )
                    print("\033[92m[DB Profile]: New record added.\033[0m")
            else:
                cursor.execute(
                    "SELECT 1 FROM profile_facts WHERE category=? AND fact=? LIMIT 1",
                    (category, fact),
                )
                if cursor.fetchone():
                    print("\033[90m[DB Profile]: Exact duplicate skipped.\033[0m")
                else:
                    cursor.execute(
                        "INSERT INTO profile_facts (category, fact, photo_path, date, metadata_json) "
                        "VALUES (?, ?, ?, ?, ?)",
                        (category, fact, photo_path, date_str, metadata_json),
                    )
                    print("\033[92m[DB Profile]: New record added.\033[0m")
            conn.commit()
            return True
        except Exception as db_err:
            print(f"\033[91m[DB Profile Error]: {db_err}\033[0m")
            return False
        finally:
            if conn:
                conn.close()

    def _save_fact(
        self,
        fact: str,
        category: str,
        agent_name: str,
        photo_path: str = None,
        source: str = "unknown",
        reason: str = "agent_inferred",
        confidence: float = 0.7,
        tags: list[str] | None = None,
        entities: list[str] | None = None,
        topic: str = "",
        topic_detail: str = "",
        state_markers: list[str] | None = None,
        time_scope: str = "",
        relation_type: str = "",
        external_content_sources: list[str] | None = None,
    ):
        # ── Threshold per fact type ──────────────────────────────
        if "[LESSON]" in fact:
            dup_threshold = 0.82   # technical courses — strict
        elif "[USER_FACT]" in fact:
            dup_threshold = 0.82   # events — medium
        else:
            dup_threshold = 0.85   # general

        # [MASTRO-FIX]: Unified overwrite — ONE decision (decide_memory_overwrite) for
        # ALL stores. If we decide here that the old one must be replaced
        # Chroma-record, we store its EXACT text so that step 4
        # (JSON Profile) find and replace THE SAME record — not to
        # run a separate, potentially conflicting, similarity-check.
        replace_old_fact_text = None
        add_alongside_old_text = None

        # 1. Semantic Overwrite for [LESSON] / [USER_FACT] — category-safe first
        if "[LESSON]" in fact or "[USER_FACT]" in fact:
            query_emb = embeddings.embed_query(fact)

            def _meta_of(res):
                try:
                    return (res.get('metadatas') or [[]])[0][0] or {}
                except (IndexError, TypeError):
                    return {}

            # Search FIRST within the SAME category — we avoid comparing
            # (and potentially erase) irrelevant memory of another category simply
            # because its embedding happened to be similar.
            same_cat = _safe_chroma_query(
                query_embeddings=[query_emb],
                n_results=1,
                where={"category": category},
                include=["documents", "metadatas", "distances"],
            )

            old_id = old_content = old_meta = None
            dist = None
            if same_cat['ids'] and same_cat['ids'][0]:
                d = same_cat['distances'][0][0]
                if d < 0.25:
                    old_id = same_cat['ids'][0][0]
                    old_content = same_cat['documents'][0][0]
                    old_meta = _meta_of(same_cat)
                    dist = d

            if old_id is None and not same_cat.get("_error"):
                # Nothing close within the category — see if there is something suspicious
                # close cross-category. Update only, we NEVER delete cross-category.
                cross = _safe_chroma_query(
                    query_embeddings=[query_emb],
                    n_results=1,
                    include=["documents", "metadatas", "distances"],
                )
                cross_ids = cross.get("ids") or [[]]
                cross_distances = cross.get("distances") or [[]]
                cross_documents = cross.get("documents") or [[]]

                if (
                    cross_ids and cross_ids[0]
                    and cross_distances and cross_distances[0]
                    and cross_distances[0][0] < 0.20
                ):
                    c_meta = _meta_of(cross)
                    c_doc = cross_documents[0][0]

                    if memory_has_meaningful_overlap(fact, c_doc):
                        print(
                            f"\033[93m[MemoryManager]: ⚠️ Close memory in another category "
                            f"({c_meta.get('category', '?')}, dist={cross_distances[0][0]:.3f}): "
                            f"{c_doc[:80]} — skipping it (different category).\033[0m"
                        )

            if old_id is not None:
                decision = decide_memory_overwrite(
                    fact,
                    old_content,
                    old_meta,
                    new_confidence=confidence,
                )
                try:
                    old_state_markers = json.loads((old_meta or {}).get("state_markers") or "[]")
                except Exception:
                    old_state_markers = []
                storage = decide_memory_storage_action(
                    decision,
                    fact,
                    old_content,
                    distance=dist,
                    new_relation_type=relation_type,
                    old_relation_type=(old_meta or {}).get("relation_type") or "",
                    new_state_markers=state_markers,
                    old_state_markers=old_state_markers,
                )

                if storage["action"] == "keep_old":
                    print(
                        f"\033[90m[MemoryManager]: Keep richer! Old (richness={decision['old_richness']:.1f}, "
                        f"{len(old_content)} char) > New (richness={decision['new_richness']:.1f}, {len(str(fact))} char) "
                        f"— keeping the detailed one, the new one is NOT saved (avoiding duplication).\033[0m"
                    )
                    # [MASTRO-FIX]: keep_old until now only meant "do not delete the
                    # old" — but the code proceeded to save anyway
                    # of the new one, ending up with TWO almost-identical entries in Chroma
                    # (the loose SIM_THRESHOLD_DISTANCE=0.30 did not always catch it).
                    # If we decided to "keep the old one", we stop here — in NO store.
                    _audit_log("skip_keep_old", category=category,
                               fact=str(fact)[:100], old=str(old_content)[:100],
                               old_richness=round(decision["old_richness"], 1),
                               new_richness=round(decision["new_richness"], 1),
                               distance=round(float(dist), 3) if dist is not None else None,
                               overlap=round(float(storage["overlap"]), 3))
                    self._trigger_routine_reconciler(
                        fact,
                        category,
                        reason,
                        external_content_sources=external_content_sources,
                    )
                    return False
                elif storage["action"] == "add_alongside":
                    add_alongside_old_text = old_content
                    print(
                        f"\033[90m[MemoryManager]: Add alongside close memory "
                        f"(dist={dist:.3f}, overlap={storage['overlap']:.2f}, "
                        f"episodic={storage.get('episodic', False)}) - keeping both.\033[0m"
                    )
                    _audit_log("add_alongside", category=category,
                               fact=str(fact)[:100], old=str(old_content)[:100],
                               distance=round(float(dist), 3) if dist is not None else None,
                               overlap=round(float(storage["overlap"]), 3),
                               episodic=bool(storage.get("episodic", False)))
                else:
                    deleted = _safe_chroma_delete([old_id])
                    if not deleted:
                        _audit_log(
                            "delete_skip",
                            category=category,
                            fact=str(fact)[:100],
                            old=str(old_content)[:100],
                            old_id=old_id,
                        )
                    reason_tag = []
                    if decision["looks_like_correction"]:
                        reason_tag.append(t("prompts.ext_str_157"))
                    if decision["stale"]:
                        reason_tag.append(t("memory.vector_store.old_record", days=decision['old_age_days']))
                    if not decision["looks_like_correction"] and not decision["stale"]:
                        reason_tag.append(f"richness {decision['new_richness']:.1f}≥{decision['old_richness']:.1f}")
                    tag_str = f" [{', '.join(reason_tag)}]" if reason_tag else ""
                    print(f"\033[94m[MemoryManager]: Overwrite!{tag_str} ({old_content[:80]} | Dist: {dist:.3f})\033[0m")
                    _audit_log("overwrite", category=category,
                               fact=str(fact)[:100], old=str(old_content)[:100],
                               reason=", ".join(reason_tag) if reason_tag else "richness",
                               distance=round(float(dist), 3) if dist is not None else None,
                               overlap=round(float(storage["overlap"]), 3))
                    # The SAME decision will also guide the JSON Profile below —
                    # we keep the exact text of the old record to find it there.
                    replace_old_fact_text = old_content

        # 2. Duplicate check with dynamic threshold
        results = vector_store.similarity_search_with_score(fact, k=1)
        for doc, score in results:
            if score >= SIM_THRESHOLD_DISTANCE:
                continue

            if doc.metadata.get("category") != category:
                continue

            if add_alongside_old_text is not None and doc.page_content == add_alongside_old_text:
                continue

            if category == "family":
                existing_topic = str(doc.metadata.get("topic") or "").strip().lower()
                existing_detail = str(doc.metadata.get("topic_detail") or "").strip().lower()
                existing_relation = str(doc.metadata.get("relation_type") or "").strip().lower()

                try:
                    existing_state_markers = json.loads(doc.metadata.get("state_markers") or "[]")
                except Exception:
                    existing_state_markers = []

                same_topic = bool(topic and str(topic).strip().lower() == existing_topic)
                same_detail = bool(topic_detail and str(topic_detail).strip().lower() == existing_detail)
                overlap = memory_overlap_ratio(fact, doc.page_content)
                episodic = memory_looks_episodic(
                    fact,
                    doc.page_content,
                    new_relation_type=relation_type,
                    old_relation_type=existing_relation,
                    new_state_markers=state_markers,
                    old_state_markers=existing_state_markers,
                )

                if overlap < 0.82:
                    continue
                if not (same_topic or same_detail):
                    continue
                if episodic:
                    continue

            if "[USER_FACT]" in fact:
                shared_tokens = memory_token_overlap_count(fact, doc.page_content)
                if shared_tokens < 2:
                    continue

            print(f"\033[90m[MemoryManager]: Duplicate skip (distance={score:.3f}): {doc.page_content}\033[0m")
            _audit_log(
                "skip_duplicate",
                category=category,
                fact=str(fact)[:100],
                existing=doc.page_content[:100],
                distance=round(float(score), 3),
            )
            self._trigger_routine_reconciler(
                fact,
                category,
                reason,
                external_content_sources=external_content_sources,
            )
            return False

        # 3. Chroma Storage
        # Auto-compute importance
        if "goal" in category:
            _importance = 10
        elif reason == "user_stated" or "[USER_FACT]" in fact:
            _importance = 8
        elif "[LESSON]" in fact:
            _importance = 7
        elif reason == "agent_inferred":
            _importance = 5
        else:
            _importance = 6

        tags = tags or []
        entities = entities or []
        state_markers = state_markers or []
        external_content_sources = external_content_sources or []
        now_ts = datetime.now().timestamp()
        metadata = {
            "category": category, "agent": agent_name,
            "timestamp": now_ts, "date": datetime.now().strftime("%Y-%m-%d"),
            "retrieval_count": 0,
            "last_accessed": now_ts,
            "importance": _importance,
            "confidence": confidence,
            "source": source,
            "reason": reason,
            "tags": _json_meta_list(tags),
            "entities": _json_meta_list(entities),
            "topic": topic or "",
            "topic_detail": topic_detail or "",
            "state_markers": _json_meta_list(state_markers),
            "time_scope": time_scope or "",
            "relation_type": relation_type or "",
        }
        if external_content_sources:
            from core.untrusted_content import EXTERNAL_CONTENT_HISTORY_METADATA_KEY

            metadata[EXTERNAL_CONTENT_HISTORY_METADATA_KEY] = _json_meta_list(
                external_content_sources,
            )
        if photo_path:
            if not os.path.isabs(photo_path):
                photo_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", photo_path)
            metadata["photo_path"] = photo_path

        vector_store.add_texts([fact], metadatas=[metadata])
        _audit_log(
            "add",
            category=category,
            fact=str(fact)[:100],
            importance=_importance,
            confidence=confidence,
            source=source,
            tags=tags,
            entities=entities,
            topic=topic or "",
            topic_detail=topic_detail or "",
            state_markers=state_markers,
            time_scope=time_scope or "",
            relation_type=relation_type or "",
        )

# 4. Save DB Profile — with the same overwrite decision as semantic storage.
        self._save_fact_profile_only(
            fact=fact,
            category=category,
            agent_name=agent_name,
            photo_path=photo_path,
            source=source,
            reason=reason,
            confidence=confidence,
            tags=tags,
            entities=entities,
            topic=topic,
            topic_detail=topic_detail,
            state_markers=state_markers,
            time_scope=time_scope,
            relation_type=relation_type,
            external_content_sources=external_content_sources,
            replace_old_fact_text=replace_old_fact_text,
        )

        # 5. Automatic fact -> routine reconciliation
        self._trigger_routine_reconciler(
            fact,
            category,
            reason,
            external_content_sources=external_content_sources,
        )
        return True

    def _trigger_routine_reconciler(
        self,
        fact: str,
        category: str,
        reason: str,
        *,
        external_content_sources: list[str] | None = None,
    ) -> None:
        """Reconcile trusted facts with routines without extending external approval scope."""
        if external_content_sources:
            print("\033[90m[RoutineReconciler]: skip untrusted external fact\033[0m")
            return

        # Runs to evaluate facts against routines, EVEN IF the memory wasn't saved
        # (e.g. because it was already known/duplicate). We still want to act on the fact today.
        try:
            from services.routine_reconciler import reconcile_fact_to_routines

            reconcile_stats = reconcile_fact_to_routines(
                fact,
                category=category,
                reason=reason,
            )
            if reconcile_stats.get("applied"):
                print(
                    "\033[95m[RoutineReconciler]: "
                    f"{reconcile_stats['directives']} directive(s), "
                    f"matched={reconcile_stats['matched_routines']}, "
                    f"paused={reconcile_stats.get('schedule_paused', 0)}, "
                    f"muted={reconcile_stats.get('notifications_muted', 0)}, "
                    f"unmuted={reconcile_stats.get('notifications_unmuted', 0)}"
                    "\033[0m"
                )
        except Exception as reconcile_err:
            print(f"\033[90m[RoutineReconciler]: skip ({reconcile_err})\033[0m")

    def _save_photo(
        self,
        file_path: str,
        analysis: str,
        caption: str,
        external_content_sources: list[str] | None = None,
    ):
        """Store a photo archive while retaining any untrusted-source provenance."""
        fact = t("memory.vector_store.photo_fact", caption=caption or t("memory.vector_store.photo_default"), analysis=analysis[:350])
        metadata = {
            "category": "photos", "agent": "Direct_Index", "photo_path": file_path,
            "timestamp": datetime.now().timestamp(), "date": datetime.now().strftime("%Y-%m-%d"),
            "retrieval_count": 0,
            "importance": 4, "confidence": 0.8,
            "last_accessed": datetime.now().timestamp(),
        }
        if external_content_sources:
            from core.untrusted_content import EXTERNAL_CONTENT_HISTORY_METADATA_KEY

            metadata[EXTERNAL_CONTENT_HISTORY_METADATA_KEY] = _json_meta_list(
                external_content_sources,
            )
        vector_store.add_texts([fact], metadatas=[metadata])
        print(f"\033[92m[ChromaDB]: Photo 'pinned' ({os.path.basename(file_path)})\033[0m")

        self._append_photo_archive(
            file_path=file_path,
            analysis=analysis,
            caption=caption,
            external_content_sources=external_content_sources,
        )
        return True

    def _append_photo_archive(
        self,
        *,
        file_path: str,
        analysis: str,
        caption: str,
        external_content_sources: list[str] | None = None,
    ) -> bool:
        """Append a confirmed photo to its non-semantic archive."""
        entry = {
            "file_path": file_path, "analysis": analysis, "caption": caption,
            "date": datetime.now().strftime("%Y-%m-%d"), "timestamp": datetime.now().isoformat(),
            "external_content_sources": external_content_sources or [],
        }
        index = []
        if os.path.exists(PHOTOS_INDEX_FILE):
            with open(PHOTOS_INDEX_FILE, "r", encoding="utf-8") as f:
                try:
                    index = json.load(f)
                except:
                    pass
        index.append(entry)
        with open(PHOTOS_INDEX_FILE, "w", encoding="utf-8") as f:
            json.dump(index, f, ensure_ascii=False, indent=2)
        return True

    def _save_document(
        self,
        file_path: str,
        analysis: str,
        caption: str,
        external_content_sources: list[str] | None = None,
    ):
        """Store a document archive while retaining any untrusted-source provenance."""
        fact = t("memory.vector_store.doc_fact", caption=caption or t("memory.vector_store.doc_default"), analysis=analysis[:1000])
        metadata = {
            "category": "documents", "agent": "Direct_Index", "file_path": file_path,
            "timestamp": datetime.now().timestamp(), "date": datetime.now().strftime("%Y-%m-%d"),
            "retrieval_count": 0,
            "importance": 5, "confidence": 0.8,
            "last_accessed": datetime.now().timestamp(),
        }
        if external_content_sources:
            from core.untrusted_content import EXTERNAL_CONTENT_HISTORY_METADATA_KEY

            metadata[EXTERNAL_CONTENT_HISTORY_METADATA_KEY] = _json_meta_list(
                external_content_sources,
            )
        vector_store.add_texts([fact], metadatas=[metadata])
        print(f"\033[92m[ChromaDB]: Document 'pinned' ({os.path.basename(file_path)})\033[0m")

        self._append_document_archive(
            file_path=file_path,
            analysis=analysis,
            caption=caption,
            external_content_sources=external_content_sources,
        )
        return True

    def _append_document_archive(
        self,
        *,
        file_path: str,
        analysis: str,
        caption: str,
        external_content_sources: list[str] | None = None,
    ) -> bool:
        """Append a confirmed document to its non-semantic archive."""
        from config import DOCS_INDEX_FILE

        entry = {
            "file_path": file_path, "summary": analysis, "caption": caption,
            "date": datetime.now().strftime("%Y-%m-%d"), "timestamp": datetime.now().isoformat(),
            "external_content_sources": external_content_sources or [],
        }
        index = []
        if os.path.exists(DOCS_INDEX_FILE):
            with open(DOCS_INDEX_FILE, "r", encoding="utf-8") as f:
                try:
                    index = json.load(f)
                except:
                    pass
        index.append(entry)
        with open(DOCS_INDEX_FILE, "w", encoding="utf-8") as f:
            json.dump(index, f, ensure_ascii=False, indent=2)
        return True

    def _save_session(self, summary: dict, session_text: str):
        vector_store.add_texts([session_text], metadatas=[{
            "category": "session", "date": summary.get("date"),
            "mood": summary.get("mood", "unknown"), "agent": "SessionSummary",
            "timestamp": datetime.now().timestamp(),
            "retrieval_count": 0,
            "importance": 4, "confidence": 0.9,
            "last_accessed": datetime.now().timestamp(),
        }])

        conn = None
        try:
            conn = sqlite3.connect(STATE_DB)
            cursor = conn.cursor()

            completed = json.dumps(summary.get("completed", []), ensure_ascii=False)
            pending = json.dumps(summary.get("pending", []), ensure_ascii=False)

            cursor.execute('''
                INSERT INTO sessions (session_date, channel, summary, completed, pending, next_session_hint, mood)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (
                summary.get("date", ""),
                summary.get("channel", ""),
                summary.get("summary", ""),
                completed,
                pending,
                summary.get("next_session_hint", ""),
                summary.get("mood", "")
            ))

            cursor.execute("SELECT id FROM sessions ORDER BY id DESC LIMIT -1 OFFSET 30")
            old_ids = cursor.fetchall()
            for (old_id,) in old_ids:
                cursor.execute("DELETE FROM sessions WHERE id=?", (old_id,))

            conn.commit()
        except Exception as e:
            print(f"Error saving session to DB: {e}")
        finally:
            if conn:
                conn.close()

        return True


    def _save_reflection(self, source: str, observation: str, action: str,
                         confidence: float = 0.7, lesson: str = "", applied: bool = False):
        """Wrapper → services/reflection_engine._save_reflection"""
        from services.reflection_engine import _save_reflection
        _save_reflection(source=source, observation=observation, action=action,
                        confidence=confidence, lesson=lesson, applied=applied)
        return True

    def _save_event(self, job: str, action: str, **kwargs):
        """Wrapper → memory/event_log.log_event"""
        from memory.event_log import log_event
        log_event(job=job, action=action, **kwargs)
        return True


def bump_retrieval_count(doc_ids: list[str]):
    """
    Increments the retrieval_count by 1 for each doc_id.
    Called after each semantic search that returns results.
    """
    if not doc_ids:
        return
    try:
        with vector_lock, _cross_process_lock():
            existing = _safe_chroma_get(ids=doc_ids, include=["metadatas", "documents"])
            if not existing["ids"]:
                return
            new_metas = []
            for meta in existing["metadatas"]:
                m = dict(meta)
                m["retrieval_count"] = int(m.get("retrieval_count", 0)) + 1
                m["last_accessed"] = datetime.now().timestamp()
                new_metas.append(m)
            vector_store._collection.update(ids=existing["ids"], metadatas=new_metas)
    except Exception as e:
        print(f"\033[90m[bump_retrieval_count]: {e}\033[0m")



def compute_score(metadata: dict) -> float:
    """
    Calculates the score of a memory.
    score = importance*0.4 + retrieval_count_norm*0.3 + confidence*0.2 + freshness*0.1
    """
    from datetime import datetime as _dt
    importance     = float(metadata.get("importance", 5)) / 10.0
    retrieval      = min(float(metadata.get("retrieval_count", 0)) / 20.0, 1.0)  # cap at 20
    confidence     = float(metadata.get("confidence", 0.7))
    # Freshness: 1.0 = today, 0.0 = 365 days ago
    last_ts = metadata.get("last_accessed") or metadata.get("timestamp", 0)
    days_old = (_dt.now().timestamp() - float(last_ts)) / 86400.0
    freshness = max(0.0, 1.0 - days_old / 365.0)

    return round(
        importance * 0.4 +
        retrieval  * 0.3 +
        confidence * 0.2 +
        freshness  * 0.1,
        3
    )



# Singleton
memory = AstakosMemoryManager()


def save_photo_to_index(file_path: str, analysis: str, caption: str = ""):
    """Wrapper — sends the photo data to the Memory Manager."""
    memory.save(memory_type="photo", file_path=file_path, analysis=analysis, caption=caption)

# ================================================================
# Long-Term Goals
# ================================================================

def _merged_goal_external_content_sources(
    metadata: dict | None,
    new_sources: list[str] | None,
) -> list[str]:
    """Merge existing goal provenance with an approved external goal update."""
    from core.untrusted_content import (
        EXTERNAL_CONTENT_HISTORY_METADATA_KEY,
        external_content_sources_from_json,
    )

    existing_sources = external_content_sources_from_json(
        (metadata or {}).get(EXTERNAL_CONTENT_HISTORY_METADATA_KEY, ""),
    )
    return sorted(set(existing_sources) | set(new_sources or []))


def save_goal(
    project: str,
    description: str,
    status: str = "active",
    progress: int = 0,
    milestones: str = "",
    external_content_sources: list[str] | None = None,
) -> bool:
    """Save or update a goal while retaining any untrusted-source provenance."""
    try:
        with vector_lock, _cross_process_lock():
            existing = _safe_chroma_get(where={"$and": [{"category": "goal"}, {"project": project}]})
            existing_metadata = None
            if existing["ids"]:
                existing_metadata = dict(existing["metadatas"][0])
                vector_store._collection.delete(ids=existing["ids"])
                print(f"\033[94m[Goals]: Overwrite '{project}'\033[0m")
            merged_sources = _merged_goal_external_content_sources(
                existing_metadata,
                external_content_sources,
            )
            text = f"[GOAL] {project}: {description}"
            metadata = {
                "category": "goal", "project": project, "status": status,
                "progress": progress, "milestones": milestones,
                "agent": "GoalTracker", "timestamp": datetime.now().timestamp(),
                "date": datetime.now().strftime("%Y-%m-%d"), "retrieval_count": 0,
                "importance": 10, "confidence": 0.95, "last_accessed": datetime.now().timestamp(),
            }
            if merged_sources:
                from core.untrusted_content import EXTERNAL_CONTENT_HISTORY_METADATA_KEY

                metadata[EXTERNAL_CONTENT_HISTORY_METADATA_KEY] = _json_meta_list(
                    merged_sources,
                )
            vector_store.add_texts([text], metadatas=[metadata])
            print(f"\033[92m[Goals]: '{project}' ({status}, {progress}%)\033[0m")
            return True
    except Exception as e:
        print(f"\033[91m[Goals Error]: {e}\033[0m")
        return False


def update_goal_status(project: str, status: str) -> bool:
    """Changes the status of a goal."""
    try:
        with vector_lock, _cross_process_lock():
            existing = _safe_chroma_get(where={"$and": [{"category": "goal"}, {"project": project}]})
            if not existing["ids"]:
                return False
            old_meta = dict(existing["metadatas"][0])
            vector_store._collection.delete(ids=existing["ids"])
            new_meta = {**old_meta, "status": status, "timestamp": datetime.now().timestamp()}
            vector_store.add_texts([existing["documents"][0]], metadatas=[new_meta])
            print(f"\033[92m[Goals]: '{project}' → {status}\033[0m")
            return True
    except Exception as e:
        print(f"\033[91m[Goals Error]: {e}\033[0m")
        return False


def update_goal_progress(project: str, progress: int) -> bool:
    """Updates the progress percentage of a goal (0-100)."""
    try:
        with vector_lock, _cross_process_lock():
            existing = _safe_chroma_get(where={"$and": [{"category": "goal"}, {"project": project}]})
            if not existing["ids"]:
                return False
            old_meta = dict(existing["metadatas"][0])
            vector_store._collection.delete(ids=existing["ids"])
            new_meta = {**old_meta, "progress": max(0, min(100, progress)), "timestamp": datetime.now().timestamp()}
            vector_store.add_texts([existing["documents"][0]], metadatas=[new_meta])
            print(f"\033[92m[Goals]: '{project}' progress → {progress}%\033[0m")
            return True
    except Exception as e:
        print(f"\033[91m[Goals Error]: {e}\033[0m")
        return False


def update_goal_milestones(
    project: str,
    milestones: str,
    external_content_sources: list[str] | None = None,
) -> bool:
    """Update goal milestones while retaining any external-source provenance."""
    try:
        with vector_lock, _cross_process_lock():
            existing = _safe_chroma_get(where={"$and": [{"category": "goal"}, {"project": project}]})
            if not existing["ids"]:
                return False
            old_meta = dict(existing["metadatas"][0])
            vector_store._collection.delete(ids=existing["ids"])
            new_meta = {**old_meta, "milestones": milestones, "timestamp": datetime.now().timestamp()}
            merged_sources = _merged_goal_external_content_sources(
                old_meta,
                external_content_sources,
            )
            if merged_sources:
                from core.untrusted_content import EXTERNAL_CONTENT_HISTORY_METADATA_KEY

                new_meta[EXTERNAL_CONTENT_HISTORY_METADATA_KEY] = _json_meta_list(
                    merged_sources,
                )
            vector_store.add_texts([existing["documents"][0]], metadatas=[new_meta])
            print(f"\033[92m[Goals]: '{project}' milestones updated\033[0m")
            return True
    except Exception as e:
        print(f"\033[91m[Goals Error]: {e}\033[0m")
        return False


def get_active_goals() -> list[dict]:
    """Returns active/paused goals."""
    try:
        with vector_lock, _cross_process_lock():
            results = vector_store._collection.get(where={"category": "goal"})
        goals = []
        for doc, meta in zip(results.get("documents", []), results.get("metadatas", [])):
            if meta.get("status") in ("active", "paused"):
                goals.append({
                    "project":     meta.get("project", ""),
                    "description": doc.split(": ", 1)[-1].replace("[GOAL] ", ""),
                    "status":      meta.get("status", "active"),
                    "date":        meta.get("date", ""),
                    "progress":    meta.get("progress", 0),
                    "milestones":  meta.get("milestones", ""),
                    "metadata": meta,
                })
        return goals
    except Exception as e:
        print(f"\033[91m[Goals Error]: {e}\033[0m")
        return []


def _safe_load_metadata_json(raw: str | None) -> dict:
    import json
    if not raw:
        return {}
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _profile_row_to_memory_doc(row) -> dict:
    metadata = _safe_load_metadata_json(row["metadata_json"])

    return {
        "id": row["id"],
        "category": row["category"],
        "fact": row["fact"],
        "photo_path": row["photo_path"],
        "date": row["date"],
        "created_at": row["created_at"],
        "tags": metadata.get("tags", []) or [],
        "entities": metadata.get("entities", []) or [],
        "topic": metadata.get("topic", "") or "",
        "topic_detail": metadata.get("topic_detail", "") or "",
        "state_markers": metadata.get("state_markers", []) or [],
        "time_scope": metadata.get("time_scope", "") or "",
        "relation_type": metadata.get("relation_type", "") or "",
        "confidence": metadata.get("confidence"),
        "source": metadata.get("source", "") or "",
        "reason": metadata.get("reason", "") or "",
        "agent_name": metadata.get("agent_name", "") or "",
        "metadata": metadata,
    }


def delete_profile_facts_by_exact_fact(fact: str) -> int:
    """Delete structured-profile records whose fact exactly matches fact."""
    from config import PROFILE_DB

    normalized_fact = str(fact or "").strip()
    if not normalized_fact:
        return 0

    conn = None
    try:
        conn = sqlite3.connect(PROFILE_DB)
        cursor = conn.cursor()
        cursor.execute(
            """
            DELETE FROM profile_facts
            WHERE lower(trim(fact)) = lower(trim(?))
            """,
            (normalized_fact,),
        )
        deleted_count = cursor.rowcount
        conn.commit()
        return deleted_count
    except Exception as exc:
        print(f"[ProfileFacts Delete Error]: {exc}")
        raise
    finally:
        if conn:
            conn.close()


def get_profile_facts(
    category: str | None = None,
    limit: int = 100,
) -> list[dict]:
    from config import PROFILE_DB
    import sqlite3

    conn = None
    try:
        conn = sqlite3.connect(PROFILE_DB)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()

        if category:
            c.execute(
                """
                SELECT id, category, fact, photo_path, date, metadata_json, created_at
                FROM profile_facts
                WHERE category = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (category, limit),
            )
        else:
            c.execute(
                """
                SELECT id, category, fact, photo_path, date, metadata_json, created_at
                FROM profile_facts
                ORDER BY id DESC
                LIMIT ?
                """,
                (limit,),
            )

        rows = c.fetchall()
        return [_profile_row_to_memory_doc(row) for row in rows]

    except Exception as e:
        print(f"[ProfileFacts Error]: {e}")
        return []
    finally:
        if conn:
            conn.close()


def filter_profile_docs_by_entity(docs: list[dict], entity: str) -> list[dict]:
    needle = entity.strip().lower()
    if not needle:
        return docs
    out = []
    for doc in docs:
        entities = doc.get("entities", []) or []
        if any(str(x).strip().lower() == needle for x in entities):
            out.append(doc)
    return out


def filter_profile_docs_by_topic(docs: list[dict], topic: str) -> list[dict]:
    needle = topic.strip().lower()
    if not needle:
        return docs
    return [
        doc for doc in docs
        if str(doc.get("topic", "")).strip().lower() == needle
    ]


def filter_profile_docs_by_topic_detail(docs: list[dict], topic_detail: str) -> list[dict]:
    needle = topic_detail.strip().lower()
    if not needle:
        return docs
    return [
        doc for doc in docs
        if str(doc.get("topic_detail", "")).strip().lower() == needle
    ]


def filter_profile_docs_by_relation_type(docs: list[dict], relation_type: str) -> list[dict]:
    needle = relation_type.strip().lower()
    if not needle:
        return docs
    return [
        doc for doc in docs
        if str(doc.get("relation_type", "")).strip().lower() == needle
    ]


def filter_profile_docs_by_state_marker(docs: list[dict], marker: str) -> list[dict]:
    needle = marker.strip().lower()
    if not needle:
        return docs
    out = []
    for doc in docs:
        markers = doc.get("state_markers", []) or []
        if any(str(x).strip().lower() == needle for x in markers):
            out.append(doc)
    return out


def get_recent_entity_topic_facts(
    entity: str,
    topic: str,
    limit: int = 10,
    category: str | None = None,
) -> list[dict]:
    docs = get_profile_facts(category=category, limit=300)

    docs = filter_profile_docs_by_entity(docs, entity)
    docs = filter_profile_docs_by_topic(docs, topic)

    docs.sort(
        key=lambda d: (
            str(d.get("date", "") or ""),
            str(d.get("created_at", "") or ""),
            int(d.get("id", 0) or 0),
        ),
        reverse=True,
    )
    return docs[:limit]


def get_latest_entity_state(
    entity: str,
    topic: str,
    category: str | None = None,
) -> dict | None:
    docs = get_recent_entity_topic_facts(
        entity=entity,
        topic=topic,
        limit=20,
        category=category,
    )

    if not docs:
        return None

    stateful_docs = [
        d for d in docs
        if d.get("state_markers") or d.get("relation_type") in {
            "temporary_state",
            "state_update",
            "follow_up",
            "confirmed",
        }
    ]

    return stateful_docs[0] if stateful_docs else docs[0]


def get_profile_docs_with_photos(
    category: str | None = None,
    limit: int = 100,
) -> list[dict]:
    docs = get_profile_facts(category=category, limit=limit)
    return [d for d in docs if d.get("photo_path")]


def _profile_doc_match_score(doc: dict, query: str) -> int:
    q = (query or "").strip().lower()
    if not q:
        return 0

    tokens = [tok for tok in q.split() if len(tok) >= 2]
    if not tokens:
        tokens = [q]

    score = 0
    fact = str(doc.get("fact", "")).lower()
    topic = str(doc.get("topic", "")).lower()
    topic_detail = str(doc.get("topic_detail", "")).lower()
    relation_type = str(doc.get("relation_type", "")).lower()
    entities = [str(x).strip().lower() for x in (doc.get("entities", []) or []) if str(x).strip()]
    tags = [str(x).strip().lower() for x in (doc.get("tags", []) or []) if str(x).strip()]
    state_markers = [str(x).strip().lower() for x in (doc.get("state_markers", []) or []) if str(x).strip()]

    for token in tokens:
        if token in fact:
            score += 3
        if topic and (token == topic or token in topic):
            score += 4
        if topic_detail and (token == topic_detail or token in topic_detail):
            score += 4
        if relation_type and (token == relation_type or token in relation_type):
            score += 1
        if any(token == entity or token in entity for entity in entities):
            score += 5
        if any(token == tag or token in tag for tag in tags):
            score += 3
        if any(token == state or token in state for state in state_markers):
            score += 1

    return score


def search_profile_facts(query: str, category: str | None = None, limit: int = 10) -> list[dict]:
    docs = get_profile_facts(category=category, limit=300)
    scored = []
    for doc in docs:
        score = _profile_doc_match_score(doc, query)
        if score > 0:
            scored.append((score, doc))

    scored.sort(
        key=lambda item: (
            item[0],
            str(item[1].get("date", "") or ""),
            str(item[1].get("created_at", "") or ""),
            int(item[1].get("id", 0) or 0),
        ),
        reverse=True,
    )
    return [doc for _, doc in scored[:limit]]


def get_latest_state_for_query(query: str, category: str | None = None) -> dict | None:
    docs = search_profile_facts(query, category=category, limit=20)
    if not docs:
        return None

    stateful_docs = [
        d for d in docs
        if d.get("state_markers") or d.get("relation_type") in {
            "temporary_state",
            "state_update",
            "follow_up",
            "confirmed",
        }
    ]
    return stateful_docs[0] if stateful_docs else docs[0]


def get_recent_profile_facts_for_query(
    query: str,
    category: str | None = None,
    limit: int = 8,
) -> list[dict]:
    return search_profile_facts(query, category=category, limit=limit)


def format_profile_fact(doc: dict) -> str:
    fact = doc.get("fact", "").strip()
    states = ", ".join(doc.get("state_markers", []) or [])
    topic = doc.get("topic", "")
    relation_type = doc.get("relation_type", "")

    bits = []
    if topic:
        bits.append(f"topic={topic}")
    if relation_type:
        bits.append(f"rel={relation_type}")
    if states:
        bits.append(f"states={states}")

    suffix = f" [{' | '.join(bits)}]" if bits else ""
    return f"{fact}{suffix}"


def build_profile_memory_summary(query: str, category: str | None = None, limit: int = 5) -> list[str]:
    docs = search_profile_facts(query, category=category, limit=limit)
    if not docs:
        return []

    lines = []
    for doc in docs:
        fact = doc.get("fact", "").strip()
        topic = doc.get("topic", "")
        topic_detail = doc.get("topic_detail", "")
        relation_type = doc.get("relation_type", "")
        states = ", ".join(doc.get("state_markers", []) or [])
        entities = ", ".join(doc.get("entities", []) or [])

        meta_bits = []
        if entities:
            meta_bits.append(f"entities={entities}")
        if topic:
            meta_bits.append(f"topic={topic}")
        if topic_detail:
            meta_bits.append(f"detail={topic_detail}")
        if relation_type:
            meta_bits.append(f"rel={relation_type}")
        if states:
            meta_bits.append(f"states={states}")

        meta_suffix = f" [{' | '.join(meta_bits)}]" if meta_bits else ""
        lines.append(f"  • {fact}{meta_suffix}")

    return lines

