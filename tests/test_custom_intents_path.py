"""Tests for isolating custom-intent data from the user's local overlay."""

import json

import config
from core import nl_config


def test_custom_intents_path_honors_environment_override(
    monkeypatch,
    tmp_path,
) -> None:
    """Ensure tests can redirect custom-intent reads away from user data."""
    override_path = tmp_path / "test_custom_intents.json"
    monkeypatch.setenv("ASTAKOS_CUSTOM_INTENTS_PATH", str(override_path))

    assert config.get_custom_intents_path() == str(override_path)


def test_both_nlp_loaders_read_the_environment_override(
    monkeypatch,
    tmp_path,
) -> None:
    """Ensure config and nl_config merge an isolated custom overlay."""
    override_path = tmp_path / "test_custom_intents.json"
    marker = "test-only-custom-marker"
    override_path.write_text(
        json.dumps({"test_overlay": {"markers": [marker]}}),
        encoding="utf-8",
    )
    monkeypatch.setenv("ASTAKOS_CUSTOM_INTENTS_PATH", str(override_path))
    monkeypatch.setattr(nl_config, "_intents", None)

    assert config._load_nlp_config()["test_overlay"]["markers"] == [marker]
    assert nl_config.load_intents()["test_overlay"]["markers"] == [marker]
