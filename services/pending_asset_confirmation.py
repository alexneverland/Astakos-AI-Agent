"""Channel-neutral confirmation of pending user asset archives."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

from config import CONVERSATION_DB_FILE
from memory.conversation_history import append_message
from memory.pending_assets import (
    classify_pending_asset_reply,
    clear_expired_pending_assets,
    get_latest_pending_asset,
    init_pending_assets_table,
    is_reply_to_recent_asset_prompt,
    mark_pending_asset_cancelled,
    mark_pending_asset_confirmed,
)

PersistedHook = Callable[[dict[str, Any]], None]
CompletedHook = Callable[[str, str, str, str], None]


def build_asset_archive_prompt(asset_type: str) -> str:
    """Build a localized prompt that the canonical reply classifier recognizes."""
    from core.i18n import t

    phrase_key = "prompts.ext_str_8" if asset_type == "photo" else "prompts.ext_str_10"
    question = str(t(phrase_key)).strip()
    answer_only = str(t("prompts.ext_str_60")).strip()
    yes_or_no = str(t("prompts.ext_str_262")).strip()
    return (
        f"\n\n**{question[:1].upper() + question[1:]}?**\n"
        f"{answer_only[:1].upper() + answer_only[1:]}: {yes_or_no}."
    )


class PendingAssetConfirmationService:
    """Consume an explicit yes/no only when the channel has a recent asset prompt."""

    def __init__(
        self,
        *,
        channel: str,
        memory_store: Any,
        confirm_reply: str,
        cancel_reply: str,
        conversation_db_path: str = CONVERSATION_DB_FILE,
        on_user_persisted: PersistedHook | None = None,
        on_exchange_completed: CompletedHook | None = None,
    ) -> None:
        normalized_channel = str(channel or "").strip()
        if not normalized_channel:
            raise ValueError("Pending asset confirmation requires a channel")
        self._channel = normalized_channel
        self._memory_store = memory_store
        self._conversation_db_path = conversation_db_path
        self._confirm_reply = str(confirm_reply or "").strip()
        self._cancel_reply = str(cancel_reply or "").strip()
        if not self._confirm_reply or not self._cancel_reply:
            raise ValueError("Pending asset confirmation requires both replies")
        self._on_user_persisted = on_user_persisted
        self._on_exchange_completed = on_exchange_completed

    @staticmethod
    def _run_hook(hook: Callable[..., None] | None, *args: Any) -> None:
        if hook is None:
            return
        try:
            hook(*args)
        except Exception as exc:
            print(f"[PendingAsset]: post-turn hook failed: {type(exc).__name__}")

    async def __call__(self, user_text: str, event_id: str) -> str | None:
        """Confirm/cancel a recent channel-local asset prompt, or decline handling."""
        init_pending_assets_table()
        clear_expired_pending_assets()
        pending = get_latest_pending_asset(self._channel, "photo")
        if pending is None:
            pending = get_latest_pending_asset(self._channel, "document")
        if pending is None:
            return None

        reply_kind = classify_pending_asset_reply(user_text)
        if reply_kind not in {"yes", "no"}:
            return None
        if not is_reply_to_recent_asset_prompt(
            self._channel,
            db_path=self._conversation_db_path,
        ):
            print(
                "[PendingAssetGuard]: ignored generic yes/no because no recent "
                "archive prompt was active"
            )
            return None

        if reply_kind == "yes":
            await asyncio.to_thread(
                self._memory_store.save,
                memory_type=pending["asset_type"],
                file_path=pending["file_path"],
                analysis=pending.get("analysis", ""),
                caption=pending.get("caption", "") or pending["filename"],
                external_content_sources=pending.get("external_content_sources", []),
            )
            mark_pending_asset_confirmed(pending["id"])
            response = self._confirm_reply
        else:
            mark_pending_asset_cancelled(pending["id"])
            response = self._cancel_reply

        metadata = {
            "transport": self._channel,
            "matrix_event_id": str(event_id or "").strip(),
        }
        saved_user = append_message(
            role="user",
            content=str(user_text or "").strip(),
            channel=self._channel,
            metadata=metadata,
            db_path=self._conversation_db_path,
        )
        append_message(
            role="assistant",
            content=response,
            channel=self._channel,
            agent="Chat_Agent",
            metadata=metadata,
            db_path=self._conversation_db_path,
        )
        self._run_hook(self._on_user_persisted, saved_user)
        self._run_hook(
            self._on_exchange_completed,
            str(user_text or "").strip(),
            response,
            "Chat_Agent",
            self._channel,
        )
        return response
