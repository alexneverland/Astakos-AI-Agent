"""Offline contracts for encrypted Matrix voice replies."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from clients.matrix_voice import MatrixVoiceSender


@dataclass
class FakeUploadResponse:
    content_uri: str = "mxc://example.test/audio"


class FakeUploadError:
    pass


class FakeSendError:
    pass


class FakeClient:
    def __init__(self) -> None:
        self.uploads: list[dict[str, Any]] = []
        self.sent: list[dict[str, Any]] = []

    async def upload(self, provider, **kwargs):
        self.uploads.append({"provider": provider, **kwargs})
        assert provider(0, 0) == b"mp3-bytes"
        return (
            FakeUploadResponse(),
            {
                "v": "v2",
                "key": {"k": "secret"},
                "iv": "iv",
                "hashes": {"sha256": "hash"},
            },
        )

    async def room_send(self, **kwargs):
        self.sent.append(kwargs)
        return object()


@pytest.mark.asyncio
async def test_voice_reply_is_synthesized_uploaded_encrypted_and_sent() -> None:
    client = FakeClient()
    synthesized: list[tuple[str, str]] = []
    sender = MatrixVoiceSender(
        client=client,
        room_id="!private-room:example.test",
        locale="el",
        synthesizer=lambda text, locale: synthesized.append((text, locale))
        or b"mp3-bytes",
        upload_error_types=(FakeUploadError,),
        send_error_types=(FakeSendError,),
    )

    result = await sender.send("**Καλημέρα**")

    assert result.sent is True
    assert result.fallback_notice is None
    assert synthesized == [("Καλημέρα", "el")]
    assert client.uploads[0]["encrypt"] is True
    assert client.uploads[0]["content_type"] == "audio/mpeg"
    assert client.uploads[0]["filesize"] == len(b"mp3-bytes")
    assert client.sent == [
        {
            "room_id": "!private-room:example.test",
            "message_type": "m.room.message",
            "content": {
                "msgtype": "m.audio",
                "body": "voice.mp3",
                "file": {
                    "v": "v2",
                    "key": {"k": "secret"},
                    "iv": "iv",
                    "hashes": {"sha256": "hash"},
                    "url": "mxc://example.test/audio",
                    "mimetype": "audio/mpeg",
                },
                "info": {"mimetype": "audio/mpeg", "size": len(b"mp3-bytes")},
            },
        }
    ]


@pytest.mark.asyncio
async def test_empty_synthesis_requests_text_fallback() -> None:
    sender = MatrixVoiceSender(
        client=FakeClient(),
        room_id="!private-room:example.test",
        locale="el",
        synthesizer=lambda text, locale: b"",
        upload_error_types=(FakeUploadError,),
        send_error_types=(FakeSendError,),
    )

    result = await sender.send("Απάντηση")

    assert result.sent is False
    assert "no audio" in result.fallback_notice.lower()
