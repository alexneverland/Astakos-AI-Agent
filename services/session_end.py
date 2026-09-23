"""Channel-neutral session finalization."""

from __future__ import annotations

from collections.abc import Callable
from os import PathLike
from pathlib import Path

SummaryRunner = Callable[..., bool | None]


def finalize_session(
    *,
    channel: str,
    summary_runner: SummaryRunner | None = None,
    working_memory_file: str | PathLike[str] | None = None,
    reset_text: str | None = None,
) -> None:
    """Archive pending exchanges, then reset the shared working-memory note."""
    normalized_channel = str(channel or "").strip().lower()
    if not normalized_channel:
        raise ValueError("Session finalization requires a channel")

    if summary_runner is None:
        from memory.session_memory import _run_session_summary

        summary_runner = _run_session_summary
    if working_memory_file is None:
        from config import WORKING_MEMORY_FILE

        working_memory_file = WORKING_MEMORY_FILE
    if reset_text is None:
        from core.i18n import t

        reset_text = t("clients.telegram_bot.bot_msg_4cd007")

    if summary_runner(channel=normalized_channel) is False:
        raise RuntimeError(f"Session archive failed for {normalized_channel}")
    Path(working_memory_file).write_text(reset_text, encoding="utf-8")
