"""Canonical selection for Astakos external messaging transports."""

from __future__ import annotations

import os
from typing import Literal, cast


ExternalChannel = Literal["telegram", "matrix"]

EXTERNAL_CHANNEL_ENV_VAR = "ASTAKOS_EXTERNAL_CHANNEL"
DEFAULT_EXTERNAL_CHANNEL: ExternalChannel = "telegram"
SUPPORTED_EXTERNAL_CHANNELS = frozenset({"telegram", "matrix"})


class ExternalChannelConfigurationError(ValueError):
    """Raised when the configured external messaging channel is invalid."""


def resolve_external_channel(raw_value: str | None = None) -> ExternalChannel:
    """Return the validated external messaging channel without side effects.

    A missing environment setting preserves the existing Telegram behavior.
    Explicit blank or unsupported values fail closed so a transport is never
    selected accidentally.
    """
    configured = (
        os.getenv(EXTERNAL_CHANNEL_ENV_VAR)
        if raw_value is None
        else raw_value
    )
    if configured is None:
        return DEFAULT_EXTERNAL_CHANNEL

    normalized = configured.strip().lower()
    if normalized not in SUPPORTED_EXTERNAL_CHANNELS:
        supported = ", ".join(sorted(SUPPORTED_EXTERNAL_CHANNELS))
        raise ExternalChannelConfigurationError(
            f"{EXTERNAL_CHANNEL_ENV_VAR} must be one of: {supported}."
        )

    return cast(ExternalChannel, normalized)
