"""Application processing for locally decrypted Matrix media assets."""

from __future__ import annotations

import asyncio
import threading
import time
from collections.abc import Awaitable, Callable

from clients.matrix_media import MatrixMediaAsset
from core.ai_provider import (
    CapabilityNotSupportedError,
    AIProviderError,
    ProviderAuthError,
    RateLimitError,
    VoiceProviderSetupRequired,
)
from services.voice_input import transcribe_voice_audio
from services.image_input import analyze_image_bytes

MatrixTurn = Callable[[str, str], Awaitable[str]]
AudioTranscriber = Callable[..., str]
ImageAnalyzer = Callable[..., str]
AssetQuestionTurn = Callable[..., Awaitable[str]]
DocumentTurn = Callable[[MatrixMediaAsset], Awaitable[str]]
PendingAssetConfirmation = Callable[[str, str], Awaitable[str | None]]
PhotoCommandProcessor = Callable[[str], str]


class MatrixMediaTurnService:
    """Route one downloaded Matrix asset into its shared application pipeline."""

    def __init__(
        self,
        *,
        matrix_turn: MatrixTurn,
        silence_reply: str,
        transcribe_audio: AudioTranscriber = transcribe_voice_audio,
        analyze_image: ImageAnalyzer | None = None,
        vision_prompt: str | None = None,
        default_photo_question: str | None = None,
        asset_question_turn: AssetQuestionTurn | None = None,
        pending_photo_ttl_seconds: float = 30.0,
        clock: Callable[[], float] = time.monotonic,
        document_turn: DocumentTurn | None = None,
        analyze_nutrition: PhotoCommandProcessor | None = None,
        scan_receipt: PhotoCommandProcessor | None = None,
        missing_nutrition_photo_reply: str | None = None,
        missing_receipt_photo_reply: str | None = None,
    ) -> None:
        normalized_silence_reply = str(silence_reply or "").strip()
        if not normalized_silence_reply:
            raise ValueError("Matrix media requires a non-empty silence reply")
        self._matrix_turn = matrix_turn
        self._silence_reply = normalized_silence_reply
        self._transcribe_audio = transcribe_audio
        image_config = (
            analyze_image,
            str(vision_prompt or "").strip() or None,
            str(default_photo_question or "").strip() or None,
            asset_question_turn,
        )
        if any(value is not None for value in image_config) and not all(
            value is not None for value in image_config
        ):
            raise ValueError("Matrix image processing requires complete configuration")
        if pending_photo_ttl_seconds <= 0:
            raise ValueError("Matrix pending photo TTL must be positive")
        self._analyze_image = analyze_image
        self._vision_prompt = image_config[1]
        self._default_photo_question = image_config[2]
        self._asset_question_turn = asset_question_turn
        self._pending_photo_ttl_seconds = float(pending_photo_ttl_seconds)
        self._clock = clock
        self._pending_photo_lock = threading.Lock()
        self._pending_photo: tuple[MatrixMediaAsset, str, float] | None = None
        self._document_turn = document_turn
        photo_command_config = (
            analyze_nutrition,
            scan_receipt,
            str(missing_nutrition_photo_reply or "").strip() or None,
            str(missing_receipt_photo_reply or "").strip() or None,
        )
        if any(value is not None for value in photo_command_config) and not all(
            value is not None for value in photo_command_config
        ):
            raise ValueError("Matrix photo commands require complete configuration")
        self._analyze_nutrition = analyze_nutrition
        self._scan_receipt = scan_receipt
        self._missing_nutrition_photo_reply = photo_command_config[2]
        self._missing_receipt_photo_reply = photo_command_config[3]

    async def __call__(self, asset: MatrixMediaAsset) -> str:
        """Process a supported asset and return the text reply for Matrix."""
        if asset.kind == "image" and self._analyze_image is not None:
            return await self._handle_image(asset)
        if asset.kind == "file" and self._document_turn is not None:
            return await self._document_turn(asset)
        if asset.kind != "audio":
            raise ValueError(f"Unsupported Matrix media kind: {asset.kind}")

        audio_data = await asyncio.to_thread(asset.path.read_bytes)
        try:
            transcript = await asyncio.to_thread(
                self._transcribe_audio,
                audio_data,
                mime_type=asset.mime_type,
            )
        except VoiceProviderSetupRequired as exc:
            return f"⚠️ {exc}"
        except CapabilityNotSupportedError:
            return (
                "⚠️ Voice transcription is not supported by the active AI provider. "
                "Please send a text message or configure a provider with voice support."
            )
        except ProviderAuthError:
            return (
                "⚠️ Voice transcription authentication failed. "
                "Please verify your provider credentials."
            )
        except RateLimitError:
            return (
                "⚠️ Voice transcription quota or rate limit exceeded. "
                "Please retry shortly."
            )

        normalized = str(transcript or "").strip()
        if not normalized or normalized in {"[SILENCE]", "[ΣΙΩΠΗ]"}:
            return self._silence_reply
        return await self._matrix_turn(normalized, asset.event_id)

    async def _handle_image(self, asset: MatrixMediaAsset) -> str:
        """Analyze one image and stage it for the owner's next ordinary message."""
        image_data = await asyncio.to_thread(asset.path.read_bytes)
        try:
            analysis = await asyncio.to_thread(
                self._analyze_image,
                image_data,
                mime_type=asset.mime_type,
                prompt=self._vision_prompt,
            )
        except CapabilityNotSupportedError as exc:
            analysis = (
                "Vision analysis is not supported by active provider "
                f"'{exc.provider}'."
            )
        except ProviderAuthError:
            return (
                "⚠️ Photo analysis authentication failed. "
                "Please verify provider credentials."
            )
        except RateLimitError:
            return (
                "⚠️ Photo analysis quota or rate limit exceeded. "
                "Please retry shortly."
            )
        except AIProviderError as exc:
            analysis = f"Vision analysis error ({exc.provider}): {exc}"
        except Exception as exc:
            analysis = f"Vision analysis error: {exc}"

        normalized_analysis = str(analysis or "").strip()
        if not normalized_analysis:
            normalized_analysis = "No visual analysis available."
        with self._pending_photo_lock:
            self._pending_photo = (asset, normalized_analysis, self._clock())
        caption = str(asset.caption or "").strip()
        if caption.lower() in {"/nutrition", "/receipt"}:
            command_reply = await self.consume_pending_photo_command(caption)
            if command_reply is not None:
                return command_reply

        return await self._asset_question_turn(
            question=caption or self._default_photo_question,
            event_id=asset.event_id,
            filename=asset.original_name or asset.path.name,
            file_path=str(asset.path),
            analysis=normalized_analysis,
        )

    def _take_fresh_pending_photo(self) -> tuple[MatrixMediaAsset, str] | None:
        """Atomically consume one unexpired pending photo, if present."""
        with self._pending_photo_lock:
            pending = self._pending_photo
            if pending is None:
                return None
            asset, analysis, created_at = pending
            self._pending_photo = None
        if self._clock() - created_at >= self._pending_photo_ttl_seconds:
            return None
        return asset, analysis

    async def consume_pending_photo_command(self, user_text: str) -> str | None:
        """Run an exact photo command against one fresh staged Matrix photo."""
        command = str(user_text or "").strip().lower()
        if command not in {"/nutrition", "/receipt"}:
            return None
        if self._analyze_nutrition is None or self._scan_receipt is None:
            return None

        pending = self._take_fresh_pending_photo()
        if pending is None:
            if command == "/nutrition":
                return self._missing_nutrition_photo_reply
            return self._missing_receipt_photo_reply

        asset, _analysis = pending
        processor = (
            self._analyze_nutrition if command == "/nutrition" else self._scan_receipt
        )
        return str(await asyncio.to_thread(processor, str(asset.path)))


class MatrixInboundTurnRouter:
    """Combine pending Matrix media context with the next ordinary text turn."""

    def __init__(
        self,
        *,
        text_turn: MatrixTurn,
        media_turn: MatrixMediaTurnService,
        pending_asset_confirmation: PendingAssetConfirmation | None = None,
    ) -> None:
        self._text_turn = text_turn
        self._media_turn = media_turn
        self._pending_asset_confirmation = pending_asset_confirmation

    async def __call__(self, user_text: str, event_id: str) -> str:
        """Resolve confirmations/commands, then run an ordinary Matrix text turn."""
        if self._pending_asset_confirmation is not None:
            confirmation_reply = await self._pending_asset_confirmation(
                user_text,
                event_id,
            )
            if confirmation_reply is not None:
                return confirmation_reply
        photo_command_reply = await self._media_turn.consume_pending_photo_command(
            user_text
        )
        if photo_command_reply is not None:
            return photo_command_reply
        return await self._text_turn(user_text, event_id)
