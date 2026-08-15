"""Regression tests for authentication of private static asset mounts."""

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from api.server import LOCAL_TOKEN, server


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


def test_lan_static_asset_request_with_invalid_token_is_rejected() -> None:
    """A guessed query token cannot fetch a private static asset."""
    client = TestClient(server)

    response = client.get(f"/outputs/{uuid4().hex}.txt?token=not-the-local-token")

    assert response.status_code == 401
    assert response.json() == {"detail": "Unauthorized"}


def test_loopback_static_asset_request_reaches_handler_without_token() -> None:
    """The local Web UI keeps working without exposing assets on the LAN."""
    client = TestClient(server, client=("127.0.0.1", 50000))

    response = client.get(f"/photos/{uuid4().hex}.txt")

    assert response.status_code == 404
