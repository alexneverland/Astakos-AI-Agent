# ================================================================
# Project: Astakos AI Agent 🦞
# Description: Modular LLM-agnostic multi-agent framework
# Module: Tests for Google OAuth Refresh and Recovery Handling
# Copyright (c) 2026 - All Rights Reserved
# ================================================================

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch


import pytest
from google.auth.exceptions import RefreshError

import tools.system as system
from core.workspace_oauth import (
    WorkspaceMissingCredentialsError,
    WorkspaceTokenRevokedOrInvalidError,
    load_workspace_credentials,
)


@pytest.mark.parametrize(
    "refresh_error",
    (
        "invalid_grant: Token has been revoked.",
        "invalid_scope: Requested scopes are invalid or missing.",
        "invalid_client: Client is deleted or changed.",
        "unauthorized_client: Client unauthorized.",
    ),
)
def test_workspace_oauth_refresh_failure_raises_actionable_error(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    refresh_error: str,
) -> None:
    """Verifies that recoverable OAuth refresh failures raise WorkspaceTokenRevokedOrInvalidError without touching credentials.json."""
    token_path = tmp_path / "token.json"
    token_path.write_text(json.dumps({"scopes": ["https://www.googleapis.com/auth/gmail.modify"]}), encoding="utf-8")


    stale_creds = MagicMock(valid=False, expired=True, refresh_token="revoked")
    stale_creds.refresh.side_effect = RefreshError(refresh_error)

    monkeypatch.setattr("core.workspace_oauth.get_token_path", lambda: str(token_path))

    with patch("google.oauth2.credentials.Credentials.from_authorized_user_file", return_value=stale_creds):
        with pytest.raises(WorkspaceTokenRevokedOrInvalidError) as exc_info:
            load_workspace_credentials(scopes=["https://www.googleapis.com/auth/gmail.modify"])

        assert "reconnect" in str(exc_info.value).lower() or "revoked" in str(exc_info.value).lower()


def test_get_gmail_service_raises_clean_error_on_missing_token(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    non_existent = tmp_path / "missing_token.json"
    monkeypatch.setattr("core.workspace_oauth.get_token_path", lambda: str(non_existent))

    with pytest.raises(Exception) as exc_info:
        system.get_gmail_service()

    assert "Google Workspace is not connected" in str(exc_info.value)
