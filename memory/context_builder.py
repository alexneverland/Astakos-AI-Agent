from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
import os
from typing import Callable, Iterable, Any

from config import BASE_DIR


MEMORY_CONTEXT_DEBUG_FILE = os.path.join(BASE_DIR, "runtime_memory_context.json")


@dataclass(frozen=True)
class MemoryContext:
    recent_lines: list[str]
    semantic_facts: list[str]

    def render(self) -> str:
        sections = []
        if self.recent_lines:
            sections.append(
                "[ΠΡΟΣΦΑΤΟ ΙΣΤΟΡΙΚΟ WEB+TELEGRAM]\n"
                + "\n".join(self.recent_lines)
            )
        if self.semantic_facts:
            sections.append(
                "[ΣΧΕΤΙΚΕΣ ΜΝΗΜΕΣ CHROMA]\n"
                + "\n".join(f"• {fact}" for fact in self.semantic_facts)
            )
        if not sections:
            return ""
        return (
            "\n\n".join(sections)
            + "\n\nΧρησιμοποίησε αυτά ως φόντο. Αν συγκρούονται με το τρέχον μήνυμα, προτίμησε το τρέχον μήνυμα."
        )


def format_recent_messages(messages: Iterable[dict[str, Any]], *, limit: int = 10) -> list[str]:
    if limit <= 0:
        return []
    lines = []
    for message in list(messages)[-limit:]:
        role = message.get("role", "")
        speaker = "Λάζαρος" if role == "user" else "Αστακός"
        channel = message.get("channel", "?")
        time_label = message.get("time") or str(message.get("timestamp", ""))[-8:-3]
        content = str(message.get("content", "")).strip()
        if not content:
            continue
        content = " ".join(content.split())
        if len(content) > 260:
            content = content[:257].rstrip() + "..."
        lines.append(f"- [{channel} {time_label}] {speaker}: {content}")
    return lines


def semantic_facts_for_query(
    query: str,
    *,
    k: int = 5,
    search_fn: Callable[[str, int], Iterable[Any]] | None = None,
) -> list[str]:
    clean_query = str(query or "").strip()
    if len(clean_query) < 8 or k <= 0:
        return []

    if search_fn is None:
        from memory.vector_store import vector_lock, vector_store

        def search_fn(q: str, n: int):
            with vector_lock:
                return vector_store.similarity_search(q, k=n)

    facts = []
    seen = set()
    for result in search_fn(clean_query, k):
        content = getattr(result, "page_content", str(result))
        fact = content.split(" [Tags:")[0].strip()
        if not fact or fact in seen:
            continue
        seen.add(fact)
        facts.append(fact)
    return facts


def build_memory_context(
    query: str,
    *,
    channel: str = "telegram",
    recent_loader: Callable[..., list[dict[str, Any]]] | None = None,
    semantic_search: Callable[[str, int], Iterable[Any]] | None = None,
    recent_limit: int = 10,
    semantic_k: int = 5,
) -> MemoryContext:
    if recent_loader is None:
        from memory.conversation_history import load_recent_context

        recent_loader = load_recent_context

    if recent_limit > 0:
        try:
            recent_messages = recent_loader(
                channel=channel,
                global_limit=12,
                channel_limit=10,
                total_limit=recent_limit * 2,
            )
        except Exception:
            recent_messages = []
    else:
        recent_messages = []

    context = MemoryContext(
        recent_lines=format_recent_messages(recent_messages, limit=recent_limit),
        semantic_facts=semantic_facts_for_query(query, k=semantic_k, search_fn=semantic_search),
    )
    _record_memory_context_debug(
        channel=channel,
        query=query,
        recent_count=len(context.recent_lines),
        semantic_count=len(context.semantic_facts),
        recent_preview=context.recent_lines[:3],
        semantic_preview=context.semantic_facts[:3],
    )
    return context


def _record_memory_context_debug(
    *,
    channel: str,
    query: str,
    recent_count: int,
    semantic_count: int,
    recent_preview: list[str],
    semantic_preview: list[str],
) -> None:
    payload = {
        "written_at": datetime.now().isoformat(timespec="seconds"),
        "channel": channel,
        "query_preview": " ".join(str(query or "").split())[:180],
        "recent_count": recent_count,
        "semantic_count": semantic_count,
        "recent_preview": recent_preview,
        "semantic_preview": semantic_preview,
    }
    print(
        f"\033[90m[MemoryContext]: channel={channel} "
        f"recent={recent_count} semantic={semantic_count} "
        f"query='{payload['query_preview'][:80]}'\033[0m"
    )
    try:
        with open(MEMORY_CONTEXT_DEBUG_FILE, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
    except Exception as exc:
        print(f"\033[93m[MemoryContext]: debug write failed: {exc}\033[0m")


def load_memory_context_debug() -> dict[str, Any]:
    try:
        with open(MEMORY_CONTEXT_DEBUG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}
