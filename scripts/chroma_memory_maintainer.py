from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterable, Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@dataclass(frozen=True)
class MemoryCandidate:
    fact: str
    category: str
    source: str
    reason: str
    confidence: float
    message_id: str
    timestamp: str
    role: str


def normalize_text(value: str) -> str:
    text = unicodedata.normalize("NFD", str(value or "").lower())
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    return " ".join(text.split())


def compact_text(value: str, limit: int = 320) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def infer_category(text: str) -> str:
    clean = normalize_text(text)
    if any(marker in clean for marker in ("σοφια", "αλεξανδρ", "μαρια", "μικρο", "παιδι", "γενεθλια", "δωρο")):
        return "family"
    if any(marker in clean for marker in ("mastroapp", "praxis", "astakos", "αστακο", "github", "project", "repo", "tool", "skill")):
        return "projects"
    if any(marker in clean for marker in ("σπιτι", "κουζινα", "ψυγειο", "αφυγραντηρ", "σκουπα", "συσκευ", "ψωνια")):
        return "home"
    if any(marker in clean for marker in ("κανονας", "bug", "prompt", "lesson", "μαθημα", "διορθωσ", "λαθος")):
        return "lesson"
    return "lazaros"


def looks_like_noise(text: str) -> bool:
    clean = normalize_text(text)
    noise_markers = (
        "action approval required",
        "εκτελω;",
        "αναμονη εγκρισης",
        "tool loop stopped",
        "terminal execution",
        "προσχεδιο αποθηκευτηκε",
        "οριστε το προσχεδιο",
        "θελεις αλλαγες η να το στειλω",
        "θελεις αλλαγες ή να το στειλω",
        "το αποθηκευσα. θελεις αλλαγες",
        "δεν κραταω τιποτα",
        "send_photo:",
        "δεν μου βγαζει κατι η μνημη",
        "δεν εχω συνδεδεμενο",
        "αν θελεις να",
        "στειλτης",
        "στειλε ενα μηνυμα",
        "στειλε κανενα",
        "να στειλουμε",
        "οριστε ο χαρτης",
    )
    return any(marker in clean for marker in noise_markers)


def looks_like_question_or_command(text: str) -> bool:
    clean = normalize_text(text)
    stripped = str(text or "").strip()
    if stripped.endswith(("?", ";")):
        return True
    question_markers = (
        "τι λες",
        "πως",
        "γιατι",
        "δωσε πληροφοριες",
        "δωσε καμια ιδεα",
        "καμια ιδεα",
        "να κανουμε",
        "φτιαξε",
        "σβησε",
        "ξεκιναμε",
    )
    return any(marker in clean for marker in question_markers)


def is_important_memory(text: str, role: str) -> bool:
    clean = normalize_text(text)
    if looks_like_noise(text):
        return False

    user_explicit_save = ("αποθηκευ", "μνημη", "σημειω", "κρατα", "υποψιν")
    assistant_confirmed_save = (
        "αποθηκευτηκε",
        "το αποθηκευσα",
        "σημειωθηκε",
        "κρατηθηκε",
        "κατεγραψα ηδη",
        "περαστηκε στη μνημη",
    )
    family_terms = ("σοφια", "αλεξανδρ", "γενεθλια", "δωρο", "παρκο", "σχολειο", "ποδοσφ", "αγων", "μεταλλ")
    personal_terms = ("δουλεια", "συνεντευξ", "υγεια", "υπνο", "προτιμ", "δεν θελω", "μου αρεσει", "στοχος")
    project_terms = ("mastroapp", "astakos", "αστακο", "tool", "skill", "bug", "prompt", "github", "commit", "sql", "chroma")
    home_terms = ("σπιτι", "αφυγραντηρ", "συσκευ", "ψωνια", "google fit", "ρολοι", "receipt")
    event_terms = ("πηγαμε", "ειμαστε", "ειναι στη", "εχει", "εκανε", "καθαρισα", "δουλευει", "θα παμε", "κρατα", "βρηκαμε")
    durable_home_terms = ("καθαρισα", "χαλασε", "επισκευασ", "αγορασα", "συντηρησ", "αλλαξα")
    durable_work_terms = ("ωραριο", "πρωινος", "βραδινος", "συνεντευξ", "αιτηση", "δουλευω")

    has_user_explicit_save = any(marker in clean for marker in user_explicit_save)
    has_assistant_confirmed_save = any(marker in clean for marker in assistant_confirmed_save)
    if role != "user" and not has_assistant_confirmed_save:
        return False
    if role == "user" and looks_like_question_or_command(text) and not has_user_explicit_save:
        return False
    if role == "user" and has_user_explicit_save:
        return True
    if role != "user" and has_assistant_confirmed_save:
        return True
    if any(marker in clean for marker in family_terms) and any(marker in clean for marker in event_terms + ("link", "http")):
        return True
    if any(marker in clean for marker in personal_terms) and any(marker in clean for marker in durable_work_terms):
        return True
    if any(marker in clean for marker in project_terms) and any(marker in clean for marker in ("διορθω", "πρεπει", "bug", "κανόνα", "κανονα")):
        return True
    if any(marker in clean for marker in home_terms) and any(marker in clean for marker in durable_home_terms):
        return True
    return False


def tag_for_category(category: str) -> str:
    return "[LESSON]" if category in {"lesson", "projects"} else "[USER_FACT]"


def candidate_from_message(message: dict[str, Any]) -> MemoryCandidate | None:
    content = compact_text(message.get("content", ""))
    role = str(message.get("role", ""))
    if not content or not is_important_memory(content, role):
        return None

    category = infer_category(content)
    date = message.get("date") or str(message.get("timestamp", ""))[:10] or datetime.now().strftime("%Y-%m-%d")
    tag = tag_for_category(category)
    fact = f"{tag}: Στις {date}, {content}"
    return MemoryCandidate(
        fact=fact,
        category=category,
        source=str(message.get("channel") or "sqlite"),
        reason="sql_backfill",
        confidence=0.78 if role == "user" else 0.68,
        message_id=str(message.get("id") or ""),
        timestamp=str(message.get("timestamp") or ""),
        role=role,
    )


def dedupe_candidates(candidates: Iterable[MemoryCandidate]) -> list[MemoryCandidate]:
    seen: set[tuple[str, str]] = set()
    unique: list[MemoryCandidate] = []
    for candidate in candidates:
        key = (candidate.category, normalize_text(candidate.fact))
        if key in seen:
            continue
        seen.add(key)
        unique.append(candidate)
    return unique


def load_sql_candidates(since_date: str, limit: int) -> list[MemoryCandidate]:
    from memory.conversation_history import load_messages_since

    messages = load_messages_since(since_date=since_date, limit=limit)
    return dedupe_candidates(
        candidate
        for message in messages
        for candidate in [candidate_from_message(message)]
        if candidate is not None
    )


def collect_chroma_duplicate_plan() -> dict[str, Any]:
    from memory.vector_store import vector_lock, vector_store

    with vector_lock:
        data = vector_store._collection.get(include=["documents", "metadatas"])

    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for doc_id, document, metadata in zip(data.get("ids", []), data.get("documents", []), data.get("metadatas", [])):
        category = str((metadata or {}).get("category", "general"))
        key = (category, normalize_text(document))
        groups.setdefault(key, []).append({"id": doc_id, "document": document, "metadata": metadata or {}})

    duplicates = []
    delete_ids = []
    for (category, _), items in groups.items():
        if len(items) < 2:
            continue
        items_sorted = sorted(
            items,
            key=lambda item: (
                len(str(item["document"])),
                float(item["metadata"].get("importance", 0) or 0),
                float(item["metadata"].get("timestamp", 0) or 0),
            ),
            reverse=True,
        )
        keep = items_sorted[0]
        remove = items_sorted[1:]
        delete_ids.extend(item["id"] for item in remove)
        duplicates.append({
            "category": category,
            "keep_id": keep["id"],
            "remove_ids": [item["id"] for item in remove],
            "preview": compact_text(keep["document"], 180),
        })

    return {"duplicates": duplicates, "delete_ids": delete_ids}


def apply_chroma_deletes(delete_ids: list[str]) -> None:
    if not delete_ids:
        return
    from memory.vector_store import vector_lock, vector_store

    with vector_lock:
        vector_store._collection.delete(ids=delete_ids)


def apply_backfill(candidates: Iterable[MemoryCandidate], max_apply: int) -> int:
    from memory.vector_store import memory

    applied = 0
    for candidate in list(candidates)[:max_apply]:
        ok = memory.save(
            memory_type="fact",
            fact=candidate.fact,
            category=candidate.category,
            agent_name="ChromaMemoryMaintainer",
            source=candidate.source,
            reason=candidate.reason,
            confidence=candidate.confidence,
        )
        if ok:
            applied += 1
    return applied


def build_report(args: argparse.Namespace) -> dict[str, Any]:
    since_date = args.since_date or (datetime.now() - timedelta(days=args.days)).strftime("%Y-%m-%d")
    candidates = load_sql_candidates(since_date=since_date, limit=args.limit)
    candidates = candidates[: args.max_candidates]
    duplicate_plan = collect_chroma_duplicate_plan() if args.clean_duplicates else {"duplicates": [], "delete_ids": []}

    report = {
        "mode": "apply" if args.apply else "dry_run",
        "since_date": since_date,
        "sql_limit": args.limit,
        "candidate_count": len(candidates),
        "candidates": [asdict(candidate) for candidate in candidates],
        "duplicate_count": len(duplicate_plan["duplicates"]),
        "duplicates": duplicate_plan["duplicates"],
        "delete_count": len(duplicate_plan["delete_ids"]),
    }

    if args.apply:
        report["applied_backfill"] = apply_backfill(candidates, max_apply=args.max_apply)
        if args.clean_duplicates:
            apply_chroma_deletes(duplicate_plan["delete_ids"])
            report["deleted_duplicates"] = len(duplicate_plan["delete_ids"])

    return report


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Audit/backfill important SQLite history into Chroma memory and optionally clean exact Chroma duplicates."
    )
    parser.add_argument("--days", type=int, default=30, help="Lookback window when --since-date is omitted.")
    parser.add_argument("--since-date", default="", help="YYYY-MM-DD lower bound for SQLite history.")
    parser.add_argument("--limit", type=int, default=3000, help="Maximum SQLite messages to scan.")
    parser.add_argument("--max-candidates", type=int, default=80, help="Maximum candidates to show/apply.")
    parser.add_argument("--max-apply", type=int, default=40, help="Maximum candidates to save when --apply is used.")
    parser.add_argument("--clean-duplicates", action="store_true", help="Find exact normalized duplicate Chroma docs.")
    parser.add_argument("--apply", action="store_true", help="Apply backfill and duplicate cleanup. Omit for dry-run.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    report = build_report(args)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
