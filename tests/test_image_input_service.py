"""Offline contracts for the channel-neutral image analysis boundary."""

from __future__ import annotations

import pytest

from services.image_input import analyze_image_bytes


def test_image_analysis_uses_selected_provider_and_cleans_structured_content() -> None:
    class FakeAdapter:
        def analyze_vision(self, prompt, data, *, mime_type):
            raise AssertionError("safe adapter boundary should invoke this callable")

    adapter = FakeAdapter()
    calls: list[tuple[object, str, bytes, str]] = []

    def invoke(selected, prompt, data, *, mime_type):
        calls.append((selected, prompt, data, mime_type))
        return [{"type": "text", "text": "  Μια κίτρινη σφήκα.  ", "extras": {}}]

    result = analyze_image_bytes(
        b"image-bytes",
        mime_type="image/png",
        prompt="Περιέγραψε αντικειμενικά.",
        adapter_factory=lambda: adapter,
        adapter_call=invoke,
    )

    assert result == "Μια κίτρινη σφήκα."
    assert calls == [
        (
            adapter.analyze_vision,
            "Περιέγραψε αντικειμενικά.",
            b"image-bytes",
            "image/png",
        )
    ]


@pytest.mark.parametrize(
    ("data", "mime_type", "message"),
    [
        (b"", "image/png", "non-empty"),
        (b"image", "audio/ogg", "image MIME"),
    ],
)
def test_invalid_image_payload_fails_before_provider_call(data, mime_type, message) -> None:
    called = False

    def factory():
        nonlocal called
        called = True
        return object()

    with pytest.raises(ValueError, match=message):
        analyze_image_bytes(
            data,
            mime_type=mime_type,
            prompt="Describe",
            adapter_factory=factory,
            adapter_call=lambda *args, **kwargs: "unused",
        )

    assert called is False


def test_blank_prompt_is_rejected() -> None:
    with pytest.raises(ValueError, match="prompt"):
        analyze_image_bytes(
            b"image",
            mime_type="image/jpeg",
            prompt=" ",
            adapter_factory=lambda: type("Adapter", (), {"analyze_vision": None})(),
            adapter_call=lambda *args, **kwargs: "unused",
        )
