"""Tests for API authentication, Host-header spoofing defenses, and fail-closed Docker gateway verification in require_token."""

from typing import Any, Dict
import pytest
from fastapi import HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials

from api.server import require_token, LOCAL_TOKEN


def _build_mock_request(
    client_host: str,
    headers: Dict[str, str] | None = None,
    include_client: bool = True,
) -> Request:
    """Construct a mock request, optionally without client connection data."""
    raw_headers = []
    if headers:
        for k, v in headers.items():
            raw_headers.append((k.lower().encode("latin-1"), v.encode("latin-1")))

    scope: Dict[str, Any] = {
        "type": "http",
        "method": "POST",
        "path": "/protected",
        "headers": raw_headers,
    }
    if include_client:
        scope["client"] = (client_host, 54321)
    return Request(scope=scope)


@pytest.mark.asyncio
async def test_loopback_ipv4_allowed_without_token(monkeypatch: pytest.MonkeyPatch) -> None:
    """Proves that local loopback IPv4 requests are permitted without a bearer token on native host."""
    monkeypatch.delenv("ASTAKOS_CONTAINER", raising=False)
    req = _build_mock_request("127.0.0.1")
    await require_token(req, credentials=None)


@pytest.mark.asyncio
async def test_loopback_ipv6_allowed_without_token(monkeypatch: pytest.MonkeyPatch) -> None:
    """Proves that local loopback IPv6 requests are permitted without a bearer token on native host."""
    monkeypatch.delenv("ASTAKOS_CONTAINER", raising=False)
    req = _build_mock_request("::1")
    await require_token(req, credentials=None)


@pytest.mark.asyncio
async def test_loopback_localhost_named_allowed_without_token(monkeypatch: pytest.MonkeyPatch) -> None:
    """Proves that named localhost is permitted without a bearer token."""
    monkeypatch.delenv("ASTAKOS_CONTAINER", raising=False)
    req_localhost = _build_mock_request("localhost")
    await require_token(req_localhost, credentials=None)


@pytest.mark.asyncio
async def test_missing_client_requires_bearer_token(monkeypatch: pytest.MonkeyPatch) -> None:
    """Proves that missing connection data fails closed without a bearer token."""
    monkeypatch.delenv("ASTAKOS_CONTAINER", raising=False)
    req = _build_mock_request("127.0.0.1", include_client=False)

    with pytest.raises(HTTPException) as exc_info:
        await require_token(req, credentials=None)

    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == "Unauthorized"


@pytest.mark.asyncio
async def test_lan_private_ip_with_spoofed_localhost_host_header_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    """Proves that a LAN client spoofing 'Host: localhost:8000' is rejected with 401."""
    monkeypatch.delenv("ASTAKOS_CONTAINER", raising=False)
    req = _build_mock_request(
        client_host="192.168.1.50",
        headers={"Host": "localhost:8000"},
    )
    with pytest.raises(HTTPException) as exc_info:
        await require_token(req, credentials=None)
    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == "Unauthorized"


@pytest.mark.asyncio
async def test_lan_private_ip_with_spoofed_127_host_header_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    """Proves that a LAN client spoofing 'Host: 127.0.0.1:8000' is rejected with 401."""
    monkeypatch.delenv("ASTAKOS_CONTAINER", raising=False)
    req = _build_mock_request(
        client_host="10.0.0.15",
        headers={"Host": "127.0.0.1:8000"},
    )
    with pytest.raises(HTTPException) as exc_info:
        await require_token(req, credentials=None)
    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == "Unauthorized"


@pytest.mark.asyncio
async def test_lan_private_ip_with_valid_bearer_token_allowed(monkeypatch: pytest.MonkeyPatch) -> None:
    """Proves that a LAN client presenting the valid local bearer token is permitted."""
    monkeypatch.delenv("ASTAKOS_CONTAINER", raising=False)
    req = _build_mock_request(
        client_host="192.168.1.50",
        headers={"Authorization": f"Bearer {LOCAL_TOKEN}"},
    )
    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=LOCAL_TOKEN)
    await require_token(req, credentials=credentials)


@pytest.mark.asyncio
async def test_lan_private_ip_with_invalid_bearer_token_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    """Proves that a LAN client with an invalid bearer token is rejected with 401."""
    monkeypatch.delenv("ASTAKOS_CONTAINER", raising=False)
    req = _build_mock_request(
        client_host="192.168.1.50",
        headers={"Authorization": "Bearer invalid_token_xyz"},
    )
    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="invalid_token_xyz")
    with pytest.raises(HTTPException) as exc_info:
        await require_token(req, credentials=credentials)
    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == "Unauthorized"


@pytest.mark.asyncio
async def test_public_ip_without_token_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    """Proves that a public IP client without a token is rejected with 401."""
    monkeypatch.delenv("ASTAKOS_CONTAINER", raising=False)
    req = _build_mock_request("203.0.113.195")
    with pytest.raises(HTTPException) as exc_info:
        await require_token(req, credentials=None)
    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == "Unauthorized"


# ────────────────────────────────────────────────────────────────
# DOCKER GATEWAY VERIFICATION & FAIL-CLOSED TESTS
# ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_docker_container_verified_default_gateway_allowed_without_token(monkeypatch: pytest.MonkeyPatch) -> None:
    """Proves that in container mode, only the verified default gateway from route table is permitted without token."""
    monkeypatch.setenv("ASTAKOS_CONTAINER", "1")
    monkeypatch.setattr("api.server._get_default_gateway_linux", lambda: "172.18.0.1")

    req = _build_mock_request("172.18.0.1")
    # Should not raise HTTPException
    await require_token(req, credentials=None)


@pytest.mark.asyncio
async def test_docker_container_non_default_docker_subnet_addresses_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    """Proves that non-default 172.16.0.0/12 addresses (even ending in .1 or .254) are rejected when they do not match the verified gateway."""
    monkeypatch.setenv("ASTAKOS_CONTAINER", "1")
    monkeypatch.setattr("api.server._get_default_gateway_linux", lambda: "172.18.0.1")

    # 172.29.12.1 is in 172.16.0.0/12 and ends in .1, but is not the container's gateway
    req_other_subnet = _build_mock_request("172.29.12.1")
    with pytest.raises(HTTPException) as exc_info:
        await require_token(req_other_subnet, credentials=None)
    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == "Unauthorized"

    # 172.17.0.1 (default docker0 bridge) is not the verified gateway (172.18.0.1)
    req_other_bridge = _build_mock_request("172.17.0.1")
    with pytest.raises(HTTPException) as exc_info:
        await require_token(req_other_bridge, credentials=None)
    assert exc_info.value.status_code == 401

    # 172.18.0.254 is not the verified gateway
    req_suffix_254 = _build_mock_request("172.18.0.254")
    with pytest.raises(HTTPException) as exc_info:
        await require_token(req_suffix_254, credentials=None)
    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_docker_desktop_verified_gateway_allowed_without_token(monkeypatch: pytest.MonkeyPatch) -> None:
    """Proves that Docker Desktop gateway (192.168.65.1) is permitted when verified as the container's default gateway."""
    monkeypatch.setenv("ASTAKOS_CONTAINER", "1")
    monkeypatch.setattr("api.server._get_default_gateway_linux", lambda: "192.168.65.1")

    req = _build_mock_request("192.168.65.1")
    # Should not raise HTTPException
    await require_token(req, credentials=None)


@pytest.mark.asyncio
async def test_docker_container_indeterminate_gateway_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    """Proves that when the gateway cannot be determined (_get_default_gateway_linux returns None), access fails closed."""
    monkeypatch.setenv("ASTAKOS_CONTAINER", "1")
    monkeypatch.setattr("api.server._get_default_gateway_linux", lambda: None)

    req_candidate = _build_mock_request("172.18.0.1")
    with pytest.raises(HTTPException) as exc_info:
        await require_token(req_candidate, credentials=None)
    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == "Unauthorized"


@pytest.mark.asyncio
async def test_docker_container_rejects_arbitrary_lan_client_with_spoofed_host(monkeypatch: pytest.MonkeyPatch) -> None:
    """Proves that in container mode, arbitrary LAN IPs (192.168.1.50) with spoofed Host headers are rejected."""
    monkeypatch.setenv("ASTAKOS_CONTAINER", "1")
    monkeypatch.setattr("api.server._get_default_gateway_linux", lambda: "172.18.0.1")

    req = _build_mock_request(
        client_host="192.168.1.50",
        headers={"Host": "localhost:8000"},
    )
    with pytest.raises(HTTPException) as exc_info:
        await require_token(req, credentials=None)
    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == "Unauthorized"


@pytest.mark.asyncio
async def test_non_container_rejects_docker_subnet_ips_without_token(monkeypatch: pytest.MonkeyPatch) -> None:
    """Proves that when NOT in container mode, 172.18.0.1 is treated as external and requires a token."""
    monkeypatch.delenv("ASTAKOS_CONTAINER", raising=False)
    monkeypatch.setattr("api.server._get_default_gateway_linux", lambda: "172.18.0.1")

    req = _build_mock_request("172.18.0.1")
    with pytest.raises(HTTPException) as exc_info:
        await require_token(req, credentials=None)
    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == "Unauthorized"
