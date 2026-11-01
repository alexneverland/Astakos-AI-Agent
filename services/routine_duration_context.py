"""Bound explicit-duration evidence without refreshing presence observations."""
from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime, time, timedelta
import json
from typing import Any

from services.routine_context_evidence import (
    ContextEvidence, VOLATILE_FLAGS, _recorded_time, evaluate_stored_evidence,
)

DURATION_KEY = "routine_context_duration_proof"


def load_daily_schedule_reference(now: datetime) -> list[dict[str, Any]]:
    """Read bounded applicable schedules as plans, never evidence of execution."""
    from memory import routine_db as db
    from services.routine_context import build_runtime_routine_context, build_routine_context_evidence
    from services.routine_conditions import evaluate_routine_conditions
    try:
        rows = db.get_routines_for_day(now.strftime("%A"))
        if len(rows) > 32:
            return []
        context = build_runtime_routine_context(now)
        # An explicit reader suppresses duration-proof loading: schedules must
        # use canonical GPS-reconciled observations, never validate themselves.
        evidence = build_routine_context_evidence(now, state_reader=db.get_context_state)
        context.update({flag: item.effective_value for flag, item in evidence.items()})
        result = []
        for row in rows:
            if json.loads(row.get("external_content_sources_json", "[]")) != []:
                continue
            rid = row["id"]
            meta = db.get_routine_schedule_meta(rid)
            if db.is_routine_temporarily_inactive_meta(meta, now=now)[0]:
                continue
            conditions = db.get_routine_conditions(rid)
            if any(cond.get("condition_type") not in {
                    "context_flag", "shift_mode", "date_range", "location"} for cond in conditions):
                continue
            scoped = dict(context)
            for cond in conditions:
                payload = cond.get("condition_payload") or {}
                if isinstance(payload, str):
                    payload = json.loads(payload)
                if not isinstance(payload, dict):
                    return []
                if cond["condition_type"] == "context_flag":
                    flags = [payload["flag"]] if payload.get("flag") else list(payload)
                    for flag in flags:
                        if flag not in VOLATILE_FLAGS and isinstance(scoped.get(flag), bool):
                            scoped[flag] = evaluate_stored_evidence(db.get_context_state(flag), now=now).effective_value
                # Legacy location evaluation negates bool(None) for user_at_home.
                # Preserve uncertainty before that conversion can imply home.
                if (cond["condition_type"] == "location" and payload.get("flag") == "user_at_home"
                        and scoped.get("user_out_of_home") is None):
                    scoped = None
                    break
            if scoped is None:
                continue
            checked = evaluate_routine_conditions(conditions, scoped, now=now)
            if not checked["allowed"] or any(
                    "actual_value" in item and item["actual_value"] is None for item in checked["results"]):
                continue
            hour, minute = map(int, row["time"].split(":"))
            slot = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            result.append({"id": rid, "event": row["event"], "slot_at": slot.isoformat(),
                           "conditions": conditions, "schedule_meta": meta})
        return result if len(json.dumps(result, ensure_ascii=False)) <= 12000 else []
    except (OSError, ValueError, TypeError, KeyError, RuntimeError):
        return []


def commit_duration_resolution(
    payload: dict, rows: list[dict], expected: dict, *, allowed: set[str],
    now: datetime, still_current: Callable[[], bool],
    schedule_reference: list[dict[str, Any]] | None = None,
) -> frozenset[str] | None:
    """Persist one source-anchored proof via canonical CAS, never renew flags."""
    from memory.routine_db import set_context_states_if_unchanged
    fields = {"flags", "event_rowid", "support_rowids", "duration_source_rowids", "valid_until"}
    if set(payload) not in (fields, fields | {"schedule_routine_id"}):
        return None
    flags = payload["flags"]
    sources = {row["rowid"]: row for row in rows}
    support, duration = payload["support_rowids"], payload["duration_source_rowids"]
    if (not isinstance(flags, dict) or not flags or not set(flags) <= allowed
            or not set(flags) <= set(VOLATILE_FLAGS) or any(type(v) is not bool for v in flags.values())
            or type(payload["event_rowid"]) is not int or payload["event_rowid"] not in sources):
        return None
    for ids in (support, duration):
        if (not isinstance(ids, list) or not 1 <= len(ids) <= 12
                or any(type(i) is not int or i not in sources for i in ids) or len(set(ids)) != len(ids)):
            return None
    for source_id in support:
        source_at = _recorded_time(sources[source_id]["timestamp"], now)
        if source_at is None or source_at.date() != now.date() or source_at.timestamp() > now.timestamp():
            return None
    if payload["event_rowid"] not in support or not set(duration) <= set(support):
        return None
    event_at = _recorded_time(sources[payload["event_rowid"]]["timestamp"], now)
    try:
        end = datetime.fromisoformat(payload["valid_until"])
        if end.tzinfo is None or end.utcoffset() is None:
            return None
    except (TypeError, ValueError):
        return None
    until = _recorded_time(payload["valid_until"], now)
    midnight = datetime.combine(now.date() + timedelta(days=1), time(), now.tzinfo)
    if (event_at is None or until is None or event_at.date() != now.date()
            or not event_at.timestamp() <= now.timestamp() < until.timestamp() <= midnight.timestamp()):
        return None
    schedule_bound = None
    if "schedule_routine_id" in payload:
        rid = payload["schedule_routine_id"]
        if type(rid) is not int:
            return None
        schedule_bound = next((row for row in schedule_reference or [] if row["id"] == rid), None)
        if (schedule_bound is None or until != datetime.fromisoformat(schedule_bound["slot_at"])
                or schedule_bound not in load_daily_schedule_reference(now)):
            return None
    for flag in flags:
        prior = expected.get(flag)
        if prior:
            prior_at = _recorded_time(prior.get("updated_at"), now)
            if (prior_at is None or prior_at.timestamp() > event_at.timestamp()
                    or (prior_at.timestamp() == event_at.timestamp()
                        and prior.get("value") != str(flags[flag]).lower())):
                return None
    proof = {"version": 1, "flags": flags, "event_at": event_at.isoformat(),
        "valid_until": until.isoformat(), "history_marker": max(sources),
        "source_rowids": support, "anchors": {k: v for k, v in expected.items() if k != DURATION_KEY}}
    if schedule_bound is not None:
        proof["schedule_bound"] = schedule_bound
    if (not still_current() or DURATION_KEY not in expected
            or not set_context_states_if_unchanged(
                {DURATION_KEY: (json.dumps(proof, ensure_ascii=False), now.date().isoformat())},
                expected, recorded_at=event_at)):
        return None
    return frozenset(flags)


def apply_duration_evidence(
    evidence: dict[str, ContextEvidence], *, now: datetime,
    state_reader: Callable[[str], Mapping[str, Any] | None], history_marker: int,
) -> dict[str, ContextEvidence]:
    """Use a bounded proof only while its history, state and end remain current."""
    try:
        record = state_reader(DURATION_KEY)
        if not record or record.get("expires_at") != now.date().isoformat():
            return evidence
        raw = record.get("value")
        if not isinstance(raw, str) or len(raw) > 16000:
            return evidence
        proof = json.loads(raw)
        fields = {"version", "flags", "event_at", "valid_until", "history_marker", "source_rowids", "anchors"}
        if (not isinstance(proof, dict) or set(proof) not in (fields, fields | {"schedule_bound"})
                or type(proof["version"]) is not int or proof["version"] != 1
                or type(proof["history_marker"]) is not int or proof["history_marker"] != history_marker
                or not isinstance(proof["anchors"], dict) or not 1 <= len(proof["anchors"]) <= 32):
            return evidence
        flags = proof["flags"]
        if (not isinstance(flags, dict) or not flags or not set(flags) <= set(VOLATILE_FLAGS)
                or any(type(v) is not bool for v in flags.values()) or not set(flags) <= set(proof["anchors"])):
            return evidence
        ids = proof["source_rowids"]
        if (not isinstance(ids, list) or not 1 <= len(ids) <= 12
                or any(type(i) is not int or not 0 < i <= history_marker for i in ids)):
            return evidence
        event_at, until = (_recorded_time(proof[key], now) for key in ("event_at", "valid_until"))
        if any(datetime.fromisoformat(proof[key]).tzinfo is None for key in ("event_at", "valid_until")):
            return evidence
        midnight = datetime.combine(now.date() + timedelta(days=1), time(), now.tzinfo)
        if (event_at is None or until is None or event_at.date() != now.date()
                or not event_at.timestamp() <= now.timestamp() < until.timestamp() <= midnight.timestamp()
                or any(state_reader(k) != v for k, v in proof["anchors"].items())):
            return evidence
        if "schedule_bound" in proof:
            bound = proof["schedule_bound"]
            if (not isinstance(bound, dict) or type(bound.get("id")) is not int
                    or bound not in load_daily_schedule_reference(now)
                    or until != _recorded_time(bound.get("slot_at"), now)):
                return evidence
        result = dict(evidence)
        for flag, value in flags.items():
            # A live observation/conflict remains authoritative over a proof.
            if result[flag].reason in {"missing", "stale", "expired"}:
                result[flag] = ContextEvidence(effective_value=value,
                    stored_value=result[flag].stored_value, source="explicit_duration",
                    recorded_at=event_at, valid_until=until,
                    age_seconds=now.timestamp()-event_at.timestamp(), status="known", reason="duration")
        return result
    except (ValueError, TypeError, KeyError, OSError):
        return evidence
