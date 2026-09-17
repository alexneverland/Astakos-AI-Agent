"""Offline contracts for trusted Matrix location events."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest


@dataclass
class FakeRoom:
    room_id: str = "!private-room:example.test"
    encrypted: bool = True


@dataclass
class FakeLocationEvent:
    event_id: str = "$location-1"
    sender: str = "@owner:example.test"
    decrypted: bool = True
    source: dict[str, Any] = field(
        default_factory=lambda: {
            "type": "m.room.message",
            "content": {"msgtype": "m.location", "geo_uri": "geo:40.6401,22.9444;u=12"},
        }
    )


def test_parse_matrix_geo_uri_validates_coordinate_bounds() -> None:
    from services.location_update import parse_geo_uri

    assert parse_geo_uri("geo:40.6401,22.9444;u=12") == (40.6401, 22.9444)
    assert parse_geo_uri("https://maps.example/40,22") is None
    assert parse_geo_uri("geo:91,22") is None


def test_record_location_update_preserves_anchor_and_silences_live_updates(tmp_path) -> None:
    import json
    from services.location_update import record_location_update

    location_file = tmp_path / "last_location.json"

    static_reply = record_location_update(
        40.6401,
        22.9444,
        live_update=False,
        storage_file=location_file,
        now_ts=100.0,
    )
    live_reply = record_location_update(
        40.6500,
        22.9500,
        live_update=True,
        storage_file=location_file,
        now_ts=110.0,
    )

    stored = json.loads(location_file.read_text(encoding="utf-8"))
    assert "40.6401" in static_reply and "22.9444" in static_reply
    assert live_reply is None
    assert stored["lat"] == 40.65 and stored["lon"] == 22.95
    assert stored["anchor_lat"] == 40.6401


@pytest.mark.asyncio
async def test_transport_accepts_trusted_static_location_once(tmp_path) -> None:
    from clients.matrix_client import MatrixTextTransport
    from memory.matrix_event_state import get_matrix_event

    handled: list[tuple[float, float, bool]] = []

    async def location_handler(lat: float, lon: float, live_update: bool):
        handled.append((lat, lon, live_update))
        return "📍 Η τοποθεσία ενημερώθηκε."

    class Client:
        def __init__(self):
            self.sent = []

        async def room_send(self, **kwargs):
            self.sent.append(kwargs)
            return object()

    client = Client()
    transport = MatrixTextTransport(
        client=client,
        allowed_user_id="@owner:example.test",
        allowed_room_id="!private-room:example.test",
        service_user_id="@astakos:example.test",
        turn_handler=lambda text, event_id: None,
        state_db_path=str(tmp_path / "state.db"),
        text_event_type=type("Text", (), {}),
        location_event_types=(FakeLocationEvent,),
        location_handler=location_handler,
        send_error_types=(),
    )
    event = FakeLocationEvent()

    await transport.handle_location_event(FakeRoom(), event)
    await transport.handle_location_event(FakeRoom(), event)

    assert handled == [(40.6401, 22.9444, False)]
    assert len(client.sent) == 1
    assert get_matrix_event("$location-1", db_path=str(tmp_path / "state.db"))["status"] == "replied"


@pytest.mark.asyncio
async def test_live_location_update_is_processed_without_chat_reply(tmp_path) -> None:
    from clients.matrix_client import MatrixTextTransport

    handled: list[tuple[float, float, bool]] = []

    async def location_handler(lat: float, lon: float, live_update: bool):
        handled.append((lat, lon, live_update))
        return None

    class Client:
        sent = []

        async def room_send(self, **kwargs):
            self.sent.append(kwargs)
            return object()

    event = FakeLocationEvent(
        event_id="$live-1",
        source={
            "type": "m.beacon",
            "content": {"m.location": {"uri": "geo:40.64,22.94"}},
        },
    )
    client = Client()
    transport = MatrixTextTransport(
        client=client,
        allowed_user_id="@owner:example.test",
        allowed_room_id="!private-room:example.test",
        service_user_id="@astakos:example.test",
        turn_handler=lambda text, event_id: None,
        state_db_path=str(tmp_path / "state.db"),
        text_event_type=type("Text", (), {}),
        location_event_types=(FakeLocationEvent,),
        location_handler=location_handler,
        send_error_types=(),
    )

    await transport.handle_location_event(FakeRoom(), event)

    assert handled == [(40.64, 22.94, True)]
    assert client.sent == []
