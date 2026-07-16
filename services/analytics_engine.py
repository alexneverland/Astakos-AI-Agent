# ================================================================
# Project: Astakos AI Agent 🦞
# Module:  Analytics Engine — Passive Routine Detection
# Runs every night at 03:00. Analyzes the chat history, finds
# recurring patterns and calls upsert_routine automatically.
# ================================================================

import os
import sys

# Bootstrap repo root before any project-local imports when this file runs as a script.
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from core.i18n import t
import json
import re
import time
from collections import defaultdict
from datetime import datetime, timedelta
from difflib import SequenceMatcher

# ── Config ───────────────────────────────────────────────────────
LOOKBACK_DAYS     = 30    # History days
MIN_OCCURRENCES   = 3     # Minimum total appearances
MIN_WEEKS         = 2     # In how many different weeks
TIME_BUCKET_MIN   = 30    # Time window (±15 minutes)
SIMILARITY_THRESH = 0.60  # Difflib threshold for grouping_
EVERYDAY_DAYS     = 5     # If it appears in 5+ days → Everyday_

_BASE             = os.path.dirname(os.path.abspath(__file__))
LOG_FILE          = os.path.join(_BASE, "..", "analytics_engine_log.json")

BATCH_SIZE = 80   # messages per LLM call
MAX_INCREMENTAL_ROWS = 2000
ANALYTICS_STATE_KEY = "routine_analytics"


# ────────────────────────────────────────────────────────────────
# HELPERS
# ────────────────────────────────────────────────────────────────

def _round_to_bucket(time_str: str, bucket_min: int = TIME_BUCKET_MIN) -> str:
    """07:22 → 07:00 | 07:47 → 08:00 (nearest 30-min bucket)"""
    try:
        h, m = map(int, time_str.split(":"))
        total = h * 60 + m
        rounded = round(total / bucket_min) * bucket_min
        rh, rm = divmod(rounded % (24 * 60), 60)
        return f"{rh:02d}:{rm:02d}"
    except Exception:
        return time_str


def _extract_activities_llm(msgs: list) -> list:
    """
    Batch LLM call: takes N messages, returns a list with
    (event_name, event_type) or None for each message.
    """
    from langchain_core.messages import HumanMessage
    from core.brain import llm, safe_llm_invoke

    if not msgs:
        return []

    lines = [f"{i}: {m.get('content', '').strip()[:200]}" for i, m in enumerate(msgs)]

    prompt = f"""{t("services.analytics_engine.prompt")}
{chr(10).join(lines)}

JSON:"""

    try:
        response = safe_llm_invoke(llm, [HumanMessage(content=prompt)])
        content = response.content
        if isinstance(content, list):
            content = "".join(
                part.get("text", "") if isinstance(part, dict) else str(part)
                for part in content
            )
        raw = content.strip()
        from core.utils import extract_json_from_text
        data = extract_json_from_text(raw)
        if not isinstance(data, list):
            data = []

        result = [None] * len(msgs)
        for item in data:
            idx = item.get("idx")
            event = item.get("event")
            if idx is not None and isinstance(idx, int) and 0 <= idx < len(msgs) and event:
                result[idx] = (event, item.get("type", "general"))
        return result
    except Exception as e:
        print(f"\033[91m[Analytics LLM Error]: {e}\033[0m")
        return [None] * len(msgs)


def _get_week_id(date_str: str) -> str:
    """Returns "2026-W21" for dedup per week."""
    try:
        d = datetime.strptime(date_str, "%Y-%m-%d")
        return f"{d.year}-W{d.isocalendar()[1]:02d}"
    except Exception:
        return date_str


def _similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()


def _load_shared_user_messages(cutoff: str) -> list:
    from memory.conversation_history import load_messages_since

    return load_messages_since(
        since_date=cutoff,
        roles=("user", "human", "Human"),
    )


def _load_user_messages_for_analytics(cutoff: str) -> tuple[list, str]:
    return _load_shared_user_messages(cutoff), "shared_sqlite"


def _is_user_message(msg: dict) -> bool:
    return msg.get("role") in ("user", "human", "Human")


def _extract_activities_batched(user_msgs: list, *, stats: dict | None = None) -> list:
    activities = []
    batch_durations = []
    for i in range(0, len(user_msgs), BATCH_SIZE):
        batch = user_msgs[i:i + BATCH_SIZE]
        batch_no = i // BATCH_SIZE + 1
        print(f"[Analytics]: LLM batch {batch_no} ({len(batch)} msgs)...")
        t0 = time.time()
        extracted = _extract_activities_llm(batch)
        duration = round(time.time() - t0, 2)
        batch_durations.append({"batch": batch_no, "messages": len(batch), "duration": duration})
        print(f"[Analytics]: batch {batch_no} done in {duration}s")
        activities.extend(extracted)
    if stats is not None:
        stats["llm_batches"] = len(batch_durations)
        stats["batch_durations"] = batch_durations
    return activities


def _group_activities(user_msgs: list, activities: list) -> dict:
    groups = defaultdict(list)
    for msg, activity in zip(user_msgs, activities):
        if not activity:
            continue

        event_name, event_type = activity

        try:
            d = datetime.strptime(msg["date"], "%Y-%m-%d")
            day_of_week = d.strftime("%A")
        except Exception:
            continue

        time_bucket = _round_to_bucket(msg["time"])
        week_id = _get_week_id(msg["date"])

        groups[(day_of_week, time_bucket, event_name, event_type)].append({
            "date": msg["date"],
            "week": week_id
        })
    return groups


def _merge_activity_groups(groups: dict) -> dict:
    merged = {}
    used = set()
    group_list = list(groups.items())

    for i, (k1, v1) in enumerate(group_list):
        if k1 in used:
            continue
        day1, time1, ev1, type1 = k1
        combined = list(v1)

        for j, (k2, v2) in enumerate(group_list):
            if j == i or k2 in used:
                continue
            day2, time2, ev2, type2 = k2
            if day1 == day2 and time1 == time2 and _similarity(ev1, ev2) >= SIMILARITY_THRESH:
                combined.extend(v2)
                used.add(k2)

        merged[k1] = combined
        used.add(k1)
    return merged


def _promote_everyday_groups(merged: dict) -> dict:
    by_time_event = defaultdict(lambda: {"entries": [], "days": set()})
    for (day, time_bucket, event, evtype), entries in merged.items():
        key = (time_bucket, event, evtype)
        by_time_event[key]["entries"].extend(entries)
        by_time_event[key]["days"].add(day)

    final_groups = {}
    promoted_to_everyday = set()

    for (time_bucket, event, evtype), data in by_time_event.items():
        if len(data["days"]) >= EVERYDAY_DAYS:
            final_groups[("Everyday", time_bucket, event, evtype)] = data["entries"]
            promoted_to_everyday.update(
                (day, time_bucket, event, evtype) for day in data["days"]
            )

    for key, entries in merged.items():
        if key not in promoted_to_everyday:
            final_groups[key] = entries
    return final_groups


def _promote_groups_to_routines(final_groups: dict, *, stats: dict, found_routines: list) -> None:
    from memory.routine_db import upsert_routine

    for (day_of_week, time_bucket, event_name, event_type), entries in final_groups.items():
        total = len(entries)
        weeks = len(set(e["week"] for e in entries))
        stats["detected"] += 1

        required_weeks = 1 if day_of_week == "Everyday" else MIN_WEEKS

        if total >= MIN_OCCURRENCES and weeks >= required_weeks:
            try:
                result = upsert_routine(
                    day=day_of_week,
                    time=time_bucket,
                    event=event_name,
                    ev_type=event_type,
                    confidence_boost=0.2
                )
                if result in stats:
                    stats[result] += 1

                found_routines.append({
                    "day": day_of_week, "time": time_bucket,
                    "event": event_name, "count": total,
                    "weeks": weeks, "result": result
                })
                print(f"[Analytics]: ✅ '{event_name}' {day_of_week} {time_bucket} → {result} ({total}x / {weeks}w)")
            except Exception as e:
                stats["errors"] += 1
                print(f"[Analytics ERROR]: {e}")
        else:
            stats["skipped"] += 1


def _load_incremental_messages(after_rowid: int, *, limit: int = MAX_INCREMENTAL_ROWS) -> tuple[list, int, int]:
    from memory.conversation_history import load_messages_after_rowid

    rows = load_messages_after_rowid(after_rowid=after_rowid, limit=limit)
    max_seen = max((int(m.get("rowid") or 0) for m in rows), default=after_rowid)
    user_msgs = [m for m in rows if _is_user_message(m)]
    return user_msgs, max_seen, len(rows)


def _record_incremental_activities(user_msgs: list, activities: list, *, state_db_path: str | None = None) -> dict:
    from memory import analytics_state

    stats = {
        "recorded": 0,
        "created_candidate": 0,
        "merged_candidate": 0,
        "added_occurrence": 0,
        "duplicate_occurrence": 0,
    }
    kwargs = {"db_path": state_db_path} if state_db_path else {}

    for msg, activity in zip(user_msgs, activities):
        if not activity:
            continue
        event_name, event_type = activity
        try:
            d = datetime.strptime(msg["date"], "%Y-%m-%d")
            day_of_week = d.strftime("%A")
        except Exception:
            continue
        result = analytics_state.add_occurrence(
            day_of_week=day_of_week,
            time_bucket=_round_to_bucket(msg["time"]),
            event_name=event_name,
            event_type=event_type,
            message=msg,
            week_id=_get_week_id(msg["date"]),
            **kwargs,
        )
        stats["recorded"] += 1
        action = result.get("action")
        if action in stats:
            stats[action] += 1
    return stats


def _promote_incremental_candidates(*, dry_run: bool = False, state_db_path: str | None = None) -> tuple[dict, list]:
    from memory import analytics_state
    from memory.routine_db import upsert_routine

    kwargs = {"db_path": state_db_path} if state_db_path else {}
    stats = {"detected": 0, "created": 0, "merged": 0, "updated": 0, "skipped": 0, "errors": 0, "would_promote": 0}
    promoted = []
    ready = analytics_state.eligible_candidates(
        min_occurrences=MIN_OCCURRENCES,
        min_weeks=MIN_WEEKS,
        everyday_days=EVERYDAY_DAYS,
        **kwargs,
    )
    stats["detected"] = len(ready)

    for candidate in ready:
        if dry_run:
            result = "dry_run"
            stats["would_promote"] += 1
        else:
            try:
                result = upsert_routine(
                    day=candidate["day_of_week"],
                    time=candidate["time_bucket"],
                    event=candidate["event_name"],
                    ev_type=candidate["event_type"],
                    confidence_boost=0.2,
                )
                if result in stats:
                    stats[result] += 1
                analytics_state.mark_promoted(candidate["id"], result=result, **kwargs)
            except Exception as e:
                stats["errors"] += 1
                print(f"[Analytics Incremental ERROR]: {e}")
                continue
        promoted.append({
            "day": candidate["day_of_week"],
            "time": candidate["time_bucket"],
            "event": candidate["event_name"],
            "count": candidate["occurrence_count"],
            "weeks": candidate["week_count"],
            "result": result,
        })
    return stats, promoted


# ────────────────────────────────────────────────────────────────
# CORE
# ────────────────────────────────────────────────────────────────

def run_analytics() -> dict:
    """
    Main function of the Analytics Engine.
    Returns a stats dict: {detected, created, merged, updated, skipped, errors}
    """
    from memory import analytics_state

    progress = analytics_state.get_progress(key=ANALYTICS_STATE_KEY)
    if progress.get("bootstrap_completed"):
        return run_analytics_incremental()

    stats = {"detected": 0, "created": 0, "merged": 0,
             "updated": 0, "skipped": 0, "errors": 0}
    found_routines = []

    # ── 1. Load shared history (Web + Telegram) ───────────────
    cutoff = (datetime.now() - timedelta(days=LOOKBACK_DAYS)).strftime("%Y-%m-%d")
    user_msgs, history_source = _load_user_messages_for_analytics(cutoff)

    if not user_msgs:
        print("[Analytics]: No messages with date field (recent).")
        _write_log(stats, found_routines)
        return stats

    print(f"[Analytics]: Analyzing {len(user_msgs)} messages ({LOOKBACK_DAYS} days, {history_source})...")

    activities = _extract_activities_batched(user_msgs, stats=stats)
    groups = _group_activities(user_msgs, activities)
    merged = _merge_activity_groups(groups)
    final_groups = _promote_everyday_groups(merged)
    _promote_groups_to_routines(final_groups, stats=stats, found_routines=found_routines)

    print(f"[Analytics]: Completed → {stats}")
    _write_log(stats, found_routines)
    return stats


def run_analytics_incremental(
    *,
    bootstrap: bool = False,
    dry_run: bool = False,
    state_db_path: str | None = None,
    max_rows: int = MAX_INCREMENTAL_ROWS,
) -> dict:
    from memory import analytics_state
    from memory.conversation_history import get_max_rowid

    kwargs = {"db_path": state_db_path} if state_db_path else {}
    progress = analytics_state.get_progress(
        key=ANALYTICS_STATE_KEY,
        initialize=not dry_run,
        **kwargs,
    )
    stats = {
        "mode": "bootstrap" if bootstrap else "incremental",
        "dry_run": dry_run,
        "loaded": 0,
        "user_messages": 0,
        "last_rowid_before": progress["last_rowid"],
        "last_rowid_after": progress["last_rowid"],
        "detected": 0,
        "created": 0,
        "merged": 0,
        "updated": 0,
        "skipped": 0,
        "errors": 0,
    }

    if bootstrap:
        cutoff = (datetime.now() - timedelta(days=LOOKBACK_DAYS)).strftime("%Y-%m-%d")
        user_msgs, history_source = _load_user_messages_for_analytics(cutoff)
        stats["history_source"] = history_source
        stats["loaded"] = len(user_msgs)
        max_seen = get_max_rowid()
    else:
        user_msgs, max_seen, loaded_rows = _load_incremental_messages(progress["last_rowid"], limit=max_rows)
        stats["loaded"] = loaded_rows

    stats["user_messages"] = len(user_msgs)
    stats["last_rowid_after"] = max_seen

    if not user_msgs:
        if not dry_run:
            analytics_state.set_progress(
                key=ANALYTICS_STATE_KEY,
                last_rowid=max_seen,
                bootstrap_completed=progress["bootstrap_completed"] or bootstrap,
                **kwargs,
            )
            _write_log(stats, [])
        return stats

    activities = _extract_activities_batched(user_msgs, stats=stats)
    if dry_run:
        stats["detected"] = sum(1 for activity in activities if activity)
        stats["skipped"] = len(activities) - stats["detected"]
        return stats

    record_stats = _record_incremental_activities(user_msgs, activities, state_db_path=state_db_path)
    promotion_stats, promoted = _promote_incremental_candidates(dry_run=False, state_db_path=state_db_path)

    stats.update({f"state_{k}": v for k, v in record_stats.items()})
    for key in ("detected", "created", "merged", "updated", "skipped", "errors"):
        stats[key] = promotion_stats.get(key, 0)

    analytics_state.set_progress(
        key=ANALYTICS_STATE_KEY,
        last_rowid=max_seen,
        bootstrap_completed=progress["bootstrap_completed"] or bootstrap,
        **kwargs,
    )
    print(f"[Analytics Incremental]: Completed → {stats}")
    _write_log(stats, promoted)
    return stats


def get_candidates() -> list:
    """
    Returns the patterns that have not passed the threshold yet.
    Usage: Lobster can answer 'what routines have you detected?'
    """
    if not os.path.exists(LOG_FILE):
        return []
    with open(LOG_FILE, "r", encoding="utf-8") as f:
        log = json.load(f)
    if not log:
        return []
    # Last run
    last = log[-1]
    return last.get("detected_routines", [])


# ────────────────────────────────────────────────────────────────
# LOG
# ────────────────────────────────────────────────────────────────

def _write_log(stats: dict, routines: list):
    try:
        log = []
        if os.path.exists(LOG_FILE):
            with open(LOG_FILE, "r", encoding="utf-8") as f:
                log = json.load(f)
        log.append({
            "run_at":            datetime.now().isoformat(timespec="seconds"),
            "stats":             stats,
            "detected_routines": routines
        })
        log = log[-30:]  # Keep last 30 runs
        with open(LOG_FILE, "w", encoding="utf-8") as f:
            json.dump(log, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[Analytics Log Error]: {e}")


# ────────────────────────────────────────────────────────────────
# STANDALONE EXECUTION
# ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    results = run_analytics()
    print(f"\n📊 Analytics Results: {results}")
