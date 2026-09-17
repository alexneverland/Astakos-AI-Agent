"""Safe local download boundary for encrypted Matrix media events."""

from __future__ import annotations

import hashlib
import mimetypes
import os
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from nio import RoomEncryptedAudio, RoomEncryptedFile, RoomEncryptedImage
from nio.crypto.attachments import decrypt_attachment
from nio.responses import DownloadError


@dataclass(frozen=True)
class MatrixMediaAsset:
    """One validated and decrypted Matrix attachment stored locally."""

    event_id: str
    kind: str
    path: Path
    mime_type: str
    original_name: str


class MatrixMediaDownloader:
    """Accept only trusted encrypted media from the configured private room."""

    def __init__(
        self,
        *,
        client: Any,
        allowed_user_id: str,
        allowed_room_id: str,
        service_user_id: str,
        storage_dir: str | os.PathLike[str],
        max_bytes: int = 20 * 1024 * 1024,
        encrypted_image_type: type = RoomEncryptedImage,
        encrypted_file_type: type = RoomEncryptedFile,
        encrypted_audio_type: type = RoomEncryptedAudio,
        download_error_types: tuple[type, ...] = (DownloadError,),
        decryptor: Callable[[bytes, str, str, str], bytes] = decrypt_attachment,
    ) -> None:
        self._client = client
        self._allowed_user_id = self._required_id(allowed_user_id, "allowed_user_id")
        self._allowed_room_id = self._required_id(allowed_room_id, "allowed_room_id")
        self._service_user_id = self._required_id(service_user_id, "service_user_id")
        self._storage_dir = Path(storage_dir).resolve()
        if max_bytes <= 0:
            raise ValueError("Matrix media max_bytes must be positive")
        self._max_bytes = int(max_bytes)
        self._encrypted_image_type = encrypted_image_type
        self._encrypted_file_type = encrypted_file_type
        self._encrypted_audio_type = encrypted_audio_type
        self._download_error_types = download_error_types
        self._decryptor = decryptor

    @staticmethod
    def _required_id(value: str, field: str) -> str:
        normalized = str(value or "").strip()
        if not normalized:
            raise ValueError(f"Matrix media requires {field}")
        return normalized

    def _trusted_media(self, room: Any, event: Any) -> tuple[str, str] | None:
        """Return ``(kind, msgtype)`` for an accepted encrypted media event."""
        if str(getattr(room, "room_id", "")) != self._allowed_room_id:
            return None
        if getattr(room, "encrypted", False) is not True:
            return None
        if getattr(event, "decrypted", False) is not True:
            return None

        sender = str(getattr(event, "sender", ""))
        if sender != self._allowed_user_id or sender == self._service_user_id:
            return None

        expected: tuple[str, str] | None = None
        # Keep the more specific injected test types ahead of their base type.
        if isinstance(event, self._encrypted_file_type):
            expected = ("file", "m.file")
        elif isinstance(event, self._encrypted_audio_type):
            expected = ("audio", "m.audio")
        elif isinstance(event, self._encrypted_image_type):
            expected = ("image", "m.image")
        if expected is None:
            return None

        source = getattr(event, "source", None)
        if not isinstance(source, dict) or source.get("type") != "m.room.message":
            return None
        content = source.get("content")
        if not isinstance(content, dict) or content.get("msgtype") != expected[1]:
            return None
        if not isinstance(content.get("file"), dict):
            return None

        event_id = str(getattr(event, "event_id", "") or "").strip()
        url = str(getattr(event, "url", "") or "").strip()
        key = getattr(event, "key", None)
        hashes = getattr(event, "hashes", None)
        iv = str(getattr(event, "iv", "") or "").strip()
        if (
            not event_id
            or not url.startswith("mxc://")
            or not isinstance(key, dict)
            or not str(key.get("k") or "").strip()
            or not isinstance(hashes, dict)
            or not str(hashes.get("sha256") or "").strip()
            or not iv
        ):
            return None
        return expected

    @staticmethod
    def _safe_extension(mime_type: str) -> str:
        """Derive an extension from trusted media metadata, never the body path."""
        normalized = str(mime_type or "application/octet-stream").split(";", 1)[0]
        normalized = normalized.strip().lower() or "application/octet-stream"
        return mimetypes.guess_extension(normalized, strict=False) or ".bin"

    def _target_path(self, event: Any, mime_type: str) -> Path:
        digest = hashlib.sha256(
            f"{event.event_id}\0{event.url}".encode("utf-8")
        ).hexdigest()
        return self._storage_dir / f"matrix_{digest}{self._safe_extension(mime_type)}"

    async def download(self, room: Any, event: Any) -> MatrixMediaAsset | None:
        """Download, authenticate, decrypt, and atomically store one attachment."""
        trusted = self._trusted_media(room, event)
        if trusted is None:
            return None
        kind, _ = trusted

        mime_type = (
            str(getattr(event, "mimetype", "") or "").split(";", 1)[0].strip().lower()
            or "application/octet-stream"
        )
        target = self._target_path(event, mime_type)
        original_name = str(getattr(event, "body", "") or "")
        if target.is_file() and target.stat().st_size <= self._max_bytes:
            return MatrixMediaAsset(
                event_id=str(event.event_id).strip(),
                kind=kind,
                path=target,
                mime_type=mime_type,
                original_name=original_name,
            )

        response = await self._client.download(str(event.url))
        if self._download_error_types and isinstance(response, self._download_error_types):
            raise RuntimeError("Matrix media download failed")
        ciphertext = getattr(response, "body", None)
        if not isinstance(ciphertext, bytes):
            raise RuntimeError("Matrix media download returned no byte payload")
        if len(ciphertext) > self._max_bytes:
            raise ValueError(
                f"Matrix media exceeds the {self._max_bytes} bytes limit"
            )

        plaintext = self._decryptor(
            ciphertext,
            str(event.key["k"]),
            str(event.hashes["sha256"]),
            str(event.iv),
        )
        if not isinstance(plaintext, bytes):
            raise RuntimeError("Matrix media decryptor returned no byte payload")
        if len(plaintext) > self._max_bytes:
            raise ValueError(
                f"Matrix media exceeds the {self._max_bytes} bytes limit"
            )

        self._storage_dir.mkdir(parents=True, exist_ok=True)
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb",
                dir=self._storage_dir,
                prefix=".matrix-",
                suffix=".part",
                delete=False,
            ) as temporary:
                temporary.write(plaintext)
                temporary_path = Path(temporary.name)
            os.replace(temporary_path, target)
            temporary_path = None
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)

        return MatrixMediaAsset(
            event_id=str(event.event_id).strip(),
            kind=kind,
            path=target,
            mime_type=mime_type,
            original_name=original_name,
        )
