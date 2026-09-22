"""Matrix application turns through the existing Astakos graph."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import datetime
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from clients.matrix_client import MatrixReply
from config import CONVERSATION_DB_FILE
from core.utils import clean_message
from memory.conversation_history import (
    append_message,
    load_recent_context,
)

UserPersistedHook = Callable[[dict[str, Any]], None]
ExchangeCompletedHook = Callable[[str, str, str, str], None]
ToolChannelSelector = Callable[[str], None]
CommandHandler = Callable[[str], str | MatrixReply | None]
RoutineConfirmationHandler = Callable[[str], Any | None]


def _select_default_tool_channel(channel: str) -> None:
    """Set the channel used by tools inside this process's graph invocation."""
    import tools.system as system_tools

    system_tools._CURRENT_CHANNEL = channel


class MatrixTurnService:
    """Persist and process one trusted Matrix text turn."""

    def __init__(
        self,
        *,
        graph: Any | None = None,
        conversation_db_path: str = CONVERSATION_DB_FILE,
        on_user_persisted: UserPersistedHook | None = None,
        on_exchange_completed: ExchangeCompletedHook | None = None,
        select_tool_channel: ToolChannelSelector = _select_default_tool_channel,
        command_handler: CommandHandler | None = None,
        routine_confirmation_handler: RoutineConfirmationHandler | None = None,
    ) -> None:
        if graph is None:
            from core.graph import graph as default_graph

            graph = default_graph
        self._graph = graph
        self._conversation_db_path = conversation_db_path
        self._on_user_persisted = on_user_persisted
        self._on_exchange_completed = on_exchange_completed
        self._select_tool_channel = select_tool_channel
        self._command_handler = command_handler
        self._routine_confirmation_handler = routine_confirmation_handler

    async def __call__(self, user_text: str, event_id: str) -> str | MatrixReply:
        """Run the blocking graph outside the Matrix sync event loop."""
        return await asyncio.to_thread(self._run_sync, user_text, event_id)

    async def run_asset_question(
        self,
        *,
        question: str,
        event_id: str,
        filename: str,
        file_path: str,
        analysis: str,
    ) -> str | MatrixReply:
        """Run a photo question while persisting only the user-visible question."""
        from core.untrusted_content import user_asset_history_metadata

        asset_metadata = user_asset_history_metadata(
            filename=filename,
            file_path=file_path,
            analysis=analysis,
        )
        reply = await asyncio.to_thread(
            self._run_sync,
            question,
            event_id,
            asset_metadata,
            True,
            False,
            "photo",
        )
        from memory.pending_assets import (
            create_pending_asset_archive,
            init_pending_assets_table,
        )
        from core.untrusted_content import USER_PROVIDED_ASSET_SOURCE

        raw_name = str(filename or "").replace("\\", "/").rsplit("/", 1)[-1]
        safe_name = "".join(
            ch for ch in raw_name if ch.isprintable() and ch != "`"
        ).strip()[:255]
        init_pending_assets_table()
        create_pending_asset_archive(
            channel="matrix",
            asset_type="photo",
            file_path=file_path,
            filename=safe_name or "matrix_photo",
            analysis=analysis,
            caption=question,
            external_content_sources=[USER_PROVIDED_ASSET_SOURCE],
        )
        return reply

    @staticmethod
    def _run_hook(hook: Callable[..., None] | None, *args: Any, **kwargs: Any) -> None:
        """Keep an optional background hook failure from losing the reply."""
        if hook is None:
            return
        try:
            if kwargs:
                import inspect
                try:
                    sig = inspect.signature(hook)
                    has_var_kw = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values())
                    if has_var_kw:
                        hook(*args, **kwargs)
                        return
                    accepted_kwargs = {k: v for k, v in kwargs.items() if k in sig.parameters}
                    hook(*args, **accepted_kwargs)
                    return
                except (ValueError, TypeError):
                    pass
            hook(*args)
        except Exception as exc:
            print(f"[MatrixTurn]: post-turn hook failed: {type(exc).__name__}")

    def _history_messages(self, *, exclude_message_id: str) -> list[Any]:
        entries = load_recent_context(
            channel="matrix",
            channel_limit=10,
            total_limit=10,
            same_channel_only=True,
            db_path=self._conversation_db_path,
        )
        messages: list[Any] = []
        from core.untrusted_content import (
            format_model_history_content,
            history_message_additional_kwargs,
        )

        for entry in entries:
            if entry.get("id") == exclude_message_id:
                continue
            content = str(entry.get("content") or "").strip()
            if not content:
                continue
            prefix = (
                f"[{entry.get('date', '')} {entry.get('time', '')} "
                f"/ {entry.get('channel', '')}] "
            )
            formatted = format_model_history_content(
                f"{prefix}{content}",
                entry.get("metadata"),
            )
            kwargs = history_message_additional_kwargs(entry.get("metadata"))
            if entry.get("role") in {"user", "human", "Human"}:
                messages.append(HumanMessage(content=formatted, additional_kwargs=kwargs))
            else:
                messages.append(AIMessage(content=formatted, additional_kwargs=kwargs))
        return messages

    def _run_sync(
        self,
        user_text: str,
        event_id: str,
        user_metadata_extra: dict[str, Any] | None = None,
        external_derived: bool = False,
        allow_commands: bool = True,
        ensure_asset_prompt_type: str | None = None,
    ) -> str | MatrixReply:
        clean_user_text = str(user_text or "").strip()
        if not clean_user_text:
            raise ValueError("Matrix turn requires non-empty user text")
        normalized_event_id = str(event_id or "").strip()
        if not normalized_event_id:
            raise ValueError("Matrix turn requires event_id")

        if (
            allow_commands
            and clean_user_text.startswith("/")
            and self._command_handler is not None
        ):
            command_reply = self._command_handler(clean_user_text)
            if command_reply is not None:
                if isinstance(command_reply, MatrixReply):
                    if not str(command_reply.text or "").strip():
                        raise ValueError("Matrix command handler returned an empty reply")
                    return command_reply
                normalized_reply = str(command_reply).strip()
                if not normalized_reply:
                    raise ValueError("Matrix command handler returned an empty reply")
                return normalized_reply

        routine_completion_context = None
        routine_draft_offer = None
        if self._routine_confirmation_handler is not None:
            try:
                routine_result = self._routine_confirmation_handler(clean_user_text)
                from services.matrix_routine_completion import MatrixRoutineDraftOffer

                if isinstance(routine_result, MatrixRoutineDraftOffer):
                    routine_draft_offer = routine_result
                    routine_completion_context = routine_result.context
                else:
                    routine_completion_context = routine_result
            except Exception as exc:
                print(
                    "[MatrixTurn]: routine confirmation failed: "
                    f"{type(exc).__name__}"
                )

        provenance = {
            "transport": "matrix",
            "matrix_event_id": normalized_event_id,
        }
        user_metadata = {**provenance, **(user_metadata_extra or {})}

        saved_user = append_message(
            role="user",
            content=clean_user_text,
            channel="matrix",
            metadata=user_metadata,
            db_path=self._conversation_db_path,
        )
        self._run_hook(self._on_user_persisted, saved_user)

        context = self._history_messages(exclude_message_id=str(saved_user["id"]))
        from core.untrusted_content import (
            external_content_history_metadata,
            format_model_history_content,
            history_message_additional_kwargs,
            USER_PROVIDED_ASSET_SOURCE,
        )

        current_content = format_model_history_content(clean_user_text, user_metadata)
        current = HumanMessage(
            content=f"[{datetime.now().strftime('%H:%M')}] {current_content}",
            additional_kwargs=history_message_additional_kwargs(user_metadata),
        )
        self._select_tool_channel("matrix")

        final_reply = ""
        handling_agent = "Chat_Agent"
        graph_messages = context + [current]
        if routine_completion_context is not None:
            graph_messages.append(routine_completion_context)
        graph_state: dict[str, Any] = {
            "messages": graph_messages,
            "channel": "matrix",
        }
        if routine_draft_offer is not None:
            graph_state["routine_draft_offer_authorized"] = True
        tool_results: list[str] = []
        for event in self._graph.stream(
            graph_state,
            {"recursion_limit": 100},
        ):
            for node, data in event.items():
                if data is None:
                    continue
                messages = data.get("messages", [])
                if node == "tools":
                    tool_results.extend(
                        clean_message(getattr(message, "content", "")).strip()
                        for message in messages
                        if getattr(message, "type", "") == "tool"
                    )
                    continue
                if node == "supervisor":
                    continue
                if not messages:
                    continue
                last_message = messages[-1]
                if getattr(last_message, "tool_calls", None):
                    continue
                candidate = clean_message(getattr(last_message, "content", "")).strip()
                if candidate and not candidate.startswith("[Tool Call:"):
                    handling_agent = node
                    final_reply = candidate

        if not final_reply:
            raise RuntimeError("Matrix graph produced no final reply")

        if ensure_asset_prompt_type is not None:
            from services.pending_asset_confirmation import ensure_asset_archive_prompt

            final_reply = ensure_asset_archive_prompt(
                final_reply,
                ensure_asset_prompt_type,
            )

        if routine_draft_offer is not None:
            from core.utils import looks_like_terminal_messenger_draft_result
            from memory.routine_db import acknowledge_pending_draft_offer
            from memory.event_log import log_event

            if any(
                looks_like_terminal_messenger_draft_result(result)
                for result in tool_results
            ) and acknowledge_pending_draft_offer(
                routine_draft_offer.routine_id,
                routine_draft_offer.sent_at,
            ):
                log_event(
                    "routines",
                    "routine_acknowledged",
                    routine_id=routine_draft_offer.routine_id,
                    event=routine_draft_offer.event_name,
                    debug_type="manual_control",
                    debug_source="user_message",
                    debug_effect="routine_changed",
                )

        from services.created_file import extract_created_files

        created_files = extract_created_files(final_reply)
        visible_reply = created_files.text
        if not visible_reply and created_files.paths:
            visible_reply = "Το αρχείο είναι έτοιμο."
        if not visible_reply:
            raise RuntimeError("Matrix graph produced no visible reply")

        assistant_metadata = dict(provenance)
        if external_derived:
            assistant_metadata.update(
                external_content_history_metadata([USER_PROVIDED_ASSET_SOURCE])
            )
        append_message(
            role="assistant",
            content=visible_reply,
            channel="matrix",
            agent=handling_agent,
            metadata=assistant_metadata,
            db_path=self._conversation_db_path,
        )
        external_sources = [USER_PROVIDED_ASSET_SOURCE] if external_derived else None
        self._run_hook(
            self._on_exchange_completed,
            clean_user_text,
            "" if external_derived else visible_reply,
            handling_agent,
            "matrix",
            external_content_sources=external_sources,
        )
        if created_files.paths:
            return MatrixReply(
                visible_reply,
                attachment_paths=created_files.paths,
            )
        return visible_reply
