"""Channel-neutral image analysis through the configured provider."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from core.utils import clean_message


def analyze_image_bytes(
    image_data: bytes,
    *,
    mime_type: str,
    prompt: str,
    adapter_factory: Callable[[], Any] | None = None,
    adapter_call: Callable[..., Any] | None = None,
) -> str:
    """Analyze image bytes without binding the result to a delivery channel."""
    if not isinstance(image_data, bytes) or not image_data:
        raise ValueError("Image analysis requires non-empty image bytes")
    normalized_mime = str(mime_type or "").strip().lower()
    if not normalized_mime.startswith("image/"):
        raise ValueError("Image analysis requires an image MIME type")
    normalized_prompt = str(prompt or "").strip()
    if not normalized_prompt:
        raise ValueError("Image analysis requires a non-empty prompt")

    if adapter_factory is None or adapter_call is None:
        from core.brain import get_active_provider_adapter, safe_adapter_call

        adapter_factory = adapter_factory or get_active_provider_adapter
        adapter_call = adapter_call or safe_adapter_call

    adapter = adapter_factory()
    result = adapter_call(
        adapter.analyze_vision,
        normalized_prompt,
        image_data,
        mime_type=normalized_mime,
    )
    return clean_message(result).strip()
