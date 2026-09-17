"""Offline contracts for trusted encrypted Matrix media downloads."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from clients.matrix_media import MatrixMediaAsset, MatrixMediaDownloader


@dataclass
class FakeRoom:
    room_id: str = "!private-room:example.test"
    encrypted: bool = True


@dataclass
class FakeEncryptedImage:
    event_id: str = "$media-1"
    sender: str = "@owner:example.test"
    url: str = "mxc://example.test/image"
    body: str = "../../credentials.json"
    key: dict[str, str] = field(default_factory=lambda: {"k": "secret-key"})
    hashes: dict[str, str] = field(default_factory=lambda: {"sha256": "cipher-hash"})
    iv: str = "initial-vector"
    mimetype: str = "image/png"
    decrypted: bool = True
    source: dict[str, Any] = field(
        default_factory=lambda: {
            "type": "m.room.message",
            "content": {"msgtype": "m.image", "body": "photo.png", "file": {}},
        }
    )


@dataclass
class FakeEncryptedFile(FakeEncryptedImage):
    mimetype: str = "application/pdf"
    source: dict[str, Any] = field(
        default_factory=lambda: {
            "type": "m.room.message",
            "content": {"msgtype": "m.file", "body": "notes.pdf", "file": {}},
        }
    )


@dataclass
class FakeEncryptedAudio(FakeEncryptedImage):
    mimetype: str = "audio/ogg"
    source: dict[str, Any] = field(
        default_factory=lambda: {
            "type": "m.room.message",
            "content": {"msgtype": "m.audio", "body": "voice.ogg", "file": {}},
        }
    )


@dataclass
class FakeDownloadResponse:
    body: bytes


class FakeDownloadError:
    pass


class FakeClient:
    def __init__(self, body: bytes = b"encrypted") -> None:
        self.body = body
        self.downloaded: list[str] = []

    async def download(self, url: str) -> FakeDownloadResponse:
        self.downloaded.append(url)
        return FakeDownloadResponse(self.body)


def _downloader(tmp_path: Path, client: FakeClient, *, max_bytes: int = 20) -> MatrixMediaDownloader:
    return MatrixMediaDownloader(
        client=client,
        allowed_user_id="@owner:example.test",
        allowed_room_id="!private-room:example.test",
        service_user_id="@astakos:example.test",
        storage_dir=tmp_path / "matrix_media",
        max_bytes=max_bytes,
        encrypted_image_type=FakeEncryptedImage,
        encrypted_file_type=FakeEncryptedFile,
        encrypted_audio_type=FakeEncryptedAudio,
        download_error_types=(FakeDownloadError,),
        decryptor=lambda ciphertext, key, digest, iv: b"plain-content",
    )


@pytest.mark.asyncio
async def test_trusted_encrypted_image_is_decrypted_to_safe_local_path(tmp_path) -> None:
    client = FakeClient()
    downloader = _downloader(tmp_path, client)

    asset = await downloader.download(FakeRoom(), FakeEncryptedImage())

    assert asset == MatrixMediaAsset(
        event_id="$media-1",
        kind="image",
        path=asset.path,
        mime_type="image/png",
        original_name="../../credentials.json",
    )
    assert asset.path.parent == (tmp_path / "matrix_media").resolve()
    assert asset.path.suffix == ".png"
    assert "credentials" not in asset.path.name
    assert asset.path.read_bytes() == b"plain-content"
    assert client.downloaded == ["mxc://example.test/image"]

    cached = await downloader.download(FakeRoom(), FakeEncryptedImage())
    assert cached == asset
    assert client.downloaded == ["mxc://example.test/image"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("room", "event"),
    [
        (FakeRoom(room_id="!other:example.test"), FakeEncryptedImage()),
        (FakeRoom(encrypted=False), FakeEncryptedImage()),
        (FakeRoom(), FakeEncryptedImage(decrypted=False)),
        (FakeRoom(), FakeEncryptedImage(sender="@other:example.test")),
        (FakeRoom(), FakeEncryptedImage(sender="@astakos:example.test")),
        (
            FakeRoom(),
            FakeEncryptedImage(
                source={
                    "type": "m.room.message",
                    "content": {"msgtype": "m.file", "body": "mismatch", "file": {}},
                }
            ),
        ),
    ],
)
async def test_untrusted_or_mismatched_media_is_ignored(tmp_path, room, event) -> None:
    client = FakeClient()
    downloader = _downloader(tmp_path, client)

    assert await downloader.download(room, event) is None
    assert client.downloaded == []
    assert not (tmp_path / "matrix_media").exists()


@pytest.mark.asyncio
async def test_plain_media_event_is_not_accepted(tmp_path) -> None:
    @dataclass
    class PlainImage:
        event_id: str = "$plain"
        sender: str = "@owner:example.test"
        decrypted: bool = True
        source: dict[str, Any] = field(
            default_factory=lambda: {
                "type": "m.room.message",
                "content": {"msgtype": "m.image", "url": "mxc://plain"},
            }
        )

    client = FakeClient()
    downloader = _downloader(tmp_path, client)

    assert await downloader.download(FakeRoom(), PlainImage()) is None
    assert client.downloaded == []


@pytest.mark.asyncio
async def test_ciphertext_over_limit_is_rejected_before_decryption_or_write(tmp_path) -> None:
    client = FakeClient(body=b"x" * 21)
    decrypt_calls: list[bytes] = []
    downloader = _downloader(tmp_path, client, max_bytes=20)
    downloader._decryptor = lambda *args: decrypt_calls.append(args[0]) or b"plain"

    with pytest.raises(ValueError, match="20 bytes"):
        await downloader.download(FakeRoom(), FakeEncryptedImage())

    assert decrypt_calls == []
    assert not list((tmp_path / "matrix_media").glob("*"))


@pytest.mark.asyncio
async def test_decryption_failure_leaves_no_partial_file(tmp_path) -> None:
    client = FakeClient()
    downloader = _downloader(tmp_path, client)

    def fail_decryption(*args: Any) -> bytes:
        raise ValueError("integrity mismatch")

    downloader._decryptor = fail_decryption

    with pytest.raises(ValueError, match="integrity mismatch"):
        await downloader.download(FakeRoom(), FakeEncryptedImage())

    assert not list((tmp_path / "matrix_media").glob("*"))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("event", "kind", "suffix"),
    [
        (FakeEncryptedFile(), "file", ".pdf"),
        (FakeEncryptedAudio(), "audio", ".ogg"),
    ],
)
async def test_supported_file_and_audio_types_are_classified(
    tmp_path, event, kind, suffix
) -> None:
    downloader = _downloader(tmp_path, FakeClient())

    asset = await downloader.download(FakeRoom(), event)

    assert asset.kind == kind
    assert asset.path.suffix == suffix
