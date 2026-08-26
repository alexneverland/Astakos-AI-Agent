# ================================================================
# Project: Astakos AI Agent 🦞
# Description: Modular LLM-agnostic multi-agent framework
# Module: Google Workspace User OAuth Management
# Copyright (c) 2026 - All Rights Reserved
# ================================================================

from __future__ import annotations

import json
import logging
import os

from typing import Any, Sequence

from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import Resource, build

import config

logger = logging.getLogger(__name__)

# Standard Google Workspace Scopes supported by Astakos
DEFAULT_WORKSPACE_SCOPES: list[str] = [
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/tasks",
    "https://www.googleapis.com/auth/fitness.activity.read",
    "https://www.googleapis.com/auth/fitness.body.read",
    "https://www.googleapis.com/auth/fitness.sleep.read",
    "https://www.googleapis.com/auth/fitness.heart_rate.read",
]

def _write_token_file_atomic(token_path: str, content: str) -> None:
    """Writes token content atomically to avoid partial writes and sets secure permissions."""
    import stat
    import tempfile

    dir_name = os.path.dirname(token_path)
    os.makedirs(dir_name, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", dir=dir_name, delete=False, encoding="utf-8") as tmp:
        tmp.write(content)
        tmp_name = tmp.name
    try:
        if hasattr(os, "chmod"):
            os.chmod(tmp_name, stat.S_IRUSR | stat.S_IWUSR)
        os.replace(tmp_name, token_path)
    except Exception:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)
        raise


class WorkspaceAuthError(Exception):

    """Base error for Google Workspace user OAuth operations."""


class WorkspaceMissingCredentialsError(WorkspaceAuthError):
    """Raised when Google Workspace has not been authorized (token.json missing)."""


class WorkspaceMissingScopeError(WorkspaceAuthError):
    """Raised when an authorized token lacks a required scope for the requested feature."""


class WorkspaceMissingOAuthClientSecretsError(WorkspaceAuthError):
    """Raised when the dedicated OAuth client secrets file (client_secrets.json) is missing."""


class WorkspaceTokenRevokedOrInvalidError(WorkspaceAuthError):
    """Raised when the user OAuth token is revoked, expired without valid refresh, or the OAuth client changed."""


def get_token_path() -> str:
    """Returns the absolute path to the user's Workspace OAuth token.json."""
    return getattr(config, "TOKEN_PATH", os.path.join(config.BASE_DIR, "credentials", "token.json"))


def get_oauth_client_secrets_path() -> str:
    """
    Returns the path to the dedicated Google Workspace OAuth client secrets file.
    Optionally configured via WORKSPACE_CLIENT_SECRETS_PATH env var.
    Defaults to credentials/client_secrets.json (or client_secrets.json in root).
    Never uses credentials.json (which may be a Vertex service account).
    """
    env_path = os.environ.get("WORKSPACE_CLIENT_SECRETS_PATH") or os.environ.get("GOOGLE_WORKSPACE_CLIENT_SECRETS_PATH")
    if env_path:
        return env_path

    cred_client_secrets = os.path.join(config.BASE_DIR, "credentials", "client_secrets.json")
    if os.path.exists(cred_client_secrets):
        return cred_client_secrets

    root_client_secrets = os.path.join(config.BASE_DIR, "client_secrets.json")
    if os.path.exists(root_client_secrets):
        return root_client_secrets

    return cred_client_secrets


def is_workspace_connected() -> bool:
    """Checks whether a valid token.json exists for Google Workspace."""
    token_path = get_token_path()
    return bool(os.path.exists(token_path) and os.path.getsize(token_path) > 0)


def read_stored_token_scopes(token_path: str | None = None) -> list[str]:
    """Reads the granted scopes from token.json, supporting either 'scopes' list or 'scope' space-separated string."""
    target_path = token_path or get_token_path()

    if not os.path.exists(target_path) or os.path.getsize(target_path) == 0:
        return []
    try:
        with open(target_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as exc:
        logger.warning(f"Could not parse token.json for scopes: {exc}")
        return []

    raw_scopes = data.get("scopes") or data.get("scope") or []
    if isinstance(raw_scopes, str):
        return [s for s in raw_scopes.split() if s]
    if isinstance(raw_scopes, list):
        return [str(s) for s in raw_scopes if s]
    return []


def check_missing_scopes(
    required_scopes: Sequence[str],
    token_scopes: Sequence[str] | None = None,
) -> list[str]:
    """Returns any required scopes that are not present in the token's granted scopes."""
    granted_set = set(token_scopes if token_scopes is not None else read_stored_token_scopes())
    return [req for req in required_scopes if req and req not in granted_set]


def authorize_workspace_oauth(
    client_secrets_path: str | None = None,
    scopes: Sequence[str] | None = None,
    port: int = 0,
) -> str:
    """
    Initiates an explicit interactive OAuth consent flow in the browser.
    Requests all DEFAULT_WORKSPACE_SCOPES plus any caller-provided additional scopes,
    deterministically deduplicated, and writes the resulting user token to token.json.
    Never uses credentials.json (Vertex service account).
    """
    from google_auth_oauthlib.flow import InstalledAppFlow

    target_secrets = client_secrets_path or get_oauth_client_secrets_path()
    if not os.path.exists(target_secrets) or os.path.getsize(target_secrets) == 0:
        raise WorkspaceMissingOAuthClientSecretsError(
            f"Google Workspace OAuth client secrets file not found at '{target_secrets}'. "
            "Please place your OAuth client secrets JSON at 'credentials/client_secrets.json' "
            "or set WORKSPACE_CLIENT_SECRETS_PATH."
        )

    consent_scopes: list[str] = list(DEFAULT_WORKSPACE_SCOPES)
    if scopes:
        for scope in scopes:
            if scope and scope not in consent_scopes:
                consent_scopes.append(scope)

    flow = InstalledAppFlow.from_client_secrets_file(target_secrets, consent_scopes)
    creds = flow.run_local_server(port=port, prompt="consent", access_type="offline")

    token_path = get_token_path()
    _write_token_file_atomic(token_path, creds.to_json())

    return "Google Workspace authorization successful."




def load_workspace_credentials(
    scopes: Sequence[str] | None = None,
    auto_refresh: bool = True,
) -> Credentials:
    """
    Loads and optionally refreshes the user's Google Workspace OAuth credentials.
    Preserves existing granted scopes and never injects new ungranted default scopes.

    Raises:
        WorkspaceMissingCredentialsError: If token.json is not found.
        WorkspaceMissingScopeError: If token.json lacks a requested scope.
        WorkspaceTokenRevokedOrInvalidError: If the token is invalid or refresh fails.
    """
    token_path = get_token_path()
    if not os.path.exists(token_path) or os.path.getsize(token_path) == 0:
        raise WorkspaceMissingCredentialsError(
            "Google Workspace is not connected (token.json not found). "
            "Please connect your Google Workspace account in settings or authorize OAuth."
        )

    stored_scopes = read_stored_token_scopes(token_path)

    # Validate caller's requested scopes against granted scopes only when stored scope metadata is present
    if stored_scopes and scopes:
        missing = check_missing_scopes(scopes, stored_scopes)
        if missing:
            raise WorkspaceMissingScopeError(
                f"Google Workspace authorization lacks required permissions ({', '.join(missing)}). "
                "Please reconnect your Google Workspace account to grant access."
            )

    try:
        creds = Credentials.from_authorized_user_file(token_path, scopes=stored_scopes or None)
    except Exception as exc:
        raise WorkspaceTokenRevokedOrInvalidError(
            f"Google Workspace token is invalid: {exc}. Please reconnect your Google account."
        ) from exc

    if not creds:
        raise WorkspaceMissingCredentialsError(
            "Google Workspace credentials could not be loaded from token.json."
        )

    if not creds.valid and auto_refresh:
        if creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
                try:
                    refreshed_json = creds.to_json()
                    # If original token omitted scope metadata, ensure we do not persist
                    # a caller scope subset as the full token grant set.
                    if not stored_scopes:
                        try:
                            token_dict = json.loads(refreshed_json)
                            token_dict.pop("scopes", None)
                            token_dict.pop("scope", None)
                            refreshed_json = json.dumps(token_dict, indent=2)
                        except Exception:
                            pass

                    _write_token_file_atomic(token_path, refreshed_json)
                except Exception as write_exc:
                    logger.warning(f"Could not persist refreshed token: {write_exc}")
            except RefreshError as exc:
                logger.warning(f"[WorkspaceOAuth] Token refresh failed: {exc}")

                raise WorkspaceTokenRevokedOrInvalidError(
                    f"Google Workspace authorization expired or revoked ({exc}). "
                    "Please reconnect your Google Workspace account."
                ) from exc
            except Exception as exc:
                logger.warning(f"[WorkspaceOAuth] Token refresh failed: {exc}")
                raise WorkspaceTokenRevokedOrInvalidError(
                    f"Google Workspace token refresh failed: {exc}. Please reconnect your Google account."
                ) from exc
        else:
            raise WorkspaceTokenRevokedOrInvalidError(
                "Google Workspace token has expired and has no refresh token. Please reconnect your Google account."
            )

    return creds



def get_workspace_service(
    api_name: str,
    api_version: str,
    scopes: Sequence[str] | None = None,
    **kwargs: Any,
) -> Resource:
    """Constructs a Google API service Resource using the authenticated user's OAuth credentials."""
    creds = load_workspace_credentials(scopes=scopes, auto_refresh=True)
    return build(api_name, api_version, credentials=creds, cache_discovery=False, **kwargs)
