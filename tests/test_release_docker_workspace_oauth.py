"""Regression checks for the release Docker OAuth storage contract."""

from __future__ import annotations

from pathlib import Path

import yaml


def test_release_compose_keeps_workspace_token_storage_writable() -> None:
    """Release Docker must separate writable OAuth tokens from read-only secrets."""
    compose_path = Path(__file__).resolve().parents[1] / "docker-compose.release.yml"
    compose = yaml.safe_load(compose_path.read_text(encoding="utf-8"))

    astakos = compose["services"]["astakos"]
    assert astakos["environment"]["ASTAKOS_TOKEN_PATH"] == "/app/workspace/token.json"
    assert "astakos_workspace:/app/workspace" in astakos["volumes"]
    assert "astakos_workspace" in compose["volumes"]
    assert "./credentials:/app/credentials:ro" in astakos["volumes"]
