"""Validated one-time import for portable first-run routine definitions."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any


SCHEMA_VERSION = 1
_TOP_LEVEL_FIELDS = frozenset({"version", "routines"})
_ROUTINE_FIELDS = frozenset({"day", "time", "event", "type"})
_CANONICAL_DAYS = frozenset(
    {
        "Monday",
        "Tuesday",
        "Wednesday",
        "Thursday",
        "Friday",
        "Saturday",
        "Sunday",
        "Everyday",
        "Weekdays",
        "Weekends",
    }
)
_ROUTINE_TYPES = frozenset({"family", "work", "hobby", "general"})
_TIME_PATTERN = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")


class RoutineImportError(ValueError):
    """Raised when a portable routine file is invalid or unsafe to import."""


def _reject_duplicate_object_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    """Decode a JSON object while rejecting ambiguous duplicate member names."""
    decoded: dict[str, Any] = {}
    for key, value in pairs:
        if key in decoded:
            raise RoutineImportError(f"Routine import contains duplicate key: {key}")
        decoded[key] = value
    return decoded


def _require_exact_fields(value: dict[str, Any], expected: frozenset[str], label: str) -> None:
    """Reject fields outside the portable schema instead of silently ignoring them."""
    unknown_fields = sorted(set(value) - expected)
    missing_fields = sorted(expected - set(value))
    if unknown_fields:
        raise RoutineImportError(f"{label} contains unknown fields: {', '.join(unknown_fields)}")
    if missing_fields:
        raise RoutineImportError(f"{label} is missing fields: {', '.join(missing_fields)}")


def _validate_routine(raw_routine: Any, index: int) -> dict[str, str]:
    """Validate and normalize one declarative routine without touching persistence."""
    if not isinstance(raw_routine, dict):
        raise RoutineImportError(f"routines[{index}] must be an object")
    _require_exact_fields(raw_routine, _ROUTINE_FIELDS, f"routines[{index}]")

    day = raw_routine["day"]
    time = raw_routine["time"]
    event = raw_routine["event"]
    event_type = raw_routine["type"]
    if not all(isinstance(value, str) for value in (day, time, event, event_type)):
        raise RoutineImportError(f"routines[{index}] values must all be strings")
    if day not in _CANONICAL_DAYS:
        raise RoutineImportError(f"routines[{index}].day must be a canonical weekday")
    if not _TIME_PATTERN.fullmatch(time):
        raise RoutineImportError(f"routines[{index}].time must use HH:MM")
    event = event.strip()
    if not 3 <= len(event) <= 200:
        raise RoutineImportError(f"routines[{index}].event must contain 3-200 characters")
    if event_type not in _ROUTINE_TYPES:
        raise RoutineImportError(f"routines[{index}].type is unsupported")
    return {"day": day, "time": time, "event": event, "type": event_type}


def _make_declaration_fingerprint(routine: dict[str, str]) -> str:
    """Build the routine-db-compatible fingerprint without importing persistence."""
    key = f"{routine['day']}|{routine['time']}|{routine['event'].lower().strip()}"
    return hashlib.md5(key.encode("utf-8")).hexdigest()[:12]


def load_routine_import(path: Path) -> list[dict[str, str]]:
    """Read and fully validate a portable routine JSON file before database access."""
    try:
        raw_payload = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_reject_duplicate_object_keys,
        )
    except FileNotFoundError as e:
        raise RoutineImportError(f"Routine import file does not exist: {path}") from e
    except UnicodeDecodeError as e:
        raise RoutineImportError("Routine import file must use UTF-8 encoding") from e
    except OSError as e:
        raise RoutineImportError(f"Routine import file cannot be read: {path}") from e
    except json.JSONDecodeError as e:
        raise RoutineImportError(f"Routine import file contains invalid JSON: {e.msg}") from e

    if not isinstance(raw_payload, dict):
        raise RoutineImportError("Routine import root must be an object")
    _require_exact_fields(raw_payload, _TOP_LEVEL_FIELDS, "Routine import root")
    if type(raw_payload["version"]) is not int or raw_payload["version"] != SCHEMA_VERSION:
        raise RoutineImportError(f"Unsupported routine import version: {raw_payload['version']!r}")
    if not isinstance(raw_payload["routines"], list):
        raise RoutineImportError("Routine import routines must be a list")

    routines = [_validate_routine(raw_routine, index) for index, raw_routine in enumerate(raw_payload["routines"])]
    fingerprints = [_make_declaration_fingerprint(routine) for routine in routines]
    if len(fingerprints) != len(set(fingerprints)):
        raise RoutineImportError("Routine import contains duplicate day/time/event entries")
    return routines


def import_routines_file(path: Path) -> dict[str, int | str]:
    """Import a validated routine file only into an empty routine database."""
    routines = load_routine_import(path)
    from memory.routine_db import import_declared_routines

    imported_count = import_declared_routines(routines)
    if imported_count is None:
        return {"status": "skipped_existing_database", "count": 0}
    return {"status": "imported", "count": imported_count}
