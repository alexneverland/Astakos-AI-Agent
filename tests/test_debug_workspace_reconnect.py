"""Offline coverage for explicit Google Workspace reconnect from the Debug Dashboard."""

from __future__ import annotations

from pathlib import Path
from urllib.parse import parse_qs, urlparse
from unittest.mock import MagicMock

from fastapi.testclient import TestClient
import pytest

from api.server import LOCAL_TOKEN, server


def _start_debug_workspace_oauth(
    client: TestClient,
) -> str:
    """Start the protected Debug OAuth flow and return its one-time state."""
    headers = {"Authorization": f"Bearer {LOCAL_TOKEN}"}
    start_response = client.get("/api/workspace/oauth/start", headers=headers)

    assert start_response.status_code == 200
    return parse_qs(urlparse(start_response.json()["auth_url"]).query)["state"][0]


def test_debug_workspace_reconnect_completes_the_shared_oauth_flow(
    monkeypatch,
    tmp_path: Path,
) -> None:
    """The Debug button starts a state-protected flow and writes the shared token."""
    import core.workspace_oauth as workspace_oauth

    token_path = tmp_path / "token.json"
    monkeypatch.setattr(workspace_oauth, "get_token_path", lambda: str(token_path))
    workspace_oauth._oauth_states.clear()
    flow_calls: list[dict[str, str]] = []

    class _MockFlow:
        """Offline stand-in for Google's OAuth flow boundary."""

        code_verifier = "pkce-test-verifier"

        def __init__(self) -> None:
            self.credentials = MagicMock()
            self.credentials.to_json.return_value = (
                '{"token":"new","client_id":"cid","client_secret":"secret","refresh_token":"refresh"}'
            )

        def authorization_url(self, **kwargs: str) -> tuple[str, str]:
            state = kwargs["state"]
            return (f"https://accounts.google.com/o/oauth2/auth?state={state}", state)

        def fetch_token(self, code: str) -> None:
            assert code == "authorized-code"

    def _mock_flow_factory(**kwargs: str) -> _MockFlow:
        """Record OAuth flow construction without contacting Google."""
        flow_calls.append(kwargs)
        return _MockFlow()

    monkeypatch.setattr(workspace_oauth, "get_workspace_oauth_flow", _mock_flow_factory)

    client = TestClient(server)
    state = _start_debug_workspace_oauth(client)

    invalid_response = client.get(
        "/api/workspace/oauth/callback?code=authorized-code&state=wrong-state",
    )
    assert invalid_response.status_code == 400

    callback_response = client.get(
        f"/api/workspace/oauth/callback?code=authorized-code&state={state}",
    )

    assert callback_response.status_code == 200
    assert token_path.exists()
    assert "workspace_oauth_complete" in callback_response.text
    assert flow_calls[1]["code_verifier"] == "pkce-test-verifier"


def test_debug_workspace_reconnect_reports_google_code_exchange_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A Google exchange failure is not misreported as a missing client secrets file."""
    import core.workspace_oauth as workspace_oauth

    token_path = tmp_path / "token.json"
    monkeypatch.setattr(workspace_oauth, "get_token_path", lambda: str(token_path))
    workspace_oauth._oauth_states.clear()

    class _FailingFlow:
        """Offline OAuth flow that rejects the one-time authorization code."""

        code_verifier = "pkce-rejected-verifier"
        credentials = MagicMock()

        def authorization_url(self, **kwargs: str) -> tuple[str, str]:
            state = kwargs["state"]
            return (f"https://accounts.google.com/o/oauth2/auth?state={state}", state)

        def fetch_token(self, code: str) -> None:
            assert code == "rejected-code"
            raise RuntimeError("invalid_grant")

    monkeypatch.setattr(
        workspace_oauth,
        "get_workspace_oauth_flow",
        lambda **_kwargs: _FailingFlow(),
    )

    client = TestClient(server)
    state = _start_debug_workspace_oauth(client)
    response = client.get(
        f"/api/workspace/oauth/callback?code=rejected-code&state={state}",
    )

    assert response.status_code == 400
    assert "Google could not complete authorization" in response.text
    assert "client_secrets.json" not in response.text


def test_debug_dashboard_exposes_an_explicit_workspace_reconnect_control() -> None:
    """The dashboard opens a protected consent popup directly from the user click."""
    dashboard_path = Path(__file__).parents[1] / "api" / "debug_dashboard.html"
    dashboard = dashboard_path.read_text(encoding="utf-8")

    assert 'id="workspace-reconnect-btn"' in dashboard
    assert "async function reconnectGoogleWorkspace()" in dashboard
    assert "localStorage.getItem('astakos_token')" in dashboard
    assert "'Authorization': `Bearer ${storedToken}`" in dashboard
    assert "fetch('/api/workspace/oauth/start', {headers})" in dashboard
    assert dashboard.index("window.open(") < dashboard.index("await fetch('/api/workspace/oauth/start'")
    assert "popup.location.replace(payload.auth_url)" in dashboard
    assert "workspace_oauth_complete" in dashboard
