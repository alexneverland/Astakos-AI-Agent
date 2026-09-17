"""Offline application contracts for Matrix media turns."""

from __future__ import annotations

from pathlib import Path

import pytest

from clients.matrix_media import MatrixMediaAsset
from core.ai_provider import CapabilityNotSupportedError, ProviderAuthError, RateLimitError
from services.matrix_media_turn import MatrixMediaTurnService


def _audio_asset(path: Path) -> MatrixMediaAsset:
    return MatrixMediaAsset(
        event_id="$voice-1",
        kind="audio",
        path=path,
        mime_type="audio/ogg",
        original_name="voice.ogg",
    )


@pytest.mark.asyncio
async def test_audio_transcript_enters_normal_matrix_turn(tmp_path) -> None:
    audio_path = tmp_path / "voice.ogg"
    audio_path.write_bytes(b"voice-bytes")
    transcription_calls: list[tuple[bytes, str]] = []
    turn_calls: list[tuple[str, str]] = []

    def transcribe(data: bytes, *, mime_type: str) -> str:
        transcription_calls.append((data, mime_type))
        return "Στείλε ένα μήνυμα"

    async def matrix_turn(text: str, event_id: str) -> str:
        turn_calls.append((text, event_id))
        return "Έτοιμο το προσχέδιο."

    service = MatrixMediaTurnService(
        matrix_turn=matrix_turn,
        transcribe_audio=transcribe,
        silence_reply="Δεν ακούστηκε κάτι.",
    )

    reply = await service(_audio_asset(audio_path))

    assert reply == "Έτοιμο το προσχέδιο."
    assert transcription_calls == [(b"voice-bytes", "audio/ogg")]
    assert turn_calls == [("Στείλε ένα μήνυμα", "$voice-1")]


@pytest.mark.asyncio
@pytest.mark.parametrize("transcript", ["", "  ", "[SILENCE]", "[ΣΙΩΠΗ]"])
async def test_silence_returns_local_reply_without_graph(tmp_path, transcript) -> None:
    audio_path = tmp_path / "voice.ogg"
    audio_path.write_bytes(b"voice-bytes")

    async def matrix_turn(text: str, event_id: str) -> str:
        raise AssertionError("silence must not enter the graph")

    service = MatrixMediaTurnService(
        matrix_turn=matrix_turn,
        transcribe_audio=lambda data, *, mime_type: transcript,
        silence_reply="Δεν ακούστηκε κάτι.",
    )

    assert await service(_audio_asset(audio_path)) == "Δεν ακούστηκε κάτι."


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (
            CapabilityNotSupportedError("anthropic", "voice", "no voice"),
            "not supported",
        ),
        (ProviderAuthError("vertex", "bad auth"), "authentication failed"),
        (RateLimitError("vertex", "quota"), "quota or rate limit"),
    ],
)
async def test_provider_failures_return_actionable_matrix_reply(
    tmp_path, error, expected
) -> None:
    audio_path = tmp_path / "voice.ogg"
    audio_path.write_bytes(b"voice-bytes")

    def transcribe(data: bytes, *, mime_type: str) -> str:
        raise error

    async def matrix_turn(text: str, event_id: str) -> str:
        raise AssertionError("provider failures must not enter the graph")

    service = MatrixMediaTurnService(
        matrix_turn=matrix_turn,
        transcribe_audio=transcribe,
        silence_reply="Δεν ακούστηκε κάτι.",
    )

    assert expected in (await service(_audio_asset(audio_path))).lower()


@pytest.mark.asyncio
async def test_non_audio_asset_is_not_silently_processed(tmp_path) -> None:
    path = tmp_path / "photo.png"
    path.write_bytes(b"png")
    asset = MatrixMediaAsset("$image", "image", path, "image/png", "photo.png")

    async def matrix_turn(text: str, event_id: str) -> str:
        raise AssertionError

    service = MatrixMediaTurnService(
        matrix_turn=matrix_turn,
        transcribe_audio=lambda data, *, mime_type: "unused",
        silence_reply="silence",
    )

    with pytest.raises(ValueError, match="Unsupported Matrix media kind"):
        await service(asset)


@pytest.mark.asyncio
async def test_image_is_staged_then_next_question_uses_asset_turn(tmp_path) -> None:
    path = tmp_path / "photo.png"
    path.write_bytes(b"png-bytes")
    asset = MatrixMediaAsset("$image", "image", path, "image/png", "photo.png")
    analysis_calls: list[tuple[bytes, str, str]] = []
    question_calls: list[tuple[str, str, MatrixMediaAsset, str]] = []

    def analyze(data: bytes, *, mime_type: str, prompt: str) -> str:
        analysis_calls.append((data, mime_type, prompt))
        return "Μια μεγάλη σφήκα."

    async def asset_turn(*, question, event_id, filename, file_path, analysis):
        question_calls.append((question, event_id, filename, file_path, analysis))
        return "Είναι ανατολικός σκούρκος."

    async def matrix_turn(text: str, event_id: str) -> str:
        raise AssertionError("photo question must use the asset-aware turn")

    service = MatrixMediaTurnService(
        matrix_turn=matrix_turn,
        transcribe_audio=lambda data, *, mime_type: "unused",
        silence_reply="silence",
        analyze_image=analyze,
        vision_prompt="Περιέγραψε αντικειμενικά.",
        photo_received_reply="📷 Φωτό ελήφθη! Τι θέλεις να κάνω με αυτή;",
        asset_question_turn=asset_turn,
    )

    assert await service(asset) == "📷 Φωτό ελήφθη! Τι θέλεις να κάνω με αυτή;"
    assert analysis_calls == [
        (b"png-bytes", "image/png", "Περιέγραψε αντικειμενικά.")
    ]
    assert await service.consume_pending_photo("Τι είναι;", "$question") == (
        "Είναι ανατολικός σκούρκος."
    )
    assert question_calls == [
        (
            "Τι είναι;",
            "$question",
            "photo.png",
            str(path),
            "Μια μεγάλη σφήκα.",
        )
    ]
    assert await service.consume_pending_photo("ξανά", "$question-2") is None


@pytest.mark.asyncio
async def test_command_does_not_consume_pending_photo_and_expired_photo_is_dropped(
    tmp_path,
) -> None:
    path = tmp_path / "photo.png"
    path.write_bytes(b"png-bytes")
    asset = MatrixMediaAsset("$image", "image", path, "image/png", "photo.png")
    now = [100.0]

    async def matrix_turn(text: str, event_id: str) -> str:
        return "unused"

    async def asset_turn(**kwargs):
        return "answered"

    service = MatrixMediaTurnService(
        matrix_turn=matrix_turn,
        transcribe_audio=lambda data, *, mime_type: "unused",
        silence_reply="silence",
        analyze_image=lambda data, *, mime_type, prompt: "analysis",
        vision_prompt="Describe",
        photo_received_reply="received",
        asset_question_turn=asset_turn,
        pending_photo_ttl_seconds=30,
        clock=lambda: now[0],
    )
    await service(asset)

    assert await service.consume_pending_photo("/status", "$command") is None
    now[0] = 131.0
    assert await service.consume_pending_photo("Τι είναι;", "$late") is None


@pytest.mark.asyncio
async def test_photo_commands_consume_only_the_matching_fresh_pending_photo(
    tmp_path,
) -> None:
    from services.matrix_media_turn import MatrixInboundTurnRouter

    path = tmp_path / "label.png"
    path.write_bytes(b"png-bytes")
    asset = MatrixMediaAsset("$image", "image", path, "image/png", "label.png")
    calls: list[tuple[str, str]] = []

    async def normal_turn(text: str, event_id: str) -> str:
        calls.append(("normal", text))
        return "normal"

    async def asset_turn(**kwargs) -> str:
        return "asset question"

    media = MatrixMediaTurnService(
        matrix_turn=normal_turn,
        transcribe_audio=lambda data, *, mime_type: "unused",
        silence_reply="silence",
        analyze_image=lambda data, *, mime_type, prompt: "analysis",
        vision_prompt="Describe",
        photo_received_reply="received",
        asset_question_turn=asset_turn,
        analyze_nutrition=lambda photo_path: calls.append(("nutrition", photo_path))
        or "nutrition result",
        scan_receipt=lambda photo_path: calls.append(("receipt", photo_path))
        or "receipt result",
        missing_nutrition_photo_reply="missing nutrition photo",
        missing_receipt_photo_reply="missing receipt photo",
    )
    router = MatrixInboundTurnRouter(text_turn=normal_turn, media_turn=media)
    await media(asset)

    assert await router("/status", "$status") == "normal"
    assert await router(" /NUTRITION ", "$nutrition") == "nutrition result"
    assert calls == [("normal", "/status"), ("nutrition", str(path))]
    assert await router("/receipt", "$receipt") == "missing receipt photo"


@pytest.mark.asyncio
async def test_inbound_router_prefers_pending_photo_then_returns_to_normal_turn(
    tmp_path,
) -> None:
    from services.matrix_media_turn import MatrixInboundTurnRouter

    path = tmp_path / "photo.png"
    path.write_bytes(b"png-bytes")
    asset = MatrixMediaAsset("$image", "image", path, "image/png", "photo.png")
    normal_calls: list[tuple[str, str]] = []

    async def normal_turn(text: str, event_id: str) -> str:
        normal_calls.append((text, event_id))
        return "normal"

    async def asset_turn(**kwargs) -> str:
        return f"photo:{kwargs['question']}"

    media = MatrixMediaTurnService(
        matrix_turn=normal_turn,
        transcribe_audio=lambda data, *, mime_type: "unused",
        silence_reply="silence",
        analyze_image=lambda data, *, mime_type, prompt: "analysis",
        vision_prompt="Describe",
        photo_received_reply="received",
        asset_question_turn=asset_turn,
    )
    router = MatrixInboundTurnRouter(text_turn=normal_turn, media_turn=media)
    await media(asset)

    assert await router("/status", "$command") == "normal"
    assert await router("Τι είναι;", "$question") == "photo:Τι είναι;"
    assert await router("Μετά", "$next") == "normal"
    assert normal_calls == [("/status", "$command"), ("Μετά", "$next")]


@pytest.mark.asyncio
async def test_file_asset_delegates_to_document_turn(tmp_path) -> None:
    path = tmp_path / "report.pdf"
    path.write_bytes(b"pdf")
    asset = MatrixMediaAsset("$file", "file", path, "application/pdf", "report.pdf")
    calls: list[MatrixMediaAsset] = []

    async def document_turn(item: MatrixMediaAsset) -> str:
        calls.append(item)
        return "document reply"

    async def matrix_turn(text: str, event_id: str) -> str:
        raise AssertionError

    service = MatrixMediaTurnService(
        matrix_turn=matrix_turn,
        transcribe_audio=lambda data, *, mime_type: "unused",
        silence_reply="silence",
        document_turn=document_turn,
    )

    assert await service(asset) == "document reply"
    assert calls == [asset]


@pytest.mark.asyncio
async def test_inbound_router_checks_asset_confirmation_before_photo_or_graph() -> None:
    order: list[str] = []

    async def confirmation(text: str, event_id: str) -> str | None:
        order.append("confirmation")
        return "saved" if text == "ναι" else None

    async def normal_turn(text: str, event_id: str) -> str:
        order.append("normal")
        return "normal"

    media = type(
        "Media",
        (),
        {"consume_pending_photo": lambda self, text, event_id: _none(order)},
    )()
    from services.matrix_media_turn import MatrixInboundTurnRouter

    router = MatrixInboundTurnRouter(
        text_turn=normal_turn,
        media_turn=media,
        pending_asset_confirmation=confirmation,
    )

    assert await router("ναι", "$yes") == "saved"
    assert order == ["confirmation"]


async def _none(order):
    order.append("photo")
    return None
