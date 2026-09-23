"""Offline behavior contracts for the encrypted Matrix text transport."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

import pytest
from nio import ReactionEvent
from nio.exceptions import OlmUnverifiedDeviceError

from clients.matrix_client import MatrixReply, MatrixTextTransport
from clients.matrix_voice import MatrixVoiceSendResult
from memory.matrix_event_state import get_matrix_event


@dataclass
class FakeRoom:
    room_id: str = "!private-room:example.test"
    encrypted: bool = True


@dataclass
class FakeTextEvent:
    event_id: str = "$event-1"
    sender: str = "@owner:example.test"
    body: str = "Καλημέρα"
    decrypted: bool = True
    verified: bool = True
    sender_key: str = "owner-curve-key"
    source: dict[str, Any] = field(
        default_factory=lambda: {
            "type": "m.room.message",
            "content": {"msgtype": "m.text", "body": "Καλημέρα"},
        }
    )


@dataclass
class FakeReactionEvent:
    event_id: str = "$reaction-1"
    sender: str = "@owner:example.test"
    reacts_to: str = "$approval-event"
    key: str = "✅"
    decrypted: bool = True
    verified: bool = True
    sender_key: str = "owner-curve-key"


class FakeSendError:
    message = "temporary failure"


@dataclass
class FakeDevice:
    id: str = "OWNERDEVICE"
    curve25519: str = "owner-curve-key"
    verified: bool = True


class FakeDeviceStore:
    def __init__(self, devices: list[FakeDevice]) -> None:
        self.devices = devices

    def active_user_devices(self, user_id: str) -> list[FakeDevice]:
        assert user_id == "@owner:example.test"
        return self.devices


class FakeMatrixClient:
    def __init__(self) -> None:
        self.device_store = FakeDeviceStore([FakeDevice()])
        self.callback: Callable[[Any, Any], Awaitable[None]] | None = None
        self.callbacks: list[tuple[Callable[[Any, Any], Awaitable[None]], Any]] = []
        self.calls: list[str] = []
        self.sent: list[dict[str, Any]] = []
        self.send_results: list[Any] = []
        self.typing: list[tuple[str, bool, int]] = []

    async def sync(self, **kwargs: Any) -> object:
        self.calls.append("initial_sync")
        return object()

    def add_event_callback(self, callback: Callable, event_type: Any) -> None:
        self.calls.append("add_callback")
        self.callback = callback
        self.callbacks.append((callback, event_type))

    async def sync_forever(self, **kwargs: Any) -> None:
        self.calls.append("sync_forever")

    async def room_send(self, **kwargs: Any) -> object:
        self.calls.append("room_send")
        self.sent.append(kwargs)
        if self.send_results:
            result = self.send_results.pop(0)
            if isinstance(result, Exception):
                raise result
            return result
        return object()

    async def room_typing(
        self,
        room_id: str,
        typing_state: bool = True,
        timeout: int = 30_000,
    ) -> object:
        self.calls.append(f"typing:{'on' if typing_state else 'off'}")
        self.typing.append((room_id, typing_state, timeout))
        return object()

    async def close(self) -> None:
        self.calls.append("close")


def _transport(
    tmp_path,
    client: FakeMatrixClient,
    handler: Callable[[str], Awaitable[str]],
    *,
    approval_reaction_handler=None,
    voice_sender=None,
    attachment_sender=None,
    close_client_on_exit=True,
) -> MatrixTextTransport:
    return MatrixTextTransport(
        client=client,
        allowed_user_id="@owner:example.test",
        allowed_room_id="!private-room:example.test",
        service_user_id="@astakos:example.test",
        allowed_approval_device_ids=("OWNERDEVICE",),
        turn_handler=handler,
        state_db_path=str(tmp_path / "state.db"),
        text_event_type=FakeTextEvent,
        reaction_event_type=FakeReactionEvent,
        approval_reaction_handler=approval_reaction_handler,
        voice_sender=voice_sender,
        attachment_sender=attachment_sender,
        close_client_on_exit=close_client_on_exit,
        send_error_types=(FakeSendError,),
    )


@pytest.mark.asyncio
async def test_trusted_encrypted_text_invokes_handler_once_and_sends_once(tmp_path) -> None:
    client = FakeMatrixClient()
    handled: list[str] = []

    async def handler(text: str, event_id: str) -> str:
        handled.append(f"{event_id}:{text}")
        return "Καλημέρα φίλε"

    transport = _transport(tmp_path, client, handler)
    await transport.handle_event(FakeRoom(), FakeTextEvent())

    assert handled == ["$event-1:Καλημέρα"]
    assert client.sent == [
        {
            "room_id": "!private-room:example.test",
            "message_type": "m.room.message",
            "content": {"msgtype": "m.text", "body": "Καλημέρα φίλε"},
        }
    ]
    assert get_matrix_event(
        "$event-1", db_path=str(tmp_path / "state.db")
    )["status"] == "replied"


@pytest.mark.asyncio
async def test_trusted_text_shows_typing_until_reply_is_ready(tmp_path) -> None:
    client = FakeMatrixClient()

    async def handler(text: str, event_id: str) -> str:
        client.calls.append("handler")
        return "Έτοιμη απάντηση"

    transport = _transport(tmp_path, client, handler)
    await transport.handle_event(FakeRoom(), FakeTextEvent())

    assert client.typing == [
        ("!private-room:example.test", True, 30_000),
        ("!private-room:example.test", False, 30_000),
    ]
    assert client.calls == ["typing:on", "handler", "typing:off", "room_send"]


@pytest.mark.asyncio
async def test_handler_failure_always_stops_typing(tmp_path) -> None:
    client = FakeMatrixClient()

    async def handler(text: str, event_id: str) -> str:
        raise RuntimeError("graph failed")

    transport = _transport(tmp_path, client, handler)

    with pytest.raises(RuntimeError, match="graph failed"):
        await transport.handle_event(FakeRoom(), FakeTextEvent())

    assert [typing_state for _, typing_state, _ in client.typing] == [True, False]
    assert client.sent == []


@pytest.mark.asyncio
async def test_typing_api_failure_does_not_block_reply(tmp_path) -> None:
    class TypingFailureClient(FakeMatrixClient):
        async def room_typing(
            self,
            room_id: str,
            typing_state: bool = True,
            timeout: int = 30_000,
        ) -> object:
            del room_id, typing_state, timeout
            raise RuntimeError("typing unavailable")

    client = TypingFailureClient()

    async def handler(text: str, event_id: str) -> str:
        return "Η απάντηση συνεχίζει κανονικά"

    transport = _transport(tmp_path, client, handler)
    await transport.handle_event(FakeRoom(), FakeTextEvent())

    assert [item["content"]["body"] for item in client.sent] == [
        "Η απάντηση συνεχίζει κανονικά"
    ]


@pytest.mark.asyncio
async def test_stalled_typing_api_does_not_delay_turn_or_reply(tmp_path) -> None:
    """A hanging homeserver typing endpoint cannot stall the real answer."""
    import asyncio

    class StalledTypingClient(FakeMatrixClient):
        async def room_typing(
            self,
            room_id: str,
            typing_state: bool = True,
            timeout: int = 30_000,
        ) -> object:
            del room_id, typing_state, timeout
            await asyncio.Event().wait()

    client = StalledTypingClient()
    handler_started = asyncio.Event()

    async def handler(text: str, event_id: str) -> str:
        handler_started.set()
        return "Η απάντηση συνεχίζει κανονικά"

    transport = _transport(tmp_path, client, handler)
    await asyncio.wait_for(
        transport.handle_event(FakeRoom(), FakeTextEvent()),
        timeout=1.5,
    )

    assert handler_started.is_set()
    assert client.sent[0]["content"]["body"] == "Η απάντηση συνεχίζει κανονικά"


@pytest.mark.asyncio
async def test_voice_reply_uses_voice_sender_and_persists_delivery_mode(tmp_path) -> None:
    client = FakeMatrixClient()
    voice_calls: list[str] = []

    async def handler(text: str, event_id: str) -> MatrixReply:
        return MatrixReply("Φωνητική απάντηση", mode="voice")

    async def voice_sender(text: str) -> MatrixVoiceSendResult:
        voice_calls.append(text)
        return MatrixVoiceSendResult(sent=True)

    transport = _transport(tmp_path, client, handler, voice_sender=voice_sender)
    await transport.handle_event(FakeRoom(), FakeTextEvent())

    assert voice_calls == ["Φωνητική απάντηση"]
    assert client.sent == []
    stored = get_matrix_event("$event-1", db_path=str(tmp_path / "state.db"))
    assert stored["reply_mode"] == "voice"
    assert stored["status"] == "replied"


@pytest.mark.asyncio
async def test_voice_failure_sends_notice_and_text_fallback(tmp_path) -> None:
    client = FakeMatrixClient()

    async def handler(text: str, event_id: str) -> MatrixReply:
        return MatrixReply("Απάντηση", mode="voice")

    async def voice_sender(text: str) -> MatrixVoiceSendResult:
        return MatrixVoiceSendResult(sent=False, fallback_notice="⚠️ TTS unavailable")

    transport = _transport(tmp_path, client, handler, voice_sender=voice_sender)
    await transport.handle_event(FakeRoom(), FakeTextEvent())

    assert [item["content"]["body"] for item in client.sent] == [
        "⚠️ TTS unavailable",
        "Απάντηση",
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("room", "event"),
    [
        (FakeRoom(room_id="!other:example.test"), FakeTextEvent()),
        (FakeRoom(encrypted=False), FakeTextEvent()),
        (FakeRoom(), FakeTextEvent(decrypted=False)),
        (FakeRoom(), FakeTextEvent(sender="@other:example.test")),
        (FakeRoom(), FakeTextEvent(sender="@astakos:example.test")),
        (
            FakeRoom(),
            FakeTextEvent(
                source={
                    "type": "m.room.message",
                    "content": {"msgtype": "m.notice", "body": "notice"},
                }
            ),
        ),
        (
            FakeRoom(),
            FakeTextEvent(
                source={
                    "type": "m.room.message",
                    "content": {
                        "msgtype": "m.text",
                        "body": "edited",
                        "m.relates_to": {"rel_type": "m.replace"},
                    },
                }
            ),
        ),
    ],
)
async def test_untrusted_or_unsupported_events_are_ignored(
    tmp_path,
    room: FakeRoom,
    event: FakeTextEvent,
) -> None:
    client = FakeMatrixClient()
    handled: list[str] = []

    async def handler(text: str, event_id: str) -> str:
        handled.append(text)
        return "should not happen"

    transport = _transport(tmp_path, client, handler)
    await transport.handle_event(room, event)

    assert handled == []
    assert client.sent == []
    assert get_matrix_event(
        event.event_id, db_path=str(tmp_path / "state.db")
    ) is None


@pytest.mark.asyncio
async def test_duplicate_event_never_reruns_handler_or_resends(tmp_path) -> None:
    client = FakeMatrixClient()
    handled: list[str] = []

    async def handler(text: str, event_id: str) -> str:
        handled.append(text)
        return "μία απάντηση"

    transport = _transport(tmp_path, client, handler)
    event = FakeTextEvent()
    await transport.handle_event(FakeRoom(), event)
    await transport.handle_event(FakeRoom(), event)

    assert handled == ["Καλημέρα"]
    assert len(client.sent) == 1


@pytest.mark.asyncio
async def test_send_failure_retries_saved_reply_without_rerunning_handler(tmp_path) -> None:
    client = FakeMatrixClient()
    client.send_results = [FakeSendError(), object()]
    handled: list[str] = []

    async def handler(text: str, event_id: str) -> str:
        handled.append(text)
        return "ίδια αποθηκευμένη απάντηση"

    transport = _transport(tmp_path, client, handler)
    await transport.handle_event(FakeRoom(), FakeTextEvent())

    pending = get_matrix_event("$event-1", db_path=str(tmp_path / "state.db"))
    assert pending["status"] == "reply_pending"
    assert pending["reply_text"] == "ίδια αποθηκευμένη απάντηση"

    await transport.resend_pending_replies()

    assert handled == ["Καλημέρα"]
    assert [item["content"]["body"] for item in client.sent] == [
        "ίδια αποθηκευμένη απάντηση",
        "ίδια αποθηκευμένη απάντηση",
    ]
    assert get_matrix_event(
        "$event-1", db_path=str(tmp_path / "state.db")
    )["status"] == "replied"


@pytest.mark.asyncio
async def test_unverified_owner_device_keeps_reply_pending_without_stopping_transport(
    tmp_path,
) -> None:
    client = FakeMatrixClient()
    client.send_results = [OlmUnverifiedDeviceError(object())]

    async def handler(text: str, event_id: str) -> str:
        return "Αποθηκευμένη απάντηση"

    transport = _transport(tmp_path, client, handler)
    await transport.handle_event(FakeRoom(), FakeTextEvent())

    pending = get_matrix_event("$event-1", db_path=str(tmp_path / "state.db"))
    assert pending["status"] == "reply_pending"
    assert pending["reply_text"] == "Αποθηκευμένη απάντηση"


@pytest.mark.asyncio
async def test_retry_resumes_after_sent_text_and_first_attachment(tmp_path) -> None:
    from clients.matrix_attachment import MatrixAttachmentSendResult

    client = FakeMatrixClient()
    handled: list[str] = []
    attachment_calls: list[str] = []
    outcomes = [
        MatrixAttachmentSendResult(sent=True),
        MatrixAttachmentSendResult(sent=False, retryable=True),
        MatrixAttachmentSendResult(sent=True),
    ]

    async def handler(text: str, event_id: str) -> MatrixReply:
        handled.append(text)
        return MatrixReply(
            "Έτοιμα",
            attachment_paths=("C:/outputs/one.pdf", "C:/outputs/two.png"),
        )

    async def attachment_sender(path: str) -> MatrixAttachmentSendResult:
        attachment_calls.append(path)
        return outcomes.pop(0)

    transport = _transport(
        tmp_path,
        client,
        handler,
        attachment_sender=attachment_sender,
    )
    await transport.handle_event(FakeRoom(), FakeTextEvent())

    pending = get_matrix_event("$event-1", db_path=str(tmp_path / "state.db"))
    assert pending["status"] == "reply_pending"
    assert pending["text_sent"] == 1
    assert pending["attachments_sent_count"] == 1

    await transport.resend_pending_replies()

    assert handled == ["Καλημέρα"]
    assert [item["content"]["body"] for item in client.sent] == ["Έτοιμα"]
    assert attachment_calls == [
        "C:/outputs/one.pdf",
        "C:/outputs/two.png",
        "C:/outputs/two.png",
    ]
    assert get_matrix_event(
        "$event-1", db_path=str(tmp_path / "state.db")
    )["status"] == "replied"


@pytest.mark.asyncio
async def test_run_establishes_initial_sync_before_registering_live_callback(tmp_path) -> None:
    client = FakeMatrixClient()

    async def handler(text: str, event_id: str) -> str:
        raise AssertionError("initial sync backlog must not reach the turn handler")

    transport = _transport(tmp_path, client, handler)
    await transport.run()

    assert client.calls[:3] == ["initial_sync", "add_callback", "sync_forever"]
    assert client.calls[-1] == "close"


@pytest.mark.asyncio
async def test_run_can_leave_client_open_for_composer_shutdown_messages(tmp_path) -> None:
    """The production composer can notify the room before it closes the client."""
    client = FakeMatrixClient()

    async def handler(text: str, event_id: str) -> str:
        raise AssertionError("initial sync backlog must not reach the turn handler")

    transport = _transport(
        tmp_path,
        client,
        handler,
        close_client_on_exit=False,
    )
    await transport.run()

    assert client.calls[:3] == ["initial_sync", "add_callback", "sync_forever"]
    assert "close" not in client.calls


@pytest.mark.asyncio
async def test_blank_handler_reply_stays_processing_and_is_not_sent(tmp_path) -> None:
    client = FakeMatrixClient()

    async def handler(text: str, event_id: str) -> str:
        return "   "

    transport = _transport(tmp_path, client, handler)

    with pytest.raises(ValueError, match="non-empty reply"):
        await transport.handle_event(FakeRoom(), FakeTextEvent())

    assert client.sent == []
    assert get_matrix_event(
        "$event-1", db_path=str(tmp_path / "state.db")
    )["status"] == "processing"


@pytest.mark.asyncio
async def test_trusted_approval_reaction_handler_can_send_one_result(tmp_path) -> None:
    client = FakeMatrixClient()
    handled: list[dict[str, Any]] = []

    async def turn_handler(text: str, event_id: str) -> str:
        raise AssertionError("reaction must not enter the text graph")

    async def reaction_handler(**kwargs: Any) -> str:
        handled.append(kwargs)
        return "✅ Η ενέργεια εκτελέστηκε."

    transport = _transport(
        tmp_path,
        client,
        turn_handler,
        approval_reaction_handler=reaction_handler,
    )
    await transport.handle_reaction_event(FakeRoom(), FakeReactionEvent())

    assert handled == [
        {
            "room_id": "!private-room:example.test",
            "sender_id": "@owner:example.test",
            "authenticated": True,
            "reacts_to": "$approval-event",
            "key": "✅",
        }
    ]
    assert client.sent[0]["content"]["body"] == "✅ Η ενέργεια εκτελέστηκε."


@pytest.mark.asyncio
async def test_element_cleartext_reaction_in_encrypted_room_cannot_approve(tmp_path) -> None:
    """A room setting cannot authenticate a cleartext reaction."""
    client = FakeMatrixClient()
    handled: list[dict[str, Any]] = []

    async def turn_handler(text: str, event_id: str) -> str:
        raise AssertionError("reaction must not enter the text graph")

    async def reaction_handler(**kwargs: Any) -> None:
        handled.append(kwargs)
        return None

    transport = _transport(
        tmp_path,
        client,
        turn_handler,
        approval_reaction_handler=reaction_handler,
    )
    transport._reaction_event_type = ReactionEvent
    reaction = ReactionEvent.from_dict(
        {
            "type": "m.reaction",
            "event_id": "$reaction-1",
            "sender": "@owner:example.test",
            "origin_server_ts": 1,
            "content": {
                "m.relates_to": {
                    "rel_type": "m.annotation",
                    "event_id": "$approval-event",
                    "key": "👍",
                }
            },
        }
    )
    assert isinstance(reaction, ReactionEvent)
    assert reaction.decrypted is False
    await transport.handle_reaction_event(
        FakeRoom(),
        reaction,
    )

    assert handled == []


@pytest.mark.asyncio
async def test_decrypted_reaction_from_unverified_device_cannot_approve(tmp_path) -> None:
    client = FakeMatrixClient()
    handled: list[dict[str, Any]] = []

    async def turn_handler(text: str, event_id: str) -> str:
        raise AssertionError("reaction must not enter the text graph")

    async def approval_handler(**kwargs: Any) -> None:
        handled.append(kwargs)

    transport = _transport(
        tmp_path, client, turn_handler,
        approval_reaction_handler=approval_handler,
    )
    await transport.handle_reaction_event(
        FakeRoom(), FakeReactionEvent(decrypted=True, verified=False),
    )

    assert handled == []


@pytest.mark.asyncio
@pytest.mark.parametrize("approval_kind", ["reaction", "reply"])
async def test_previously_verified_device_removed_from_allowlist_cannot_approve(
    tmp_path, approval_kind: str,
) -> None:
    """Persisted Olm trust must not override the current device allowlist."""
    client = FakeMatrixClient()
    client.device_store = FakeDeviceStore([FakeDevice(id="OLDDEVICE")])
    handled: list[dict[str, Any]] = []

    async def turn_handler(text: str, event_id: str) -> str:
        raise AssertionError("approval must not enter the text graph")

    async def approval_handler(**kwargs: Any) -> None:
        handled.append(kwargs)

    transport = _transport(
        tmp_path, client, turn_handler,
        approval_reaction_handler=approval_handler,
    )
    if approval_kind == "reaction":
        await transport.handle_reaction_event(FakeRoom(), FakeReactionEvent())
    else:
        await transport.handle_event(
            FakeRoom(),
            FakeTextEvent(
                body="👍",
                source={"type": "m.room.message", "content": {
                    "msgtype": "m.text", "body": "👍",
                    "m.relates_to": {"m.in_reply_to": {"event_id": "$approval-event"}},
                }},
            ),
        )
    assert handled == []


@pytest.mark.asyncio
async def test_verified_encrypted_reply_to_approval_executes_without_graph(tmp_path) -> None:
    client = FakeMatrixClient()
    handled: list[dict[str, Any]] = []

    async def turn_handler(text: str, event_id: str) -> str:
        raise AssertionError("approval must not enter the text graph")

    async def approval_handler(**kwargs: Any) -> str:
        handled.append(kwargs)
        return "✅ Η ενέργεια εκτελέστηκε."

    transport = _transport(
        tmp_path, client, turn_handler,
        approval_reaction_handler=approval_handler,
    )
    event = FakeTextEvent(
        body="> <@astakos:example.test> approve this\n\n👍",
        source={
            "type": "m.room.message",
            "content": {
                "msgtype": "m.text",
                "body": "> <@astakos:example.test> approve this\n\n👍",
                "m.relates_to": {"m.in_reply_to": {"event_id": "$approval-event"}},
            },
        },
    )
    await transport.handle_event(FakeRoom(), event)

    assert handled == [{
        "room_id": "!private-room:example.test",
        "sender_id": "@owner:example.test",
        "authenticated": True,
        "reacts_to": "$approval-event",
        "key": "👍",
    }]
    assert client.sent[0]["content"]["body"] == "✅ Η ενέργεια εκτελέστηκε."


@pytest.mark.asyncio
async def test_unverified_encrypted_reply_cannot_approve(tmp_path) -> None:
    client = FakeMatrixClient()
    handled: list[dict[str, Any]] = []

    async def turn_handler(text: str, event_id: str) -> str:
        raise AssertionError("unverified approval must not enter the text graph")

    async def approval_handler(**kwargs: Any) -> None:
        handled.append(kwargs)

    transport = _transport(
        tmp_path, client, turn_handler,
        approval_reaction_handler=approval_handler,
    )
    event = FakeTextEvent(
        body="👍", verified=False,
        source={
            "type": "m.room.message",
            "content": {
                "msgtype": "m.text", "body": "👍",
                "m.relates_to": {"m.in_reply_to": {"event_id": "$approval-event"}},
            },
        },
    )
    await transport.handle_event(FakeRoom(), event)

    assert handled == []
    assert client.sent == []


@pytest.mark.asyncio
async def test_reaction_in_unencrypted_room_cannot_approve(tmp_path) -> None:
    client = FakeMatrixClient()
    handled: list[dict[str, Any]] = []

    async def turn_handler(text: str, event_id: str) -> str:
        raise AssertionError("reaction must not enter the text graph")

    async def reaction_handler(**kwargs: Any) -> None:
        handled.append(kwargs)

    transport = _transport(
        tmp_path, client, turn_handler, approval_reaction_handler=reaction_handler
    )
    await transport.handle_reaction_event(
        FakeRoom(encrypted=False), FakeReactionEvent(key="👍", decrypted=False)
    )

    assert handled == []


@pytest.mark.asyncio
async def test_untrusted_approval_reaction_never_reaches_handler(tmp_path) -> None:
    client = FakeMatrixClient()
    handled: list[dict[str, Any]] = []

    async def turn_handler(text: str, event_id: str) -> str:
        return "unused"

    async def reaction_handler(**kwargs: Any) -> str:
        handled.append(kwargs)
        return "should not send"

    transport = _transport(
        tmp_path,
        client,
        turn_handler,
        approval_reaction_handler=reaction_handler,
    )
    await transport.handle_reaction_event(
        FakeRoom(),
        FakeReactionEvent(sender="@other:example.test"),
    )

    assert handled == []
    assert client.sent == []


@pytest.mark.asyncio
async def test_run_registers_reaction_callback_only_when_configured(tmp_path) -> None:
    client = FakeMatrixClient()

    async def turn_handler(text: str, event_id: str) -> str:
        return "unused"

    async def reaction_handler(**kwargs: Any) -> None:
        return None

    transport = _transport(
        tmp_path,
        client,
        turn_handler,
        approval_reaction_handler=reaction_handler,
    )
    await transport.run()

    assert [event_type for _, event_type in client.callbacks] == [
        FakeTextEvent,
        FakeReactionEvent,
    ]
