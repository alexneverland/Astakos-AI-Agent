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
                "MATRIX_ALLOWED_DEVICE_IDS": "PHONE",
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
            "MATRIX_ALLOWED_DEVICE_IDS": " PHONE, DESKTOP ",
            "MATRIX_ROOM_ID": " !private:example.test ",
            "MATRIX_STORE_PATH": " matrix_store ",
        }
    )

    assert config.homeserver_url == "https://matrix.example.test"
    assert config.service_user_id == "@astakos:example.test"
    assert config.access_token == "secret-token"
    assert config.allowed_user_id == "@owner:example.test"
    assert config.allowed_device_ids == ("PHONE", "DESKTOP")
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
                "MATRIX_ALLOWED_DEVICE_IDS": "PHONE",
                "MATRIX_ROOM_ID": "!private:example.test",
                "MATRIX_STORE_PATH": "matrix_store",
            }
        )


def test_runtime_trusts_only_explicitly_configured_owner_devices() -> None:
    """Only owner device IDs confirmed out of band enter the trust set."""
    from clients.matrix_bot import verify_configured_owner_devices

    client = FakeTrustClient([FakeDevice("PHONE"), FakeDevice("DESKTOP")])

    assert verify_configured_owner_devices(
        client,
        "@owner:example.test",
        ("PHONE",),
    ) == 1
    assert client.verified == ["PHONE"]


def test_existing_trust_never_auto_accepts_a_new_owner_device() -> None:
    """Later devices remain unverified instead of silently receiving secrets."""
    from clients.matrix_bot import verify_configured_owner_devices

    client = FakeTrustClient(
        [FakeDevice("PHONE", verified=True), FakeDevice("NEW-DEVICE")]
    )

    assert verify_configured_owner_devices(
        client,
        "@owner:example.test",
        ("PHONE",),
    ) == 0
    assert client.verified == []


def test_missing_configured_owner_device_fails_closed() -> None:
    """A typo or removed device never falls back to trusting every device."""
    from clients.matrix_bot import verify_configured_owner_devices

    client = FakeTrustClient([FakeDevice("PHONE")])

    with pytest.raises(RuntimeError, match="not present"):
        verify_configured_owner_devices(
            client,
            "@owner:example.test",
            ("UNKNOWN",),
        )
    assert client.verified == []
