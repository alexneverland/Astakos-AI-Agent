"""Regression checks for the release Docker OAuth storage contract."""

from __future__ import annotations

from pathlib import Path

import yaml


def test_release_compose_keeps_workspace_token_storage_writable() -> None:
    """Release Docker must isolate and preserve writable Workspace tokens."""
    compose_path = Path(__file__).resolve().parents[1] / "docker-compose.release.yml"
    compose = yaml.safe_load(compose_path.read_text(encoding="utf-8"))

    astakos = compose["services"]["astakos"]
    assert astakos["environment"]["ASTAKOS_TOKEN_PATH"] == "/workspace/token.json"
    assert "astakos_workspace:/workspace" in astakos["volumes"]
    assert "astakos_workspace" in compose["volumes"]
    assert "./credentials:/app/credentials:ro" in astakos["volumes"]

    entrypoint = (compose_path.parent / "docker" / "release-entrypoint.sh").read_text(encoding="utf-8")
    assert 'legacy_token_path="/app/credentials/token.json"' in entrypoint
    assert 'workspace_token_path="${ASTAKOS_TOKEN_PATH:-/workspace/token.json}"' in entrypoint
    assert 'cp "$legacy_token_path" "$workspace_token_path"' in entrypoint
