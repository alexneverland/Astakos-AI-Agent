"""Offline contracts for encrypted generated-file delivery to Matrix."""

from dataclasses import dataclass
from typing import Any

import pytest

from clients.matrix_attachment import MatrixAttachmentSender


@dataclass
class FakeUploadResponse:
    content_uri: str = "mxc://example.test/generated"


class FakeUploadError:
    pass


class FakeSendError:
    pass


class FakeClient:
    def __init__(self) -> None:
        self.uploads: list[dict[str, Any]] = []
        self.sent: list[dict[str, Any]] = []
        self.upload_result: Any = None
        self.send_result: Any = None

    async def upload(self, provider, **kwargs):
        self.uploads.append({"provider": provider, **kwargs})
        assert provider(0, 0) == b"payload"
        if self.upload_result is not None:
            return self.upload_result
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
        return self.send_result if self.send_result is not None else object()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("filename", "expected_type", "expected_mime"),
    [
        ("result.png", "m.image", "image/png"),
        ("report.pdf", "m.file", "application/pdf"),
    ],
)
async def test_generated_file_is_uploaded_encrypted_and_sent(
    tmp_path, filename: str, expected_type: str, expected_mime: str
) -> None:
    outputs = tmp_path / "outputs"
    outputs.mkdir()
    path = outputs / filename
    path.write_bytes(b"payload")
    client = FakeClient()
    sender = MatrixAttachmentSender(
        client=client,
        room_id="!private-room:example.test",
        allowed_root=outputs,
        upload_error_types=(FakeUploadError,),
        send_error_types=(FakeSendError,),
    )

    result = await sender.send(str(path))

    assert result.sent is True
    assert result.retryable is False
    assert client.uploads[0]["encrypt"] is True
    assert client.uploads[0]["content_type"] == expected_mime
    assert client.sent[0]["content"]["msgtype"] == expected_type
    assert client.sent[0]["content"]["body"] == filename
    assert client.sent[0]["content"]["file"]["url"] == "mxc://example.test/generated"


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["outside", "missing", "oversized"])
async def test_unsafe_or_unavailable_generated_file_never_uploads(
    tmp_path, kind: str
) -> None:
    outputs = tmp_path / "outputs"
    outputs.mkdir()
    if kind == "outside":
        path = tmp_path / "secret.txt"
        path.write_bytes(b"payload")
    elif kind == "missing":
        path = outputs / "missing.txt"
    else:
        path = outputs / "large.txt"
        path.write_bytes(b"payload")
    client = FakeClient()
    sender = MatrixAttachmentSender(
        client=client,
        room_id="!private-room:example.test",
        allowed_root=outputs,
        max_bytes=3 if kind == "oversized" else 20 * 1024 * 1024,
        upload_error_types=(FakeUploadError,),
        send_error_types=(FakeSendError,),
    )

    result = await sender.send(str(path))

    assert result.sent is False
    assert result.retryable is False
    assert result.fallback_notice
    assert str(tmp_path) not in result.fallback_notice
    assert client.uploads == []
    assert client.sent == []


@pytest.mark.asyncio
async def test_transient_upload_failure_remains_retryable(tmp_path) -> None:
    outputs = tmp_path / "outputs"
    outputs.mkdir()
    path = outputs / "report.pdf"
    path.write_bytes(b"payload")
    client = FakeClient()
    client.upload_result = (FakeUploadError(), {})
    sender = MatrixAttachmentSender(
        client=client,
        room_id="!private-room:example.test",
        allowed_root=outputs,
        upload_error_types=(FakeUploadError,),
        send_error_types=(FakeSendError,),
    )

    result = await sender.send(str(path))

    assert result.sent is False
    assert result.retryable is True
