"""Regression tests for the local text-to-speech endpoint."""

from __future__ import annotations

from types import SimpleNamespace

from fastapi.testclient import TestClient


def test_tts_endpoint_reports_required_voice_setup(monkeypatch) -> None:
    """A missing separate voice provider is returned as an actionable setup error."""
    import api.server as api_server
    from core.ai_provider import VoiceProviderSetupRequired

    def require_voice_setup(text: str, locale: str) -> bytes:
        raise VoiceProviderSetupRequired("Configure VOICE_PROVIDER.", provider="anthropic")

    monkeypatch.setattr(api_server, "_synthesize_speech", require_voice_setup)
    client = TestClient(api_server.server, client=("127.0.0.1", 50000))

    response = client.post("/tts", json={"text": "Hello"})

    assert response.status_code == 400
    assert response.json() == {
        "error": "Configure VOICE_PROVIDER.",
        "setup_required": True,
    }


def test_google_tts_uses_the_greek_chirp_voice_without_network(monkeypatch) -> None:
    """Greek speech uses the configured Cloud TTS voice without a live request."""
    import core.text_to_speech as tts

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
        tts,
        "_get_text_to_speech_client",
        lambda credentials=None: (FakeTextToSpeech, FakeClient()),
    )

    assert tts._synthesize_google_cloud_chunk("Γεια σου", "el") == b"offline-test-audio"
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


def test_tts_chunks_utf8_text_that_exceeds_the_provider_limit(monkeypatch) -> None:
    """Every configured provider receives chunks within the shared byte limit."""
    import core.text_to_speech as tts
    import core.brain as brain

    captured_inputs: list[str] = []

    class FakeVoiceAdapter:
        """Offline provider substitute that records each shared TTS chunk."""

        def synthesize_speech(self, text: str, locale: str) -> bytes:
            raise AssertionError("Test replaces this method with the recording boundary.")

    adapter = FakeVoiceAdapter()
    monkeypatch.setattr(brain, "get_voice_provider_adapter", lambda: adapter)
    text = "α" * 3_000

    # Keep the provider boundary byte-oriented and concatenate its MP3 chunks.
    monkeypatch.setattr(
        adapter,
        "synthesize_speech",
        lambda chunk, locale: (
            captured_inputs.append(chunk)
            or f"audio-{len(captured_inputs)}".encode()
        ),
    )
    assert tts.synthesize_speech(text, "el") == b"audio-1audio-2"
    assert "".join(captured_inputs) == text
    assert all(len(chunk.encode("utf-8")) <= tts.MAX_TTS_INPUT_BYTES for chunk in captured_inputs)
