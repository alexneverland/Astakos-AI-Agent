"""Offline contract tests for the production Matrix process wiring."""

from __future__ import annotations

import pytest


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
