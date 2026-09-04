"""Regression tests for the local text-to-speech endpoint."""

from __future__ import annotations

from types import SimpleNamespace

from fastapi.testclient import TestClient


def test_google_tts_uses_the_greek_chirp_voice_without_network(monkeypatch) -> None:
    """Greek speech uses the configured Cloud TTS voice without a live request."""
    import api.server as api_server

    captured: dict[str, object] = {}

    class FakeTextToSpeech:
        """Offline substitute for the Cloud TTS module types."""

        class AudioEncoding:
            MP3 = "mp3"

        @staticmethod
        def SynthesisInput(*, text: str) -> dict[str, str]:
            return {"text": text}

        @staticmethod
        def VoiceSelectionParams(**kwargs: str) -> dict[str, str]:
            return kwargs

        @staticmethod
        def AudioConfig(**kwargs: str) -> dict[str, str]:
            return kwargs

    class FakeClient:
        """Offline substitute for the Cloud TTS API client."""

        def synthesize_speech(self, *, input, voice, audio_config):
            captured["input"] = input
            captured["voice"] = voice
            captured["audio_config"] = audio_config
            return SimpleNamespace(audio_content=b"offline-test-audio")

    monkeypatch.setattr(
        api_server,
        "_get_text_to_speech_client",
        lambda: (FakeTextToSpeech, FakeClient()),
    )

    assert api_server._synthesize_speech("Γεια σου", "el") == b"offline-test-audio"
    assert captured == {
        "input": {"text": "Γεια σου"},
        "voice": {"language_code": "el-GR", "name": "el-GR-Chirp3-HD-Fenrir"},
        "audio_config": {"audio_encoding": "mp3"},
    }


def test_tts_passes_the_active_english_locale_to_google_tts_without_network(
    monkeypatch,
) -> None:
    """The endpoint delegates English replies to the Cloud TTS synthesizer."""
    import api.server as api_server
    import core.i18n as i18n

    captured: dict[str, str] = {}

    def fake_synthesize(text: str, locale: str) -> bytes:
        """Capture the endpoint delegation without calling Google Cloud."""
        captured["text"] = text
        captured["locale"] = locale
        return b"offline-test-audio"

    monkeypatch.setattr(i18n, "LANG", "en")
    monkeypatch.setattr(api_server, "_synthesize_speech", fake_synthesize)

    client = TestClient(api_server.server, client=("127.0.0.1", 50000))
    response = client.post("/tts", json={"text": "Hello"})

    assert response.status_code == 200
    assert response.content == b"offline-test-audio"
    assert response.headers["content-type"] == "audio/mpeg"
    assert captured == {"text": "Hello", "locale": "en"}
