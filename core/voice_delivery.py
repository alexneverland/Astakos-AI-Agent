"""Trusted response-delivery context for spoken conversations."""

from langchain_core.messages import SystemMessage

from core.i18n import load_prompt


def build_voice_delivery_context(enabled: bool) -> SystemMessage | None:
    """Return bounded system context when a response will be spoken aloud."""
    if not enabled:
        return None

    return SystemMessage(content=load_prompt("live_voice_context.md").strip())
