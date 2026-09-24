"""Offline contracts for trusted Matrix location events."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest
from nio import UnknownEvent


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


def test_record_location_update_preserves_anchor_and_silences_live_updates(
    tmp_path, monkeypatch
) -> None:
    import json
    import config
    from services.location_update import record_location_update

    monkeypatch.setattr(config, "HOME_COORDS", (0.0, 0.0))
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


def test_live_matrix_location_updates_home_context_without_repeating_same_state(
    tmp_path, monkeypatch
) -> None:
    import config
    from memory import routine_db
    from services.location_update import record_location_update

    monkeypatch.setattr(config, "HOME_COORDS", (40.0, 22.0))
    monkeypatch.setattr(config, "HOME_RADIUS_M", 150)
    monkeypatch.setattr(routine_db, "DB_PATH", str(tmp_path / "routines.db"))
    routine_db.setup_db()
    updates: list[tuple[str, str]] = []
    original_set = routine_db.set_context_state

    def capture_context(key: str, value: str, **kwargs) -> None:
        updates.append((key, value))
        original_set(key, value, **kwargs)

    monkeypatch.setattr(routine_db, "set_context_state", capture_context)
    storage_file = tmp_path / "location.json"
    record_location_update(40.0, 22.0, live_update=True, storage_file=storage_file)
    record_location_update(40.01, 22.0, live_update=True, storage_file=storage_file)
    record_location_update(40.01, 22.0, live_update=True, storage_file=storage_file)
    record_location_update(40.0, 22.0, live_update=True, storage_file=storage_file)

    assert updates == [
        ("user_out_of_home", "false"),
        ("user_out_of_home", "true"),
        ("user_out_of_home", "false"),
    ]


def test_matrix_location_fires_home_reminder_once_and_ignores_time_reminder(
    tmp_path, monkeypatch
) -> None:
    import config
    from services.location_update import process_location_update
    from tests.test_reminders_sql import _make_reminders_db, _row_status

    state_db = tmp_path / "state.db"
    _make_reminders_db(
        str(state_db),
        [
            {"task": "Βγάλε το κουνέλι", "time": "loc:home"},
            {"task": "Πλήρωσε λογαριασμό", "time": "2099-01-01 00:00"},
        ],
    )
    monkeypatch.setattr(config, "HOME_COORDS", (40.0, 22.0))
    monkeypatch.setattr(config, "HOME_RADIUS_M", 150)
    monkeypatch.setattr(config, "STATE_DB", str(state_db))
    sent: list[str] = []

    def deliver(text: str) -> None:
        sent.append(text)

    process_location_update(
        40.0,
        22.0,
        live_update=False,
        source_channel="matrix",
        send_reminder=deliver,
        storage_file=tmp_path / "location.json",
    )
    process_location_update(
        40.0,
        22.0,
        live_update=False,
        source_channel="matrix",
        send_reminder=deliver,
        storage_file=tmp_path / "location.json",
    )

    assert len(sent) == 1 and "Βγάλε το κουνέλι" in sent[0]
    assert _row_status(str(state_db), "Βγάλε το κουνέλι") == "done"
    assert _row_status(str(state_db), "Πλήρωσε λογαριασμό") == "pending"


def test_matrix_location_leaving_anchor_sends_once_and_failed_delivery_stays_pending(
    tmp_path, monkeypatch
) -> None:
    import sqlite3
    import config
    from memory.location_reminders import save_leave_current_location_anchor
    from services.location_update import process_location_update
    from tests.test_reminders_sql import _make_reminders_db, _row_status

    state_db = tmp_path / "state.db"
    _make_reminders_db(
        str(state_db),
        [{"task": "Πάρε ψωμί", "time": "loc:leave_current_location"}],
    )
    with sqlite3.connect(state_db) as conn:
        save_leave_current_location_anchor(
            conn, reminder_id=1, anchor_lat=40.0, anchor_lon=22.0
        )
    monkeypatch.setattr(config, "HOME_COORDS", (0.0, 0.0))
    monkeypatch.setattr(config, "STATE_DB", str(state_db))

    def failed_delivery(_message: str) -> None:
        raise ConnectionError("offline")

    with pytest.raises(ConnectionError, match="offline"):
        process_location_update(
            40.01, 22.0, live_update=False, source_channel="matrix",
            send_reminder=failed_delivery, storage_file=tmp_path / "location.json"
        )
    assert _row_status(str(state_db), "Πάρε ψωμί") == "pending"

    sent: list[str] = []
    for _ in range(2):
        process_location_update(
            40.01, 22.0, live_update=False, source_channel="matrix",
            send_reminder=lambda message: sent.append(message),
            storage_file=tmp_path / "location.json",
        )
    assert len(sent) == 1 and "Πάρε ψωμί" in sent[0]
    assert _row_status(str(state_db), "Πάρε ψωμί") == "done"


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


@pytest.mark.asyncio
async def test_default_transport_accepts_decrypted_element_live_beacon(tmp_path) -> None:
    from clients.matrix_client import MatrixTextTransport

    handled: list[tuple[float, float, bool]] = []

    async def location_handler(lat: float, lon: float, live_update: bool):
        handled.append((lat, lon, live_update))
        return None

    class Client:
        async def room_send(self, **kwargs):
            raise AssertionError("live GPS updates must remain silent")

    event = UnknownEvent.from_dict(
        {
            "event_id": "$live-element-1",
            "sender": "@owner:example.test",
            "origin_server_ts": 1,
            "type": "m.beacon",
            "content": {"m.location": {"uri": "geo:40.64,22.94"}},
        }
    )
    event.decrypted = True
    transport = MatrixTextTransport(
        client=Client(),
        allowed_user_id="@owner:example.test",
        allowed_room_id="!private-room:example.test",
        service_user_id="@astakos:example.test",
        turn_handler=lambda text, event_id: None,
        state_db_path=str(tmp_path / "state.db"),
        text_event_type=type("Text", (), {}),
        location_handler=location_handler,
        send_error_types=(),
    )

    await transport.handle_location_event(FakeRoom(), event)

    assert handled == [(40.64, 22.94, True)]
