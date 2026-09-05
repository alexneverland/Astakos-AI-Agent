"""Shared provider-aware text-to-speech synthesis for Web and Telegram."""

from typing import Any


TTS_VOICES: dict[str, tuple[str, str]] = {
    "el": ("el-GR", "el-GR-Chirp3-HD-Fenrir"),
    "en": ("en-US", "en-US-Chirp3-HD-Charon"),
}
MAX_TTS_INPUT_BYTES = 4_500


def _get_text_to_speech_client(credentials: Any = None) -> tuple[Any, Any]:
    """Build a Cloud Text-to-Speech client with Astakos' Google credentials."""
    from google.cloud import texttospeech

    return texttospeech, texttospeech.TextToSpeechClient(
        credentials=credentials,
    )


def _synthesize_google_cloud_chunk(
    text: str,
    locale: str,
    credentials: Any = None,
) -> bytes:
    """Generate one MP3 chunk through Cloud TTS with explicit credentials."""
    language_code, voice_name = TTS_VOICES.get(locale, TTS_VOICES["en"])
    texttospeech, client = _get_text_to_speech_client(credentials)
    response = client.synthesize_speech(
        input=texttospeech.SynthesisInput(text=text),
        voice=texttospeech.VoiceSelectionParams(
            language_code=language_code,
            name=voice_name,
        ),
        audio_config=texttospeech.AudioConfig(
            audio_encoding=texttospeech.AudioEncoding.MP3,
        ),
    )
    return bytes(response.audio_content or b"")


def split_text_for_tts(
    text: str,
    max_bytes: int = MAX_TTS_INPUT_BYTES,
) -> list[str]:
    """Split text into UTF-8-safe chunks accepted by Cloud TTS."""
    chunks: list[str] = []
    remaining = text
    while remaining:
        if len(remaining.encode("utf-8")) <= max_bytes:
            chunks.append(remaining)
            break
        truncated = remaining.encode("utf-8")[:max_bytes].decode(
            "utf-8",
            errors="ignore",
        )
        split_at = max(truncated.rfind(" "), truncated.rfind("\n"))
        chunk_length = split_at + 1 if split_at > 0 else len(truncated)
        chunks.append(remaining[:chunk_length])
        remaining = remaining[chunk_length:]
    return chunks


def synthesize_speech(text: str, locale: str) -> bytes:
    """Generate an MP3 response with the configured voice provider."""
    from core.brain import get_voice_provider_adapter

    adapter = get_voice_provider_adapter()
    return b"".join(
        adapter.synthesize_speech(chunk, locale)
        for chunk in split_text_for_tts(text)
    )
