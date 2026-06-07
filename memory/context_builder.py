from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable, Any


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

    return MemoryContext(
        recent_lines=format_recent_messages(recent_messages, limit=recent_limit),
        semantic_facts=semantic_facts_for_query(query, k=semantic_k, search_fn=semantic_search),
    )
