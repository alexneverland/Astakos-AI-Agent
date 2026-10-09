"""OwnTracks-only HTTP surface with independent mandatory authentication."""
from __future__ import annotations

import asyncio
import hashlib
import json
import secrets
import time
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from services.owntracks import OwnTracksStore, default_auth_file, parse_location

MAX_BODY_BYTES = 8192


def build_owntracks_app(*, auth_file: Path | None = None,
                       store: OwnTracksStore | None = None) -> FastAPI:
    """Expose only one POST, with no docs, admin routes or loopback exemption."""
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    basic = HTTPBasic(auto_error=False)

    def authenticate(request: Request,
                     credentials: HTTPBasicCredentials | None = Depends(basic)) -> None:
        """Require the dedicated owner credential and bound phone identifier."""
        try:
            settings = json.loads((auth_file or default_auth_file()).read_text(encoding="utf-8"))
            username, device, verifier = (settings[key] for key in
                                           ("username", "device", "secret_sha256"))
            if (not all(isinstance(value, str) and value for value in (username, device, verifier))
                    or len(verifier) != 64):
                raise ValueError("Invalid verifier")
        except (OSError, ValueError, KeyError, TypeError):
            raise HTTPException(503, "OwnTracks is not configured") from None
        if (credentials is None or len(credentials.password) > 256
                or not secrets.compare_digest(credentials.username.encode(), username.encode())
                or not secrets.compare_digest(hashlib.sha256(credentials.password.encode()).hexdigest(), verifier)):
            raise HTTPException(401, "Unauthorized", headers={"WWW-Authenticate": "Basic"})
        if not secrets.compare_digest(request.headers.get("X-Limit-D", "").encode(), device.encode()):
            raise HTTPException(403, "Unauthorized device")

    @app.post("/")
    async def receive(request: Request, _: None = Depends(authenticate)) -> list:
        """Acknowledge durable intake with the protocol's empty response array."""
        body = bytearray()
        try:
            async with asyncio.timeout(10):
                async for chunk in request.stream():
                    if len(body) + len(chunk) > MAX_BODY_BYTES:
                        raise HTTPException(413, "Payload too large")
                    body.extend(chunk)
        except TimeoutError:
            raise HTTPException(408, "Request timed out") from None
        if not body:
            return []
        try:
            payload = json.loads(body)
            if not isinstance(payload, dict):
                raise ValueError("Invalid object")
            point = parse_location(payload, now_ts=time.time())
        except (ValueError, TypeError, OverflowError):
            raise HTTPException(422, "Invalid location payload") from None
        if point is not None:
            try:
                await asyncio.to_thread((store or OwnTracksStore()).enqueue, point)
            except Exception:
                raise HTTPException(503, "Location intake unavailable") from None
        return []

    return app
