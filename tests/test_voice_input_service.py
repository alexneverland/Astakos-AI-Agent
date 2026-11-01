"""Offline contracts for the channel-neutral voice transcription boundary."""

from __future__ import annotations

import pytest

from services.voice_input import transcribe_voice_audio


class FakeAdapter:
    def __init__(self, result: str = "  Ακριβές κείμενο  ") -> None:
        self.result = result
        self.calls: list[tuple[bytes, str]] = []

    def transcribe_audio(self, data: bytes, *, mime_type: str) -> str:
        self.calls.append((data, mime_type))
        return self.result


def test_transcription_uses_selected_voice_provider_without_rewording() -> None:
    adapter = FakeAdapter()

    result = transcribe_voice_audio(
        b"voice-bytes",
        mime_type="audio/ogg",
        adapter_factory=lambda: adapter,
    )

    assert result == "  Ακριβές κείμενο  "
    assert adapter.calls == [(b"voice-bytes", "audio/ogg")]


@pytest.mark.parametrize(
    ("data", "mime_type", "message"),
    [
        (b"", "audio/ogg", "non-empty"),
        (b"voice", "image/png", "audio MIME"),
    ],
)
def test_invalid_voice_payload_fails_before_provider_call(data, mime_type, message) -> None:
    called = False

    def factory():
        nonlocal called
        called = True
        return FakeAdapter()

    with pytest.raises(ValueError, match=message):
        transcribe_voice_audio(data, mime_type=mime_type, adapter_factory=factory)

    assert called is False
