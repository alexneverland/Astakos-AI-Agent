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
    "η ρουτινα",
    "η ρουτίνα",
    "σιγαστηκε μεχρι",
    "σιγάστηκε μέχρι",
    "ξαναενεργοποιηθηκε κανονικα",
    "ξαναενεργοποιήθηκε κανονικά",
    "συναισθηματικα μηνυματα",
    "συναισθηματικά μηνύματα",
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

_RECALL_MARKERS = (
    "θυμασαι",
    "θυμάσαι",
    "ειχαμε πει",
    "είχαμε πει",
    "σου ειχα",
    "σου είχα",
    "ειχα ανεβασει",
    "είχα ανεβάσει",
    "σημειωσει",
    "σημειώσει",
    "γενεθλι",
    "δωρο",
    "δώρο",
    "ρολοι",
    "ρολόι",
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


# Prefixes που βάζει το σύστημα σε μηνύματα (upload, vision, tool results).
# Στριπάρονται πριν το semantic search ώστε να ψάχνουμε με το πραγματικό
# κείμενο του χρήστη, όχι με filenames/system tags.
_SYSTEM_PREFIX_RE = re.compile(
    r"^\s*\["
    r"(?:USER_UPLOADED_FILE|CURRENT_PHOTO_PATH|ΟΠΤΙΚΗ ΑΝΑΛΥΣΗ|SYSTEM|TOOL_RESULT)"
    r"\][:\s]*\S+\s*",
    re.IGNORECASE,
)


def _clean_query_for_search(query: str) -> str:
    """Αφαιρεί system prefixes (π.χ. [USER_UPLOADED_FILE]: web_xxx.txt) από το query.
    Κρατάει μόνο το πραγματικό κείμενο του χρήστη για semantic search."""
    cleaned = _SYSTEM_PREFIX_RE.sub("", query).strip()
    return cleaned if cleaned else query


_SIMPLE_ACKS = {
    "ναι", "nai", "yes",
    "οκ", "ok", "okay",
    "έγινε", "εγινε",
    "καλά", "καλα",
    "ευχαριστώ", "ευχαριστω",
    "τέλεια", "τελεια",
    "ωραία", "ωραια",
    "σωστά", "σωστα",
}

def _looks_low_complexity_query(query: str) -> bool:
    if not query:
        return True

    q = query.strip().lower()
    if not q:
        return True

    # Αφαίρεσε timestamp prefix τύπου [10:24]
    q = re.sub(r"^\[\d{1,2}:\d{2}\]\s*", "", q).strip()

    # Πολύ μικρά acknowledgements
    if q in _SIMPLE_ACKS:
        return True

    # Πολύ σύντομο μήνυμα χωρίς ερώτηση
    word_count = len(q.split())
    has_question = "?" in q or ";" in q

    if word_count <= 3 and not has_question:
        return True

    # Σύντομα status / follow-up χωρίς ξεκάθαρο info request
    low_signal_starts = (
        "ναι ",
        "οκ ",
        "έγινε ",
        "σε λίγο ",
        "αργότερα ",
        "μετά ",
        "καλά είμαστε",
        "ολα καλα",
        "όλα καλά",
        "ευχαριστώ ",
    )
    if q.startswith(low_signal_starts) and word_count <= 8 and not has_question:
        return True

    return False

def _must_keep_semantic(query: str) -> bool:
    if not query:
        return False

    q = query.strip().lower()

    strong_tokens = (
        "σοφία", "σοφια",
        "αλέξανδρ", "αλεξανδρ",
        "μαρία", "μαρια",
        "δουλει", "βάρδια", "βαρδια",
        "πάρκο", "παρκο",
        "ποδόσφαιρ", "ποδοσφαιρ",
        "κατασκήν", "κατασκην",
        "σπίτι", "σπιτι",
        "μήνυμα", "μηνυμα",
        "υπνος", "ύπνος",
        "μαγείρε", "μαγειρε",
        "ψών", "ψων",
        "λίστα", "λιστα",
        "θυμά", "θυμα",
        "remember",
        "γιατί", "γιατι",
        "πώς", "πως",
        "τι ",
        "ποιος", "ποια", "ποιο",
        "πότε", "ποτε",
        "πού", "που",
        "στείλε", "στειλε",
        "πάγωσε", "παγωσε",
        "άλλαξε", "αλλαξε",
    )

    return any(token in q for token in strong_tokens)


def _has_temporal_marker(query: str) -> bool:
    clean = _normalize_text(query)
    return any(marker in clean for marker in _TEMPORAL_MARKERS)


def _has_recall_marker(query: str) -> bool:
    clean = _normalize_text(query)
    return any(marker in clean for marker in _RECALL_MARKERS)


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
        
        from core.utils import looks_like_operational_assistant_text
        if role == "assistant" and looks_like_operational_assistant_text(content):
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
    has_recall_marker = _has_recall_marker(clean_query)
    if limit <= 0:
        return []
    # [PERF]: SQL scan only for explicit time or recall/history intent.
    # Plain semantic queries stay on Chroma; "θυμάσαι/δώρο/γενέθλια" still
    # search SQLite because many details may exist only in conversation history.
    if not has_temporal_marker and not has_recall_marker:
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
        
        # Inject the date it was learned, so LLM understands temporal anchors ("this week")
        metadata = getattr(result, "metadata", {})
        ts = metadata.get("timestamp")
        if ts:
            try:
                date_str = datetime.fromtimestamp(ts).strftime("%Y-%m-%d")
                fact = f"[{date_str}] {fact}"
            except Exception:
                pass
                
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
    from time import perf_counter
    # Χρησιμοποιούμε clean_query για semantic search & debug — αφαιρούμε
    # system prefixes ([USER_UPLOADED_FILE], [CURRENT_PHOTO_PATH] κ.λπ.)
    # ώστε το embedding να γίνει με το πραγματικό κείμενο του χρήστη.
    clean_query = _clean_query_for_search(query)

    is_tool_output = looks_like_tool_output(query)
    if is_tool_output:
        recent_limit = 0
        temporal_limit = 0
        semantic_k = 0

    if recent_loader is None:
        from memory.conversation_history import load_recent_context

        recent_loader = load_recent_context

    t_recent_0 = perf_counter()
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
    recent_ms = int((perf_counter() - t_recent_0) * 1000)

    t_hist_0 = perf_counter()
    historical_lines = temporal_history_for_query(
        clean_query,
        channel=channel,
        limit=temporal_limit,
        history_loader=temporal_loader,
    )
    historical_ms = int((perf_counter() - t_hist_0) * 1000)

    effective_semantic_k = semantic_k
    semantic_skip_reason = None

    if semantic_k > 0:
        if _looks_low_complexity_query(clean_query) and not _must_keep_semantic(clean_query):
            effective_semantic_k = 0
            semantic_skip_reason = "low_complexity_query"

    t_sem_0 = perf_counter()
    semantic_facts = semantic_facts_for_query(clean_query, k=effective_semantic_k, search_fn=semantic_search)
    semantic_ms = int((perf_counter() - t_sem_0) * 1000)

    context = MemoryContext(
        recent_lines=format_recent_messages(recent_messages, limit=recent_limit),
        historical_lines=historical_lines,
        semantic_facts=semantic_facts,
    )
    _record_memory_context_debug(
        channel=channel,
        query=clean_query,  # debug panel shows clean query, not raw with filename
        is_tool_output=is_tool_output,
        recent_count=len(context.recent_lines),
        historical_count=len(context.historical_lines),
        semantic_count=len(context.semantic_facts),
        recent_preview=context.recent_lines[:3],
        historical_preview=context.historical_lines[:3],
        semantic_preview=context.semantic_facts[:3],
        recent_ms=recent_ms,
        historical_ms=historical_ms,
        semantic_ms=semantic_ms,
        semantic_k_used=effective_semantic_k,
        semantic_skip_reason=semantic_skip_reason,
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
    recent_ms: int = 0,
    historical_ms: int = 0,
    semantic_ms: int = 0,
    semantic_k_used: int = 0,
    semantic_skip_reason: str | None = None,
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
        "recent_ms": recent_ms,
        "historical_ms": historical_ms,
        "semantic_ms": semantic_ms,
        "semantic_k_used": semantic_k_used,
        "semantic_skip_reason": semantic_skip_reason,
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
            f"recent={recent_count} ({recent_ms}ms) "
            f"sqlite={historical_count} ({historical_ms}ms) "
            f"semantic={semantic_count} ({semantic_ms}ms, k={semantic_k_used}, skip={semantic_skip_reason}) "
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
