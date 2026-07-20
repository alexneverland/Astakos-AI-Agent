from unittest.mock import MagicMock

import pytest
from google.auth.exceptions import RefreshError

import tools.system as system


@pytest.mark.parametrize(
    "refresh_error",
    (
        "invalid_grant: Token has been revoked.",
        "invalid_scope: Requested scopes are invalid or missing.",
    ),
)
def test_get_gmail_service_reauthorizes_after_recoverable_refresh_error(
    monkeypatch,
    tmp_path,
    refresh_error,
):
    token_path = tmp_path / "token.json"
    token_path.write_text("stale-token", encoding="utf-8")
    credentials_path = tmp_path / "credentials.json"
    credentials_path.write_text("{}", encoding="utf-8")

    stale_creds = MagicMock(valid=False, expired=True, refresh_token="revoked")
    stale_creds.refresh.side_effect = RefreshError(refresh_error)

    fresh_creds = MagicMock(valid=True)
    fresh_creds.to_json.return_value = "fresh-token"

    flow = MagicMock()
    flow.run_local_server.return_value = fresh_creds

    monkeypatch.setattr(system, "TOKEN_PATH", str(token_path))
    monkeypatch.setattr(system, "CREDS_PATH", str(credentials_path))
    monkeypatch.setattr(
        system.Credentials,
        "from_authorized_user_file",
        lambda *_args: stale_creds,
    )
    monkeypatch.setattr(
        system.InstalledAppFlow,
        "from_client_secrets_file",
        lambda *_args: flow,
    )
    build_mock = MagicMock(return_value="gmail-service")
    monkeypatch.setattr(system, "build", build_mock)

    assert system.get_gmail_service() == "gmail-service"
    flow.run_local_server.assert_called_once_with(
        port=0,
        prompt="consent",
        access_type="offline",
    )
    assert token_path.read_text(encoding="utf-8") == "fresh-token"
