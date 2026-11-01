"""Matrix-local Greek/Georgian translation command state."""

from __future__ import annotations

import threading
import time
from collections.abc import Awaitable, Callable

GEORGIAN_QUICK_PHRASES_ALIASES = frozenset(
    {"/georgian_phrases", "/g_phrases"}
)
GEORGIAN_COMMAND_ALIASES = frozenset({"/georgian", "/geo", "/g"}) | (
    GEORGIAN_QUICK_PHRASES_ALIASES
)
GREEK_COMMAND_ALIASES = frozenset({"/gr", "/greek"})

TextTurn = Callable[[str, str], Awaitable[object]]
Translator = Callable[..., dict[str, str]]


def format_translation(result: dict[str, str]) -> str:
    """Format a translation for plain-text external channels."""
    translated = str(result.get("translated") or "").strip()
    target = str(result.get("tgt") or "").strip().lower()
    flag = "🇬🇪" if target == "ka" else "🇬🇷"
    reply = f"{flag} {translated}"
    phonetic = str(result.get("phonetic") or "").strip()
    if phonetic:
        reply += f"\n📢 {phonetic}"
    return reply


class MatrixGeorgianTurnRouter:
    """Handle translation commands without sharing pending state across channels."""

    def __init__(
        self,
        *,
        text_turn: TextTurn,
        translate: Translator,
        phrases_message: Callable[[], str],
        prompt_greek_to_georgian: str,
        prompt_georgian_to_greek: str,
        ttl_seconds: float = 120.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if ttl_seconds <= 0:
            raise ValueError("Georgian pending-mode TTL must be positive")
        self._text_turn = text_turn
        self._translate = translate
        self._phrases_message = phrases_message
        self._prompt_greek_to_georgian = prompt_greek_to_georgian
        self._prompt_georgian_to_greek = prompt_georgian_to_greek
        self._ttl_seconds = float(ttl_seconds)
        self._clock = clock
        self._lock = threading.Lock()
        self._pending_mode: tuple[str, float] | None = None

    def _arm(self, source: str) -> None:
        with self._lock:
            self._pending_mode = (source, self._clock() + self._ttl_seconds)

    def _consume(self) -> str | None:
        with self._lock:
            pending = self._pending_mode
            self._pending_mode = None
        if pending is None or self._clock() > pending[1]:
            return None
        return pending[0]

    def _clear(self) -> None:
        with self._lock:
            self._pending_mode = None

    def _translated(self, text: str, *, source: str) -> str:
        return format_translation(self._translate(text, src=source))

    async def __call__(self, user_text: str, event_id: str) -> object:
        """Handle one translation command or delegate the untouched turn."""
        normalized = str(user_text or "").strip()
        lowered = normalized.lower()
        command, _, rest = lowered.partition(" ")
        original_rest = normalized[len(command) :].strip()

        if not lowered.startswith("/"):
            pending_source = self._consume()
            if pending_source is not None:
                return self._translated(normalized, source=pending_source)
            return await self._text_turn(normalized, event_id)

        if command in GEORGIAN_QUICK_PHRASES_ALIASES:
            self._clear()
            return self._phrases_message()
        if command in GEORGIAN_COMMAND_ALIASES:
            self._clear()
            if not original_rest:
                self._arm("auto")
                return self._prompt_greek_to_georgian
            if original_rest.lower() == "phrases":
                return self._phrases_message()
            return self._translated(original_rest, source="auto")
        if command in GREEK_COMMAND_ALIASES:
            self._clear()
            if not original_rest:
                self._arm("ka")
                return self._prompt_georgian_to_greek
            return self._translated(original_rest, source="ka")

        self._clear()
        return await self._text_turn(normalized, event_id)
