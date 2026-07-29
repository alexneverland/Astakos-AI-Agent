"""Regression coverage for the portable first-run routine importer."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Iterator

import pytest


@pytest.fixture
def isolated_routine_db(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> Iterator[ModuleType]:
    """Route routine persistence to a dedicated temporary database."""
    import memory.routine_db as routine_db

    database_path = tmp_path / "routines.db"
    monkeypatch.setattr(routine_db, "DB_PATH", str(database_path))
    routine_db.setup_db()
    yield routine_db


def _write_routine_json(path: Path, payload: dict[str, object]) -> None:
    """Write a UTF-8 declarative routine payload for an isolated test."""
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def test_importer_creates_active_declared_routines_in_an_empty_database(
    isolated_routine_db: ModuleType, tmp_path: Path
) -> None:
    """A new setup import activates declared routines without runtime history."""
    from memory.routine_importer import import_routines_file

    routines_file = tmp_path / "astakos_routines.json"
    _write_routine_json(
        routines_file,
        {
            "version": 1,
            "routines": [
                {
                    "day": "Monday",
                    "time": "18:00",
                    "event": "Evening walk",
                    "type": "hobby",
                }
            ],
        },
    )

    result = import_routines_file(routines_file)

    assert result == {"status": "imported", "count": 1}
    assert isolated_routine_db.get_routines_for_day("Monday") == [
        {
            "id": 1,
            "time": "18:00",
            "event": "Evening walk",
            "type": "hobby",
            "confidence": 1.0,
            "mentions": 1,
            "state": "active",
        }
    ]


def test_importer_rejects_unknown_fields_without_writing(
    isolated_routine_db: ModuleType, tmp_path: Path
) -> None:
    """Unknown fields fail closed before the empty database is changed."""
    from memory.routine_importer import RoutineImportError, import_routines_file

    routines_file = tmp_path / "astakos_routines.json"
    _write_routine_json(
        routines_file,
        {
            "version": 1,
            "routines": [
                {
                    "day": "Monday",
                    "time": "18:00",
                    "event": "Evening walk",
                    "type": "hobby",
                    "last_triggered": "never",
                }
            ],
        },
    )

    with pytest.raises(RoutineImportError, match="unknown fields"):
        import_routines_file(routines_file)

    assert isolated_routine_db.get_routines_for_day("Monday") == []


def test_importer_rejects_boolean_schema_version_without_writing(
    isolated_routine_db: ModuleType, tmp_path: Path
) -> None:
    """A JSON boolean cannot be accepted as schema version one."""
    from memory.routine_importer import RoutineImportError, import_routines_file

    routines_file = tmp_path / "astakos_routines.json"
    _write_routine_json(
        routines_file,
        {
            "version": True,
            "routines": [
                {
                    "day": "Monday",
                    "time": "18:00",
                    "event": "Evening walk",
                    "type": "hobby",
                }
            ],
        },
    )

    with pytest.raises(RoutineImportError, match="Unsupported routine import version"):
        import_routines_file(routines_file)

    assert isolated_routine_db.get_routines_for_day("Monday") == []


@pytest.mark.parametrize(
    ("path_kind", "expected_message"),
    [
        ("directory", "cannot be read"),
        ("non_utf8", "must use UTF-8"),
    ],
)
def test_importer_reports_file_access_and_decoding_errors(
    tmp_path: Path, path_kind: str, expected_message: str
) -> None:
    """Unreadable import inputs fail through the routine validation contract."""
    from memory.routine_importer import RoutineImportError, load_routine_import

    routines_path = tmp_path / "astakos_routines.json"
    if path_kind == "directory":
        routines_path.mkdir()
    else:
        routines_path.write_bytes(b"\xff")

    with pytest.raises(RoutineImportError, match=expected_message):
        load_routine_import(routines_path)


@pytest.mark.parametrize(
    "raw_payload",
    [
        '{"version": 1, "routines": [], "routines": []}',
        (
            '{"version": 1, "routines": ['
            '{"day": "Monday", "time": "18:00", '
            '"event": "Evening walk", "event": "Night walk", "type": "hobby"}'
            ']}'
        ),
    ],
)
def test_importer_rejects_duplicate_json_object_members(
    tmp_path: Path, raw_payload: str
) -> None:
    """Ambiguous JSON object members fail before routine validation or persistence."""
    from memory.routine_importer import RoutineImportError, load_routine_import

    routines_path = tmp_path / "astakos_routines.json"
    routines_path.write_text(raw_payload, encoding="utf-8")

    with pytest.raises(RoutineImportError, match="duplicate key"):
        load_routine_import(routines_path)


def test_importer_rejects_unpaired_unicode_surrogates(tmp_path: Path) -> None:
    """An escaped lone surrogate is a validation error, not a fingerprint crash."""
    from memory.routine_importer import RoutineImportError, load_routine_import

    routines_path = tmp_path / "astakos_routines.json"
    routines_path.write_text(
        (
            '{"version": 1, "routines": ['
            '{"day": "Monday", "time": "18:00", '
            '"event": "ab\\ud800", "type": "hobby"}'
            ']}'
        ),
        encoding="utf-8",
    )

    with pytest.raises(RoutineImportError, match="valid Unicode"):
        load_routine_import(routines_path)


def test_importer_rejects_duplicate_declarations_without_writing(
    isolated_routine_db: ModuleType, tmp_path: Path
) -> None:
    """Duplicate declarations cannot simulate repeated learning or activation."""
    from memory.routine_importer import RoutineImportError, import_routines_file

    routines_file = tmp_path / "astakos_routines.json"
    _write_routine_json(
        routines_file,
        {
            "version": 1,
            "routines": [
                {
                    "day": "Monday",
                    "time": "18:00",
                    "event": "Evening walk",
                    "type": "hobby",
                },
                {
                    "day": "Monday",
                    "time": "18:00",
                    "event": "Evening walk",
                    "type": "hobby",
                },
            ],
        },
    )

    with pytest.raises(RoutineImportError, match="duplicate"):
        import_routines_file(routines_file)

    assert isolated_routine_db.get_routines_for_day("Monday") == []


def test_duplicate_validation_does_not_initialize_the_routine_database(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A duplicate-invalid file fails before it imports or initializes routine persistence."""
    from memory.routine_importer import RoutineImportError, load_routine_import

    monkeypatch.setitem(sys.modules, "memory.routine_db", None)
    routines_file = tmp_path / "astakos_routines.json"
    _write_routine_json(
        routines_file,
        {
            "version": 1,
            "routines": [
                {
                    "day": "Monday",
                    "time": "18:00",
                    "event": "Evening walk",
                    "type": "hobby",
                },
                {
                    "day": "Monday",
                    "time": "18:00",
                    "event": "Evening walk",
                    "type": "hobby",
                },
            ],
        },
    )

    with pytest.raises(RoutineImportError, match="duplicate"):
        load_routine_import(routines_file)


def test_importer_refuses_to_change_a_database_that_already_has_routines(
    isolated_routine_db: ModuleType, tmp_path: Path
) -> None:
    """A second setup run preserves learned or existing routine state."""
    from memory.routine_importer import import_routines_file

    isolated_routine_db.upsert_routine("Monday", "08:00", "Existing routine")
    routines_file = tmp_path / "astakos_routines.json"
    _write_routine_json(
        routines_file,
        {
            "version": 1,
            "routines": [
                {
                    "day": "Tuesday",
                    "time": "18:00",
                    "event": "New declared routine",
                    "type": "general",
                }
            ],
        },
    )

    result = import_routines_file(routines_file)

    assert result == {"status": "skipped_existing_database", "count": 0}
    assert isolated_routine_db.get_routines_for_day("Tuesday") == []


def test_empty_import_reports_existing_database_without_writing(
    isolated_routine_db: ModuleType, tmp_path: Path
) -> None:
    """An empty starter file cannot report a successful import over existing data."""
    from memory.routine_importer import import_routines_file

    isolated_routine_db.upsert_routine("Monday", "08:00", "Existing routine")
    routines_file = tmp_path / "astakos_routines.json"
    _write_routine_json(routines_file, {"version": 1, "routines": []})

    assert import_routines_file(routines_file) == {
        "status": "skipped_existing_database",
        "count": 0,
    }
