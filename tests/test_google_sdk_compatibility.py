"""Real Google/protobuf boundaries with synthetic data and offline transports."""

from __future__ import annotations

import base64
import json

import pytest

pytestmark = pytest.mark.usefixtures("offline_behavioral_io")


@pytest.mark.parametrize(
    ("locale", "language", "voice"),
    [
        ("el", "el-GR", "el-GR-Chirp3-HD-Fenrir"),
        ("en", "en-US", "en-US-Chirp3-HD-Charon"),
    ],
)
def test_cloud_tts_real_rest_serialization(
    monkeypatch: pytest.MonkeyPatch, locale: str, language: str, voice: str
) -> None:
    """Exercise the application's real Cloud TTS request and response codecs."""
    from google.auth.credentials import AnonymousCredentials
    from google.cloud import texttospeech
    import requests

    from core import text_to_speech

    client = texttospeech.TextToSpeechClient(
        credentials=AnonymousCredentials(), transport="rest"
    )
    captured: list[dict] = []

    def respond(method: str, url: str, **kwargs: object) -> requests.Response:
        """Substitute only the outbound HTTP boundary, retaining SDK codecs."""
        assert method.upper() == "POST"
        assert url.endswith("/v1/text:synthesize")
        captured.append(json.loads(kwargs["data"]))
        response = requests.Response()
        response.status_code = 200
        response._content = json.dumps(
            {"audioContent": base64.b64encode(b"synthetic-mp3").decode("ascii")}
        ).encode("utf-8")
        return response

    monkeypatch.setattr(client.transport._session, "request", respond)
    monkeypatch.setattr(
        text_to_speech,
        "_get_text_to_speech_client",
        lambda credentials=None: (texttospeech, client),
    )
    try:
        assert text_to_speech._synthesize_google_cloud_chunk("Synthetic", locale) == b"synthetic-mp3"
        assert captured == [{
            "input": {"text": "Synthetic"},
            "voice": {"languageCode": language, "name": voice},
            "audioConfig": {"audioEncoding": "MP3"},
        }]
    finally:
        client.transport.close()


def test_cloud_tts_permission_failure_does_not_become_audio(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A real SDK 403 response must propagate as a typed failure."""
    from google.api_core.exceptions import Forbidden
    from google.auth.credentials import AnonymousCredentials
    from google.cloud import texttospeech
    import requests

    from core import text_to_speech

    client = texttospeech.TextToSpeechClient(
        credentials=AnonymousCredentials(), transport="rest"
    )

    def deny(*args: object, **kwargs: object) -> requests.Response:
        """Return a synthetic permanent error without sending a request."""
        response = requests.Response()
        response.status_code = 403
        response.request = requests.Request(
            "POST", "https://texttospeech.googleapis.com/v1/text:synthesize"
        ).prepare()
        response._content = b'{"error":{"code":403,"message":"synthetic denial","status":"PERMISSION_DENIED"}}'
        return response

    monkeypatch.setattr(client.transport._session, "request", deny)
    monkeypatch.setattr(
        text_to_speech,
        "_get_text_to_speech_client",
        lambda credentials=None: (texttospeech, client),
    )
    try:
        with pytest.raises(Forbidden, match="synthetic denial"):
            text_to_speech._synthesize_google_cloud_chunk("Synthetic", "el")
    finally:
        client.transport.close()


def test_telemetry_protobuf_roundtrip() -> None:
    """The Chroma telemetry dependency keeps real protobuf binary compatibility."""
    from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest
    from opentelemetry.proto.trace.v1.trace_pb2 import ResourceSpans, ScopeSpans, Span

    original = ExportTraceServiceRequest(resource_spans=[
        ResourceSpans(scope_spans=[ScopeSpans(spans=[Span(name="synthetic-span")])])
    ])
    restored = ExportTraceServiceRequest.FromString(original.SerializeToString())
    assert restored == original
    assert restored.resource_spans[0].scope_spans[0].spans[0].name == "synthetic-span"
