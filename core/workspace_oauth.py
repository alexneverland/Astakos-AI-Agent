# ================================================================
# Project: Astakos AI Agent 🦞
# Description: Modular LLM-agnostic multi-agent framework
# Module: Google Workspace User OAuth Management
# Copyright (c) 2026 - All Rights Reserved
# ================================================================

from __future__ import annotations

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

_RECOVERABLE_REFRESH_ERRORS: tuple[str, ...] = (
    "invalid_grant",
    "invalid_client",
    "unauthorized_client",
    "invalid_scope",
    "deleted_client",
)


class WorkspaceAuthError(Exception):
    """Base error for Google Workspace user OAuth operations."""


class WorkspaceMissingCredentialsError(WorkspaceAuthError):
    """Raised when Google Workspace has not been authorized (token.json missing)."""


class WorkspaceTokenRevokedOrInvalidError(WorkspaceAuthError):
    """Raised when the user OAuth token is revoked, expired without valid refresh, or the OAuth client changed."""


def get_token_path() -> str:
    """Returns the absolute path to the user's Workspace OAuth token.json."""
    return getattr(config, "TOKEN_PATH", os.path.join(config.BASE_DIR, "credentials", "token.json"))


def get_credentials_path() -> str:
    """Returns the absolute path to the OAuth client secrets credentials.json."""
    return getattr(config, "CREDENTIALS_PATH", os.path.join(config.BASE_DIR, "credentials", "credentials.json"))


def is_workspace_connected() -> bool:
    """Checks whether a valid token.json exists for Google Workspace."""
    token_path = get_token_path()
    return bool(os.path.exists(token_path) and os.path.getsize(token_path) > 0)


def load_workspace_credentials(
    scopes: Sequence[str] | None = None,
    auto_refresh: bool = True,
) -> Credentials:
    """
    Loads and optionally refreshes the user's Google Workspace OAuth credentials.

    Raises:
        WorkspaceMissingCredentialsError: If token.json is not found.
        WorkspaceTokenRevokedOrInvalidError: If the token is invalid or refresh fails.
    """
    token_path = get_token_path()
    if not os.path.exists(token_path) or os.path.getsize(token_path) == 0:
        raise WorkspaceMissingCredentialsError(
            "Google Workspace is not connected (token.json not found). "
            "Please connect your Google Workspace account in settings or authorize OAuth."
        )

    effective_scopes = list(scopes) if scopes else DEFAULT_WORKSPACE_SCOPES

    try:
        creds = Credentials.from_authorized_user_file(token_path, scopes=effective_scopes)
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
                    with open(token_path, "w", encoding="utf-8") as f:
                        f.write(creds.to_json())
                except Exception as write_exc:
                    logger.warning(f"Could not persist refreshed token: {write_exc}")
            except RefreshError as exc:
                err_msg = str(exc).lower()
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
