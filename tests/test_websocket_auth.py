"""Tests for /ws/logs WebSocket authentication and authorization."""

from collections.abc import Iterator
from typing import Any
from unittest.mock import AsyncMock, MagicMock
import pytest
from starlette.websockets import WebSocketDisconnect
from starlette import status
from fastapi.testclient import TestClient

from api.server import server, LOCAL_TOKEN, require_ws_token, active_websockets


@pytest.fixture(autouse=True)
def _reset_active_websockets() -> Iterator[None]:
    """Isolate process-wide WebSocket state across authentication tests."""
    active_websockets.clear()
    try:
        yield
    finally:
        active_websockets.clear()


def _build_mock_websocket(
    client_host: str,
    query_params: dict[str, str] | None = None,
    headers: dict[str, str] | None = None,
) -> MagicMock:
    """Constructs a mock WebSocket object with host, query parameters, and headers."""
    ws = MagicMock()
    ws.client.host = client_host
    ws.query_params = query_params or {}
    ws.headers = headers or {}
    ws.close = AsyncMock()
    ws.accept = AsyncMock()
    return ws


# ────────────────────────────────────────────────────────────────
# UNIT TESTS: require_ws_token dependency
# ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_websocket_loopback_allowed_without_token(monkeypatch: pytest.MonkeyPatch) -> None:
    """Proves that native loopback connections (127.0.0.1, ::1, localhost) are permitted without requiring a token."""
    monkeypatch.delenv("ASTAKOS_CONTAINER", raising=False)
    for host in ("127.0.0.1", "::1", "localhost"):
        ws = _build_mock_websocket(client_host=host)
        allowed = await require_ws_token(ws)
        assert allowed is True
        assert not ws.close.called


@pytest.mark.asyncio
async def test_websocket_lan_client_without_token_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    """Proves that LAN clients connecting without a token are closed with WS_1008_POLICY_VIOLATION."""
    monkeypatch.delenv("ASTAKOS_CONTAINER", raising=False)
    ws = _build_mock_websocket(client_host="192.168.1.100")

    allowed = await require_ws_token(ws)
    assert allowed is False
    ws.close.assert_awaited_once_with(
        code=status.WS_1008_POLICY_VIOLATION,
        reason="Unauthorized",
    )


@pytest.mark.asyncio
async def test_websocket_lan_client_with_valid_query_token_allowed(monkeypatch: pytest.MonkeyPatch) -> None:
    """Proves that LAN clients providing valid token in query param (?token=...) are accepted."""
    monkeypatch.delenv("ASTAKOS_CONTAINER", raising=False)
    ws = _build_mock_websocket(
        client_host="192.168.1.100",
        query_params={"token": LOCAL_TOKEN},
    )

    allowed = await require_ws_token(ws)
    assert allowed is True
    assert not ws.close.called


@pytest.mark.asyncio
async def test_websocket_lan_client_with_invalid_query_token_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    """Proves that LAN clients with an invalid query token are rejected."""
    monkeypatch.delenv("ASTAKOS_CONTAINER", raising=False)
    ws = _build_mock_websocket(
        client_host="192.168.1.100",
        query_params={"token": "wrong_secret_token"},
    )

    allowed = await require_ws_token(ws)
    assert allowed is False
    ws.close.assert_awaited_once_with(
        code=status.WS_1008_POLICY_VIOLATION,
        reason="Unauthorized",
    )


@pytest.mark.asyncio
async def test_websocket_lan_client_with_valid_bearer_header_allowed(monkeypatch: pytest.MonkeyPatch) -> None:
    """Proves that clients providing valid Authorization header are accepted."""
    monkeypatch.delenv("ASTAKOS_CONTAINER", raising=False)
    ws = _build_mock_websocket(
        client_host="192.168.1.100",
        headers={"authorization": f"Bearer {LOCAL_TOKEN}"},
    )

    allowed = await require_ws_token(ws)
    assert allowed is True
    assert not ws.close.called


@pytest.mark.asyncio
async def test_websocket_docker_gateway_allowed_without_token(monkeypatch: pytest.MonkeyPatch) -> None:
    """Proves that in container mode, only the verified container gateway is permitted without token."""
    monkeypatch.setenv("ASTAKOS_CONTAINER", "1")
    monkeypatch.setattr("api.server._get_default_gateway_linux", lambda: "172.18.0.1")

    ws = _build_mock_websocket(client_host="172.18.0.1")
    allowed = await require_ws_token(ws)
    assert allowed is True
    assert not ws.close.called


@pytest.mark.asyncio
async def test_websocket_docker_non_default_address_rejected_without_token(monkeypatch: pytest.MonkeyPatch) -> None:
    """Proves that non-gateway docker subnet IPs are rejected without a valid token."""
    monkeypatch.setenv("ASTAKOS_CONTAINER", "1")
    monkeypatch.setattr("api.server._get_default_gateway_linux", lambda: "172.18.0.1")

    ws = _build_mock_websocket(client_host="172.29.12.1")
    allowed = await require_ws_token(ws)
    assert allowed is False
    ws.close.assert_awaited_once_with(
        code=status.WS_1008_POLICY_VIOLATION,
        reason="Unauthorized",
    )


# ────────────────────────────────────────────────────────────────
# END-TO-END INTEGRATION TESTS: TestClient /ws/logs Endpoint
# ────────────────────────────────────────────────────────────────

def test_websocket_logs_e2e_authenticated_with_query_token_succeeds() -> None:
    """Proves that a client authenticating with valid ?token= query parameter connects and registers in active_websockets."""
    client = TestClient(server)
    with client.websocket_connect(f"/ws/logs?token={LOCAL_TOKEN}") as websocket:
        assert len(active_websockets) >= 1
    # After exit, socket should be cleaned up
    assert len(active_websockets) == 0


def test_websocket_logs_e2e_no_token_rejected() -> None:
    """Proves that a non-loopback TestClient connection without a token is rejected with policy violation (1008)."""
    client = TestClient(server)
    with pytest.raises(WebSocketDisconnect) as exc_info:
        with client.websocket_connect("/ws/logs"):
            pass
    assert exc_info.value.code == status.WS_1008_POLICY_VIOLATION
    assert len(active_websockets) == 0


def test_websocket_logs_e2e_invalid_token_rejected() -> None:
    """Proves that a connection with an invalid ?token= query parameter is rejected with policy violation (1008)."""
    client = TestClient(server)
    with pytest.raises(WebSocketDisconnect) as exc_info:
        with client.websocket_connect("/ws/logs?token=invalid_untrusted_token_123"):
            pass
    assert exc_info.value.code == status.WS_1008_POLICY_VIOLATION
    assert len(active_websockets) == 0
