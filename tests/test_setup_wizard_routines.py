"""Coverage for portable routine setup through the local Setup Wizard."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from fastapi import HTTPException


_VALID_ROUTINES_JSON = """{
  "version": 1,
  "routines": [
    {
      "day": "Monday",
      "time": "18:00",
      "event": "Evening walk",
      "type": "hobby"
    }
  ]
}"""


class _NoOpThread:
    """Prevent the setup endpoint test from scheduling a process exit."""

    def __init__(self, *args: object, **kwargs: object) -> None:
        """Accept the production thread constructor arguments without using them."""

    def start(self) -> None:
        """Leave the test process alive after a successful setup response."""


def _configure_isolated_setup_files(monkeypatch: pytest.MonkeyPatch, base: Path) -> None:
    """Redirect every Setup Wizard write target into one temporary directory."""
    import api.setup_wizard as wizard

    prompts_dir = base / "prompts"
    prompts_dir.mkdir()
    monkeypatch.setattr(wizard, "ENV_FILE", str(base / ".env"))
    monkeypatch.setattr(wizard, "PERSONA_FILE", str(base / "persona.md"))
    monkeypatch.setattr(wizard, "INTENTS_FILE", str(base / "astakos_custom_intents.json"))
    monkeypatch.setattr(wizard, "ROUTINES_FILE", str(base / "astakos_routines.json"))
    monkeypatch.setattr(wizard, "SETTINGS_FILE", str(base / "astakos_settings.json"))
    monkeypatch.setattr(wizard, "PROMPTS_DIR", str(prompts_dir))
    monkeypatch.setattr(wizard.threading, "Thread", _NoOpThread)


def test_setup_wizard_returns_routine_template_when_no_local_file_exists(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A new user receives the portable routine template in the Wizard."""
    import api.setup_wizard as wizard

    _configure_isolated_setup_files(monkeypatch, tmp_path)
    example_path = tmp_path / "astakos_routines.json.example"
    example_path.write_text(_VALID_ROUTINES_JSON, encoding="utf-8")
    monkeypatch.setattr(wizard, "ROUTINES_EXAMPLE", str(example_path))

    result = asyncio.run(wizard.get_raw_files())

    assert result["routines"] == _VALID_ROUTINES_JSON


def test_setup_wizard_writes_valid_routines_then_imports_once(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """The Wizard validates, persists, and explicitly imports a routine declaration."""
    import api.setup_wizard as wizard
    import memory.routine_importer as routine_importer

    _configure_isolated_setup_files(monkeypatch, tmp_path)
    imported_routines: list[list[dict[str, str]]] = []
    monkeypatch.setattr(
        routine_importer,
        "import_validated_routines",
        lambda routines: imported_routines.append(routines) or {"status": "imported", "count": 1},
    )

    result = asyncio.run(wizard.save_setup(wizard.SetupPayload(
        basic={},
        advanced={},
        prompts={},
        routines=_VALID_ROUTINES_JSON,
    )))

    routines_path = tmp_path / "astakos_routines.json"
    assert routines_path.read_text(encoding="utf-8") == f"{_VALID_ROUTINES_JSON}\n"
    assert imported_routines == [[{
        "day": "Monday",
        "time": "18:00",
        "event": "Evening walk",
        "type": "hobby",
    }]]
    assert result["routine_import"] == {"status": "imported", "count": 1}


def test_setup_wizard_rejects_invalid_routines_before_writing(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Invalid routine JSON must not create a local routine declaration file."""
    import api.setup_wizard as wizard

    _configure_isolated_setup_files(monkeypatch, tmp_path)

    with pytest.raises(
        HTTPException,
        match="Routine validation failed. Please check routine definitions.",
    ):
        asyncio.run(wizard.save_setup(wizard.SetupPayload(
            basic={},
            advanced={},
            prompts={},
            routines='{"version": 1, "routines": [{"day": "Monday", "time": "6pm", "event": "Walk", "type": "hobby"}]}',
        )))

    assert not (tmp_path / "astakos_routines.json").exists()


def test_release_entrypoint_preserves_user_routine_declaration() -> None:
    """Release updates must not delete the optional local first-run routine file."""
    entrypoint = Path("docker/release-entrypoint.sh").read_text(encoding="utf-8")

    assert "--exclude 'astakos_routines.json'" in entrypoint
