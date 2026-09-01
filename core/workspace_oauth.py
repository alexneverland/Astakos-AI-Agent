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
import secrets
import threading
import time

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

_OAUTH_STATE_TTL_SECONDS = 900
_oauth_states: dict[str, tuple[float, str]] = {}
_oauth_state_lock = threading.Lock()

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


class WorkspaceOAuthStateError(WorkspaceAuthError):
    """Raised when a browser OAuth callback has missing, invalid, or expired state."""


class WorkspaceOAuthTokenExchangeError(WorkspaceAuthError):
    """Raised when Google rejects or cannot complete a consent-code exchange."""


class WorkspaceOAuthTokenPersistenceError(WorkspaceAuthError):
    """Raised when a newly authorized Workspace token cannot be saved locally."""


def get_token_path() -> str:
    """Returns the absolute path to the user's Workspace OAuth token.json."""
    env_path = os.environ.get("ASTAKOS_TOKEN_PATH") or os.environ.get("WORKSPACE_TOKEN_PATH")
    if env_path:
        return env_path
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


def inspect_workspace_token_metadata(token_path: str | None = None) -> tuple[str, list[str]]:
    """
    Safely inspects token.json structure offline without network calls.

    Returns:
        tuple[status, scopes]:
          - ("missing", []) if file does not exist or is empty
          - ("malformed", []) if JSON cannot be parsed or is not a dict
          - ("legacy", []) if valid JSON dict but has no scopes/scope metadata
          - ("valid", scopes_list) if valid JSON dict with explicit scopes list/string
    """
    target_path = token_path or get_token_path()
    if not os.path.exists(target_path) or os.path.getsize(target_path) == 0:
        return ("missing", [])

    try:
        with open(target_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return ("malformed", [])

    if not isinstance(data, dict) or not data:
        return ("malformed", [])

    # Complete authorized-user credential fields required by google.oauth2.credentials.Credentials:
    # Credentials.from_authorized_user_file strictly requires client_id + client_secret + refresh_token
    has_client = bool(data.get("client_id") and data.get("client_secret"))
    has_refresh = bool(data.get("refresh_token"))
    if not (has_client and has_refresh):
        return ("malformed", [])

    has_scopes_field = "scopes" in data
    has_scope_field = "scope" in data

    if has_scopes_field or has_scope_field:
        raw_scopes = data["scopes"] if has_scopes_field else data["scope"]
        if isinstance(raw_scopes, list):
            parsed = [str(s).strip() for s in raw_scopes if str(s).strip()]
            return ("valid", parsed)
        elif isinstance(raw_scopes, str):
            parsed = [s.strip() for s in raw_scopes.split() if s.strip()]
            return ("valid", parsed)
        elif raw_scopes is None:
            return ("valid", [])
        return ("malformed", [])

    return ("legacy", [])




def get_workspace_oauth_flow(
    client_secrets_path: str | None = None,
    scopes: Sequence[str] | None = None,
    redirect_uri: str | None = None,
    code_verifier: str | None = None,
):
    """Creates a configured google_auth_oauthlib Flow without launching an interactive server."""
    from google_auth_oauthlib.flow import Flow

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

    flow = Flow.from_client_secrets_file(
        target_secrets,
        scopes=consent_scopes,
        redirect_uri=redirect_uri or "http://localhost:8000/api/workspace/oauth/callback",
        code_verifier=code_verifier,
    )
    return flow


def create_workspace_oauth_authorization_url(redirect_uri: str) -> str:
    """Create a state-protected Google Workspace consent URL for an explicit user action."""
    if not redirect_uri:
        raise WorkspaceOAuthStateError("OAuth redirect URI is required.")

    flow = get_workspace_oauth_flow(redirect_uri=redirect_uri)
    state = secrets.token_urlsafe(32)
    auth_url, _ = flow.authorization_url(
        state=state,
        prompt="consent",
        access_type="offline",
        include_granted_scopes="true",
    )
    code_verifier = flow.code_verifier
    if not code_verifier:
        raise WorkspaceOAuthStateError("OAuth PKCE verifier could not be created.")

    with _oauth_state_lock:
        now = time.time()
        expired_states = [
            value for value, (created_at, _) in _oauth_states.items()
            if now - created_at > _OAUTH_STATE_TTL_SECONDS
        ]
        for expired_state in expired_states:
            _oauth_states.pop(expired_state, None)
        _oauth_states[state] = (now, code_verifier)

    return auth_url


def complete_workspace_oauth_authorization(
    redirect_uri: str,
    code: str,
    state: str,
) -> None:
    """Verify a browser callback and atomically persist the shared Workspace token."""
    if not code:
        raise WorkspaceOAuthStateError("OAuth authorization code is required.")

    with _oauth_state_lock:
        state_data = _oauth_states.pop(state, None)

    if not state_data or time.time() - state_data[0] > _OAUTH_STATE_TTL_SECONDS:
        raise WorkspaceOAuthStateError("OAuth state is invalid or expired.")

    _, code_verifier = state_data
    flow = get_workspace_oauth_flow(
        redirect_uri=redirect_uri,
        code_verifier=code_verifier,
    )
    try:
        flow.fetch_token(code=code)
    except Exception as exc:
        logger.warning("[WorkspaceOAuth] Consent-code exchange failed: %s", exc)
        raise WorkspaceOAuthTokenExchangeError(
            "Google could not complete the Workspace authorization.",
        ) from exc

    try:
        _write_token_file_atomic(get_token_path(), flow.credentials.to_json())
    except Exception as exc:
        logger.warning("[WorkspaceOAuth] Authorized token could not be saved: %s", exc)
        raise WorkspaceOAuthTokenPersistenceError(
            "Google authorization completed, but the Workspace token could not be saved.",
        ) from exc



def read_stored_token_scopes(token_path: str | None = None) -> list[str] | None:
    """
    Reads the granted scopes from token.json.
    Returns:
      - list[str] (which may be empty) if explicit scope metadata was present in token.json
      - None if token.json lacks scope metadata (legacy token)
    """
    status, scopes = inspect_workspace_token_metadata(token_path)
    return scopes if status == "valid" else None



def check_missing_scopes(
    required_scopes: Sequence[str],
    token_scopes: Sequence[str] | None = None,
) -> list[str]:
    """Returns any required scopes that are not present in the token's granted scopes."""
    if token_scopes is not None:
        granted_set = set(token_scopes)
    else:
        scopes = read_stored_token_scopes()
        granted_set = set(scopes) if scopes is not None else set()
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
    if stored_scopes is not None and scopes:
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
                    if stored_scopes is None:
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
