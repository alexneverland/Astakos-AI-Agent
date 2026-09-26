"""Conservative timing and context for goal check-ins."""

import json
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any


def _recorded_time(value: object) -> datetime | None:
    """Return a trustworthy local datetime from a stored Unix timestamp."""
    try:
        stamp = float(value)
        if stamp <= 0:
            return None
        return datetime.fromtimestamp(stamp)
    except (OverflowError, OSError, TypeError, ValueError):
        return None


def _last_recorded_goal_time(meta: dict[str, Any]) -> datetime | None:
    """Use the latest trustworthy creation, change, or activity marker."""
    times = [
        recorded
        for key in ("created_at", "updated_at", "last_activity_at", "timestamp")
        if (recorded := _recorded_time(meta.get(key))) is not None
    ]
    return max(times) if times else None


def goal_followup_due(goal: dict[str, Any], *, now: datetime) -> bool:
    """Require seven full days since the latest recorded goal activity."""
    meta = goal.get("metadata") or {}
    recorded = _last_recorded_goal_time(meta)
    return recorded is not None and now - recorded >= timedelta(days=7)


def select_goals_for_followup(
    goals: list[dict[str, Any]],
    *,
    now: datetime,
    has_recent_memory: Callable[[dict[str, Any]], bool],
) -> list[dict[str, Any]]:
    """Select only dated, inactive goals with a successful recent-memory check."""
    selected = []
    for goal in goals:
        if not goal_followup_due(goal, now=now):
            continue
        try:
            if not has_recent_memory(goal):
                selected.append(goal)
        except Exception as exc:
            print(f"[GoalFollowup]: recent-memory check unavailable for '{goal.get('project', '')}': {exc}")
    return selected


def format_goal_followup_context(goal: dict[str, Any]) -> str:
    """Describe only known goal events and dates for the message writer."""
    meta = goal.get("metadata") or {}
    lines = [f"- {goal.get('project', '')}: {goal.get('description', '')}"]
    created = _recorded_time(meta.get("created_at"))
    changed = _recorded_time(meta.get("updated_at"))
    activity = _last_recorded_goal_time(meta)
    if created:
        lines.append(f"  Created: {created:%Y-%m-%d %H:%M}")
    if changed:
        lines.append(f"  Last change: {changed:%Y-%m-%d %H:%M}")
    if activity:
        lines.append(f"  Last recorded activity: {activity:%Y-%m-%d %H:%M}")
    if goal.get("progress"):
        lines.append(f"  Progress: {goal['progress']}%")
    if goal.get("milestones"):
        lines.append(f"  Milestones: {goal['milestones']}")
    try:
        events = json.loads(meta.get("goal_events_json") or "[]")
    except (TypeError, ValueError):
        events = []
    if isinstance(events, list):
        for event in events[-3:]:
            if not isinstance(event, dict):
                continue
            event_at = _recorded_time(event.get("at"))
            if event_at:
                lines.append(f"  Event {event_at:%Y-%m-%d %H:%M}: {str(event.get('detail', ''))[:300]}")
    return "\n".join(lines)


def goal_temporal_brief(goal: dict[str, Any]) -> str:
    """Render verified dates for general agent context without inventing a start."""
    meta = goal.get("metadata") or {}
    created = _recorded_time(meta.get("created_at"))
    activity = _last_recorded_goal_time(meta)
    parts = []
    if created:
        parts.append(f"created: {created:%Y-%m-%d %H:%M}")
    if activity:
        parts.append(f"last activity: {activity:%Y-%m-%d %H:%M}")
    elif goal.get("date"):
        parts.append(f"last recorded date: {goal['date']}")
    return f" ({'; '.join(parts)})" if parts else ""
