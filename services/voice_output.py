"""Channel-neutral cleanup and synthesis for spoken assistant replies."""

from __future__ import annotations

import re
from collections.abc import Callable


def clean_voice_reply(text: str) -> str:
    """Remove formatting that should not be spoken while preserving wording."""
    cleaned = re.sub(r"```.*?```", "", str(text or ""), flags=re.DOTALL)
    cleaned = re.sub(r"\[.*?\]", "", cleaned)
    cleaned = re.sub(r"[*_#`~]", "", cleaned)
    return " ".join(cleaned.split())


def synthesize_voice_reply(
    text: str,
    *,
    locale: str,
    synthesizer: Callable[[str, str], bytes] | None = None,
) -> bytes:
    """Synthesize one cleaned reply through the configured voice provider."""
    cleaned = clean_voice_reply(text)
    if not cleaned:
        raise ValueError("Voice reply contains no speakable text")
    if synthesizer is None:
        from core.text_to_speech import synthesize_speech

        synthesizer = synthesize_speech
    return bytes(synthesizer(cleaned, locale) or b"")
