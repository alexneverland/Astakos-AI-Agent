from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
import json
import os
import re
import unicodedata
from typing import Callable, Iterable, Any

from config import BASE_DIR


MEMORY_CONTEXT_DEBUG_FILE = os.path.join(BASE_DIR, "runtime_memory_context.json")


@dataclass(frozen=True)
class MemoryContext:
    recent_lines: list[str]
    historical_lines: list[str]
    semantic_facts: list[str]

    def render(self) -> str:
        sections = []
        if self.recent_lines:
            sections.append(
                "[ΠΡΟΣΦΑΤΟ ΙΣΤΟΡΙΚΟ WEB+TELEGRAM]\n"
                + "\n".join(self.recent_lines)
            )
        if self.historical_lines:
            sections.append(
                "[ΣΧΕΤΙΚΟ ΙΣΤΟΡΙΚΟ SQLITE]\n"
                + "\n".join(self.historical_lines)
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


_TOOL_OUTPUT_MARKERS = (
    "μνημες που βρεθηκαν",
    "μνημεσ που βρεθηκαν",
    "μνήμες που βρέθηκαν",
    "μνήμες που βρέθηκαν",
    "αποτελεσμα εργαλείου",
    "αποτέλεσμα εργαλείου",
    "πληροφορια απο αναζητηση",
    "πληροφορία από αναζήτηση",
    "καταγραφηκε επιτυχως",
    "καταγράφηκε επιτυχώς",
    "draft αποθηκευτηκε",
    "draft αποθηκεύτηκε",
    "ολοκληρωθηκε",
    "ολοκληρώθηκε",
)

_TEMPORAL_MARKERS = (
    "χτες",
    "χθες",
    "χθεσιν",
    "yesterday",
    "πρωι",
    "πρωί",
    "βραδυ",
    "βράδυ",
    "μεσημερι",
    "μεσημέρι",
    "απογευμα",
    "απόγευμα",
)

_TOKEN_STOPWORDS = {
    "και",
    "που",
    "τον",
    "την",
    "το",
    "τα",
    "τι",
    "χτες",
    "χθες",
    "χθεσιν",
    "πρωι",
    "πρωί",
    "ολοι",
    "μαζι",
    "κανε",
    "εκανε",
    "πηγαμε",
    "yesterday",
    "morning",
}


def _normalize_text(value: str) -> str:
    text = unicodedata.normalize("NFD", str(value or "").lower())
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    return " ".join(text.split())


def looks_like_tool_output(query: str) -> bool:
    clean = _normalize_text(query)
    return any(marker in clean for marker in _TOOL_OUTPUT_MARKERS)


def _has_temporal_marker(query: str) -> bool:
    clean = _normalize_text(query)
    return any(marker in clean for marker in _TEMPORAL_MARKERS)


def _query_tokens(query: str) -> list[str]:
    tokens = re.findall(r"[a-zA-Zα-ωΑ-Ωάέήίόύώϊϋΐΰ]+", _normalize_text(query))
    return [token for token in tokens if len(token) >= 4 and token not in _TOKEN_STOPWORDS]


def _stem_token(token: str) -> str:
    """Πρόχειρο ελληνικό stemming: κόβει τις πιο συνηθισμένες κλιτικές καταλήξεις
    (πτώσεις/αριθμός: -ος/-ου/-ο/-οι/-ων/-ους, -α/-ας/-ες κ.λπ.) ώστε
    'γενεθλια' να ταιριάζει με 'γενεθλιων' και 'αλεξανδρος' με 'αλεξανδρου'.
    Κρατάει πάντα στέλεχος >= 4 χαρακτήρων (ίδιο όριο με τα tokens) για να
    μην αυξάνεται ο θόρυβος από πολύ κοντά στελέχη.
    """
    if len(token) >= 7:
        return token[:-2]
    if len(token) >= 5:
        return token[:-1]
    return token


def _date_marker(message_date: str, today: str, yesterday: str) -> str:
    """Ένδειξη μέρας στις γραμμές 'πρόσφατου ιστορικού' ώστε να μη μπερδεύονται
    χθεσινά με σημερινά μηνύματα μέσα στο ίδιο context-window (π.χ. 'χθες 20:48'
    αντί για ένα γυμνό '20:48' που μοιάζει σαν να μόλις ειπώθηκε σήμερα — αυτό
    ακριβώς έκανε τον Αστακό να περάσει χθεσινές μπριζόλες για σημερινό φαγητό).
    Άδειο string για το 'σήμερα' -> καμία αλλαγή στην υπάρχουσα μορφή για την
    συντριπτική πλειοψηφία των γραμμών.
    """
    if not message_date or message_date == today:
        return ""
    if message_date == yesterday:
        return "χθες "
    try:
        year, month, day = message_date.split("-")
        return f"{day}/{month} "
    except ValueError:
        return f"{message_date} "


def format_recent_messages(
    messages: Iterable[dict[str, Any]],
    *,
    limit: int = 10,
    now: datetime | None = None,
) -> list[str]:
    if limit <= 0:
        return []
    current = now or datetime.now()
    today_str = current.strftime("%Y-%m-%d")
    yesterday_str = (current - timedelta(days=1)).strftime("%Y-%m-%d")
    lines = []
    for message in list(messages)[-limit:]:
        role = message.get("role", "")
        speaker = "Λάζαρος" if role == "user" else "Αστακός"
        channel = message.get("channel", "?")
        time_label = message.get("time") or str(message.get("timestamp", ""))[-8:-3]
        date_label = _date_marker(str(message.get("date") or ""), today_str, yesterday_str)
        content = str(message.get("content", "")).strip()
        if not content:
            continue
        content = " ".join(content.split())
        if len(content) > 260:
            content = content[:257].rstrip() + "..."
        lines.append(f"- [{channel} {date_label}{time_label}] {speaker}: {content}")
    return lines


def temporal_history_for_query(
    query: str,
    *,
    channel: str = "telegram",
    limit: int = 8,
    lookback_days: int = 30,
    now: datetime | None = None,
    history_loader: Callable[..., list[dict[str, Any]]] | None = None,
) -> list[str]:
    clean_query = _normalize_text(query)
    tokens = _query_tokens(clean_query)
    has_temporal_marker = _has_temporal_marker(clean_query)
    if limit <= 0:
        return []
    if not has_temporal_marker and len(tokens) < 2:
        return []

    current = now or datetime.now()
    target_date = None
    if any(marker in clean_query for marker in ("χτες", "χθες", "χθεσιν", "yesterday")):
        target_date = (current - timedelta(days=1)).strftime("%Y-%m-%d")
    since_date = target_date or (current - timedelta(days=lookback_days)).strftime("%Y-%m-%d")

    if history_loader is None:
        from memory.conversation_history import load_messages_since

        history_loader = load_messages_since

    try:
        messages = history_loader(since_date=since_date, limit=1500)
    except Exception:
        return []

    filtered = []
    wants_morning = any(marker in clean_query for marker in ("πρωι", "πρωί", "morning"))
    for message in messages:
        if target_date and message.get("date") != target_date:
            continue
        time_label = str(message.get("time") or "")
        if target_date and wants_morning and not ("05:00" <= time_label <= "13:00"):
            continue
        filtered.append(message)

    if not filtered:
        return []

    # Prefer the current channel, but keep mixed-channel context if needed.
    current_channel = [msg for msg in filtered if msg.get("channel") == channel]
    pool = current_channel if len(current_channel) >= max(2, limit // 2) else filtered

    def score(message: dict[str, Any]) -> int:
        content = _normalize_text(message.get("content", ""))
        value = sum(1 for token in tokens if _stem_token(token) in content)
        if "αλεξανδρ" in clean_query and any(
            marker in content for marker in ("ποδοσφ", "αγων", "τελικο", "μεταλλ")
        ):
            value += 3
        if any(marker in clean_query for marker in ("δωρο", "σοφια", "ρολοι", "watch", "λινκ", "link")) and any(
            marker in content
            for marker in (
                "rosefield",
                "bangle",
                "mother of pearl",
                "white gold",
                "καντραν",
                "ρολοι",
                "μελλοντικα δωρα",
            )
        ):
            value += 4
        return value

    scored = [(score(message), index, message) for index, message in enumerate(pool)]
    relevant = [(s, i, m) for s, i, m in scored if s > 0]
    if relevant:
        top = sorted(relevant, key=lambda item: (item[0], item[1]), reverse=True)[:limit]
        selected = [message for _, _, message in sorted(top, key=lambda item: item[1])]
    else:
        selected = pool[-limit:]
    return format_recent_messages(selected, limit=limit)


def semantic_facts_for_query(
    query: str,
    *,
    k: int = 5,
    search_fn: Callable[[str, int], Iterable[Any]] | None = None,
) -> list[str]:
    clean_query = str(query or "").strip()
    if len(clean_query) < 8 or k <= 0 or looks_like_tool_output(clean_query):
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
    temporal_loader: Callable[..., list[dict[str, Any]]] | None = None,
    semantic_search: Callable[[str, int], Iterable[Any]] | None = None,
    recent_limit: int = 10,
    temporal_limit: int = 8,
    semantic_k: int = 5,
) -> MemoryContext:
    is_tool_output = looks_like_tool_output(query)
    if is_tool_output:
        recent_limit = 0
        temporal_limit = 0
        semantic_k = 0

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
        historical_lines=temporal_history_for_query(
            query,
            channel=channel,
            limit=temporal_limit,
            history_loader=temporal_loader,
        ),
        semantic_facts=semantic_facts_for_query(query, k=semantic_k, search_fn=semantic_search),
    )
    _record_memory_context_debug(
        channel=channel,
        query=query,
        is_tool_output=is_tool_output,
        recent_count=len(context.recent_lines),
        historical_count=len(context.historical_lines),
        semantic_count=len(context.semantic_facts),
        recent_preview=context.recent_lines[:3],
        historical_preview=context.historical_lines[:3],
        semantic_preview=context.semantic_facts[:3],
    )
    return context


def _record_memory_context_debug(
    *,
    channel: str,
    query: str,
    is_tool_output: bool = False,
    recent_count: int,
    historical_count: int,
    semantic_count: int,
    recent_preview: list[str],
    historical_preview: list[str],
    semantic_preview: list[str],
) -> None:
    payload = {
        "written_at": datetime.now().isoformat(timespec="seconds"),
        "channel": channel,
        "query_preview": " ".join(str(query or "").split())[:180],
        "is_tool_output": is_tool_output,
        "recent_count": recent_count,
        "historical_count": historical_count,
        "semantic_count": semantic_count,
        "recent_preview": recent_preview,
        "historical_preview": historical_preview,
        "semantic_preview": semantic_preview,
    }
    if is_tool_output:
        # [MASTRO-FIX]: Το query εδώ είναι εσωτερικό tool-output (όχι πραγματικό
        # ερώτημα χρήστη) — το looks_like_tool_output() ήδη μηδένισε όλες τις
        # αναζητήσεις μνήμης. Δείχνουμε ξεκάθαρα ΓΙΑΤΙ recent/sqlite/semantic=0,
        # αντί να τυπώνουμε το garbage string σαν να ήταν πραγματικό query.
        print(
            f"\033[90m[MemoryContext]: channel={channel} — tool-output εντοπίστηκε "
            f"('{payload['query_preview'][:60]}...'), παράλειψη αναζήτησης μνήμης "
            f"(recent=0 sqlite=0 semantic=0)\033[0m"
        )
    else:
        print(
            f"\033[90m[MemoryContext]: channel={channel} "
            f"recent={recent_count} sqlite={historical_count} semantic={semantic_count} "
            f"query='{payload['query_preview']}'\033[0m"
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
