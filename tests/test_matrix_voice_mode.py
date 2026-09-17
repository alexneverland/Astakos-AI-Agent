"""Offline contracts for channel-local Matrix spoken-reply mode."""

from __future__ import annotations

import pytest

from clients.matrix_client import MatrixReply
from services.matrix_voice_mode import MatrixVoiceModeRouter


@pytest.mark.asyncio
async def test_voice_mode_starts_off_and_toggles_without_entering_graph() -> None:
    calls: list[tuple[str, str]] = []

    async def text_turn(text: str, event_id: str) -> str:
        calls.append((text, event_id))
        return "Απάντηση"

    router = MatrixVoiceModeRouter(
        text_turn=text_turn,
        enabled_reply="🔊 Voice replies ON",
        disabled_reply="✍️ Voice replies OFF",
    )

    assert await router("πρώτο", "$1") == MatrixReply("Απάντηση", "text")
    assert await router("/voice", "$2") == MatrixReply("🔊 Voice replies ON", "text")
    assert await router("δεύτερο", "$3") == MatrixReply("Απάντηση", "voice")
    assert await router("/voice", "$4") == MatrixReply("✍️ Voice replies OFF", "text")
    assert calls == [("πρώτο", "$1"), ("δεύτερο", "$3")]


@pytest.mark.asyncio
async def test_voice_input_uses_current_mode_but_does_not_enable_it() -> None:
    async def text_turn(text: str, event_id: str) -> str:
        return f"reply:{text}"

    router = MatrixVoiceModeRouter(
        text_turn=text_turn,
        enabled_reply="on",
        disabled_reply="off",
    )

    assert await router("φωνητικό κείμενο", "$audio") == MatrixReply(
        "reply:φωνητικό κείμενο",
        "text",
    )
    await router("/voice", "$toggle")
    assert await router("φωνητικό κείμενο", "$audio-2") == MatrixReply(
        "reply:φωνητικό κείμενο",
        "voice",
    )


@pytest.mark.asyncio
async def test_voice_mode_preserves_generated_file_attachments() -> None:
    async def text_turn(text: str, event_id: str) -> MatrixReply:
        return MatrixReply("έτοιμο", attachment_paths=("C:/outputs/report.pdf",))

    router = MatrixVoiceModeRouter(
        text_turn=text_turn,
        enabled_reply="voice on",
        disabled_reply="voice off",
    )

    reply = await router("φτιάξε", "$file")

    assert reply == MatrixReply(
        "έτοιμο",
        "text",
        ("C:/outputs/report.pdf",),
    )
