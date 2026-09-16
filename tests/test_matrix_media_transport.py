"""Offline lifecycle contracts for Matrix media transport callbacks."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from clients.matrix_client import MatrixTextTransport
from clients.matrix_media import MatrixMediaAsset
from memory.matrix_event_state import get_matrix_event


@dataclass
class FakeRoom:
    room_id: str = "!private-room:example.test"
    encrypted: bool = True


@dataclass
class FakeMediaEvent:
    event_id: str = "$media-1"


class FakeMediaDownloader:
    def __init__(self, asset: MatrixMediaAsset | None) -> None:
        self.asset = asset
        self.calls: list[str] = []

    async def download(self, room: Any, event: Any) -> MatrixMediaAsset | None:
        self.calls.append(event.event_id)
        return self.asset


class FakeClient:
    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []
        self.callbacks: list[tuple[Any, Any]] = []

    async def room_send(self, **kwargs: Any) -> object:
        self.sent.append(kwargs)
        return object()

    async def sync(self, **kwargs: Any) -> object:
        return object()

    def add_event_callback(self, callback: Any, event_type: Any) -> None:
        self.callbacks.append((callback, event_type))

    async def sync_forever(self, **kwargs: Any) -> None:
        return None

    async def close(self) -> None:
        return None


def _transport(tmp_path, client, downloader, handler) -> MatrixTextTransport:
    async def text_handler(text: str, event_id: str) -> str:
        raise AssertionError("media must not enter the text handler")

    return MatrixTextTransport(
        client=client,
        allowed_user_id="@owner:example.test",
        allowed_room_id="!private-room:example.test",
        service_user_id="@astakos:example.test",
        turn_handler=text_handler,
        state_db_path=str(tmp_path / "state.db"),
        media_downloader=downloader,
        media_handler=handler,
        media_event_types=(FakeMediaEvent,),
        text_event_type=type("UnusedText", (), {}),
        reaction_event_type=type("UnusedReaction", (), {}),
    )


@pytest.mark.asyncio
async def test_media_callback_uses_same_durable_reply_lifecycle(tmp_path) -> None:
    asset = MatrixMediaAsset(
        event_id="$media-1",
        kind="image",
        path=Path("photo.png"),
        mime_type="image/png",
        original_name="photo.png",
    )
    downloader = FakeMediaDownloader(asset)
    handled: list[MatrixMediaAsset] = []

    async def handler(item: MatrixMediaAsset) -> str:
        handled.append(item)
        return "Είδα τη φωτογραφία."

    client = FakeClient()
    transport = _transport(tmp_path, client, downloader, handler)

    await transport.handle_media_event(FakeRoom(), FakeMediaEvent())
    await transport.handle_media_event(FakeRoom(), FakeMediaEvent())

    assert handled == [asset]
    assert [item["content"]["body"] for item in client.sent] == [
        "Είδα τη φωτογραφία."
    ]
    assert get_matrix_event(
        "$media-1", db_path=str(tmp_path / "state.db")
    )["status"] == "replied"


@pytest.mark.asyncio
async def test_rejected_media_never_reserves_or_replies(tmp_path) -> None:
    downloader = FakeMediaDownloader(None)

    async def handler(item: MatrixMediaAsset) -> str:
        raise AssertionError("rejected media must not reach application code")

    client = FakeClient()
    transport = _transport(tmp_path, client, downloader, handler)

    await transport.handle_media_event(FakeRoom(), FakeMediaEvent())

    assert client.sent == []
    assert get_matrix_event(
        "$media-1", db_path=str(tmp_path / "state.db")
    ) is None


@pytest.mark.asyncio
async def test_run_registers_media_callbacks_after_backlog_barrier(tmp_path) -> None:
    downloader = FakeMediaDownloader(None)

    async def handler(item: MatrixMediaAsset) -> str:
        raise AssertionError("backlog is not dispatched")

    client = FakeClient()
    transport = _transport(tmp_path, client, downloader, handler)

    await transport.run()

    registered_types = [event_type for _, event_type in client.callbacks]
    assert FakeMediaEvent in registered_types
