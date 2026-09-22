"""Channel-neutral confirmation of pending user asset archives."""

from __future__ import annotations

import asyncio
import hashlib
import os
import shutil
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

from config import CONVERSATION_DB_FILE, PHOTOS_DIR
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


def _canonical_photo_archive_path(file_path: str) -> str:
    """Copy a confirmed photo into the shared permanent photo directory."""
    source = Path(file_path).resolve()
    if not source.is_file():
        raise FileNotFoundError(f"Confirmed photo does not exist: {source}")

    archive_dir = Path(PHOTOS_DIR).resolve()
    archive_dir.mkdir(parents=True, exist_ok=True)
    if source.parent == archive_dir:
        return str(source)

    digest = hashlib.sha256()
    with source.open("rb") as source_file:
        for chunk in iter(lambda: source_file.read(1024 * 1024), b""):
            digest.update(chunk)

    suffix = source.suffix.lower()
    if (
        len(suffix) <= 1
        or len(suffix) > 10
        or any(not (character.isascii() and character.isalnum()) for character in suffix[1:])
    ):
        suffix = ".bin"
    target = archive_dir / f"photo_{digest.hexdigest()[:24]}{suffix}"
    if target.is_file():
        return str(target)

    temporary_path: Path | None = None
    try:
        with source.open("rb") as source_file, tempfile.NamedTemporaryFile(
            mode="wb",
            dir=archive_dir,
            prefix=".photo-",
            suffix=".part",
            delete=False,
        ) as temporary_file:
            shutil.copyfileobj(source_file, temporary_file)
            temporary_file.flush()
            os.fsync(temporary_file.fileno())
            temporary_path = Path(temporary_file.name)
        os.replace(temporary_path, target)
        temporary_path = None
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
    return str(target)


def save_confirmed_asset(memory_store: Any, pending: dict[str, Any]) -> Any:
    """Persist one confirmed asset through the canonical channel-neutral path."""
    archive_path = pending["file_path"]
    if pending["asset_type"] == "photo":
        archive_path = _canonical_photo_archive_path(archive_path)
    return memory_store.save(
        memory_type=pending["asset_type"],
        file_path=archive_path,
        analysis=pending.get("analysis", ""),
        caption=pending.get("caption", "") or pending["filename"],
        external_content_sources=pending.get("external_content_sources", []),
    )


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


def build_photo_share_request() -> str:
    """Return the localized natural-language request used for a captionless photo."""
    from core.i18n import t

    return str(t("services.pending_asset_confirmation.photo_share_request")).strip()


def ensure_asset_archive_prompt(reply_text: str, asset_type: str) -> str:
    """Append one canonical archive question when the model omitted it."""
    from memory.pending_assets import looks_like_asset_confirmation_prompt

    normalized_reply = str(reply_text or "").strip()
    if not normalized_reply:
        return normalized_reply
    if looks_like_asset_confirmation_prompt(normalized_reply):
        return normalized_reply
    return normalized_reply + build_asset_archive_prompt(asset_type)


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
                save_confirmed_asset,
                self._memory_store,
                pending,
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
