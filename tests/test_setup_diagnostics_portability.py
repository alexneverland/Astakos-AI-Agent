# ================================================================
# Project: Astakos AI Agent 🦞
# Description: Test suite for Setup & Diagnostics Portability (PR 5)
# Copyright (c) 2026 - All Rights Reserved
# ================================================================

from __future__ import annotations

import asyncio
import json
import os
import socket
from pathlib import Path
from typing import Any

import pytest
from fastapi import HTTPException

import config
from core.ai_provider import (
    DEFAULT_GEMINI_FAST_MODEL,
    DEFAULT_LOCAL_EMBEDDING_MODEL,
    DEFAULT_OPENAI_EMBEDDING_MODEL,
    DEFAULT_VERTEX_EMBEDDING_MODEL,
)
from core.diagnostics import (
    format_boot_diagnostics_text,
    get_chat_provider_diagnostics,
    get_embeddings_diagnostics,
    get_semantic_memory_diagnostics,
    get_system_diagnostics_summary,
    get_workspace_diagnostics,
    is_chat_provider_configured,
)


# ────────────────────────────────────────────────────────────────
# Outbound Network Guard (Autouse)
# ────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def guard_outbound_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Blocks all outbound network sockets, HTTP clients, and OAuth servers while allowing asyncio loopback."""
    orig_connect = socket.socket.connect

    def _guarded_connect(self: socket.socket, address: Any) -> None:
        if isinstance(address, tuple) and len(address) >= 2:
            host = address[0]
            if host in ("127.0.0.1", "localhost", "::1"):
                return orig_connect(self, address)
        raise RuntimeError(f"Outbound network activity blocked by test guard: {address}")

    monkeypatch.setattr(socket.socket, "connect", _guarded_connect)



class _NoOpThread:
    """Prevents setup endpoint tests from terminating the test process."""
    def __init__(self, *args: object, **kwargs: object) -> None:
        pass

    def start(self) -> None:
        pass


def _configure_isolated_wizard(monkeypatch: pytest.MonkeyPatch, base: Path) -> None:
    """Redirects all setup wizard file operations to a clean temporary path."""
    import api.setup_wizard as wizard

    prompts_dir = base / "prompts"
    prompts_dir.mkdir(exist_ok=True)
    monkeypatch.setattr(wizard, "ENV_FILE", str(base / ".env"))
    monkeypatch.setattr(wizard, "PERSONA_FILE", str(base / "persona.md"))
    monkeypatch.setattr(wizard, "INTENTS_FILE", str(base / "astakos_custom_intents.json"))
    monkeypatch.setattr(wizard, "ROUTINES_FILE", str(base / "astakos_routines.json"))
    monkeypatch.setattr(wizard, "SETTINGS_FILE", str(base / "astakos_settings.json"))
    monkeypatch.setattr(wizard, "PROMPTS_DIR", str(prompts_dir))
    monkeypatch.setattr(wizard.threading, "Thread", _NoOpThread)


# ────────────────────────────────────────────────────────────────
# 1. Chat Provider Diagnostics
# ────────────────────────────────────────────────────────────────

def test_chat_provider_diagnostics_openai(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-key-12345")
    diag = get_chat_provider_diagnostics("openai")

    assert diag["provider"] == "openai"
    assert diag["configured"] is True
    assert diag["status"] == "ready"
    assert "sk-test-key-12345" not in json.dumps(diag)


def test_chat_provider_diagnostics_anthropic(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-key")
    diag = get_chat_provider_diagnostics("anthropic")

    assert diag["provider"] == "anthropic"
    assert diag["configured"] is True
    assert diag["status"] == "ready"
    assert "sk-ant-test-key" not in json.dumps(diag)


def test_chat_provider_diagnostics_missing_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(config, "OPENAI_API_KEY", "")
    diag = get_chat_provider_diagnostics("openai")

    assert diag["provider"] == "openai"
    assert diag["configured"] is False
    assert diag["status"] == "setup_required"
    assert "missing" in diag["status_message"].lower()


# ────────────────────────────────────────────────────────────────
# 2. Embeddings Provider Diagnostics & Separation
# ────────────────────────────────────────────────────────────────

def test_embeddings_diagnostics_auto_vertex(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    fake_cred = tmp_path / "credentials.json"
    fake_cred.write_text("{}", encoding="utf-8")
    monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", str(fake_cred))

    diag = get_embeddings_diagnostics("auto", "vertex")
    assert diag["resolved_provider"] == "vertex"
    assert diag["status"] == "ready"
    assert diag["backend_identity"] == f"vertex:{DEFAULT_VERTEX_EMBEDDING_MODEL}"


def test_embeddings_diagnostics_auto_anthropic_requires_setup() -> None:
    diag = get_embeddings_diagnostics("auto", "anthropic")
    assert diag["resolved_provider"] is None
    assert diag["status"] == "setup_required"
    assert "anthropic has no native embeddings" in diag["status_message"].lower()
    assert any(c["id"] == "local" for c in diag["available_choices"])


def test_embeddings_diagnostics_anthropic_with_openai_embeddings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai-test")
    diag = get_embeddings_diagnostics("openai", "anthropic")

    assert diag["resolved_provider"] == "openai"
    assert diag["status"] == "ready"
    assert diag["backend_identity"] == f"openai:{DEFAULT_OPENAI_EMBEDDING_MODEL}"


def test_embeddings_diagnostics_local_uninstalled(monkeypatch: pytest.MonkeyPatch) -> None:
    import importlib.util
    monkeypatch.setattr(importlib.util, "find_spec", lambda name: None)

    diag = get_embeddings_diagnostics("local", "openai")
    assert diag["resolved_provider"] == "local"
    assert diag["status"] == "unavailable"
    assert "sentence-transformers" in diag["status_message"]


# ────────────────────────────────────────────────────────────────
# 3. Semantic Memory & Reindex Isolation Diagnostics
# ────────────────────────────────────────────────────────────────

def test_semantic_memory_diagnostics_vertex_legacy_ready(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    fake_cred = tmp_path / "credentials.json"
    fake_cred.write_text("{}", encoding="utf-8")
    monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", str(fake_cred))

    diag = get_semantic_memory_diagnostics("vertex", "vertex")
    assert diag["collection_name"] == "astakos_long_term"
    assert diag["status"] == "ready"
    assert diag["reindex_needed"] is False


def test_semantic_memory_diagnostics_openai_isolated_reindex_notice(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai-key")

    diag = get_semantic_memory_diagnostics("openai", "openai")
    assert diag["collection_name"].startswith("astakos_vec_")
    assert diag["status"] == "reindex_needed"
    assert diag["reindex_needed"] is True
    assert "isolated" in diag["status_message"].lower()


def test_semantic_memory_diagnostics_unconfigured_embeddings() -> None:
    diag = get_semantic_memory_diagnostics("auto", "anthropic")
    assert diag["collection_name"] == "astakos_vec_unconfigured"
    assert diag["status"] == "degraded"
    assert diag["reindex_needed"] is False


# ────────────────────────────────────────────────────────────────
# 4. Google Workspace Diagnostics
# ────────────────────────────────────────────────────────────────

def test_workspace_diagnostics_missing_token(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("ASTAKOS_TOKEN_PATH", str(tmp_path / "token.json"))
    monkeypatch.setenv("ASTAKOS_CLIENT_SECRETS_PATH", str(tmp_path / "client_secrets.json"))

    ws = get_workspace_diagnostics()
    assert ws["connected"] is False
    assert ws["status"] == "missing_authorization"
    assert ws["services"]["drive"] == "missing_authorization"
    assert ws["services"]["google_fit"] == "missing_authorization"


def test_workspace_diagnostics_connected_with_all_scopes(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    token_file = tmp_path / "token.json"
    all_scopes = [
        "https://www.googleapis.com/auth/drive",
        "https://www.googleapis.com/auth/gmail.modify",
        "https://www.googleapis.com/auth/calendar",
        "https://www.googleapis.com/auth/tasks",
        "https://www.googleapis.com/auth/fitness.activity.read",
        "https://www.googleapis.com/auth/fitness.sleep.read",
        "https://www.googleapis.com/auth/fitness.heart_rate.read",
    ]
    token_file.write_text(json.dumps({"token": "fake-tok", "scopes": all_scopes}), encoding="utf-8")
    monkeypatch.setenv("ASTAKOS_TOKEN_PATH", str(token_file))

    ws = get_workspace_diagnostics()
    assert ws["connected"] is True
    assert ws["status"] == "connected"
    assert all(status == "connected" for status in ws["services"].values())


def test_workspace_diagnostics_missing_fit_scopes(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    token_file = tmp_path / "token.json"
    partial_scopes = [
        "https://www.googleapis.com/auth/drive",
        "https://www.googleapis.com/auth/gmail.modify",
        "https://www.googleapis.com/auth/calendar",
        "https://www.googleapis.com/auth/tasks",
    ]
    token_file.write_text(json.dumps({"token": "fake-tok", "scopes": partial_scopes}), encoding="utf-8")
    monkeypatch.setenv("ASTAKOS_TOKEN_PATH", str(token_file))

    ws = get_workspace_diagnostics()
    assert ws["connected"] is True
    assert ws["status"] == "missing_scope"
    assert ws["services"]["drive"] == "connected"
    assert ws["services"]["google_fit"] == "missing_scope"


def test_workspace_diagnostics_legacy_token_without_scopes_metadata(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    token_file = tmp_path / "token.json"
    token_file.write_text(json.dumps({"token": "fake-tok"}), encoding="utf-8")
    monkeypatch.setenv("ASTAKOS_TOKEN_PATH", str(token_file))

    ws = get_workspace_diagnostics()
    assert ws["connected"] is True
    assert ws["status"] == "connected"
    assert ws["services"]["drive"] == "connected"


# ────────────────────────────────────────────────────────────────
# 5. Setup Wizard API Endpoints & Secret Sanitization
# ────────────────────────────────────────────────────────────────

def test_setup_wizard_raw_files_masks_secrets(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    import api.setup_wizard as wizard
    _configure_isolated_wizard(monkeypatch, tmp_path)

    raw_env = (
        "LLM_PROVIDER=openai\n"
        "OPENAI_API_KEY=sk-real-super-secret-key-123\n"
        "TELEGRAM_TOKEN=123456:secret-token\n"
        "PROJECT_ID=my-project\n"
    )
    (tmp_path / ".env").write_text(raw_env, encoding="utf-8")

    result = asyncio.run(wizard.get_raw_files())
    env_out = result["env"]

    assert "sk-real-super-secret-key-123" not in env_out
    assert "secret-token" not in env_out
    assert "OPENAI_API_KEY=********" in env_out
    assert "TELEGRAM_TOKEN=********" in env_out
    assert "PROJECT_ID=my-project" in env_out


def test_setup_wizard_save_setup_preserves_masked_secrets(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    import api.setup_wizard as wizard
    _configure_isolated_wizard(monkeypatch, tmp_path)

    raw_env = (
        "LLM_PROVIDER=openai\n"
        "OPENAI_API_KEY=sk-real-super-secret-key-123\n"
        "TELEGRAM_TOKEN=123456:secret-token\n"
    )
    (tmp_path / ".env").write_text(raw_env, encoding="utf-8")

    # User changes only bot name, submits without re-entering key (leaving api_key blank)
    payload = wizard.SetupPayload(
        basic={
            "llm_provider": "openai",
            "embeddings_provider": "auto",
            "api_key": "",
            "env": "LLM_PROVIDER=openai\nOPENAI_API_KEY=********\nTELEGRAM_TOKEN=********\n",
        },
        advanced={},
        prompts={},
        routines="",
    )

    result = asyncio.run(wizard.save_setup(payload))
    assert result["status"] == "success"
    assert "diagnostics" in result

    saved_env = (tmp_path / ".env").read_text(encoding="utf-8")
    assert "OPENAI_API_KEY=sk-real-super-secret-key-123" in saved_env
    assert "TELEGRAM_TOKEN=123456:secret-token" in saved_env
    assert "EMBEDDINGS_PROVIDER=auto" in saved_env



def test_setup_wizard_diagnostics_endpoint() -> None:
    import api.setup_wizard as wizard
    diag = asyncio.run(wizard.get_diagnostics())

    assert "chat_provider" in diag
    assert "embeddings_provider" in diag
    assert "semantic_memory" in diag
    assert "workspace" in diag


def test_setup_wizard_workspace_connect_explicit_action(monkeypatch: pytest.MonkeyPatch) -> None:
    import api.setup_wizard as wizard
    import core.workspace_oauth as ws_oauth

    called = []
    monkeypatch.setattr(
        ws_oauth,
        "authorize_workspace_oauth",
        lambda: called.append(True) or "Google Workspace authorized successfully.",
    )

    res = asyncio.run(wizard.connect_workspace())
    assert res["status"] == "success"
    assert len(called) == 1


# ────────────────────────────────────────────────────────────────
# 6. Boot Diagnostic Formatting & Safety
# ────────────────────────────────────────────────────────────────

def test_format_boot_diagnostics_text_non_sensitive(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-secret-key-to-not-leak")
    text = format_boot_diagnostics_text("openai", "openai")

    assert "Astakos Boot Diagnostics" in text
    assert "Chat Provider:" in text
    assert "Embeddings Provider:" in text
    assert "Semantic Memory:" in text
    assert "Google Workspace:" in text
    assert "sk-secret-key-to-not-leak" not in text
