"""Private encrypted Matrix text transport for Astakos.

The transport validates Matrix protocol events and delegates accepted text to
an injected application turn handler. It deliberately has no knowledge of the
Astakos graph, routines, approvals, or Telegram.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from nio import (
    ReactionEvent,
    RoomEncryptedAudio,
    RoomEncryptedFile,
    RoomEncryptedImage,
    RoomMessageText,
    RoomMessageUnknown,
    RoomSendError,
    SyncError,
    UnknownEvent,
)
from nio.exceptions import OlmUnverifiedDeviceError

from clients.matrix_media import MatrixMediaAsset

from memory.matrix_event_state import (
    list_pending_matrix_replies,
    mark_matrix_attachment_sent,
    mark_matrix_event_replied,
    mark_matrix_event_processed,
    mark_matrix_reply_text_sent,
    reserve_matrix_event,
    store_matrix_event_reply,
)


@dataclass(frozen=True)
class MatrixReply:
    """One durable Matrix reply with mode and generated-file attachments."""

    text: str
    mode: str = "text"
    attachment_paths: tuple[str, ...] = ()


MatrixTurnHandler = Callable[[str, str], Awaitable[str | MatrixReply]]
MatrixApprovalReactionHandler = Callable[..., Awaitable[str | None]]
MatrixMediaHandler = Callable[[MatrixMediaAsset], Awaitable[str]]
MatrixAttachmentSender = Callable[[str], Awaitable[Any]]
MatrixLocationHandler = Callable[[float, float, bool], Awaitable[str | None]]

_TYPING_TIMEOUT_MS = 30_000
_TYPING_REFRESH_SECONDS = 20.0


class MatrixTransportError(RuntimeError):
    """Raised when the Matrix transport cannot establish its live sync loop."""


class MatrixTextTransport:
    """Process trusted live encrypted text events from one Matrix room."""

    def __init__(
        self,
        *,
        client: Any,
        allowed_user_id: str,
        allowed_room_id: str,
        service_user_id: str,
        turn_handler: MatrixTurnHandler,
        state_db_path: str,
        text_event_type: type = RoomMessageText,
        reaction_event_type: type = ReactionEvent,
        approval_reaction_handler: MatrixApprovalReactionHandler | None = None,
        media_downloader: Any | None = None,
        media_handler: MatrixMediaHandler | None = None,
        media_event_types: tuple[type, ...] = (
            RoomEncryptedImage,
            RoomEncryptedFile,
            RoomEncryptedAudio,
        ),
        voice_sender: Callable[[str], Awaitable[Any]] | None = None,
        attachment_sender: MatrixAttachmentSender | None = None,
        location_handler: MatrixLocationHandler | None = None,
        location_event_types: tuple[type, ...] = (RoomMessageUnknown, UnknownEvent),
        send_error_types: tuple[type, ...] = (RoomSendError,),
        sync_error_types: tuple[type, ...] = (SyncError,),
        close_client_on_exit: bool = True,
    ) -> None:
        self._client = client
        self._allowed_user_id = self._required_id(allowed_user_id, "allowed_user_id")
        self._allowed_room_id = self._required_id(allowed_room_id, "allowed_room_id")
        self._service_user_id = self._required_id(service_user_id, "service_user_id")
        self._turn_handler = turn_handler
        self._state_db_path = state_db_path
        self._text_event_type = text_event_type
        self._reaction_event_type = reaction_event_type
        self._approval_reaction_handler = approval_reaction_handler
        if (media_downloader is None) != (media_handler is None):
            raise ValueError(
                "Matrix media_downloader and media_handler must be configured together"
            )
        self._media_downloader = media_downloader
        self._media_handler = media_handler
        self._media_event_types = media_event_types
        self._voice_sender = voice_sender
        self._attachment_sender = attachment_sender
        self._location_handler = location_handler
        self._location_event_types = location_event_types
        self._send_error_types = send_error_types
        self._sync_error_types = sync_error_types
        self._close_client_on_exit = bool(close_client_on_exit)

    @staticmethod
    def _required_id(value: str, field: str) -> str:
        normalized = str(value or "").strip()
        if not normalized:
            raise ValueError(f"Matrix transport requires {field}")
        return normalized

    @staticmethod
    def _normalize_reply(raw_reply: Any) -> tuple[str, str, tuple[str, ...]]:
        """Normalize application output into durable delivery state."""
        if isinstance(raw_reply, MatrixReply):
            reply_text = str(raw_reply.text or "").strip()
            reply_mode = str(raw_reply.mode or "").strip().lower()
            attachment_paths = tuple(
                path
                for raw_path in raw_reply.attachment_paths
                if (path := str(raw_path or "").strip())
            )
        else:
            reply_text = str(raw_reply or "").strip()
            reply_mode = "text"
            attachment_paths = ()
        if not reply_text:
            raise ValueError("Matrix handler must return a non-empty reply")
        if reply_mode not in {"text", "voice"}:
            raise ValueError("Matrix handler returned an invalid reply mode")
        if len(attachment_paths) > 5:
            raise ValueError("Matrix handler returned too many attachments")
        return reply_text, reply_mode, attachment_paths

    def _trusted_text(self, room: Any, event: Any) -> str | None:
        """Return trusted decrypted plain text or ``None`` for ignored events."""
        if str(getattr(room, "room_id", "")) != self._allowed_room_id:
            return None
        if getattr(room, "encrypted", False) is not True:
            return None
        if not isinstance(event, self._text_event_type):
            return None
        if getattr(event, "decrypted", False) is not True:
            return None

        sender = str(getattr(event, "sender", ""))
        if sender != self._allowed_user_id or sender == self._service_user_id:
            return None

        source = getattr(event, "source", None)
        if not isinstance(source, dict) or source.get("type") != "m.room.message":
            return None
        content = source.get("content")
        if not isinstance(content, dict) or content.get("msgtype") != "m.text":
            return None
        relation = content.get("m.relates_to")
        if isinstance(relation, dict) and relation.get("rel_type") == "m.replace":
            return None
        if "m.new_content" in content:
            return None

        body = str(getattr(event, "body", "") or "").strip()
        event_id = str(getattr(event, "event_id", "") or "").strip()
        if not body or not event_id:
            return None
        return body

    async def _send_text(self, room_id: str, reply_text: str) -> bool:
        """Send one Matrix text event, returning false for SDK send errors."""
        try:
            response = await self._client.room_send(
                room_id=room_id,
                message_type="m.room.message",
                content={"msgtype": "m.text", "body": reply_text},
            )
        except OlmUnverifiedDeviceError as exc:
            device = getattr(exc, "device", None)
            device_id = str(getattr(device, "id", "") or "unknown")
            print(
                "[Matrix]: Reply kept pending; owner device "
                f"{device_id} is not trusted."
            )
            return False
        if self._send_error_types and isinstance(response, self._send_error_types):
            return False
        return True

    async def _set_typing(self, typing_state: bool) -> None:
        """Best-effort typing state that never blocks an assistant reply."""
        try:
            await self._client.room_typing(
                self._allowed_room_id,
                typing_state=typing_state,
                timeout=_TYPING_TIMEOUT_MS,
            )
        except Exception as exc:
            print(f"[Matrix]: Typing notice failed: {type(exc).__name__}")

    async def _refresh_typing(self, stop: asyncio.Event) -> None:
        """Refresh Matrix typing before its server-side timeout expires."""
        while True:
            try:
                await asyncio.wait_for(
                    stop.wait(),
                    timeout=_TYPING_REFRESH_SECONDS,
                )
                return
            except TimeoutError:
                await self._set_typing(True)

    async def _run_while_typing(self, operation: Awaitable[Any]) -> Any:
        """Keep typing visible for one newly accepted application turn."""
        await self._set_typing(True)
        stop = asyncio.Event()
        refresher = asyncio.create_task(self._refresh_typing(stop))
        try:
            return await operation
        finally:
            stop.set()
            await refresher
            await self._set_typing(False)

    async def _send_reply(
        self,
        room_id: str,
        reply_text: str,
        reply_mode: str = "text",
    ) -> bool:
        """Deliver persisted text/voice with a safe in-channel text fallback."""
        if reply_mode == "voice" and self._voice_sender is not None:
            result = await self._voice_sender(reply_text)
            if bool(getattr(result, "sent", False)):
                return True
            notice = str(getattr(result, "fallback_notice", "") or "").strip()
            if notice:
                await self._send_text(room_id, notice)
        return await self._send_text(room_id, reply_text)

    async def _deliver_pending(self, item: dict[str, Any]) -> bool:
        """Deliver one saved reply without invoking the application handler."""
        event_id = str(item["event_id"])
        room_id = str(item["room_id"])
        reply_text = str(item["reply_text"])
        reply_mode = str(item.get("reply_mode") or "text")
        attachment_paths = tuple(item.get("attachment_paths") or ())
        text_sent = bool(item.get("text_sent", 0))
        attachments_sent_count = int(item.get("attachments_sent_count", 0))
        if room_id != self._allowed_room_id:
            return False
        if not text_sent:
            if not await self._send_reply(room_id, reply_text, reply_mode):
                return False
            mark_matrix_reply_text_sent(event_id, db_path=self._state_db_path)

        for index in range(attachments_sent_count, len(attachment_paths)):
            if self._attachment_sender is None:
                return False
            result = await self._attachment_sender(attachment_paths[index])
            if bool(getattr(result, "sent", False)):
                mark_matrix_attachment_sent(
                    event_id,
                    expected_index=index,
                    db_path=self._state_db_path,
                )
                continue
            if bool(getattr(result, "retryable", False)):
                return False
            notice = str(getattr(result, "fallback_notice", "") or "").strip()
            if notice and not await self._send_text(room_id, notice):
                return False
            mark_matrix_attachment_sent(
                event_id,
                expected_index=index,
                db_path=self._state_db_path,
            )
        mark_matrix_event_replied(event_id, db_path=self._state_db_path)
        return True

    async def handle_event(self, room: Any, event: Any) -> None:
        """Validate and process one live Matrix event at most once."""
        text = self._trusted_text(room, event)
        if text is None:
            return

        event_id = str(event.event_id).strip()
        reservation = reserve_matrix_event(
            event_id=event_id,
            room_id=self._allowed_room_id,
            sender_id=self._allowed_user_id,
            db_path=self._state_db_path,
        )
        status = reservation["status"]
        if reservation["action"] == "already_reserved":
            if status == "reply_pending":
                pending = list_pending_matrix_replies(db_path=self._state_db_path)
                for item in pending:
                    if item["event_id"] == event_id:
                        await self._deliver_pending(item)
                        break
            return

        reply_text, reply_mode, attachment_paths = self._normalize_reply(
            await self._run_while_typing(self._turn_handler(text, event_id))
        )
        store_matrix_event_reply(
            event_id,
            reply_text,
            reply_mode=reply_mode,
            attachment_paths=attachment_paths,
            db_path=self._state_db_path,
        )
        await self._deliver_pending(
            {
                "event_id": event_id,
                "room_id": self._allowed_room_id,
                "reply_text": reply_text,
                "reply_mode": reply_mode,
                "attachment_paths": attachment_paths,
                "text_sent": 0,
                "attachments_sent_count": 0,
            }
        )

    async def resend_pending_replies(self) -> None:
        """Retry saved outbound text without rerunning any assistant turn."""
        for item in list_pending_matrix_replies(db_path=self._state_db_path):
            await self._deliver_pending(item)

    async def handle_reaction_event(self, room: Any, event: Any) -> None:
        """Forward one trusted reaction from the encrypted room to approval."""
        if self._approval_reaction_handler is None:
            return
        if str(getattr(room, "room_id", "")) != self._allowed_room_id:
            return
        if getattr(room, "encrypted", False) is not True:
            return
        if not isinstance(event, self._reaction_event_type):
            return
        sender = str(getattr(event, "sender", ""))
        if sender != self._allowed_user_id or sender == self._service_user_id:
            return

        reaction_key = str(getattr(event, "key", "") or "")
        print(f"[Matrix Approval]: Trusted reaction received key={reaction_key!r}")

        response = await self._approval_reaction_handler(
            room_id=self._allowed_room_id,
            sender_id=sender,
            encrypted=True,
            reacts_to=str(getattr(event, "reacts_to", "") or "").strip(),
            key=reaction_key,
        )
        response_text = str(response or "").strip()
        if response_text:
            await self._send_reply(self._allowed_room_id, response_text)
        else:
            print("[Matrix Approval]: No matching active approval for reaction.")

    async def handle_media_event(self, room: Any, event: Any) -> None:
        """Download one trusted encrypted attachment and process it at most once."""
        if self._media_downloader is None or self._media_handler is None:
            return
        asset = await self._media_downloader.download(room, event)
        if asset is None:
            return

        event_id = str(asset.event_id).strip()
        reservation = reserve_matrix_event(
            event_id=event_id,
            room_id=self._allowed_room_id,
            sender_id=self._allowed_user_id,
            db_path=self._state_db_path,
        )
        status = reservation["status"]
        if reservation["action"] == "already_reserved":
            if status == "reply_pending":
                pending = list_pending_matrix_replies(db_path=self._state_db_path)
                for item in pending:
                    if item["event_id"] == event_id:
                        await self._deliver_pending(item)
                        break
            return

        reply_text, reply_mode, attachment_paths = self._normalize_reply(
            await self._run_while_typing(self._media_handler(asset))
        )
        store_matrix_event_reply(
            event_id,
            reply_text,
            reply_mode=reply_mode,
            attachment_paths=attachment_paths,
            db_path=self._state_db_path,
        )
        await self._deliver_pending(
            {
                "event_id": event_id,
                "room_id": self._allowed_room_id,
                "reply_text": reply_text,
                "reply_mode": reply_mode,
                "attachment_paths": attachment_paths,
                "text_sent": 0,
                "attachments_sent_count": 0,
            }
        )

    def _trusted_location(self, room: Any, event: Any) -> tuple[float, float, bool] | None:
        """Return validated coordinates from one trusted decrypted location event."""
        if str(getattr(room, "room_id", "")) != self._allowed_room_id:
            return None
        if getattr(room, "encrypted", False) is not True:
            return None
        if not isinstance(event, self._location_event_types):
            return None
        if getattr(event, "decrypted", False) is not True:
            return None
        sender = str(getattr(event, "sender", ""))
        if sender != self._allowed_user_id or sender == self._service_user_id:
            return None
        source = getattr(event, "source", None)
        if not isinstance(source, dict):
            return None
        content = source.get("content")
        if not isinstance(content, dict):
            return None
        event_type = str(source.get("type") or "")
        live_update = event_type in {"m.beacon", "org.matrix.msc3672.beacon"}
        if event_type == "m.room.message" and content.get("msgtype") == "m.location":
            geo_uri = content.get("geo_uri")
        elif live_update:
            location = content.get("m.location") or content.get("org.matrix.msc3488.location")
            geo_uri = location.get("uri") if isinstance(location, dict) else None
        else:
            return None
        from services.location_update import parse_geo_uri

        coordinates = parse_geo_uri(str(geo_uri or ""))
        if coordinates is None or not str(getattr(event, "event_id", "")).strip():
            return None
        return coordinates[0], coordinates[1], live_update

    async def handle_location_event(self, room: Any, event: Any) -> None:
        """Process one trusted location event once, with optional acknowledgement."""
        if self._location_handler is None:
            return
        location = self._trusted_location(room, event)
        if location is None:
            return
        event_id = str(event.event_id).strip()
        reservation = reserve_matrix_event(
            event_id=event_id,
            room_id=self._allowed_room_id,
            sender_id=self._allowed_user_id,
            db_path=self._state_db_path,
        )
        if reservation["action"] == "already_reserved":
            return
        reply = await self._location_handler(*location)
        reply_text = str(reply or "").strip()
        if not reply_text:
            mark_matrix_event_processed(event_id, db_path=self._state_db_path)
            return
        store_matrix_event_reply(event_id, reply_text, db_path=self._state_db_path)
        await self._deliver_pending(
            {
                "event_id": event_id,
                "room_id": self._allowed_room_id,
                "reply_text": reply_text,
                "reply_mode": "text",
                "attachment_paths": (),
                "text_sent": 0,
                "attachments_sent_count": 0,
            }
        )

    async def run(self) -> None:
        """Establish a backlog barrier, then process only live text events."""
        try:
            initial = await self._client.sync(timeout=0, full_state=True)
            if self._sync_error_types and isinstance(initial, self._sync_error_types):
                raise MatrixTransportError("Matrix initial sync failed")

            self._client.add_event_callback(self.handle_event, self._text_event_type)
            if self._approval_reaction_handler is not None:
                self._client.add_event_callback(
                    self.handle_reaction_event,
                    self._reaction_event_type,
                )
            if self._media_downloader is not None:
                for event_type in self._media_event_types:
                    self._client.add_event_callback(
                        self.handle_media_event,
                        event_type,
                    )
            if self._location_handler is not None:
                for event_type in self._location_event_types:
                    self._client.add_event_callback(
                        self.handle_location_event,
                        event_type,
                    )
            await self.resend_pending_replies()
            await self._client.sync_forever(timeout=30_000, full_state=True)
        finally:
            if self._close_client_on_exit:
                await self._client.close()
