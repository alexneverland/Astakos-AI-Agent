"""Matrix adapters for Astakos's existing background behavior pipelines."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from config import CONVERSATION_DB_FILE

from memory.pending_followups import process_followup_exchange
from memory.session_memory import (
    log_exchange,
    run_memory_sifter_fast,
    run_memory_sifter_slow,
)
from memory.working_memory import update_working_memory
from services.behavioral_event_scheduler import schedule_persisted_user_intake
from services.context_extractor import extract_and_update_context_flags

TaskEnqueuer = Callable[..., None]
SessionFinalizer = Callable[..., None]


@dataclass(frozen=True)
class MatrixChannelServices:
    """Fully composed inbound text and media application handlers."""

    text_handler: Any
    media_handler: Any
    location_handler: Any | None = None


def run_slow_memory_pipeline(
    user_text: str,
    ai_text: str,
    agent_name: str,
    channel: str,
    enqueue_slow_task: TaskEnqueuer,
) -> None:
    """Run the fast sift, then queue the existing slow memory pass."""
    seed_facts = run_memory_sifter_fast(user_text, ai_text, agent_name, channel)
    enqueue_slow_task(
        run_memory_sifter_slow,
        user_text,
        ai_text,
        agent_name,
        channel,
        seed_facts,
        True,
    )


def run_followup_pipeline(
    user_text: str,
    ai_text: str,
    agent_name: str,
    channel: str,
) -> None:
    """Feed one completed Matrix exchange to the shared follow-up engine."""
    process_followup_exchange(
        user_text=user_text,
        ai_text=ai_text,
        agent_name=agent_name,
        channel=channel,
    )


class MatrixBackgroundHooks:
    """Connect trusted Matrix turns to existing asynchronous background work."""

    def __init__(
        self,
        *,
        enqueue_fast_task: TaskEnqueuer,
        enqueue_slow_task: TaskEnqueuer,
    ) -> None:
        self._enqueue_fast_task = enqueue_fast_task
        self._enqueue_slow_task = enqueue_slow_task

    def on_user_persisted(self, saved_message: dict[str, Any]) -> None:
        """Schedule behavioral-pattern intake for a newly persisted Matrix user."""
        if saved_message.get("channel") != "matrix":
            raise ValueError("Matrix background hooks require channel='matrix'")
        schedule_persisted_user_intake(
            rowid=saved_message.get("rowid"),
            metadata=saved_message.get("metadata"),
            enqueue_slow_task=self._enqueue_slow_task,
        )

    def on_exchange_completed(
        self,
        user_text: str,
        ai_text: str,
        agent_name: str,
        channel: str,
    ) -> None:
        """Queue the same memory, follow-up, and context pipelines as other channels."""
        if channel != "matrix":
            raise ValueError("Matrix background hooks require channel='matrix'")

        self._enqueue_fast_task(
            log_exchange,
            user_text,
            ai_text,
            agent_name,
            channel,
        )
        self._enqueue_fast_task(update_working_memory, user_text, ai_text)
        self._enqueue_fast_task(
            run_slow_memory_pipeline,
            user_text,
            ai_text,
            agent_name,
            channel,
            self._enqueue_slow_task,
        )
        self._enqueue_slow_task(
            run_followup_pipeline,
            user_text,
            ai_text,
            agent_name,
            channel,
        )
        self._enqueue_slow_task(
            extract_and_update_context_flags,
            user_text,
            ai_text,
        )


def build_matrix_turn_service(
    *,
    enqueue_fast_task: TaskEnqueuer,
    enqueue_slow_task: TaskEnqueuer,
    graph: Any | None = None,
    conversation_db_path: str = CONVERSATION_DB_FILE,
    command_handler: Callable[[str], str | None] | None = None,
):
    """Build a Matrix turn service with all required background hooks attached."""
    from services.matrix_turn import MatrixTurnService
    from services.matrix_routine_completion import process_pending_routine_confirmation

    hooks = MatrixBackgroundHooks(
        enqueue_fast_task=enqueue_fast_task,
        enqueue_slow_task=enqueue_slow_task,
    )
    return MatrixTurnService(
        graph=graph,
        conversation_db_path=conversation_db_path,
        on_user_persisted=hooks.on_user_persisted,
        on_exchange_completed=hooks.on_exchange_completed,
        command_handler=command_handler,
        routine_confirmation_handler=process_pending_routine_confirmation,
    )


def build_matrix_channel_services(
    *,
    enqueue_fast_task: TaskEnqueuer,
    enqueue_slow_task: TaskEnqueuer,
    graph: Any | None = None,
    conversation_db_path: str = CONVERSATION_DB_FILE,
    command_handler: Callable[[str], str | None] | None = None,
    session_finalizer: SessionFinalizer | None = None,
    story_maker: Callable[[str, str], dict[str, Any]] | None = None,
    record_location: Callable[..., str | None] | None = None,
    analyze_image: Callable[..., str] | None = None,
    transcribe_audio: Callable[..., str] | None = None,
    analyze_document: Callable[..., str] | None = None,
    memory_store: Any | None = None,
) -> MatrixChannelServices:
    """Compose Matrix text, media, pending-photo, and archive-confirmation flows."""
    from core.i18n import t
    from services.image_input import analyze_image_bytes
    from services.matrix_document_turn import (
        MatrixDocumentTurnService,
        analyze_matrix_document,
    )
    from services.matrix_media_turn import (
        MatrixInboundTurnRouter,
        MatrixMediaTurnService,
    )
    from services.matrix_turn import MatrixTurnService
    from services.matrix_routine_completion import process_pending_routine_confirmation
    from services.matrix_georgian_turn import MatrixGeorgianTurnRouter
    from services.location_update import record_location_update
    from services.matrix_voice_mode import MatrixVoiceModeRouter
    from services.pending_asset_confirmation import PendingAssetConfirmationService
    from services.photo_commands import analyze_nutrition_photo, scan_receipt_photo
    from services.session_end import finalize_session
    from services.story_generation import generate_story
    from tools.georgian import phrases_message, translate
    from services.voice_input import transcribe_voice_audio

    if memory_store is None:
        from memory.vector_store import memory as default_memory

        memory_store = default_memory

    hooks = MatrixBackgroundHooks(
        enqueue_fast_task=enqueue_fast_task,
        enqueue_slow_task=enqueue_slow_task,
    )
    finalize = session_finalizer or finalize_session
    make_story = story_maker or generate_story
    save_location = record_location or record_location_update

    async def matrix_location_handler(
        latitude: float,
        longitude: float,
        live_update: bool,
    ) -> str | None:
        """Persist a trusted Matrix location without blocking the sync loop."""
        import asyncio

        return await asyncio.to_thread(
            save_location,
            latitude,
            longitude,
            live_update=live_update,
        )

    def matrix_command_handler(user_text: str):
        """Handle Matrix-owned commands before delegating shared admin commands."""
        normalized = str(user_text or "").strip()
        command = normalized.lower()
        if command == "/story" or command.startswith("/story "):
            rest = normalized[len("/story") :].strip()
            if "|" in rest:
                theme, characters = (part.strip() for part in rest.split("|", 1))
            else:
                theme, characters = rest, ""
            theme = theme or t("clients.telegram_bot.bot_msg_9e64ca")
            result = make_story(theme, characters)
            if result.get("error") or not result.get("story"):
                error = result.get("error") or t("clients.telegram_bot.bot_msg_cf83ee")
                return f"❌ {error}"
            from clients.matrix_client import MatrixReply

            images = tuple(str(path) for path in result.get("images", []) if path)[:5]
            return MatrixReply(
                f"📖 Story: {theme}\n\n{result['story']}",
                "text",
                images,
            )
        if command != "/end":
            return command_handler(user_text) if command_handler is not None else None
        try:
            finalize(channel="matrix")
        except Exception as exc:
            print(f"[Matrix End Session Error]: {exc}")
            return t("services.session_end.error")
        print("[Matrix]: Session closed and archived successfully.")
        return t("clients.telegram_bot.bot_msg_bfe08b")

    text_turn = MatrixTurnService(
        graph=graph,
        conversation_db_path=conversation_db_path,
        on_user_persisted=hooks.on_user_persisted,
        on_exchange_completed=hooks.on_exchange_completed,
        command_handler=matrix_command_handler,
        routine_confirmation_handler=process_pending_routine_confirmation,
    )
    georgian_turn = MatrixGeorgianTurnRouter(
        text_turn=text_turn,
        translate=translate,
        phrases_message=phrases_message,
        prompt_greek_to_georgian=t("clients.telegram_bot.bot_msg_42fbb6"),
        prompt_georgian_to_greek=t("clients.telegram_bot.bot_msg_bdc64e"),
    )
    voice_turn = MatrixVoiceModeRouter(
        text_turn=georgian_turn,
        enabled_reply=t("clients.telegram_bot.bot_msg_c19e9a"),
        disabled_reply=t("clients.telegram_bot.bot_msg_adde11"),
    )
    document_turn = MatrixDocumentTurnService(
        analyze_document=analyze_document or analyze_matrix_document,
        conversation_db_path=conversation_db_path,
        on_user_persisted=hooks.on_user_persisted,
        on_exchange_completed=hooks.on_exchange_completed,
    )
    media_turn = MatrixMediaTurnService(
        matrix_turn=voice_turn,
        silence_reply=t("clients.telegram_bot.bot_msg_dacaa2"),
        transcribe_audio=transcribe_audio or transcribe_voice_audio,
        analyze_image=analyze_image or analyze_image_bytes,
        vision_prompt=t("clients.telegram_bot.bot_msg_dec305"),
        photo_received_reply=t("clients.telegram_bot.bot_msg_477e48"),
        asset_question_turn=text_turn.run_asset_question,
        document_turn=document_turn,
        analyze_nutrition=analyze_nutrition_photo,
        scan_receipt=scan_receipt_photo,
        missing_nutrition_photo_reply=t("clients.telegram_bot.bot_msg_28166e"),
        missing_receipt_photo_reply=t("clients.telegram_bot.bot_msg_f4f189"),
    )
    confirmation = PendingAssetConfirmationService(
        channel="matrix",
        memory_store=memory_store,
        conversation_db_path=conversation_db_path,
        confirm_reply=t("clients.telegram_bot.bot_msg_7e53ac"),
        cancel_reply=t("clients.telegram_bot.bot_msg_b026c8"),
        on_user_persisted=hooks.on_user_persisted,
        on_exchange_completed=hooks.on_exchange_completed,
    )
    return MatrixChannelServices(
        text_handler=MatrixInboundTurnRouter(
            text_turn=voice_turn,
            media_turn=media_turn,
            pending_asset_confirmation=confirmation,
        ),
        media_handler=media_turn,
        location_handler=matrix_location_handler,
    )
