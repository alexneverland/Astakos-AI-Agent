"""Encrypted Matrix delivery for generated Astakos files."""

from __future__ import annotations

import asyncio
import mimetypes
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from nio import RoomSendError, UploadError


@dataclass(frozen=True)
class MatrixAttachmentSendResult:
    """Outcome used by durable transport retry handling."""

    sent: bool
    retryable: bool = False
    fallback_notice: str | None = None


class MatrixAttachmentSender:
    """Validate, encrypt, upload, and send one generated output file."""

    def __init__(
        self,
        *,
        client: Any,
        room_id: str,
        allowed_root: str | Path,
        max_bytes: int = 20 * 1024 * 1024,
        upload_error_types: tuple[type, ...] = (UploadError,),
        send_error_types: tuple[type, ...] = (RoomSendError,),
    ) -> None:
        self._client = client
        self._room_id = str(room_id or "").strip()
        self._allowed_root = Path(allowed_root).resolve()
        self._max_bytes = int(max_bytes)
        if not self._room_id:
            raise ValueError("Matrix attachment delivery requires room_id")
        if self._max_bytes <= 0:
            raise ValueError("Matrix attachment max_bytes must be positive")
        self._upload_error_types = upload_error_types
        self._send_error_types = send_error_types

    @staticmethod
    def _safe_name(path: Path) -> str:
        """Return a bounded printable basename for Matrix metadata and notices."""
        name = "".join(ch for ch in path.name if ch.isprintable()).strip()[:255]
        return name or "generated-file"

    def _validate_path(self, raw_path: str) -> tuple[Path | None, str | None]:
        """Resolve one regular file beneath the approved output root."""
        candidate = Path(str(raw_path or "").strip())
        safe_name = self._safe_name(candidate)
        try:
            resolved = candidate.resolve(strict=True)
            resolved.relative_to(self._allowed_root)
        except (OSError, RuntimeError, ValueError):
            return None, f"⚠️ Generated file is unavailable: {safe_name}"
        if not resolved.is_file():
            return None, f"⚠️ Generated file is unavailable: {safe_name}"
        try:
            size = resolved.stat().st_size
        except OSError:
            return None, f"⚠️ Generated file is unavailable: {safe_name}"
        if size > self._max_bytes:
            return None, f"⚠️ Generated file is too large to send: {safe_name}"
        return resolved, None

    async def send(self, raw_path: str) -> MatrixAttachmentSendResult:
        """Send one approved file, distinguishing permanent from retryable failure."""
        path, validation_notice = self._validate_path(raw_path)
        if path is None:
            return MatrixAttachmentSendResult(
                sent=False,
                retryable=False,
                fallback_notice=validation_notice,
            )

        name = self._safe_name(path)
        mime_type = mimetypes.guess_type(name)[0] or "application/octet-stream"
        try:
            payload = await asyncio.to_thread(path.read_bytes)
            response, decryption_info = await self._client.upload(
                lambda _got_429, _got_timeouts: payload,
                content_type=mime_type,
                filename=name,
                encrypt=True,
                filesize=len(payload),
            )
            if self._upload_error_types and isinstance(response, self._upload_error_types):
                return MatrixAttachmentSendResult(sent=False, retryable=True)
            content_uri = str(getattr(response, "content_uri", "") or "").strip()
            if not content_uri or not isinstance(decryption_info, dict):
                return MatrixAttachmentSendResult(sent=False, retryable=True)
            send_response = await self._client.room_send(
                room_id=self._room_id,
                message_type="m.room.message",
                content={
                    "msgtype": "m.image" if mime_type.startswith("image/") else "m.file",
                    "body": name,
                    "file": {
                        **decryption_info,
                        "url": content_uri,
                        "mimetype": mime_type,
                    },
                    "info": {"mimetype": mime_type, "size": len(payload)},
                },
            )
            if self._send_error_types and isinstance(send_response, self._send_error_types):
                return MatrixAttachmentSendResult(sent=False, retryable=True)
            return MatrixAttachmentSendResult(sent=True)
        except OSError:
            return MatrixAttachmentSendResult(
                sent=False,
                retryable=False,
                fallback_notice=f"⚠️ Generated file is unavailable: {name}",
            )
        except Exception as exc:
            print(f"[MatrixAttachment]: delivery failed: {type(exc).__name__}")
            return MatrixAttachmentSendResult(sent=False, retryable=True)
