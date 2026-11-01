"""Offline regression tests for provider-aware speech input and output."""

from __future__ import annotations

import base64
from types import SimpleNamespace

import pytest


def test_auto_voice_provider_follows_a_voice_capable_chat_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Auto mode reuses the user's configured OpenAI provider."""
    import config
    from core.ai_provider import resolve_voice_provider

    monkeypatch.setattr(config, "LLM_PROVIDER", "openai")
    monkeypatch.setattr(config, "VOICE_PROVIDER", "auto", raising=False)

    assert resolve_voice_provider() == "openai"


def test_auto_voice_provider_requires_setup_for_anthropic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Auto mode never silently selects unrelated credentials for Anthropic."""
    import config
    from core.ai_provider import VoiceProviderSetupRequired, resolve_voice_provider

    monkeypatch.setattr(config, "LLM_PROVIDER", "anthropic")
    monkeypatch.setattr(config, "VOICE_PROVIDER", "auto", raising=False)

    with pytest.raises(VoiceProviderSetupRequired, match="VOICE_PROVIDER"):
        resolve_voice_provider()


def test_explicit_voice_provider_can_differ_from_chat_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Anthropic chat can use an explicitly configured Gemini voice backend."""
    import config
    from core.ai_provider import resolve_voice_provider

    monkeypatch.setattr(config, "LLM_PROVIDER", "anthropic")
    monkeypatch.setattr(config, "VOICE_PROVIDER", "gemini", raising=False)

    assert resolve_voice_provider() == "gemini"


def test_openai_tts_uses_the_existing_openai_key_without_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """OpenAI speech uses the adapter credential and requests MP3 output."""
    from core.ai_provider import OpenAIAdapter

    captured: dict[str, object] = {}

    class FakeSpeech:
        def create(self, **kwargs):
            captured.update(kwargs)
            return SimpleNamespace(content=b"openai-mp3")

    adapter = OpenAIAdapter(api_key="sk-test")
    monkeypatch.setattr(
        adapter,
        "_get_openai_client",
        lambda: SimpleNamespace(audio=SimpleNamespace(speech=FakeSpeech())),
    )

    assert adapter.synthesize_speech("Γεια σου", "el") == b"openai-mp3"
    assert captured == {
        "model": "gpt-4o-mini-tts",
        "voice": "cedar",
        "input": "Γεια σου",
        "instructions": "Speak naturally in Greek.",
        "response_format": "mp3",
    }


def test_gemini_tts_uses_the_existing_gemini_key_and_requests_mp3(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Gemini speech stays on the Gemini API and returns Telegram-safe MP3."""
    from core.ai_provider import GeminiAPIAdapter

    captured: dict[str, object] = {}

    class FakeInteractions:
        def create(self, **kwargs):
            captured.update(kwargs)
            return SimpleNamespace(
                output_audio=SimpleNamespace(
                    data=base64.b64encode(b"gemini-mp3").decode("ascii"),
                    mime_type="audio/mp3",
                )
            )

    adapter = GeminiAPIAdapter(api_key="gemini-test")
    monkeypatch.setattr(
        adapter,
        "_get_genai_client",
        lambda: SimpleNamespace(interactions=FakeInteractions()),
    )

    assert adapter.synthesize_speech("Hello", "en") == b"gemini-mp3"
    assert captured["model"] == "gemini-3.1-flash-tts-preview"
    assert captured["input"] == (
        "Synthesize natural speech for the following transcript. "
        "Speak only the transcript.\n\n"
        "Spoken transcript:\nHello"
    )
    assert captured["response_format"] == {
        "type": "audio",
        "mime_type": "audio/mp3",
        "delivery": "inline",
    }
    assert captured["generation_config"] == {
        "speech_config": [{"voice": "Charon", "language": "en-US"}],
    }


def test_vertex_tts_reuses_vertex_credentials_without_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Vertex speech keeps the existing Cloud TTS MP3 transport."""
    from core.ai_provider import VertexAIAdapter
    import core.text_to_speech as tts

    captured: dict[str, object] = {}
    adapter = VertexAIAdapter(project_id="test-project", credentials_path="")
    adapter._credentials = "test-credentials"

    def fake_cloud_chunk(text: str, locale: str, credentials: object) -> bytes:
        captured.update(text=text, locale=locale, credentials=credentials)
        return b"vertex-mp3"

    monkeypatch.setattr(tts, "_synthesize_google_cloud_chunk", fake_cloud_chunk)

    assert adapter.synthesize_speech("Γεια", "el") == b"vertex-mp3"
    assert captured == {
        "text": "Γεια",
        "locale": "el",
        "credentials": "test-credentials",
    }


def test_shared_tts_uses_one_resolved_voice_adapter_for_all_chunks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The shared TTS entrypoint delegates every bounded chunk to one adapter."""
    import core.brain as brain
    import core.text_to_speech as tts

    calls: list[tuple[str, str]] = []
    adapter = SimpleNamespace(
        synthesize_speech=lambda text, locale: calls.append((text, locale))
        or f"audio-{len(calls)}".encode()
    )
    monkeypatch.setattr(brain, "get_voice_provider_adapter", lambda: adapter, raising=False)
    text = "α" * 3_000

    assert tts.synthesize_speech(text, "el") == b"audio-1audio-2"
    assert "".join(chunk for chunk, _ in calls) == text
    assert all(locale == "el" for _, locale in calls)
