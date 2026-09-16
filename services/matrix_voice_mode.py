"""Channel-local toggle for Matrix spoken assistant replies."""

from __future__ import annotations

import threading
from collections.abc import Awaitable, Callable

from clients.matrix_client import MatrixReply

TextTurn = Callable[[str, str], Awaitable[str | MatrixReply]]


class MatrixVoiceModeRouter:
    """Apply `/voice` to Matrix only and annotate durable reply delivery mode."""

    def __init__(
        self,
        *,
        text_turn: TextTurn,
        enabled_reply: str,
        disabled_reply: str,
    ) -> None:
        self._text_turn = text_turn
        self._enabled_reply = str(enabled_reply or "").strip()
        self._disabled_reply = str(disabled_reply or "").strip()
        if not self._enabled_reply or not self._disabled_reply:
            raise ValueError("Matrix voice mode requires toggle replies")
        self._enabled = False
        self._lock = threading.Lock()

    @property
    def enabled(self) -> bool:
        """Return current process-local Matrix voice mode."""
        with self._lock:
            return self._enabled

    async def __call__(self, user_text: str, event_id: str) -> MatrixReply:
        """Toggle on exact `/voice`, otherwise apply the current delivery mode."""
        normalized = str(user_text or "").strip()
        if normalized.lower() == "/voice":
            with self._lock:
                self._enabled = not self._enabled
                reply = self._enabled_reply if self._enabled else self._disabled_reply
            return MatrixReply(reply, "text")

        raw_reply = await self._text_turn(normalized, event_id)
        if isinstance(raw_reply, MatrixReply):
            reply_text = raw_reply.text
            attachment_paths = raw_reply.attachment_paths
        else:
            reply_text = str(raw_reply or "")
            attachment_paths = ()
        return MatrixReply(
            reply_text,
            "voice" if self.enabled else "text",
            attachment_paths,
        )
