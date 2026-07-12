from __future__ import annotations

from core.i18n import t
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
    if any(marker in clean for marker in (t("prompts.ext_str_604"), t("prompts.ext_str_334"), t("prompts.ext_str_552"), t("prompts.ext_str_648"), t("prompts.ext_str_657"), t("prompts.ext_str_315"), t("prompts.ext_str_702"))):
        return "family"
    if any(marker in clean for marker in ("mastroapp", "praxis", "astakos", t("prompts.ext_str_533"), "github", "project", "repo", "tool", "skill")):
        return "projects"
    if any(marker in clean for marker in (t("prompts.ext_str_589"), t("prompts.ext_str_401"), t("prompts.ext_str_452"), t("prompts.ext_str_223"), t("prompts.ext_str_495"), t("prompts.ext_str_527"), t("prompts.ext_str_621"))):
        return "home"
    if any(marker in clean for marker in (t("prompts.ext_str_423"), "bug", "prompt", "lesson", t("prompts.ext_str_458"), t("prompts.ext_str_345"), t("prompts.ext_str_640"))):
        return "lesson"
    return "lazaros"


def looks_like_noise(text: str) -> bool:
    clean = normalize_text(text)
    noise_markers = (
        "action approval required",
        t("prompts.ext_str_374"),
        t("prompts.ext_str_121"),
        "tool loop stopped",
        "terminal execution",
        t("prompts.ext_str_50"),
        t("prompts.ext_str_75"),
        t("prompts.ext_str_16"),
        t("prompts.ext_str_18"),
        t("prompts.ext_str_15"),
        t("prompts.ext_str_94"),
        "send_photo:",
        t("prompts.ext_str_27"),
        t("prompts.ext_str_81"),
        t("prompts.ext_str_163"),
        t("prompts.ext_str_299"),
        t("prompts.ext_str_93"),
        t("prompts.ext_str_152"),
        t("prompts.ext_str_180"),
        t("prompts.ext_str_128"),
    )
    return any(marker in clean for marker in noise_markers)


def looks_like_question_or_command(text: str) -> bool:
    clean = normalize_text(text)
    stripped = str(text or "").strip()
    if stripped.endswith(("?", ";")):
        return True
    question_markers = (
        t("prompts.ext_str_446"),
        t("prompts.ext_str_798"),
        t("prompts.ext_str_632"),
        t("prompts.ext_str_110"),
        t("prompts.ext_str_129"),
        t("prompts.ext_str_199"),
        t("prompts.ext_str_204"),
        t("prompts.ext_str_494"),
        t("prompts.ext_str_585"),
        t("prompts.ext_str_333"),
    )
    return any(marker in clean for marker in question_markers)


def is_important_memory(text: str, role: str) -> bool:
    clean = normalize_text(text)
    if looks_like_noise(text):
        return False

    user_explicit_save = (t("prompts.ext_str_327"), t("prompts.ext_str_639"), t("prompts.ext_str_536"), t("prompts.ext_str_603"), t("prompts.ext_str_463"))
    assistant_confirmed_save = (
        t("prompts.ext_str_177"),
        t("prompts.ext_str_156"),
        t("prompts.ext_str_220"),
        t("prompts.ext_str_273"),
        t("prompts.ext_str_155"),
        t("prompts.ext_str_78"),
    )
    family_terms = (t("prompts.ext_str_604"), t("prompts.ext_str_334"), t("prompts.ext_str_315"), t("prompts.ext_str_702"), t("prompts.ext_str_574"), t("prompts.ext_str_371"), t("prompts.ext_str_535"), t("prompts.ext_str_696"), t("prompts.ext_str_497"))
    personal_terms = (t("prompts.ext_str_342"), t("prompts.ext_str_261"), t("prompts.ext_str_557"), t("prompts.ext_str_750"), t("prompts.ext_str_538"), t("prompts.ext_str_326"), t("prompts.ext_str_245"), t("prompts.ext_str_503"))
    project_terms = ("mastroapp", "astakos", t("prompts.ext_str_533"), "tool", "skill", "bug", "prompt", "github", "commit", "sql", "chroma")
    home_terms = (t("prompts.ext_str_589"), t("prompts.ext_str_223"), t("prompts.ext_str_527"), t("prompts.ext_str_621"), "google fit", t("prompts.ext_str_668"), "receipt")
    event_terms = (t("prompts.ext_str_486"), t("prompts.ext_str_377"), t("prompts.ext_str_251"), t("prompts.ext_str_671"), t("prompts.ext_str_625"), t("prompts.ext_str_312"), t("prompts.ext_str_322"), t("prompts.ext_str_389"), t("prompts.ext_str_603"), t("prompts.ext_str_358"))
    durable_home_terms = (t("prompts.ext_str_312"), t("prompts.ext_str_517"), t("prompts.ext_str_270"), t("prompts.ext_str_355"), t("prompts.ext_str_289"), t("prompts.ext_str_466"))
    durable_work_terms = (t("prompts.ext_str_480"), t("prompts.ext_str_348"), t("prompts.ext_str_324"), t("prompts.ext_str_261"), t("prompts.ext_str_544"), t("prompts.ext_str_372"))

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
    if any(marker in clean for marker in project_terms) and any(marker in clean for marker in (t("prompts.ext_str_541"), t("prompts.ext_str_500"), "bug", t("prompts.ext_str_488"), t("prompts.ext_str_454"))):
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
    fact = t("scripts.chroma_memory_maintainer.fact_format", tag=tag, date=date, content=content)
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

