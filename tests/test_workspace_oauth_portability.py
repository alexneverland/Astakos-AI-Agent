# ================================================================
# Project: Astakos AI Agent 🦞
# Description: Modular LLM-agnostic multi-agent framework
# Module: Tests for Google Workspace OAuth Portability & Offline Safety
# Copyright (c) 2026 - All Rights Reserved
# ================================================================

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from google.auth.exceptions import RefreshError
from google.oauth2.credentials import Credentials

from astakos_skills import daily_backup, gcalendar, google_fit
from core.workspace_oauth import (
    DEFAULT_WORKSPACE_SCOPES,
    WorkspaceAuthError,
    WorkspaceMissingCredentialsError,
    WorkspaceMissingOAuthClientSecretsError,
    WorkspaceMissingScopeError,
    WorkspaceTokenRevokedOrInvalidError,
    authorize_workspace_oauth,
    check_missing_scopes,
    get_oauth_client_secrets_path,
    is_workspace_connected,
    load_workspace_credentials,
    read_stored_token_scopes,
)
from tools import gdrive, system


@pytest.fixture(autouse=True)
def guard_outbound_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Safety guard ensuring that no test in this module can make real HTTP/network calls,
    send Telegram approval messages, or launch browser OAuth flows.
    """
    def _fail_outbound(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("Unexpected outbound network or Telegram call in offline test suite!")

    # Guard Telegram approval and notification paths
    monkeypatch.setattr("core.approval._notify_telegram", _fail_outbound, raising=False)
    monkeypatch.setattr("core.approval._notify_telegram_notify", _fail_outbound, raising=False)
    monkeypatch.setattr("core.approval.save_pending", _fail_outbound, raising=False)

    # Guard OAuth local server browser flow
    monkeypatch.setattr(
        "google_auth_oauthlib.flow.InstalledAppFlow.run_local_server",
        _fail_outbound,
        raising=False,
    )

    # Guard real Google Auth HTTP transport
    monkeypatch.setattr(
        "google.auth.transport.requests.Request.__call__",
        _fail_outbound,
        raising=False,
    )

    # Guard real Google API Client HTTP execution
    monkeypatch.setattr(
        "googleapiclient.http.HttpRequest.execute",
        _fail_outbound,
        raising=False,
    )

    # Guard requests HTTP transport
    monkeypatch.setattr("requests.sessions.Session.request", _fail_outbound, raising=False)
    monkeypatch.setattr("requests.request", _fail_outbound, raising=False)

    # Guard httplib2 HTTP transport
    monkeypatch.setattr("httplib2.Http.request", _fail_outbound, raising=False)


def _create_mock_creds(
    valid: bool = True,
    expired: bool = False,
    refresh_token: str | None = None,
    scopes: list[str] | None = None,
) -> MagicMock:
    """Helper to construct a typed MagicMock of google.oauth2.credentials.Credentials."""
    creds = MagicMock(spec=Credentials)
    creds.valid = valid
    creds.expired = expired
    creds.refresh_token = refresh_token
    creds.scopes = scopes or list(DEFAULT_WORKSPACE_SCOPES)
    creds.to_json.return_value = json.dumps({
        "token": "fake-token",
        "refresh_token": refresh_token,
        "scopes": creds.scopes,
    })
    return creds


def test_outbound_safety_guard_blocks_unexpected_telegram_calls() -> None:
    """Proves the safety guard raises RuntimeError if an unexpected Telegram notification is attempted."""
    from core.approval import _notify_telegram

    with pytest.raises(RuntimeError) as exc_info:
        _notify_telegram({"name": "write_custom_tool", "id": "tc-test", "args": {}})

    assert "Unexpected outbound network or Telegram call" in str(exc_info.value)


def test_outbound_safety_guard_blocks_live_http_calls() -> None:
    """Proves the safety guard raises RuntimeError if an unmocked Google HTTP transport call is attempted."""
    from google.auth.transport.requests import Request

    req = Request()
    with pytest.raises(RuntimeError) as exc_info:
        req("https://oauth2.googleapis.com/token", "POST")

    assert "Unexpected outbound network or Telegram call" in str(exc_info.value)


def test_outbound_safety_guard_blocks_generic_http_transports() -> None:
    """Proves the safety guard blocks generic requests and httplib2 HTTP calls."""
    import httplib2
    import requests

    with pytest.raises(RuntimeError) as exc_info_requests:
        requests.get("https://example.com")
    assert "Unexpected outbound network or Telegram call" in str(exc_info_requests.value)

    with pytest.raises(RuntimeError) as exc_info_session:
        requests.Session().request("GET", "https://example.com")
    assert "Unexpected outbound network or Telegram call" in str(exc_info_session.value)

    with pytest.raises(RuntimeError) as exc_info_httplib2:
        httplib2.Http().request("https://example.com")
    assert "Unexpected outbound network or Telegram call" in str(exc_info_httplib2.value)


def test_is_workspace_connected_when_token_present_and_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    token_file = tmp_path / "token.json"
    monkeypatch.setattr("core.workspace_oauth.get_token_path", lambda: str(token_file))

    assert not is_workspace_connected()

    token_file.write_text("{}", encoding="utf-8")
    assert is_workspace_connected()


def test_load_workspace_credentials_missing_token_raises_clean_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    non_existent = tmp_path / "missing_token.json"
    monkeypatch.setattr("core.workspace_oauth.get_token_path", lambda: str(non_existent))

    with pytest.raises(WorkspaceMissingCredentialsError) as exc_info:
        load_workspace_credentials()

    assert "Google Workspace is not connected" in str(exc_info.value)


def test_load_workspace_credentials_isolated_from_adc_and_vertex(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Proves Workspace credentials load from user token.json and NEVER touch google.auth.default / ADC."""
    token_file = tmp_path / "token.json"
    token_file.write_text(json.dumps({"token": "user-oauth-token", "scopes": DEFAULT_WORKSPACE_SCOPES}), encoding="utf-8")

    monkeypatch.setattr("core.workspace_oauth.get_token_path", lambda: str(token_file))
    monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", "vertex_service_account.json")

    mock_creds = _create_mock_creds(valid=True)
    with patch("google.oauth2.credentials.Credentials.from_authorized_user_file", return_value=mock_creds) as mock_loader, \
         patch("google.auth.default", side_effect=RuntimeError("ADC must not be called")) as mock_adc:
        creds = load_workspace_credentials()
        assert creds == mock_creds
        mock_loader.assert_called_once()
        mock_adc.assert_not_called()


def test_load_workspace_credentials_refresh_revoked_raises_actionable_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    token_file = tmp_path / "token.json"
    token_file.write_text(json.dumps({
        "token": "expired-token",
        "refresh_token": "refresh-tok",
        "scopes": DEFAULT_WORKSPACE_SCOPES,
    }), encoding="utf-8")
    monkeypatch.setattr("core.workspace_oauth.get_token_path", lambda: str(token_file))

    mock_creds = _create_mock_creds(valid=False, expired=True, refresh_token="refresh-tok")
    mock_creds.refresh.side_effect = RefreshError("invalid_grant: Token has been revoked.")

    with patch("google.oauth2.credentials.Credentials.from_authorized_user_file", return_value=mock_creds):
        with pytest.raises(WorkspaceTokenRevokedOrInvalidError) as exc_info:
            load_workspace_credentials()

        assert "reconnect your Google" in str(exc_info.value) or "expired or revoked" in str(exc_info.value)


def test_load_workspace_credentials_preserves_granted_scopes_and_never_expands_on_refresh(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Proves that an existing token with a legacy scope set (missing fitness.body.read)
    refreshes using only its granted scopes, never requests fitness.body.read, and
    persists the original granted scope set unchanged.
    """
    legacy_scopes = [
        "https://www.googleapis.com/auth/gmail.modify",
        "https://www.googleapis.com/auth/drive",
        "https://www.googleapis.com/auth/calendar",
        "https://www.googleapis.com/auth/tasks",
        "https://www.googleapis.com/auth/fitness.activity.read",
    ]
    token_file = tmp_path / "token.json"
    token_file.write_text(json.dumps({
        "token": "expired-legacy-token",
        "refresh_token": "legacy-refresh",
        "scopes": legacy_scopes,
    }), encoding="utf-8")
    monkeypatch.setattr("core.workspace_oauth.get_token_path", lambda: str(token_file))

    requested_loader_scopes: list[list[str]] = []

    def _mock_from_authorized_user_file(path: str, scopes: list[str] | None = None) -> MagicMock:
        requested_loader_scopes.append(scopes or [])
        creds = _create_mock_creds(valid=False, expired=True, refresh_token="legacy-refresh", scopes=scopes)

        def _do_refresh(request: Any) -> None:
            creds.valid = True
            creds.expired = False
            # When creds.to_json() is called, it should retain the granted legacy scopes
            creds.to_json.return_value = json.dumps({
                "token": "fresh-token",
                "refresh_token": "legacy-refresh",
                "scopes": creds.scopes,
            })
        creds.refresh.side_effect = _do_refresh
        return creds

    with patch("google.oauth2.credentials.Credentials.from_authorized_user_file", side_effect=_mock_from_authorized_user_file):
        # Caller requests Calendar
        creds = load_workspace_credentials(scopes=["https://www.googleapis.com/auth/calendar"], auto_refresh=True)
        assert creds.valid

        # 1. Verify loader requested ONLY the granted legacy scopes, not the new fitness.body.read
        assert requested_loader_scopes
        assert requested_loader_scopes[0] == legacy_scopes
        assert "https://www.googleapis.com/auth/fitness.body.read" not in requested_loader_scopes[0]

        # 2. Verify persisted token retains the original granted scopes unchanged
        saved_data = json.loads(token_file.read_text(encoding="utf-8"))
        assert saved_data.get("scopes") == legacy_scopes
        assert "https://www.googleapis.com/auth/fitness.body.read" not in saved_data.get("scopes", [])


def test_feature_requiring_missing_scope_raises_workspace_missing_scope_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Proves that requesting credentials with a scope not in the token raises WorkspaceMissingScopeError."""
    token_file = tmp_path / "token.json"
    token_file.write_text(json.dumps({
        "token": "valid-token",
        "scopes": ["https://www.googleapis.com/auth/drive"],
    }), encoding="utf-8")
    monkeypatch.setattr("core.workspace_oauth.get_token_path", lambda: str(token_file))

    with pytest.raises(WorkspaceMissingScopeError) as exc_info:
        load_workspace_credentials(scopes=["https://www.googleapis.com/auth/fitness.body.read"])

    assert "lacks required permissions" in str(exc_info.value)
    assert "fitness.body.read" in str(exc_info.value)


def test_read_stored_token_scopes_supports_string_and_list(tmp_path: Path) -> None:
    """Proves read_stored_token_scopes parses both list format and space-separated string format."""
    p1 = tmp_path / "token_list.json"
    p1.write_text(json.dumps({"scopes": ["https://a", "https://b"]}), encoding="utf-8")
    assert read_stored_token_scopes(str(p1)) == ["https://a", "https://b"]

    p2 = tmp_path / "token_str.json"
    p2.write_text(json.dumps({"scope": "https://a https://b"}), encoding="utf-8")
    assert read_stored_token_scopes(str(p2)) == ["https://a", "https://b"]


def test_load_workspace_credentials_without_stored_scopes_loads_caller_requested_scopes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Proves that when a legacy token.json lacks embedded scope metadata (neither 'scopes' nor 'scope'),
    load_workspace_credentials loads credentials using caller-requested scopes without raising
    WorkspaceMissingScopeError.
    """
    token_file = tmp_path / "token.json"
    token_file.write_text(json.dumps({
        "token": "legacy-token-no-scopes",
        "refresh_token": "legacy-refresh",
    }), encoding="utf-8")
    monkeypatch.setattr("core.workspace_oauth.get_token_path", lambda: str(token_file))

    requested_loader_scopes: list[list[str] | None] = []

    def _mock_from_authorized_user_file(path: str, scopes: list[str] | None = None) -> MagicMock:
        requested_loader_scopes.append(scopes)
        return _create_mock_creds(valid=True, scopes=scopes)

    with patch("google.oauth2.credentials.Credentials.from_authorized_user_file", side_effect=_mock_from_authorized_user_file):
        creds = load_workspace_credentials(scopes=["https://www.googleapis.com/auth/calendar"])
        assert creds.valid
        assert requested_loader_scopes == [["https://www.googleapis.com/auth/calendar"]]



def test_authorize_workspace_oauth_uses_client_secrets_path_and_never_vertex_credentials(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Proves that authorize_workspace_oauth uses the dedicated client_secrets.json,
    never touches credentials.json / Vertex service account, and writes resulting token.
    """
    client_secrets_file = tmp_path / "client_secrets.json"
    client_secrets_file.write_text(json.dumps({"installed": {"client_id": "cid"}}), encoding="utf-8")
    token_file = tmp_path / "token.json"

    monkeypatch.setattr("core.workspace_oauth.get_token_path", lambda: str(token_file))
    monkeypatch.setattr("core.workspace_oauth.get_oauth_client_secrets_path", lambda: str(client_secrets_file))
    monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", "vertex_service_account.json")

    mock_flow = MagicMock()
    mock_flow_creds = _create_mock_creds(valid=True)
    mock_flow.run_local_server.return_value = mock_flow_creds

    with patch("google_auth_oauthlib.flow.InstalledAppFlow.from_client_secrets_file", return_value=mock_flow) as mock_from_secrets:
        msg = authorize_workspace_oauth()
        assert msg == "Google Workspace authorization successful."
        assert str(token_file) not in msg
        assert token_file.name not in msg
        mock_from_secrets.assert_called_once_with(str(client_secrets_file), list(DEFAULT_WORKSPACE_SCOPES))
        assert token_file.exists()



def test_authorize_workspace_oauth_requests_full_default_scopes_and_caller_extras(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Proves that new explicit consent flow always includes all DEFAULT_WORKSPACE_SCOPES
    plus any extra scopes requested by callers (like Fit), deterministically deduplicated.
    """
    client_secrets_file = tmp_path / "client_secrets.json"
    client_secrets_file.write_text(json.dumps({"installed": {"client_id": "cid"}}), encoding="utf-8")
    token_file = tmp_path / "token.json"

    monkeypatch.setattr("core.workspace_oauth.get_token_path", lambda: str(token_file))
    monkeypatch.setattr("core.workspace_oauth.get_oauth_client_secrets_path", lambda: str(client_secrets_file))

    mock_flow = MagicMock()
    mock_flow_creds = _create_mock_creds(valid=True)
    mock_flow.run_local_server.return_value = mock_flow_creds

    with patch("google_auth_oauthlib.flow.InstalledAppFlow.from_client_secrets_file", return_value=mock_flow) as mock_from_secrets:
        extra_scope = "https://www.googleapis.com/auth/custom.extra.scope"
        authorize_workspace_oauth(scopes=[extra_scope, "https://www.googleapis.com/auth/drive"])

        assert mock_from_secrets.call_count == 1
        call_scopes = mock_from_secrets.call_args[0][1]
        for default_scope in DEFAULT_WORKSPACE_SCOPES:
            assert default_scope in call_scopes
        assert extra_scope in call_scopes
        assert call_scopes.count("https://www.googleapis.com/auth/drive") == 1


def test_authorize_workspace_oauth_missing_client_secrets_fails_cleanly(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    non_existent = tmp_path / "missing_client_secrets.json"
    monkeypatch.setattr("core.workspace_oauth.get_oauth_client_secrets_path", lambda: str(non_existent))

    with pytest.raises(WorkspaceMissingOAuthClientSecretsError) as exc_info:
        authorize_workspace_oauth()

    assert "client secrets file not found" in str(exc_info.value)



def test_authorize_google_fit_delegates_to_authorize_workspace_oauth(monkeypatch: pytest.MonkeyPatch) -> None:
    """Proves google_fit.authorize_google_fit delegates to the shared authorize_workspace_oauth."""
    mock_authorize = MagicMock(return_value="Auth success")
    monkeypatch.setattr("core.workspace_oauth.authorize_workspace_oauth", mock_authorize)

    res = google_fit.authorize_google_fit()
    assert res == "Auth success"
    mock_authorize.assert_called_once_with(scopes=google_fit.SCOPES)


def test_gmail_and_fit_use_shared_workspace_loader(monkeypatch: pytest.MonkeyPatch) -> None:
    """Proves Gmail and Google Fit use the centralized load_workspace_credentials loader."""
    mock_creds = _create_mock_creds(valid=True)
    loaded_scopes: list[list[str] | None] = []

    def _mock_load(scopes: list[str] | None = None, **kwargs: Any) -> MagicMock:
        loaded_scopes.append(scopes)
        return mock_creds

    monkeypatch.setattr("core.workspace_oauth.load_workspace_credentials", _mock_load)
    monkeypatch.setattr("astakos_skills.google_fit._ensure_fit_token_scopes", lambda: None)

    # 1. Fit credentials
    fit_creds = google_fit._get_credentials()
    assert fit_creds == mock_creds
    assert any("fitness.activity.read" in s for s in (loaded_scopes[-1] or []))

    # 2. Gmail service
    mock_build = MagicMock(return_value="gmail_service_obj")
    with patch("core.workspace_oauth.build", mock_build):
        svc = system.get_gmail_service()
        assert svc == "gmail_service_obj"
        assert any("gmail.modify" in s for s in (loaded_scopes[-1] or []))


def test_gdrive_upload_to_drive_degrades_gracefully_when_unauthenticated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    non_existent = tmp_path / "missing_token.json"
    monkeypatch.setattr("core.workspace_oauth.get_token_path", lambda: str(non_existent))

    dummy_file = tmp_path / "test.txt"
    dummy_file.write_text("hello", encoding="utf-8")

    result = gdrive.upload_to_drive(str(dummy_file))
    assert result == ""


def test_drive_manager_missing_credentials_returns_clean_message(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    non_existent = tmp_path / "missing_token.json"
    monkeypatch.setattr("core.workspace_oauth.get_token_path", lambda: str(non_existent))

    msg = system.drive_manager.invoke({"action": "list_files"})
    assert "Google Workspace is not connected" in msg


def test_drive_manager_defaults_to_root_even_if_backup_folder_set(monkeypatch: pytest.MonkeyPatch) -> None:
    """Proves drive_manager defaults to root My Drive and ignores BACKUP_DRIVE_FOLDER_ID for generic browsing/upload/create."""
    mock_creds = _create_mock_creds(valid=True)
    monkeypatch.setattr("core.workspace_oauth.load_workspace_credentials", lambda **kwargs: mock_creds)
    monkeypatch.setattr("config.BACKUP_DRIVE_FOLDER_ID", "dedicated_backup_folder_999")

    mock_service = MagicMock()
    mock_list = MagicMock()
    mock_list.execute.return_value = {"files": [{"id": "123", "name": "sample.pdf", "size": "1024", "modifiedTime": "2026-08-01"}]}
    mock_service.files().list.return_value = mock_list

    mock_create = MagicMock()
    mock_create.execute.return_value = {"id": "new_file_id", "name": "new_item"}
    mock_service.files().create.return_value = mock_create

    with patch("tools.system.build", return_value=mock_service):
        # 1. list_files targets root
        res = system.drive_manager.invoke({"action": "list_files"})
        assert "sample.pdf" in res
        list_kwargs = mock_service.files().list.call_args[1]
        assert "'root' in parents" in list_kwargs.get("q", "")
        assert "dedicated_backup_folder_999" not in list_kwargs.get("q", "")

        # 2. create_folder targets root (no parents)
        system.drive_manager.invoke({"action": "create_folder", "new_name": "My Notes"})
        create_kwargs = mock_service.files().create.call_args[1]
        assert "parents" not in create_kwargs.get("body", {})


def test_drive_manager_respects_explicit_folder_override(monkeypatch: pytest.MonkeyPatch) -> None:
    mock_creds = _create_mock_creds(valid=True)
    monkeypatch.setattr("core.workspace_oauth.load_workspace_credentials", lambda **kwargs: mock_creds)

    mock_service = MagicMock()
    mock_list = MagicMock()
    mock_list.execute.return_value = {"files": []}
    mock_service.files().list.return_value = mock_list

    with patch("tools.system.build", return_value=mock_service):
        system.drive_manager.invoke({"action": "list_files", "folder_id": "custom_folder_abc"})
        call_kwargs = mock_service.files().list.call_args[1]
        assert "'custom_folder_abc' in parents" in call_kwargs.get("q", "")


def test_google_tasks_tool_missing_credentials_returns_clean_message(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    non_existent = tmp_path / "missing_token.json"
    monkeypatch.setattr("core.workspace_oauth.get_token_path", lambda: str(non_existent))

    msg = system.google_tasks_tool.invoke({"action": "list"})
    assert "Google Workspace is not connected" in msg


def test_daily_backup_to_drive_unauthenticated_returns_fail_string(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    non_existent = tmp_path / "missing_token.json"
    monkeypatch.setattr("core.workspace_oauth.get_token_path", lambda: str(non_existent))

    result = daily_backup.daily_backup_to_drive()
    assert result is not None


def test_daily_backup_authenticate_google_drive_success_and_scope(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Proves authenticate_google_drive loads credentials successfully using the defined Drive scope."""
    token_file = tmp_path / "token.json"
    token_file.write_text(json.dumps({
        "token": "valid-token",
        "scopes": ["https://www.googleapis.com/auth/drive"],
    }), encoding="utf-8")
    monkeypatch.setattr("core.workspace_oauth.get_token_path", lambda: str(token_file))

    mock_creds = _create_mock_creds(valid=True, scopes=["https://www.googleapis.com/auth/drive"])
    with patch("google.oauth2.credentials.Credentials.from_authorized_user_file", return_value=mock_creds):
        creds = daily_backup.authenticate_google_drive()
        assert creds == mock_creds
        assert "https://www.googleapis.com/auth/drive" in daily_backup.SCOPES



def test_daily_backup_root_lookup_consistency(monkeypatch: pytest.MonkeyPatch) -> None:
    """Proves that when BACKUP_DRIVE_FOLDER_ID is empty or 'root', query uses 'root' in parents."""
    mock_creds = _create_mock_creds(valid=True)
    monkeypatch.setattr("astakos_skills.daily_backup.authenticate_google_drive", lambda: mock_creds)

    # 1. When BACKUP_DRIVE_FOLDER_ID is empty string
    monkeypatch.setattr("config.BACKUP_DRIVE_FOLDER_ID", "")
    mock_service = MagicMock()
    mock_list = MagicMock()
    mock_list.execute.return_value = {"files": []}
    mock_service.files().list.return_value = mock_list

    mock_create = MagicMock()
    mock_create.execute.return_value = {"id": "new_root_backup_id", "name": "astakos_v2_backup_today"}
    mock_service.files().create.return_value = mock_create

    with patch("astakos_skills.daily_backup.build", return_value=mock_service), \
         patch("astakos_skills.daily_backup.upload_folder_recursive", return_value=["item1"]):
        daily_backup.daily_backup_to_drive()
        list_kwargs = mock_service.files().list.call_args[1]
        assert "'root' in parents" in list_kwargs.get("q", "")
        create_kwargs = mock_service.files().create.call_args[1]
        assert "parents" not in create_kwargs.get("body", {})

    # 2. When BACKUP_DRIVE_FOLDER_ID is explicitly "root"
    monkeypatch.setattr("config.BACKUP_DRIVE_FOLDER_ID", "root")
    with patch("astakos_skills.daily_backup.build", return_value=mock_service), \
         patch("astakos_skills.daily_backup.upload_folder_recursive", return_value=["item1"]):
        daily_backup.daily_backup_to_drive()
        list_kwargs = mock_service.files().list.call_args[1]
        assert "'root' in parents" in list_kwargs.get("q", "")
        create_kwargs = mock_service.files().create.call_args[1]
        assert "parents" not in create_kwargs.get("body", {})


def test_daily_backup_uses_explicit_backup_folder_setting_when_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    mock_creds = _create_mock_creds(valid=True)
    monkeypatch.setattr("astakos_skills.daily_backup.authenticate_google_drive", lambda: mock_creds)
    monkeypatch.setattr("config.BACKUP_DRIVE_FOLDER_ID", "configured_backup_folder_777")

    mock_service = MagicMock()
    mock_list = MagicMock()
    mock_list.execute.return_value = {"files": []}
    mock_service.files().list.return_value = mock_list

    mock_create = MagicMock()
    mock_create.execute.return_value = {"id": "created_folder_id", "name": "astakos_v2_backup_today"}
    mock_service.files().create.return_value = mock_create

    with patch("astakos_skills.daily_backup.build", return_value=mock_service), \
         patch("astakos_skills.daily_backup.upload_folder_recursive", return_value=["item1"]):
        daily_backup.daily_backup_to_drive()
        list_kwargs = mock_service.files().list.call_args[1]
        assert "'configured_backup_folder_777' in parents" in list_kwargs.get("q", "")
        create_kwargs = mock_service.files().create.call_args[1]
        assert create_kwargs.get("body", {}).get("parents") == ["configured_backup_folder_777"]


def test_daily_backup_excludes_all_secret_layouts(tmp_path: Path) -> None:
    """
    Proves that .env, all .env.* variants, credentials/, root-level credentials.json,
    root-level token.json, root-level .astakos_token, and root-level client_secrets.json
    are all excluded from backup, while permitted project files are uploaded.
    """
    root = tmp_path / "project_root"
    root.mkdir()

    # 1. Sensitive files at root
    (root / ".env").write_text("SECRET=1\n", encoding="utf-8")
    (root / ".env.local").write_text("SECRET=2\n", encoding="utf-8")
    (root / ".env.production").write_text("SECRET=3\n", encoding="utf-8")
    (root / "credentials.json").write_text("{}", encoding="utf-8")
    (root / "token.json").write_text("{}", encoding="utf-8")
    (root / ".astakos_token").write_text("tok", encoding="utf-8")
    (root / "client_secrets.json").write_text("{}", encoding="utf-8")

    # 2. Sensitive directory
    creds_dir = root / "credentials"
    creds_dir.mkdir()
    (creds_dir / "service_account.json").write_text("{}", encoding="utf-8")

    venv_dir = root / "venv"
    venv_dir.mkdir()
    (venv_dir / "lib.py").write_text("# venv code", encoding="utf-8")

    dot_venv_dir = root / ".venv"
    dot_venv_dir.mkdir()
    (dot_venv_dir / "lib2.py").write_text("# .venv code", encoding="utf-8")

    # 3. Permitted files that SHOULD be uploaded
    main_py = root / "main.py"
    main_py.write_text("# project entry", encoding="utf-8")

    src_dir = root / "src"
    src_dir.mkdir()
    utils_py = src_dir / "utils.py"
    utils_py.write_text("# utils code", encoding="utf-8")

    uploaded_files: list[str] = []
    created_folders: list[str] = []

    mock_service = MagicMock()

    def _mock_create(body: dict[str, Any], **kwargs: Any) -> MagicMock:
        req = MagicMock()
        name = body.get("name", "")
        if body.get("mimeType") == "application/vnd.google-apps.folder":
            created_folders.append(name)
            req.execute.return_value = {"id": f"folder_id_{name}", "name": name}
        else:
            uploaded_files.append(name)
            req.execute.return_value = {"id": f"file_id_{name}", "name": name}
        return req

    mock_service.files().create.side_effect = _mock_create

    daily_backup.upload_folder_recursive(
        mock_service,
        str(root),
        "drive_backup_parent_id",
        daily_backup.BACKUP_EXCLUDE_ITEMS,
    )

    # 1. Permitted files were uploaded
    assert "main.py" in uploaded_files
    assert "utils.py" in uploaded_files
    assert "src" in created_folders

    # 2. All secret files and directories were skipped
    assert ".env" not in uploaded_files
    assert ".env.local" not in uploaded_files
    assert ".env.production" not in uploaded_files
    assert "credentials.json" not in uploaded_files
    assert "token.json" not in uploaded_files
    assert ".astakos_token" not in uploaded_files
    assert "client_secrets.json" not in uploaded_files
    assert "credentials" not in created_folders
    assert "service_account.json" not in uploaded_files
    assert "venv" not in created_folders
    assert ".venv" not in created_folders
    assert "lib.py" not in uploaded_files
    assert "lib2.py" not in uploaded_files


def test_daily_backup_rejects_symlinks_pointing_to_secrets_or_outside_tree(tmp_path: Path) -> None:
    """Proves that symlinks to .env or outside files are skipped before reading or uploading."""
    root = tmp_path / "backup_root"
    root.mkdir()

    # Secret file outside or inside
    secret_target = root / ".env"
    secret_target.write_text("SECRET_OAUTH=xyz", encoding="utf-8")

    # Permitted real file
    real_file = root / "app.py"
    real_file.write_text("# real app", encoding="utf-8")

    # Symlink with innocent name pointing to secret target
    innocent_link = root / "safe_notes.txt"
    try:
        os.symlink(str(secret_target), str(innocent_link))
        symlink_created = True
    except OSError:
        symlink_created = False

    uploaded_files: list[str] = []
    mock_service = MagicMock()

    def _mock_create(body: dict[str, Any], **kwargs: Any) -> MagicMock:
        req = MagicMock()
        name = body.get("name", "")
        uploaded_files.append(name)
        req.execute.return_value = {"id": f"file_id_{name}", "name": name}
        return req

    mock_service.files().create.side_effect = _mock_create

    daily_backup.upload_folder_recursive(
        mock_service,
        str(root),
        "drive_backup_parent_id",
        daily_backup.BACKUP_EXCLUDE_ITEMS,
    )

    assert "app.py" in uploaded_files
    assert ".env" not in uploaded_files
    if symlink_created:
        assert "safe_notes.txt" not in uploaded_files



def test_gcalendar_tool_missing_credentials_returns_error_message(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    non_existent = tmp_path / "missing_token.json"
    monkeypatch.setattr("core.workspace_oauth.get_token_path", lambda: str(non_existent))

    res = gcalendar.google_calendar_tool.invoke({"action": "list"})
    assert "Google Workspace" in res or "token.json" in res


def test_mail_manager_missing_credentials_returns_clean_message(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    non_existent_token = tmp_path / "missing_token.json"
    monkeypatch.setattr("core.workspace_oauth.get_token_path", lambda: str(non_existent_token))

    res = system.mail_manager.invoke({"action": "search", "query": "test"})
    assert "Google Workspace is not connected" in res


def test_google_fit_missing_credentials_handled_cleanly(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    non_existent_token = tmp_path / "missing_token.json"
    monkeypatch.setattr("core.workspace_oauth.get_token_path", lambda: str(non_existent_token))

    summary = google_fit.get_morning_summary()
    assert summary is not None
    assert "Google Fit auth" in summary
