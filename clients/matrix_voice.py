"""Encrypted Matrix upload and delivery for synthesized voice replies."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

from nio import RoomSendError, UploadError

from core.ai_provider import (
    CapabilityNotSupportedError,
    ProviderAuthError,
    RateLimitError,
    VoiceProviderSetupRequired,
)
from services.voice_output import synthesize_voice_reply


@dataclass(frozen=True)
class MatrixVoiceSendResult:
    """Outcome used by the text transport to decide on safe fallback."""

    sent: bool
    fallback_notice: str | None = None


class MatrixVoiceSender:
    """Synthesize and upload one encrypted MP3 to the configured Matrix room."""

    def __init__(
        self,
        *,
        client: Any,
        room_id: str,
        locale: str,
        synthesizer: Any | None = None,
        upload_error_types: tuple[type, ...] = (UploadError,),
        send_error_types: tuple[type, ...] = (RoomSendError,),
    ) -> None:
        self._client = client
        self._room_id = str(room_id or "").strip()
        self._locale = str(locale or "").strip()
        if not self._room_id or not self._locale:
            raise ValueError("Matrix voice delivery requires room_id and locale")
        self._synthesizer = synthesizer
        self._upload_error_types = upload_error_types
        self._send_error_types = send_error_types

    async def send(self, text: str) -> MatrixVoiceSendResult:
        """Send voice when possible; return an actionable text-fallback result."""
        try:
            audio = await asyncio.to_thread(
                synthesize_voice_reply,
                text,
                locale=self._locale,
                synthesizer=self._synthesizer,
            )
            if not audio:
                return MatrixVoiceSendResult(False, "⚠️ Voice provider produced no audio.")
            response, decryption_info = await self._client.upload(
                lambda _got_429, _got_timeouts: audio,
                content_type="audio/mpeg",
                filename="voice.mp3",
                encrypt=True,
                filesize=len(audio),
            )
            if self._upload_error_types and isinstance(response, self._upload_error_types):
                return MatrixVoiceSendResult(False, "⚠️ Matrix voice upload failed.")
            content_uri = str(getattr(response, "content_uri", "") or "").strip()
            if not content_uri or not isinstance(decryption_info, dict):
                return MatrixVoiceSendResult(False, "⚠️ Matrix voice upload failed.")
            send_response = await self._client.room_send(
                room_id=self._room_id,
                message_type="m.room.message",
                content={
                    "msgtype": "m.audio",
                    "body": "voice.mp3",
                    "file": {
                        **decryption_info,
                        "url": content_uri,
                        "mimetype": "audio/mpeg",
                    },
                    "info": {"mimetype": "audio/mpeg", "size": len(audio)},
                },
            )
            if self._send_error_types and isinstance(send_response, self._send_error_types):
                return MatrixVoiceSendResult(False, "⚠️ Matrix voice delivery failed.")
            return MatrixVoiceSendResult(True)
        except VoiceProviderSetupRequired as exc:
            return MatrixVoiceSendResult(False, f"⚠️ {exc}")
        except ProviderAuthError:
            return MatrixVoiceSendResult(False, "⚠️ Voice synthesis authentication failed. Please verify credentials.")
        except RateLimitError:
            return MatrixVoiceSendResult(False, "⚠️ Voice synthesis quota or rate limit exceeded. Please retry shortly.")
        except CapabilityNotSupportedError:
            return MatrixVoiceSendResult(False, "⚠️ Voice synthesis is not supported by the active provider.")
        except Exception as exc:
            print(f"[MatrixVoice]: delivery failed: {type(exc).__name__}")
            return MatrixVoiceSendResult(False, "⚠️ Voice delivery failed; using text.")
