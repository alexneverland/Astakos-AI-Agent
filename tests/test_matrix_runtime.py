"""Offline contract tests for the production Matrix process wiring."""

from __future__ import annotations

import pytest


class FakeDevice:
    def __init__(self, device_id: str, *, verified: bool = False) -> None:
        self.id = device_id
        self.verified = verified


class FakeDeviceStore:
    def __init__(self, devices: list[FakeDevice]) -> None:
        self._devices = devices

    def active_user_devices(self, user_id: str):
        del user_id
        return iter(self._devices)


class FakeTrustClient:
    def __init__(self, devices: list[FakeDevice]) -> None:
        self.device_store = FakeDeviceStore(devices)
        self.verified: list[str] = []

    def verify_device(self, device: FakeDevice) -> bool:
        self.verified.append(device.id)
        device.verified = True
        return True


def test_matrix_runtime_config_requires_every_private_room_setting() -> None:
    """The Matrix process fails closed before connecting with partial setup."""
    from clients.matrix_bot import MatrixRuntimeConfigurationError, load_runtime_config

    with pytest.raises(MatrixRuntimeConfigurationError, match="MATRIX_ROOM_ID"):
        load_runtime_config(
            {
                "MATRIX_HOMESERVER_URL": "https://matrix.example.test",
                "MATRIX_SERVICE_USER_ID": "@astakos:example.test",
                "MATRIX_ACCESS_TOKEN": "secret-token",
                "MATRIX_ALLOWED_USER_ID": "@owner:example.test",
                "MATRIX_STORE_PATH": "matrix_store",
            }
        )


def test_matrix_runtime_config_preserves_complete_setup() -> None:
    """A complete Setup Wizard result is normalized into runtime settings."""
    from clients.matrix_bot import load_runtime_config

    config = load_runtime_config(
        {
            "MATRIX_HOMESERVER_URL": " https://matrix.example.test/ ",
            "MATRIX_SERVICE_USER_ID": " @astakos:example.test ",
            "MATRIX_ACCESS_TOKEN": " secret-token ",
            "MATRIX_ALLOWED_USER_ID": " @owner:example.test ",
            "MATRIX_ROOM_ID": " !private:example.test ",
            "MATRIX_STORE_PATH": " matrix_store ",
        }
    )

    assert config.homeserver_url == "https://matrix.example.test"
    assert config.service_user_id == "@astakos:example.test"
    assert config.access_token == "secret-token"
    assert config.allowed_user_id == "@owner:example.test"
    assert config.room_id == "!private:example.test"
    assert config.store_path.name == "matrix_store"


def test_matrix_runtime_rejects_remote_plaintext_homeserver() -> None:
    """Direct environment startup enforces the same HTTPS boundary as Setup."""
    from clients.matrix_bot import MatrixRuntimeConfigurationError, load_runtime_config

    with pytest.raises(MatrixRuntimeConfigurationError, match="HTTPS"):
        load_runtime_config(
            {
                "MATRIX_HOMESERVER_URL": "http://matrix.example.test",
                "MATRIX_SERVICE_USER_ID": "@astakos:example.test",
                "MATRIX_ACCESS_TOKEN": "secret-token",
                "MATRIX_ALLOWED_USER_ID": "@owner:example.test",
                "MATRIX_ROOM_ID": "!private:example.test",
                "MATRIX_STORE_PATH": "matrix_store",
            }
        )


def test_first_start_pins_the_existing_owner_devices() -> None:
    """A fresh crypto store establishes one persistent owner trust set."""
    from clients.matrix_bot import pin_initial_owner_devices

    client = FakeTrustClient([FakeDevice("PHONE"), FakeDevice("DESKTOP")])

    assert pin_initial_owner_devices(client, "@owner:example.test") == 2
    assert client.verified == ["PHONE", "DESKTOP"]


def test_existing_trust_never_auto_accepts_a_new_owner_device() -> None:
    """Later devices remain unverified instead of silently receiving secrets."""
    from clients.matrix_bot import pin_initial_owner_devices

    client = FakeTrustClient(
        [FakeDevice("PHONE", verified=True), FakeDevice("NEW-DEVICE")]
    )

    assert pin_initial_owner_devices(client, "@owner:example.test") == 0
    assert client.verified == []
