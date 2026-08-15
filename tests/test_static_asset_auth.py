"""Regression tests for authentication of private static asset mounts."""

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from api.server import (
    AuthenticatedStaticFiles,
    LOCAL_TOKEN,
    _extract_token_from_query_and_headers,
    server,
)


def test_shared_token_extraction_prefers_query_token() -> None:
    """Static and WebSocket callers share explicit query-token precedence."""
    assert _extract_token_from_query_and_headers(
        {"token": "query-token"},
        {"authorization": f"Bearer {LOCAL_TOKEN}"},
    ) == "query-token"


@pytest.mark.parametrize("path", ["/photos", "/outputs", "/avatars"])
def test_lan_static_asset_request_without_token_is_rejected(path: str) -> None:
    """Private asset mounts fail closed for a non-loopback client."""
    client = TestClient(server)

    response = client.get(f"{path}/{uuid4().hex}.txt")

    assert response.status_code == 401
    assert response.json() == {"detail": "Unauthorized"}


@pytest.mark.parametrize("auth", ["query", "bearer"])
def test_lan_static_asset_request_with_valid_token_reaches_handler(auth: str) -> None:
    """A LAN request with a valid query or bearer token reaches the static mount."""
    client = TestClient(server)
    missing_asset = f"/outputs/{uuid4().hex}.txt"

    if auth == "query":
        response = client.get(f"{missing_asset}?token={LOCAL_TOKEN}")
    else:
        response = client.get(
            missing_asset,
            headers={"Authorization": f"Bearer {LOCAL_TOKEN}"},
        )

    assert response.status_code == 404


@pytest.mark.parametrize("path", ["/photos", "/outputs", "/avatars"])
def test_lan_static_asset_request_with_invalid_token_is_rejected(path: str) -> None:
    """A guessed query token cannot fetch a private static asset."""
    client = TestClient(server)

    response = client.get(f"{path}/{uuid4().hex}.txt?token=not-the-local-token")

    assert response.status_code == 401
    assert response.json() == {"detail": "Unauthorized"}


@pytest.mark.parametrize(
    ("query_token", "authorization", "expected_status"),
    [
        ("invalid-token", f"Bearer {LOCAL_TOKEN}", 401),
        (LOCAL_TOKEN, "Bearer invalid-token", 404),
    ],
)
def test_static_asset_query_token_has_precedence_over_bearer(
    query_token: str,
    authorization: str,
    expected_status: int,
) -> None:
    """Mixed credentials use the explicit query token, matching image URL behavior."""
    client = TestClient(server)

    response = client.get(
        f"/outputs/{uuid4().hex}.txt?token={query_token}",
        headers={"Authorization": authorization},
    )

    assert response.status_code == expected_status


@pytest.mark.asyncio
async def test_static_asset_request_without_client_scope_fails_closed(tmp_path) -> None:
    """Missing connection data cannot be replaced by a spoofable Host header."""
    static_files = AuthenticatedStaticFiles(directory=tmp_path)
    response = await static_files.get_response("missing.txt", {
        "type": "http",
        "method": "GET",
        "path": "/outputs/missing.txt",
        "root_path": "",
        "headers": [(b"host", b"localhost:8000")],
        "query_string": b"",
    })

    assert response.status_code == 401


def test_loopback_static_asset_request_reaches_handler_without_token() -> None:
    """The local Web UI keeps working without exposing assets on the LAN."""
    client = TestClient(server, client=("127.0.0.1", 50000))

    response = client.get(f"/photos/{uuid4().hex}.txt")

    assert response.status_code == 404
