"""Channel-neutral voice transcription through the configured provider."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any


def transcribe_voice_audio(
    audio_data: bytes,
    *,
    mime_type: str,
    adapter_factory: Callable[[], Any] | None = None,
) -> str:
    """Transcribe exact audio bytes without rewriting the provider transcript."""
    if not isinstance(audio_data, bytes) or not audio_data:
        raise ValueError("Voice transcription requires non-empty audio bytes")
    normalized_mime = str(mime_type or "").strip().lower()
    if not normalized_mime.startswith("audio/"):
        raise ValueError("Voice transcription requires an audio MIME type")

    if adapter_factory is None:
        from core.brain import get_voice_provider_adapter

        adapter_factory = get_voice_provider_adapter
    adapter = adapter_factory()
    return adapter.transcribe_audio(audio_data, mime_type=normalized_mime)
