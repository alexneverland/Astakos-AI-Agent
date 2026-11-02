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


@pytest.mark.parametrize("locale", ["el", "en"])
@pytest.mark.parametrize("denied", [False, True])
def test_cloud_tts_default_grpc_transport(
    monkeypatch: pytest.MonkeyPatch, locale: str, denied: bool
) -> None:
    """Retain the production factory and real gRPC codecs across success/error."""
    from typing import Any
    from unittest.mock import MagicMock

    import grpc
    from google.api_core.exceptions import PermissionDenied
    from google.auth.credentials import AnonymousCredentials
    from google.cloud import texttospeech
    from google.cloud.texttospeech_v1.services.text_to_speech.transports.grpc import TextToSpeechGrpcTransport

    from core import text_to_speech

    class SyntheticDenial(grpc.RpcError):
        """Permanent gRPC failure containing no real endpoint or credential."""

        def code(self) -> grpc.StatusCode:
            return grpc.StatusCode.PERMISSION_DENIED

        def details(self) -> str:
            return "synthetic gRPC denial"

        def trailing_metadata(self) -> tuple:
            return ()

        def result(self, timeout: float | None = None) -> Any:
            """Mirror the failed gRPC call/future returned through interceptors."""
            raise self

    channel = MagicMock(spec=grpc.Channel)
    captured: list[object] = []

    def make_rpc(
        method: str, request_serializer: Any, response_deserializer: Any,
        _registered_method: bool = False,
        **kwargs: Any,
    ) -> Any:
        """Replace only channel I/O, using the serializers chosen by the SDK."""
        rpc = MagicMock(spec=grpc.UnaryUnaryMultiCallable)

        def exchange(request: Any, *args: Any, **kwargs: Any) -> Any:
            assert method.endswith("/SynthesizeSpeech")
            encoded = request_serializer(request)
            decoded = texttospeech.SynthesizeSpeechRequest.deserialize(encoded)
            captured.append(decoded)
            if denied:
                raise SyntheticDenial()
            response = texttospeech.SynthesizeSpeechResponse(
                audio_content=b"synthetic-grpc-mp3"
            )
            return response_deserializer(
                texttospeech.SynthesizeSpeechResponse.serialize(response)
            )

        def with_call(request: Any, *args: Any, **kwargs: Any) -> tuple[Any, Any]:
            return exchange(request, *args, **kwargs), MagicMock(spec=grpc.Call)

        rpc.side_effect = exchange
        rpc.with_call.side_effect = with_call
        return rpc

    channel.unary_unary.side_effect = make_rpc
    monkeypatch.setattr(
        TextToSpeechGrpcTransport, "create_channel",
        classmethod(lambda cls, *args, **kwargs: channel),
    )

    if denied:
        with pytest.raises(PermissionDenied, match="synthetic gRPC denial"):
            text_to_speech._synthesize_google_cloud_chunk(
                "Synthetic", locale, credentials=AnonymousCredentials()
            )
    else:
        assert text_to_speech._synthesize_google_cloud_chunk(
            "Synthetic", locale, credentials=AnonymousCredentials()
        ) == b"synthetic-grpc-mp3"

    language, voice = text_to_speech.TTS_VOICES[locale]
    assert len(captured) == 1
    request = captured[0]
    assert request.input.text == "Synthetic"
    assert request.voice.language_code == language
    assert request.voice.name == voice
    assert request.audio_config.audio_encoding == texttospeech.AudioEncoding.MP3
