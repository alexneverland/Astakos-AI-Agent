"""Offline contracts for Matrix-local Georgian translation state."""

from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_pending_georgian_translation_consumes_once_and_expires() -> None:
    from services.matrix_georgian_turn import MatrixGeorgianTurnRouter

    now = [100.0]
    graph_calls: list[str] = []

    async def graph_turn(text: str, event_id: str) -> str:
        graph_calls.append(text)
        return "graph"

    router = MatrixGeorgianTurnRouter(
        text_turn=graph_turn,
        translate=lambda text, src="auto": {
            "translated": f"translated:{src}:{text}",
            "phonetic": "phonetic",
            "src": "el",
            "tgt": "ka",
        },
        phrases_message=lambda: "phrases",
        prompt_greek_to_georgian="send Greek",
        prompt_georgian_to_greek="send Georgian",
        clock=lambda: now[0],
        ttl_seconds=120,
    )

    assert await router("/g", "$arm") == "send Greek"
    assert "translated:auto:καλημέρα" in await router("καλημέρα", "$one")
    assert await router("δεύτερο", "$two") == "graph"

    assert await router("/gr", "$arm-2") == "send Georgian"
    now[0] += 121
    assert await router("გამარჯობა", "$expired") == "graph"
    assert graph_calls == ["δεύτερο", "გამარჯობა"]


@pytest.mark.asyncio
async def test_direct_translation_phrases_and_unrelated_command_boundaries() -> None:
    from services.matrix_georgian_turn import MatrixGeorgianTurnRouter

    translated: list[tuple[str, str]] = []

    async def graph_turn(text: str, event_id: str) -> str:
        return f"graph:{text}"

    def translate(text: str, src: str = "auto") -> dict[str, str]:
        translated.append((text, src))
        return {"translated": "გამარჯობა", "phonetic": "gamarjoba", "src": "el", "tgt": "ka"}

    router = MatrixGeorgianTurnRouter(
        text_turn=graph_turn,
        translate=translate,
        phrases_message=lambda: "phrases",
        prompt_greek_to_georgian="send Greek",
        prompt_georgian_to_greek="send Georgian",
    )

    assert await router("/g_phrases", "$phrases") == "phrases"
    assert "გამარჯობა" in await router("/georgian καλημέρα", "$direct")
    assert translated == [("καλημέρα", "auto")]
    assert await router("/g", "$arm") == "send Greek"
    assert await router("/status", "$cancel") == "graph:/status"
    assert await router("δεν μεταφράζεται", "$normal") == "graph:δεν μεταφράζεται"
