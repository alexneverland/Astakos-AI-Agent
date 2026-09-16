"""Matrix document analysis, history, and pending-archive lifecycle."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

from clients.matrix_media import MatrixMediaAsset
from config import CONVERSATION_DB_FILE
from core.untrusted_content import (
    USER_PROVIDED_ASSET_SOURCE,
    external_content_history_metadata,
    format_untrusted_tool_result,
)
from memory.conversation_history import append_message
from memory.pending_assets import create_pending_asset_archive, init_pending_assets_table
from services.document_analysis import summarize_document_text
from services.document_input import SUPPORTED_DOCUMENT_EXTENSIONS, extract_document_preview
from services.pending_asset_confirmation import build_asset_archive_prompt

DocumentAnalyzer = Callable[[MatrixMediaAsset], str]
PersistedHook = Callable[[dict[str, Any]], None]
CompletedHook = Callable[[str, str, str, str], None]


def analyze_matrix_document(asset: MatrixMediaAsset) -> str:
    """Run the shared bounded reader and LLM summary for one Matrix document."""
    import config
    from core.i18n import t

    try:
        document_text = extract_document_preview(asset.path, max_chars=8000)
    except Exception as exc:
        document_text = f"[Could not read content: {exc}]"
    return summarize_document_text(
        document_text=document_text,
        file_name=asset.original_name or asset.path.name,
        caption="",
        channel="matrix",
        language=config.RESPONSE_LANGUAGE,
        user_name=config.USER_NAME,
        missing_context=t("clients.telegram_bot.bot_msg_98937a"),
        missing_caption=t("clients.telegram_bot.bot_msg_05a606"),
        empty_reply=t("clients.telegram_bot.bot_msg_33d466"),
    )


class MatrixDocumentTurnService:
    """Analyze and persist one supported Matrix document without cross-channel state."""

    def __init__(
        self,
        *,
        analyze_document: DocumentAnalyzer = analyze_matrix_document,
        conversation_db_path: str = CONVERSATION_DB_FILE,
        on_user_persisted: PersistedHook | None = None,
        on_exchange_completed: CompletedHook | None = None,
    ) -> None:
        self._analyze_document = analyze_document
        self._conversation_db_path = conversation_db_path
        self._on_user_persisted = on_user_persisted
        self._on_exchange_completed = on_exchange_completed

    @staticmethod
    def _display_name(asset: MatrixMediaAsset) -> str:
        raw = str(asset.original_name or asset.path.name).replace("\\", "/")
        basename = raw.rsplit("/", 1)[-1]
        cleaned = "".join(ch for ch in basename if ch.isprintable() and ch != "`")
        return cleaned.strip()[:255] or asset.path.name

    @staticmethod
    def _run_hook(hook: Callable[..., None] | None, *args: Any) -> None:
        if hook is None:
            return
        try:
            hook(*args)
        except Exception as exc:
            print(f"[MatrixDocument]: post-turn hook failed: {type(exc).__name__}")

    async def __call__(self, asset: MatrixMediaAsset) -> str:
        """Return one document summary and create a Matrix-only archive prompt."""
        if asset.kind != "file":
            raise ValueError("Matrix document turn requires a file asset")
        suffix = asset.path.suffix.lower()
        if suffix not in SUPPORTED_DOCUMENT_EXTENSIONS:
            return f"⚠️ Unsupported document type: {suffix or '(none)'}"

        analysis = str(
            await asyncio.to_thread(self._analyze_document, asset) or ""
        ).strip()
        if not analysis:
            analysis = "No document analysis available."
        display_name = self._display_name(asset)
        reply = (
            f"📄 **Document:** `{display_name}`\n\n"
            f"{analysis}"
            f"{build_asset_archive_prompt('document')}"
        )
        metadata = {
            "transport": "matrix",
            "matrix_event_id": asset.event_id,
            **external_content_history_metadata([USER_PROVIDED_ASSET_SOURCE]),
        }
        user_log = (
            f"[USER_UPLOADED_FILE]: {display_name}\n"
            f"[FILE PATH]: {asset.path}\n"
            "[ANALYSIS]: "
            f"{format_untrusted_tool_result(USER_PROVIDED_ASSET_SOURCE, analysis[:500])}\n"
            "[CONTENT_SOURCE]: uploaded_document"
        )
        saved_user = append_message(
            role="user",
            content=user_log,
            channel="matrix",
            metadata=metadata,
            db_path=self._conversation_db_path,
        )
        append_message(
            role="assistant",
            content=reply,
            channel="matrix",
            agent="Chat_Agent",
            metadata=metadata,
            db_path=self._conversation_db_path,
        )
        init_pending_assets_table()
        create_pending_asset_archive(
            channel="matrix",
            asset_type="document",
            file_path=str(asset.path),
            filename=display_name,
            analysis=analysis[:500],
            caption="",
            external_content_sources=[USER_PROVIDED_ASSET_SOURCE],
        )
        self._run_hook(self._on_user_persisted, saved_user)
        self._run_hook(
            self._on_exchange_completed,
            display_name,
            "",
            "Chat_Agent",
            "matrix",
        )
        return reply
