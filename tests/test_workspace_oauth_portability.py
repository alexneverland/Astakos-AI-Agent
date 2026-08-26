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
    WorkspaceAuthError,
    WorkspaceMissingCredentialsError,
    WorkspaceTokenRevokedOrInvalidError,
    is_workspace_connected,
    load_workspace_credentials,
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


def _create_mock_creds(valid: bool = True, expired: bool = False, refresh_token: str | None = None) -> MagicMock:
    """Helper to construct a typed MagicMock of google.oauth2.credentials.Credentials."""
    creds = MagicMock(spec=Credentials)
    creds.valid = valid
    creds.expired = expired
    creds.refresh_token = refresh_token
    creds.to_json.return_value = json.dumps({"token": "fake-token", "refresh_token": refresh_token})
    return creds


def test_outbound_safety_guard_blocks_unexpected_telegram_calls() -> None:
    """Proves the safety guard raises RuntimeError if an unexpected Telegram notification is attempted."""
    from core.approval import _notify_telegram

    with pytest.raises(RuntimeError) as exc_info:
        _notify_telegram({"name": "write_custom_tool", "id": "tc-test", "args": {}})

    assert "Unexpected outbound network or Telegram call" in str(exc_info.value)


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
    token_file.write_text(json.dumps({"token": "user-oauth-token"}), encoding="utf-8")

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
    token_file.write_text(json.dumps({"token": "expired-token", "refresh_token": "refresh-tok"}), encoding="utf-8")
    monkeypatch.setattr("core.workspace_oauth.get_token_path", lambda: str(token_file))

    mock_creds = _create_mock_creds(valid=False, expired=True, refresh_token="refresh-tok")
    mock_creds.refresh.side_effect = RefreshError("invalid_grant: Token has been revoked.")

    with patch("google.oauth2.credentials.Credentials.from_authorized_user_file", return_value=mock_creds):
        with pytest.raises(WorkspaceTokenRevokedOrInvalidError) as exc_info:
            load_workspace_credentials()

        assert "reconnect your Google" in str(exc_info.value) or "expired or revoked" in str(exc_info.value)


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


def test_daily_backup_defaults_to_root_when_backup_folder_not_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    mock_creds = _create_mock_creds(valid=True)
    monkeypatch.setattr("astakos_skills.daily_backup.authenticate_google_drive", lambda: mock_creds)
    monkeypatch.setattr("config.BACKUP_DRIVE_FOLDER_ID", "")

    mock_service = MagicMock()
    mock_list = MagicMock()
    mock_list.execute.return_value = {"files": []}
    mock_service.files().list.return_value = mock_list

    mock_create = MagicMock()
    mock_create.execute.return_value = {"id": "new_created_backup_folder_id", "name": "astakos_v2_backup_today"}
    mock_service.files().create.return_value = mock_create

    with patch("astakos_skills.daily_backup.build", return_value=mock_service), \
         patch("astakos_skills.daily_backup.upload_folder_recursive", return_value=["item1"]):
        res = daily_backup.daily_backup_to_drive()
        assert "astakos_v2_backup" in res
        # Verify query does NOT contain broken "'' in parents"
        list_kwargs = mock_service.files().list.call_args[1]
        assert "'' in parents" not in list_kwargs.get("q", "")
        # Verify folder metadata does not have parents=['']
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
        # Verify query contains configured_backup_folder_777
        list_kwargs = mock_service.files().list.call_args[1]
        assert "'configured_backup_folder_777' in parents" in list_kwargs.get("q", "")
        # Verify folder metadata has parents=['configured_backup_folder_777']
        create_kwargs = mock_service.files().create.call_args[1]
        assert create_kwargs.get("body", {}).get("parents") == ["configured_backup_folder_777"]


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
