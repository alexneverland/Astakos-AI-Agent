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
    _check_local_e5_readiness,
    find_offline_adc_credentials_path,
    format_boot_diagnostics_text,
    get_chat_provider_diagnostics,
    get_embeddings_diagnostics,
    get_semantic_memory_diagnostics,
    get_system_diagnostics_summary,
    get_workspace_diagnostics,
    inspect_semantic_memory_inventory,
    is_chat_provider_configured,
    resolve_local_embedding_model,
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
    monkeypatch.setattr(config, "PROJECT_ID", "your-gcp-project-id")
    monkeypatch.setenv("PROJECT_ID", "your-gcp-project-id")


def _make_test_sa_dict(project_id: str = "test-project") -> dict[str, str]:
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.hazmat.primitives import serialization
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption()
    ).decode("utf-8")
    return {
        "type": "service_account",
        "project_id": project_id,
        "private_key_id": "key123",
        "private_key": pem,
        "client_email": f"sa@{project_id}.iam.gserviceaccount.com",
        "client_id": "123456789",
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
    }


def _make_test_adc_dict(project_id: str = "test-project") -> dict[str, str]:
    return {
        "type": "authorized_user",
        "client_id": "cid-123.apps.googleusercontent.com",
        "client_secret": "csec-secret",
        "refresh_token": "1//refresh-token-val",
        "quota_project_id": project_id,
    }


# ────────────────────────────────────────────────────────────────
# 1. Chat Provider Diagnostics & Vertex ADC / Credentials Handling
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


def test_chat_provider_diagnostics_vertex_placeholder_without_credentials(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """PROJECT_ID alone (e.g. 'your-gcp-project-id') must never report Vertex as ready without credential files."""
    monkeypatch.setenv("PROJECT_ID", "your-gcp-project-id")
    monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", str(tmp_path / "non_existent_cred.json"))
    monkeypatch.setattr(config, "CREDENTIALS_PATH", str(tmp_path / "non_existent_cred.json"))
    monkeypatch.setattr(config, "BASE_DIR", str(tmp_path))
    monkeypatch.setattr("core.diagnostics.find_offline_adc_credentials_path", lambda: None)

    diag = get_chat_provider_diagnostics("vertex")
    assert diag["provider"] == "vertex"
    assert diag["configured"] is False
    assert diag["status"] == "setup_required"


def test_chat_provider_diagnostics_vertex_real_service_account_credentials(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Real local service account credential file with project_id correctly reports Vertex as ready."""
    fake_cred = tmp_path / "credentials.json"
    fake_cred.write_text(json.dumps(_make_test_sa_dict("my-gcp-prod-123")), encoding="utf-8")
    monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", str(fake_cred))
    monkeypatch.setenv("PROJECT_ID", "your-gcp-project-id")

    diag = get_chat_provider_diagnostics("vertex")
    assert diag["provider"] == "vertex"
    assert diag["configured"] is True
    assert diag["status"] == "ready"


def test_chat_provider_diagnostics_vertex_credential_file_with_placeholder_project(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Credential file without project_id when PROJECT_ID is placeholder reports setup_required."""
    fake_cred = tmp_path / "credentials.json"
    sa_dict = _make_test_sa_dict("")
    sa_dict.pop("project_id", None)
    fake_cred.write_text(json.dumps(sa_dict), encoding="utf-8")
    monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", str(fake_cred))
    monkeypatch.setenv("PROJECT_ID", "your-gcp-project-id")

    diag = get_chat_provider_diagnostics("vertex")
    assert diag["provider"] == "vertex"
    assert diag["configured"] is False
    assert diag["status"] == "setup_required"


def test_chat_provider_diagnostics_vertex_rejects_truncated_or_non_credential_json(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Non-credential JSON or truncated service accounts with a project_id report setup_required."""
    fake_cred = tmp_path / "credentials.json"
    fake_cred.write_text('{"project_id": "real-project-id"}', encoding="utf-8")
    monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", str(fake_cred))
    monkeypatch.setenv("PROJECT_ID", "your-gcp-project-id")

    diag = get_chat_provider_diagnostics("vertex")
    assert diag["configured"] is False
    assert diag["status"] == "setup_required"

    fake_cred.write_text('{"type": "service_account", "project_id": "real-project-id"}', encoding="utf-8")
    diag = get_chat_provider_diagnostics("vertex")
    assert diag["configured"] is False
    assert diag["status"] == "setup_required"


def test_chat_provider_diagnostics_vertex_adc_with_real_project_id(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Offline ADC file plus a real project ID correctly reports Vertex as ready without network calls."""
    adc_file = tmp_path / "application_default_credentials.json"
    adc_file.write_text(json.dumps(_make_test_adc_dict("my-production-astakos-project")), encoding="utf-8")
    monkeypatch.delenv("GOOGLE_APPLICATION_CREDENTIALS", raising=False)
    monkeypatch.setattr(config, "CREDENTIALS_PATH", "")
    monkeypatch.setattr(config, "BASE_DIR", str(tmp_path))
    monkeypatch.setattr("core.diagnostics.find_offline_adc_credentials_path", lambda: str(adc_file))
    monkeypatch.setenv("PROJECT_ID", "my-production-astakos-project")

    diag = get_chat_provider_diagnostics("vertex")
    assert diag["provider"] == "vertex"
    assert diag["configured"] is True
    assert diag["status"] == "ready"


def test_chat_provider_diagnostics_vertex_adc_with_placeholder_project_id(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Offline ADC file with placeholder project ID reports setup_required."""
    adc_file = tmp_path / "application_default_credentials.json"
    adc_file.write_text(json.dumps(_make_test_adc_dict("")), encoding="utf-8")
    monkeypatch.delenv("GOOGLE_APPLICATION_CREDENTIALS", raising=False)
    monkeypatch.setattr(config, "CREDENTIALS_PATH", "")
    monkeypatch.setattr(config, "BASE_DIR", str(tmp_path))
    monkeypatch.setattr("core.diagnostics.find_offline_adc_credentials_path", lambda: str(adc_file))
    monkeypatch.setenv("PROJECT_ID", "your-gcp-project-id")

    diag = get_chat_provider_diagnostics("vertex")
    assert diag["provider"] == "vertex"
    assert diag["configured"] is False
    assert diag["status"] == "setup_required"


def test_chat_provider_diagnostics_vertex_falls_back_to_root_credentials_when_credentials_path_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """When config.CREDENTIALS_PATH does not exist, vertex readiness falls back to root credentials.json."""
    root_cred = tmp_path / "credentials.json"
    root_cred.write_text(json.dumps(_make_test_sa_dict("root-fallback-project")), encoding="utf-8")
    monkeypatch.delenv("GOOGLE_APPLICATION_CREDENTIALS", raising=False)
    monkeypatch.setattr(config, "CREDENTIALS_PATH", str(tmp_path / "credentials" / "credentials.json"))
    monkeypatch.setattr(config, "BASE_DIR", str(tmp_path))
    monkeypatch.setenv("PROJECT_ID", "root-fallback-project")

    diag = get_chat_provider_diagnostics("vertex")
    assert diag["provider"] == "vertex"
    assert diag["configured"] is True
    assert diag["status"] == "ready"


def test_boot_is_configured_reuses_canonical_vertex_readiness(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """boot.is_configured reuses canonical Vertex readiness logic for ADC and service accounts."""
    import boot
    env_file = tmp_path / ".env"
    env_file.write_text("LLM_PROVIDER=vertex\nPROJECT_ID=my-boot-project\n", encoding="utf-8")
    monkeypatch.setattr(boot, "__file__", str(tmp_path / "boot.py"))

    adc_file = tmp_path / "application_default_credentials.json"
    adc_file.write_text(json.dumps(_make_test_adc_dict("my-boot-project")), encoding="utf-8")
    monkeypatch.setattr("core.diagnostics.find_offline_adc_credentials_path", lambda: str(adc_file))
    monkeypatch.setattr(config, "BASE_DIR", str(tmp_path))

    assert boot.is_configured() is True


# ────────────────────────────────────────────────────────────────
# 2. Embeddings Provider Diagnostics & Local Model Resolver
# ────────────────────────────────────────────────────────────────

def test_embeddings_diagnostics_auto_vertex(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    fake_cred = tmp_path / "credentials.json"
    fake_cred.write_text(json.dumps(_make_test_sa_dict("my-vertex-proj")), encoding="utf-8")
    monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", str(fake_cred))
    monkeypatch.setenv("PROJECT_ID", "my-vertex-proj")

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
    _check_local_e5_readiness.cache_clear()
    monkeypatch.setattr(importlib.util, "find_spec", lambda name: None)

    diag = get_embeddings_diagnostics("local", "openai")
    assert diag["resolved_provider"] == "local"
    assert diag["status"] == "unavailable"
    assert "sentence-transformers" in diag["status_message"]
    _check_local_e5_readiness.cache_clear()


def test_local_e5_diagnostics_uses_configured_custom_model_and_caches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Diagnostics uses ASTAKOS_LOCAL_EMBEDDING_MODEL and instantiates model at most once across calls."""
    _check_local_e5_readiness.cache_clear()
    custom_model = "intfloat/multilingual-e5-base"
    monkeypatch.setenv("ASTAKOS_LOCAL_EMBEDDING_MODEL", custom_model)

    load_count = 0
    loaded_models: list[str] = []

    class _MockSentenceTransformer:
        def __init__(self, model_name: str, *args: Any, **kwargs: Any) -> None:
            nonlocal load_count
            load_count += 1
            loaded_models.append(model_name)

    import sys
    monkeypatch.setitem(
        sys.modules,
        "sentence_transformers",
        type("Module", (), {"SentenceTransformer": _MockSentenceTransformer})(),
    )

    # Call diagnostics 4 times
    for _ in range(4):
        diag = get_embeddings_diagnostics("local", "openai")
        assert diag["status"] == "ready"
        assert diag["backend_identity"] == f"local:{custom_model}"

    assert load_count == 1
    assert loaded_models == [custom_model]
    _check_local_e5_readiness.cache_clear()


# ────────────────────────────────────────────────────────────────
# 3. Evidence-Based Semantic Memory & Reindexing Diagnostics
# ────────────────────────────────────────────────────────────────

def test_semantic_memory_evidence_fresh_installation(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fresh install with no populated collections does not require reindexing."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-key")
    diag = get_semantic_memory_diagnostics("openai", "openai", collection_inventory={})

    assert diag["collection_name"].startswith("astakos_vec_")
    assert diag["status"] == "ready"
    assert diag["reindex_needed"] is False
    assert "ready" in diag["status_message"].lower()


def test_semantic_memory_evidence_active_collection_with_no_other_collections(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Already active collection with existing vectors and no historical collections elsewhere is ready."""
    from core.ai_provider import get_embeddings_collection_name
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-key")
    col_name = get_embeddings_collection_name("openai", "openai")
    inventory = {col_name: 42}

    diag = get_semantic_memory_diagnostics("openai", "openai", collection_inventory=inventory)
    assert diag["collection_name"] == col_name
    assert diag["status"] == "ready"
    assert diag["reindex_needed"] is False
    assert "42 memories indexed" in diag["status_message"]


def test_semantic_memory_evidence_switch_vertex_to_openai(monkeypatch: pytest.MonkeyPatch) -> None:
    """Switching from populated Vertex to empty OpenAI collection requires reindexing."""
    from core.ai_provider import get_embeddings_collection_name
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-key")
    col_name = get_embeddings_collection_name("openai", "openai")
    inventory = {
        "astakos_long_term": 50,
        col_name: 0,
    }

    diag = get_semantic_memory_diagnostics("openai", "openai", collection_inventory=inventory)
    assert diag["collection_name"] == col_name
    assert diag["status"] == "reindex_needed"
    assert diag["reindex_needed"] is True
    assert "astakos_long_term" in diag["status_message"]


def test_semantic_memory_evidence_switch_openai_to_vertex(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Switching from populated OpenAI to empty Vertex collection requires reindexing."""
    from core.ai_provider import get_embeddings_collection_name
    fake_cred = tmp_path / "credentials.json"
    fake_cred.write_text(json.dumps(_make_test_sa_dict("vertex-test-project")), encoding="utf-8")
    monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", str(fake_cred))
    monkeypatch.setenv("PROJECT_ID", "vertex-test-project")

    col_name = get_embeddings_collection_name("openai", "openai")
    inventory = {
        col_name: 50,
        "astakos_long_term": 0,
    }

    diag = get_semantic_memory_diagnostics("vertex", "vertex", collection_inventory=inventory)
    assert diag["collection_name"] == "astakos_long_term"
    assert diag["status"] == "reindex_needed"
    assert diag["reindex_needed"] is True
    assert col_name in diag["status_message"]



def test_semantic_memory_evidence_uninspectable_returns_safe_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When Chroma cannot be inspected safely, returns explicit safe status without claiming reindex is needed."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-key")
    monkeypatch.setattr("core.diagnostics.inspect_semantic_memory_inventory", lambda *args: None)

    diag = get_semantic_memory_diagnostics("openai", "openai")
    assert diag["collection_name"].startswith("astakos_vec_")
    assert diag["status"] == "ready"
    assert diag["reindex_needed"] is False


def test_semantic_memory_inventory_uses_managed_vector_store_handle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """inspect_semantic_memory_inventory uses existing managed vector_store handle without opening duplicate client."""
    import memory.vector_store as m_vs

    class _MockCollection:
        def __init__(self, name: str, count: int) -> None:
            self.name = name
            self._count = count

        def count(self) -> int:
            return self._count

    class _MockClient:
        def list_collections(self) -> list[Any]:
            return [_MockCollection("astakos_long_term", 10), _MockCollection("astakos_vec_test", 5)]

    class _MockVectorStore:
        def __init__(self) -> None:
            self._client = _MockClient()

    monkeypatch.setattr(m_vs, "vector_store", _MockVectorStore())
    inv = inspect_semantic_memory_inventory()
    assert inv == {"astakos_long_term": 10, "astakos_vec_test": 5}


def test_semantic_memory_inventory_returns_none_when_vector_store_not_loaded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When memory.vector_store is not loaded in sys.modules, inspect_semantic_memory_inventory returns None without importing or opening Chroma."""
    import sys
    monkeypatch.setitem(sys.modules, "memory.vector_store", None)
    inv = inspect_semantic_memory_inventory()
    assert inv is None


def test_semantic_memory_diagnostics_unconfigured_embeddings() -> None:
    diag = get_semantic_memory_diagnostics("auto", "anthropic")
    assert diag["collection_name"] == "astakos_vec_unconfigured"
    assert diag["status"] == "degraded"
    assert diag["reindex_needed"] is False



# ────────────────────────────────────────────────────────────────
# 4. Google Workspace Diagnostics & Token Corruption Handling
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
    token_file.write_text(
        json.dumps({
            "token": "fake-tok",
            "client_id": "cid",
            "client_secret": "csec",
            "refresh_token": "rt",
            "scopes": all_scopes,
        }),
        encoding="utf-8",
    )
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
    token_file.write_text(
        json.dumps({
            "token": "fake-tok",
            "client_id": "cid",
            "client_secret": "csec",
            "refresh_token": "rt",
            "scopes": partial_scopes,
        }),
        encoding="utf-8",
    )
    monkeypatch.setenv("ASTAKOS_TOKEN_PATH", str(token_file))

    ws = get_workspace_diagnostics()
    assert ws["connected"] is True
    assert ws["status"] == "missing_scope"
    assert ws["services"]["drive"] == "connected"
    assert ws["services"]["google_fit"] == "missing_scope"


def test_workspace_diagnostics_explicit_empty_scopes_reports_missing_scope(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Explicitly empty scopes list (e.g. 'scopes': []) reports missing_scope rather than legacy connected."""
    token_file = tmp_path / "token.json"
    token_file.write_text(
        json.dumps({
            "token": "fake-tok",
            "client_id": "cid",
            "client_secret": "csec",
            "refresh_token": "rt",
            "scopes": [],
        }),
        encoding="utf-8",
    )
    monkeypatch.setenv("ASTAKOS_TOKEN_PATH", str(token_file))

    ws = get_workspace_diagnostics()
    assert ws["connected"] is True
    assert ws["status"] == "missing_scope"
    assert all(status == "missing_scope" for status in ws["services"].values())


def test_workspace_diagnostics_legacy_token_without_scopes_metadata(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    token_file = tmp_path / "token.json"
    token_file.write_text(json.dumps({"refresh_token": "fake-rt", "client_id": "cid", "client_secret": "csec"}), encoding="utf-8")
    monkeypatch.setenv("ASTAKOS_TOKEN_PATH", str(token_file))

    ws = get_workspace_diagnostics()
    assert ws["connected"] is True
    assert ws["status"] == "connected"
    assert ws["services"]["drive"] == "connected"


def test_workspace_diagnostics_corrupt_malformed_token_json(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A corrupted/malformed token file reports needs_reconnect rather than connected."""
    token_file = tmp_path / "token.json"
    token_file.write_text("{corrupt-invalid-json-content", encoding="utf-8")
    monkeypatch.setenv("ASTAKOS_TOKEN_PATH", str(token_file))

    ws = get_workspace_diagnostics()
    assert ws["connected"] is False
    assert ws["status"] == "needs_reconnect"
    assert all(status == "needs_reconnect" for status in ws["services"].values())


# ────────────────────────────────────────────────────────────────
# 5. Setup Wizard API Endpoints, Independent Embeddings & Settings
# ────────────────────────────────────────────────────────────────

def test_setup_wizard_save_anthropic_chat_with_openai_embeddings(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Guided setup allows configuring Anthropic chat credentials together with OpenAI embeddings credentials."""
    import api.setup_wizard as wizard
    _configure_isolated_wizard(monkeypatch, tmp_path)

    payload = wizard.SetupPayload(
        basic={
            "llm_provider": "anthropic",
            "api_key": "sk-ant-chat-key-12345",
            "embeddings_provider": "openai",
            "embeddings_api_key": "sk-proj-emb-key-67890",
        },
        advanced={},
        prompts={},
        routines="",
    )

    result = asyncio.run(wizard.save_setup(payload))
    assert result["status"] == "success"

    saved_env = (tmp_path / ".env").read_text(encoding="utf-8")
    assert "LLM_PROVIDER=anthropic" in saved_env
    assert "ANTHROPIC_API_KEY=sk-ant-chat-key-12345" in saved_env
    assert "EMBEDDINGS_PROVIDER=openai" in saved_env
    assert "OPENAI_API_KEY=sk-proj-emb-key-67890" in saved_env

    # Diagnostics immediately reflects both as ready
    assert result["diagnostics"]["chat_provider"]["status"] == "ready"
    assert result["diagnostics"]["embeddings_provider"]["status"] == "ready"


def test_setup_wizard_save_gemini_and_vertex_embeddings(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Guided setup correctly routes Gemini and Vertex embeddings credentials."""
    import api.setup_wizard as wizard
    _configure_isolated_wizard(monkeypatch, tmp_path)

    # 1. Gemini embeddings
    payload_gemini = wizard.SetupPayload(
        basic={
            "llm_provider": "openai",
            "api_key": "sk-chat-key",
            "embeddings_provider": "gemini",
            "embeddings_api_key": "AIzaSyGeminiApiKey",
        },
        advanced={},
        prompts={},
        routines="",
    )
    result_gemini = asyncio.run(wizard.save_setup(payload_gemini))
    assert result_gemini["status"] == "success"
    saved_env = (tmp_path / ".env").read_text(encoding="utf-8")
    assert "GEMINI_API_KEY=AIzaSyGeminiApiKey" in saved_env

    # 2. Vertex embeddings
    fake_cred = tmp_path / "gcp_cred.json"
    fake_cred.write_text("{}", encoding="utf-8")
    payload_vertex = wizard.SetupPayload(
        basic={
            "llm_provider": "anthropic",
            "api_key": "sk-ant-key",
            "embeddings_provider": "vertex",
            "embeddings_api_key": str(fake_cred),
        },
        advanced={},
        prompts={},
        routines="",
    )
    result_vertex = asyncio.run(wizard.save_setup(payload_vertex))
    assert result_vertex["status"] == "success"
    saved_env_v = (tmp_path / ".env").read_text(encoding="utf-8")
    assert f"GOOGLE_APPLICATION_CREDENTIALS={fake_cred}" in saved_env_v


def test_setup_wizard_save_clears_all_child_names(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Clearing all children removes kid1_name and kid2_name from persisted settings."""
    import api.setup_wizard as wizard
    _configure_isolated_wizard(monkeypatch, tmp_path)

    initial_settings = {
        "user_name": "Alex",
        "kid1_name": "ChildOne",
        "kid2_name": "ChildTwo",
        "custom_feature": "preserve_this",
    }
    (tmp_path / "astakos_settings.json").write_text(json.dumps(initial_settings), encoding="utf-8")

    payload = wizard.SetupPayload(
        basic={
            "llm_provider": "openai",
            "settings": {
                "user_name": "Alex",
                # kid1_name and kid2_name omitted because user cleared the input
            },
        },
        advanced={},
        prompts={},
        routines="",
    )

    result = asyncio.run(wizard.save_setup(payload))
    assert result["status"] == "success"

    saved = json.loads((tmp_path / "astakos_settings.json").read_text(encoding="utf-8"))
    assert "kid1_name" not in saved
    assert "kid2_name" not in saved
    assert saved["user_name"] == "Alex"
    assert saved["custom_feature"] == "preserve_this"


def test_setup_wizard_save_reduces_two_child_names_to_one(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Reducing two children to one removes kid2_name and retains kid1_name."""
    import api.setup_wizard as wizard
    _configure_isolated_wizard(monkeypatch, tmp_path)

    initial_settings = {
        "user_name": "Alex",
        "kid1_name": "ChildOne",
        "kid2_name": "ChildTwo",
    }
    (tmp_path / "astakos_settings.json").write_text(json.dumps(initial_settings), encoding="utf-8")

    payload = wizard.SetupPayload(
        basic={
            "llm_provider": "openai",
            "settings": {
                "user_name": "Alex",
                "kid1_name": "ChildOne",
                # kid2_name omitted
            },
        },
        advanced={},
        prompts={},
        routines="",
    )

    result = asyncio.run(wizard.save_setup(payload))
    assert result["status"] == "success"

    saved = json.loads((tmp_path / "astakos_settings.json").read_text(encoding="utf-8"))
    assert saved["kid1_name"] == "ChildOne"
    assert "kid2_name" not in saved


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


def test_setup_wizard_diagnostics_and_setup_never_leak_sentinel_secrets(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Endpoints and diagnostics never expose raw exception strings or injected sentinel secrets."""
    import api.setup_wizard as wizard
    _configure_isolated_wizard(monkeypatch, tmp_path)

    sentinel_secret = "sk-super-secret-sentinel-leak-marker-999"

    # Inject failure into provider resolution
    def _exploding_resolve(*args: Any, **kwargs: Any) -> str:
        raise RuntimeError(f"Simulated failure containing {sentinel_secret}")

    monkeypatch.setattr("core.diagnostics.resolve_embeddings_provider", _exploding_resolve)

    # 1. GET /api/diagnostics
    diag_res = asyncio.run(wizard.get_diagnostics())
    assert sentinel_secret not in json.dumps(diag_res)

    # 2. POST /api/setup
    payload = wizard.SetupPayload(
        basic={"llm_provider": "openai", "embeddings_provider": "openai"},
        advanced={},
        prompts={},
        routines="",
    )
    setup_res = asyncio.run(wizard.save_setup(payload))
    assert sentinel_secret not in json.dumps(setup_res)


def test_setup_wizard_workspace_connect_explicit_action(monkeypatch: pytest.MonkeyPatch) -> None:
    from unittest.mock import MagicMock
    import api.setup_wizard as wizard
    import core.workspace_oauth as ws_oauth

    called = []
    monkeypatch.setattr(
        ws_oauth,
        "authorize_workspace_oauth",
        lambda: called.append(True) or "Google Workspace authorized successfully.",
    )
    mock_request = MagicMock()
    mock_request.base_url = "http://localhost:8000"

    res = asyncio.run(wizard.connect_workspace(mock_request))
    assert res["status"] == "success"
    assert len(called) == 1


def test_setup_wizard_workspace_oauth_endpoints(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """OAuth start and callback endpoints handle container-reachable flows, verify state, and persist token."""
    from unittest.mock import MagicMock
    import api.setup_wizard as wizard
    import core.workspace_oauth as ws_oauth

    _configure_isolated_wizard(monkeypatch, tmp_path)
    token_target = tmp_path / "token.json"
    monkeypatch.setattr(ws_oauth, "get_token_path", lambda: str(token_target))

    class _MockFlow:
        code_verifier = "setup-wizard-pkce-verifier"

        def __init__(self) -> None:
            self.credentials = MagicMock()
            self.credentials.to_json.return_value = '{"token": "xyz", "client_id": "cid", "client_secret": "csec", "refresh_token": "rt"}'

        def authorization_url(self, **kwargs: Any) -> tuple[str, str]:
            state = kwargs.get("state", "test_state")
            return (f"https://accounts.google.com/o/oauth2/auth?client_id=123&state={state}", state)

        def fetch_token(self, code: str) -> None:
            assert code == "test_auth_code"

    monkeypatch.setattr(ws_oauth, "get_workspace_oauth_flow", lambda **kwargs: _MockFlow())

    mock_request = MagicMock()
    mock_request.base_url = "http://localhost:8000"

    # 1. GET /api/workspace/oauth/start returns auth_url containing state
    start_res = asyncio.run(wizard.start_workspace_oauth(mock_request))
    assert "auth_url" in start_res
    auth_url = start_res["auth_url"]
    assert "state=" in auth_url

    # Extract state parameter from auth_url
    import urllib.parse
    parsed = urllib.parse.urlparse(auth_url)
    qs = urllib.parse.parse_qs(parsed.query)
    state = qs["state"][0]

    # 2. Callback with invalid state is rejected with 400
    invalid_cb = asyncio.run(wizard.workspace_oauth_callback(mock_request, code="test_auth_code", state="invalid_state"))
    assert invalid_cb.status_code == 400

    # 3. Callback with valid state succeeds and persists token
    cb_res = asyncio.run(wizard.workspace_oauth_callback(mock_request, code="test_auth_code", state=state))
    assert cb_res.status_code == 200
    assert token_target.exists()
    assert "client_id" in token_target.read_text(encoding="utf-8")

    # 4. POST /api/workspace/connect with ASTAKOS_CONTAINER=1 registers valid state
    monkeypatch.setenv("ASTAKOS_CONTAINER", "1")
    conn_res = asyncio.run(wizard.connect_workspace(mock_request))
    assert conn_res["status"] == "redirect"
    assert "auth_url" in conn_res
    conn_parsed = urllib.parse.urlparse(conn_res["auth_url"])
    conn_state = urllib.parse.parse_qs(conn_parsed.query)["state"][0]
    conn_cb = asyncio.run(wizard.workspace_oauth_callback(mock_request, code="test_auth_code", state=conn_state))
    assert conn_cb.status_code == 200


def test_vertex_ai_adapter_resolves_project_id_and_credentials(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """VertexAIAdapter resolves real project_id and loads credentials from discovered credentials JSON."""
    from unittest.mock import MagicMock
    from core.ai_provider import VertexAIAdapter, resolve_vertex_project_id, resolve_vertex_credentials_path
    fake_cred = tmp_path / "credentials.json"
    fake_cred.write_text('{"type": "service_account", "project_id": "discovered-vertex-project"}', encoding="utf-8")
    monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", str(fake_cred))
    monkeypatch.setenv("PROJECT_ID", "your-gcp-project-id")
    monkeypatch.setattr(config, "PROJECT_ID", "your-gcp-project-id")

    mock_creds = MagicMock()
    monkeypatch.setattr("core.ai_provider.get_vertex_credentials", lambda path: mock_creds)

    assert resolve_vertex_credentials_path() == str(fake_cred)
    assert resolve_vertex_project_id() == "discovered-vertex-project"
    adapter = VertexAIAdapter()
    assert adapter.project_id == "discovered-vertex-project"
    assert adapter.credentials_path == str(fake_cred)
    assert adapter._credentials is mock_creds


def test_vertex_ai_adapter_resolves_project_id_and_credentials_from_adc(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """VertexAIAdapter resolves quota_project_id from ADC file when config.PROJECT_ID is placeholder."""
    from core.ai_provider import VertexAIAdapter, resolve_vertex_project_id, resolve_vertex_credentials_path
    adc_file = tmp_path / "application_default_credentials.json"
    adc_file.write_text(json.dumps(_make_test_adc_dict("discovered-adc-project")), encoding="utf-8")
    monkeypatch.delenv("GOOGLE_APPLICATION_CREDENTIALS", raising=False)
    monkeypatch.setattr(config, "CREDENTIALS_PATH", "")
    monkeypatch.setattr(config, "BASE_DIR", str(tmp_path))
    monkeypatch.setattr("core.ai_provider.find_offline_adc_credentials_path", lambda: str(adc_file))
    monkeypatch.setenv("PROJECT_ID", "your-gcp-project-id")
    monkeypatch.setattr(config, "PROJECT_ID", "your-gcp-project-id")

    assert resolve_vertex_credentials_path() == str(adc_file)
    assert resolve_vertex_project_id() == "discovered-adc-project"
    adapter = VertexAIAdapter()
    assert adapter.project_id == "discovered-adc-project"
    assert adapter.credentials_path == str(adc_file)
    assert adapter._credentials is not None


def test_vertex_ai_adapter_preserves_configured_project_id_over_credentials_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Configured PROJECT_ID takes precedence over the credential file's project ID."""
    from core.ai_provider import VertexAIAdapter, resolve_vertex_project_id
    fake_cred = tmp_path / "credentials.json"
    fake_cred.write_text(json.dumps(_make_test_sa_dict("credential-owning-project")), encoding="utf-8")
    monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", str(fake_cred))
    monkeypatch.setenv("PROJECT_ID", "my-target-project-456")
    monkeypatch.setattr(config, "PROJECT_ID", "my-target-project-456")

    assert resolve_vertex_project_id() == "my-target-project-456"
    adapter = VertexAIAdapter()
    assert adapter.project_id == "my-target-project-456"


def test_vertex_service_account_credentials_scoped_correctly(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Proves that service-account credentials loaded for Vertex are scoped with cloud-platform."""
    from core.ai_provider import VERTEX_OAUTH_SCOPES, get_vertex_credentials
    fake_sa = tmp_path / "sa.json"
    fake_sa.write_text(json.dumps(_make_test_sa_dict("test-sa-proj")), encoding="utf-8")

    creds = get_vertex_credentials(str(fake_sa))
    assert creds is not None
    assert getattr(creds, "scopes", None) == list(VERTEX_OAUTH_SCOPES)
    assert creds.scopes == ["https://www.googleapis.com/auth/cloud-platform"]


def test_vertex_ai_adapter_and_brain_receive_scoped_service_account_credentials(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Proves VertexAIAdapter and core/brain.py primary clients receive scoped service account credentials."""
    import importlib
    from unittest.mock import MagicMock
    import core.brain
    from core.ai_provider import VERTEX_OAUTH_SCOPES, VertexAIAdapter

    fake_sa = tmp_path / "credentials.json"
    fake_sa.write_text(json.dumps(_make_test_sa_dict("test-scoped-proj")), encoding="utf-8")
    monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", str(fake_sa))
    monkeypatch.setenv("PROJECT_ID", "test-scoped-proj")
    monkeypatch.setattr(config, "PROJECT_ID", "test-scoped-proj")
    monkeypatch.setattr(config, "LLM_PROVIDER", "vertex")

    # 1. Verify VertexAIAdapter
    adapter = VertexAIAdapter()
    assert adapter._credentials is not None
    assert adapter._credentials.scopes == list(VERTEX_OAUTH_SCOPES)

    # 2. Verify core/brain.py client initialization
    mock_chat_cls = MagicMock()
    mock_genai_client_cls = MagicMock()
    monkeypatch.setattr("langchain_google_genai.ChatGoogleGenerativeAI", mock_chat_cls)
    monkeypatch.setattr("google.genai.Client", mock_genai_client_cls)

    try:
        importlib.reload(core.brain)

        assert mock_chat_cls.call_count >= 2
        fast_kwargs = mock_chat_cls.call_args_list[0].kwargs
        assert "credentials" in fast_kwargs
        assert fast_kwargs["credentials"].scopes == ["https://www.googleapis.com/auth/cloud-platform"]

        heavy_kwargs = mock_chat_cls.call_args_list[1].kwargs
        assert "credentials" in heavy_kwargs
        assert heavy_kwargs["credentials"].scopes == ["https://www.googleapis.com/auth/cloud-platform"]

        client_kwargs = mock_genai_client_cls.call_args.kwargs
        assert "credentials" in client_kwargs
        assert client_kwargs["credentials"].scopes == ["https://www.googleapis.com/auth/cloud-platform"]
    finally:
        monkeypatch.undo()
        importlib.reload(core.brain)


def test_setup_wizard_save_populates_vertex_project_id_from_credentials(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """save_setup automatically fills in discovered project ID when saving Vertex setup."""
    import api.setup_wizard as wizard
    _configure_isolated_wizard(monkeypatch, tmp_path)

    fake_cred = tmp_path / "credentials.json"
    fake_cred.write_text('{"type": "service_account", "project_id": "auto-filled-project-id"}', encoding="utf-8")
    monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", str(fake_cred))

    payload = wizard.SetupPayload(
        basic={
            "llm_provider": "vertex",
            "embeddings_provider": "vertex",
            "api_key": str(fake_cred),
            "env": "LLM_PROVIDER=vertex\nPROJECT_ID=your-gcp-project-id\n",
        },
        advanced={},
        prompts={},
        routines="",
    )

    result = asyncio.run(wizard.save_setup(payload))
    assert result["status"] == "success"
    saved_env = (tmp_path / ".env").read_text(encoding="utf-8")
    assert "PROJECT_ID=auto-filled-project-id" in saved_env




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
