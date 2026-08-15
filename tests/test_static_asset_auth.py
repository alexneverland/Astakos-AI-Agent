"""Regression tests for authentication of private static asset mounts."""

from urllib.parse import parse_qs, urlparse
from uuid import uuid4

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from api.server import (
    ASSET_TOKEN_TTL_SECONDS,
    AuthenticatedStaticFiles,
    LOCAL_TOKEN,
    _create_asset_access_token,
    _private_asset_url,
    _extract_token_from_query_and_headers,
    _validate_asset_access_token,
    server,
)


def test_shared_token_extraction_prefers_query_token() -> None:
    """Static and WebSocket callers share explicit query-token precedence."""
    assert _extract_token_from_query_and_headers(
        {"token": "query-token"},
        {"authorization": f"Bearer {LOCAL_TOKEN}"},
    ) == "query-token"


def _build_request(client_host: str) -> Request:
    """Build a minimal HTTP request with an explicit client address."""
    return Request({
        "type": "http",
        "scheme": "http",
        "server": ("astakos.local", 8000),
        "path": "/chat",
        "raw_path": b"/chat",
        "query_string": b"",
        "headers": [(b"host", b"astakos.local:8000")],
        "client": (client_host, 50000),
    })


def test_lan_generated_asset_url_includes_scoped_asset_token() -> None:
    """A browser loading a LAN image receives no master bearer credential."""
    asset_url = _private_asset_url(
        _build_request("192.168.1.100"),
        "outputs",
        "generated image.png",
    )

    parsed = urlparse(asset_url)
    assert parsed.netloc == ""
    assert parsed.path == "/outputs/generated%20image.png"
    asset_token = parse_qs(parsed.query)["asset_token"][0]
    assert asset_token != LOCAL_TOKEN
    assert _validate_asset_access_token(asset_token, parsed.path)


def test_loopback_generated_asset_url_has_no_token() -> None:
    """The native local UI does not need token-bearing image URLs."""
    asset_url = _private_asset_url(
        _build_request("127.0.0.1"),
        "photos",
        "uploaded.png",
    )

    assert urlparse(asset_url).query == ""


@pytest.mark.parametrize("path", ["/photos", "/outputs", "/avatars"])
def test_lan_static_asset_request_without_token_is_rejected(path: str) -> None:
    """Private asset mounts fail closed for a non-loopback client."""
    client = TestClient(server)

    response = client.get(f"{path}/{uuid4().hex}.txt")

    assert response.status_code == 401
    assert response.json() == {"detail": "Unauthorized"}


@pytest.mark.parametrize("auth", ["asset_query", "bearer"])
def test_lan_static_asset_request_with_valid_token_reaches_handler(auth: str) -> None:
    """A LAN request with a valid scoped token or bearer reaches the static mount."""
    client = TestClient(server)
    missing_asset = f"/outputs/{uuid4().hex}.txt"

    if auth == "asset_query":
        asset_token = _create_asset_access_token(missing_asset)
        response = client.get(f"{missing_asset}?asset_token={asset_token}")
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

    response = client.get(f"{path}/{uuid4().hex}.txt?asset_token=not-a-valid-asset-token")

    assert response.status_code == 401
    assert response.json() == {"detail": "Unauthorized"}


@pytest.mark.parametrize(
    ("asset_token", "authorization", "expected_status"),
    [
        ("invalid-token", f"Bearer {LOCAL_TOKEN}", 401),
    ],
)
def test_static_asset_token_has_precedence_over_bearer(
    asset_token: str,
    authorization: str,
    expected_status: int,
) -> None:
    """An explicit invalid asset token cannot fall back to a master bearer."""
    client = TestClient(server)

    response = client.get(
        f"/outputs/{uuid4().hex}.txt?asset_token={asset_token}",
        headers={"Authorization": authorization},
    )

    assert response.status_code == expected_status


def test_valid_asset_token_has_precedence_over_invalid_bearer() -> None:
    """A valid scoped URL remains usable when a stale bearer is also present."""
    client = TestClient(server)
    missing_asset = f"/outputs/{uuid4().hex}.txt"

    response = client.get(
        f"{missing_asset}?asset_token={_create_asset_access_token(missing_asset)}",
        headers={"Authorization": "Bearer invalid-token"},
    )

    assert response.status_code == 404


def test_master_token_query_cannot_authenticate_static_asset() -> None:
    """The master bearer credential is never accepted in a serializable URL."""
    client = TestClient(server)

    response = client.get(f"/outputs/{uuid4().hex}.txt?token={LOCAL_TOKEN}")

    assert response.status_code == 401


def test_asset_token_is_path_scoped_and_short_lived() -> None:
    """A URL token cannot be reused for another file or after its expiry."""
    asset_path = "/outputs/private.png"
    issued_at = 1_000
    asset_token = _create_asset_access_token(asset_path, now=issued_at)

    assert _validate_asset_access_token(asset_token, asset_path, now=issued_at + 1)
    assert not _validate_asset_access_token(asset_token, "/photos/private.png", now=issued_at + 1)
    assert not _validate_asset_access_token(
        asset_token,
        asset_path,
        now=issued_at + ASSET_TOKEN_TTL_SECONDS + 1,
    )


def test_scoped_asset_token_serves_its_encoded_file_path(tmp_path) -> None:
    """A generated URL can retrieve exactly its URL-encoded asset on the LAN."""
    asset_name = "generated image.txt"
    (tmp_path / asset_name).write_text("private asset", encoding="utf-8")
    app = FastAPI()
    app.mount(
        "/outputs",
        AuthenticatedStaticFiles(directory=str(tmp_path), mount_path="outputs"),
    )
    client = TestClient(app)
    asset_path = "/outputs/generated%20image.txt"

    response = client.get(
        f"{asset_path}?asset_token={_create_asset_access_token(asset_path)}",
    )

    assert response.status_code == 200
    assert response.text == "private asset"


@pytest.mark.asyncio
async def test_static_asset_request_without_client_scope_fails_closed(tmp_path) -> None:
    """Missing connection data cannot be replaced by a spoofable Host header."""
    static_files = AuthenticatedStaticFiles(directory=str(tmp_path), mount_path="outputs")
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
