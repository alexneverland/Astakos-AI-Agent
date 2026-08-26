# ================================================================
# Project: Astakos AI Agent 🦞
# Description: Modular LLM-agnostic multi-agent framework
# Module: Core System Diagnostics & Setup Observability
# Copyright (c) 2026 - All Rights Reserved
# ================================================================

from __future__ import annotations

import functools
import os
from typing import Any, Sequence

import config
from core.ai_provider import (
    DEFAULT_GEMINI_FAST_MODEL,
    DEFAULT_GEMINI_HEAVY_MODEL,
    DEFAULT_LOCAL_EMBEDDING_MODEL,
    DEFAULT_OPENAI_EMBEDDING_MODEL,
    DEFAULT_VERTEX_EMBEDDING_MODEL,
    EmbeddingsProviderSetupRequired,
    get_embeddings_backend_identity,
    get_embeddings_collection_name,
    resolve_embeddings_provider,
    resolve_provider_models,
)
from core.workspace_oauth import (
    check_missing_scopes,
    get_oauth_client_secrets_path,
    get_token_path,
    inspect_workspace_token_metadata,
    is_workspace_connected,
    read_stored_token_scopes,
)


WORKSPACE_SERVICE_SCOPES: dict[str, list[str]] = {
    "drive": ["https://www.googleapis.com/auth/drive"],
    "gmail": ["https://www.googleapis.com/auth/gmail.modify"],
    "calendar": ["https://www.googleapis.com/auth/calendar"],
    "tasks": ["https://www.googleapis.com/auth/tasks"],
    "google_fit": [
        "https://www.googleapis.com/auth/fitness.activity.read",
        "https://www.googleapis.com/auth/fitness.sleep.read",
        "https://www.googleapis.com/auth/fitness.heart_rate.read",
    ],
    "daily_backup": ["https://www.googleapis.com/auth/drive"],
}

AVAILABLE_EMBEDDINGS_CHOICES: list[dict[str, str]] = [
    {
        "id": "auto",
        "name": "Auto",
        "description": "Automatically matches chat provider if it supports native embeddings.",
    },
    {
        "id": "vertex",
        "name": "Google Cloud Vertex AI",
        "description": "text-embedding-004 (Google Cloud Service Account / ADC)",
    },
    {
        "id": "gemini",
        "name": "Google Gemini API",
        "description": "models/text-embedding-004 (Google AI Studio API Key)",
    },
    {
        "id": "openai",
        "name": "OpenAI",
        "description": "text-embedding-3-small (OpenAI API Key)",
    },
    {
        "id": "local",
        "name": "Local Multilingual E5",
        "description": "intfloat/multilingual-e5-small (Offline, requires manual installation)",
    },
]


def find_offline_adc_credentials_path() -> str | None:
    """
    Discovers standard local Application Default Credentials (ADC) file path without network calls.
    Returns path if file exists on disk, otherwise None.
    """
    gac = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    if gac and os.path.exists(gac):
        return gac

    if os.name == "nt":
        app_data = os.environ.get("APPDATA")
        if app_data:
            win_adc = os.path.join(app_data, "gcloud", "application_default_credentials.json")
            if os.path.exists(win_adc):
                return win_adc
    else:
        unix_adc = os.path.expanduser("~/.config/gcloud/application_default_credentials.json")
        if os.path.exists(unix_adc):
            return unix_adc

    return None


def resolve_local_embedding_model(
    env_snapshot: dict[str, str] | None = None,
) -> str:
    """Resolves the configured local embedding model name without mutating environment."""
    if env_snapshot is not None and "ASTAKOS_LOCAL_EMBEDDING_MODEL" in env_snapshot:
        val = env_snapshot["ASTAKOS_LOCAL_EMBEDDING_MODEL"].strip()
        if val:
            return val
    return (
        os.getenv("ASTAKOS_LOCAL_EMBEDDING_MODEL")
        or getattr(config, "LOCAL_EMBEDDING_MODEL", "")
        or DEFAULT_LOCAL_EMBEDDING_MODEL
    ).strip()


@functools.lru_cache(maxsize=8)
def _check_local_e5_readiness(model_name: str = DEFAULT_LOCAL_EMBEDDING_MODEL) -> tuple[str, str]:
    """
    Cached offline readiness check for local embeddings model.
    Never downloads or modifies model files, avoiding repeated expensive loads across polls.
    Never exposes raw exception strings.
    """
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError:
        return (
            "unavailable",
            (
                "Local E5 embeddings are selected, but 'sentence-transformers' is not installed. "
                "Please install sentence-transformers manually before selecting local embeddings."
            ),
        )

    try:
        SentenceTransformer(model_name, local_files_only=True)
        return ("ready", f"Local multilingual E5 embeddings ({model_name}) ready.")
    except Exception:
        return (
            "unavailable",
            (
                f"Local model '{model_name}' is not found locally. "
                "Please download the model explicitly before selecting local embeddings."
            ),
        )


def is_chat_provider_configured(
    provider_name: str,
    env_snapshot: dict[str, str] | None = None,
) -> bool:
    """
    Checks if the required API keys or local credentials for the chat provider are present.
    Evaluates against `env_snapshot` if supplied, otherwise environment variables and config.
    """
    p = (provider_name or "").strip().lower()

    def _get_val(k: str) -> str:
        if env_snapshot is not None and k in env_snapshot:
            return env_snapshot[k]
        return os.environ.get(k) or getattr(config, k, "") or ""

    if p == "openai":
        return bool(_get_val("OPENAI_API_KEY"))
    elif p == "anthropic":
        return bool(_get_val("ANTHROPIC_API_KEY"))
    elif p == "gemini":
        return bool(_get_val("GEMINI_API_KEY") or _get_val("GOOGLE_API_KEY"))
    elif p == "vertex":
        # 1. Explicit snapshot override
        if env_snapshot is not None and "GOOGLE_APPLICATION_CREDENTIALS" in env_snapshot:
            snap_cred = env_snapshot["GOOGLE_APPLICATION_CREDENTIALS"].strip()
            if snap_cred:
                return bool(os.path.exists(snap_cred))

        # 2. Explicit environment variable
        if "GOOGLE_APPLICATION_CREDENTIALS" in os.environ:
            os_cred = os.environ["GOOGLE_APPLICATION_CREDENTIALS"].strip()
            if os_cred:
                return bool(os.path.exists(os_cred))

        # 3. Config CREDENTIALS_PATH if explicitly configured
        config_cred = getattr(config, "CREDENTIALS_PATH", "")
        if config_cred:
            return bool(os.path.exists(config_cred))

        # 4. Standard repository credentials.json
        root_cred = os.path.join(config.BASE_DIR, "credentials.json")
        nested_cred = os.path.join(config.BASE_DIR, "credentials", "credentials.json")
        if os.path.exists(root_cred) or os.path.exists(nested_cred):
            return True

        # 5. Offline ADC (Application Default Credentials)
        adc_path = find_offline_adc_credentials_path()
        if adc_path and os.path.exists(adc_path):
            proj_id = _get_val("PROJECT_ID")
            if proj_id and proj_id.strip().lower() not in ("", "your-gcp-project-id"):
                return True

        return False


    return False


def get_chat_provider_diagnostics(
    chat_provider_name: str | None = None,
    env_snapshot: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Evaluates chat provider readiness without leaking keys or credentials."""
    raw_provider = chat_provider_name
    if raw_provider is None and env_snapshot is not None and "LLM_PROVIDER" in env_snapshot:
        raw_provider = env_snapshot["LLM_PROVIDER"]
    provider = (raw_provider or getattr(config, "LLM_PROVIDER", "vertex")).strip().lower()
    fast_model, heavy_model = resolve_provider_models(provider)
    configured = is_chat_provider_configured(provider, env_snapshot=env_snapshot)

    status = "ready" if configured else "setup_required"
    if configured:
        status_message = f"{provider.capitalize()} chat provider is configured and ready."
    else:
        status_message = f"{provider.capitalize()} chat provider is missing required API key or credentials."

    return {
        "provider": provider,
        "fast_model": fast_model,
        "heavy_model": heavy_model,
        "configured": configured,
        "status": status,
        "status_message": status_message,
    }


def get_embeddings_diagnostics(
    embeddings_provider_name: str | None = None,
    chat_provider_name: str | None = None,
    env_snapshot: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Evaluates embeddings backend readiness independently from chat."""
    configured_raw = embeddings_provider_name
    if configured_raw is None:
        if env_snapshot is not None and "EMBEDDINGS_PROVIDER" in env_snapshot:
            configured_raw = env_snapshot["EMBEDDINGS_PROVIDER"]
        else:
            configured_raw = os.environ.get("EMBEDDINGS_PROVIDER", "auto")
    configured_raw = configured_raw.strip().lower()

    raw_chat = chat_provider_name
    if raw_chat is None and env_snapshot is not None and "LLM_PROVIDER" in env_snapshot:
        raw_chat = env_snapshot["LLM_PROVIDER"]
    chat_provider = (raw_chat or getattr(config, "LLM_PROVIDER", "vertex")).strip().lower()

    try:
        resolved = resolve_embeddings_provider(configured_raw, chat_provider)
    except EmbeddingsProviderSetupRequired:
        if chat_provider == "anthropic" and configured_raw == "auto":
            msg = (
                "Anthropic has no native embeddings. Semantic memory needs a separate "
                "embeddings provider (Vertex, Gemini API, OpenAI, or Local Multilingual E5)."
            )
        else:
            msg = f"Embeddings provider '{configured_raw}' requires configuration. Please configure API keys or credentials."
        return {
            "configured_provider": configured_raw,
            "resolved_provider": None,
            "backend_identity": None,
            "status": "setup_required",
            "status_message": msg,
            "available_choices": AVAILABLE_EMBEDDINGS_CHOICES,
        }
    except Exception:
        return {
            "configured_provider": configured_raw,
            "resolved_provider": None,
            "backend_identity": None,
            "status": "unavailable",
            "status_message": f"Embeddings provider '{configured_raw}' is currently unavailable.",
            "available_choices": AVAILABLE_EMBEDDINGS_CHOICES,
        }

    # If resolved to local, use cached readiness check with resolved model
    if resolved == "local":
        local_model = resolve_local_embedding_model(env_snapshot=env_snapshot)
        status, status_message = _check_local_e5_readiness(local_model)
        return {
            "configured_provider": configured_raw,
            "resolved_provider": "local",
            "backend_identity": f"local:{local_model}",
            "status": status,
            "status_message": status_message,
            "available_choices": AVAILABLE_EMBEDDINGS_CHOICES,
        }

    # Cloud provider embeddings (vertex, gemini, openai)
    configured_creds = is_chat_provider_configured(resolved, env_snapshot=env_snapshot)
    try:
        identity = get_embeddings_backend_identity(resolved, chat_provider)
    except Exception:
        identity = f"{resolved}:default"

    if configured_creds:
        return {
            "configured_provider": configured_raw,
            "resolved_provider": resolved,
            "backend_identity": identity,
            "status": "ready",
            "status_message": f"{resolved.capitalize()} embeddings ready ({identity}).",
            "available_choices": AVAILABLE_EMBEDDINGS_CHOICES,
        }
    else:
        return {
            "configured_provider": configured_raw,
            "resolved_provider": resolved,
            "backend_identity": identity,
            "status": "setup_required",
            "status_message": f"Embeddings provider '{resolved}' is missing required API key or credentials.",
            "available_choices": AVAILABLE_EMBEDDINGS_CHOICES,
        }


def inspect_semantic_memory_inventory(
    chroma_dir: str | None = None,
) -> dict[str, int] | None:
    """
    Safely inspects the local Chroma database collections and their vector counts in read-only mode.
    Returns a mapping of {collection_name: count}, or None if Chroma is not initialized / accessible.
    """
    db_dir = chroma_dir or getattr(config, "CHROMA_DB_DIR", None)
    if not db_dir or not os.path.exists(db_dir):
        return {}
    try:
        import chromadb
        client = chromadb.PersistentClient(path=db_dir)
        collections = client.list_collections()
        inventory: dict[str, int] = {}
        for c in collections:
            try:
                inventory[c.name] = c.count()
            except Exception:
                inventory[c.name] = 0
        return inventory
    except Exception:
        return None


def get_semantic_memory_diagnostics(
    embeddings_provider_name: str | None = None,
    chat_provider_name: str | None = None,
    env_snapshot: dict[str, str] | None = None,
    collection_inventory: dict[str, int] | None = None,
) -> dict[str, Any]:
    """Evaluates semantic memory collection status and reindex requirements based on actual collection inventory."""
    configured_raw = embeddings_provider_name
    if configured_raw is None:
        if env_snapshot is not None and "EMBEDDINGS_PROVIDER" in env_snapshot:
            configured_raw = env_snapshot["EMBEDDINGS_PROVIDER"]
        else:
            configured_raw = os.environ.get("EMBEDDINGS_PROVIDER", "auto")

    raw_chat = chat_provider_name
    if raw_chat is None and env_snapshot is not None and "LLM_PROVIDER" in env_snapshot:
        raw_chat = env_snapshot["LLM_PROVIDER"]
    chat_provider = (raw_chat or getattr(config, "LLM_PROVIDER", "vertex")).strip().lower()

    try:
        collection_name = get_embeddings_collection_name(configured_raw, chat_provider)
        emb_diag = get_embeddings_diagnostics(configured_raw, chat_provider, env_snapshot=env_snapshot)
    except EmbeddingsProviderSetupRequired:
        return {
            "collection_name": "astakos_vec_unconfigured",
            "status": "degraded",
            "reindex_needed": False,
            "status_message": (
                "Semantic memory is degraded because no embeddings provider is configured. "
                "Basic chat and tools remain fully operational."
            ),
        }

    if emb_diag["status"] != "ready":
        return {
            "collection_name": collection_name,
            "status": "degraded",
            "reindex_needed": False,
            "status_message": (
                "Semantic memory is degraded because the embeddings provider is not ready. "
                "Basic chat and tools remain operational."
            ),
        }

    # Inventory inspection
    inventory = collection_inventory if collection_inventory is not None else inspect_semantic_memory_inventory()

    if inventory is None:
        return {
            "collection_name": collection_name,
            "status": "ready",
            "reindex_needed": False,
            "status_message": f"Semantic memory collection is '{collection_name}'.",
        }

    target_count = inventory.get(collection_name, 0)
    other_populated = {k: v for k, v in inventory.items() if k != collection_name and v > 0}

    if other_populated and target_count == 0:
        other_desc = ", ".join(f"'{k}' ({v} memories)" for k, v in sorted(other_populated.items()))
        return {
            "collection_name": collection_name,
            "status": "reindex_needed",
            "reindex_needed": True,
            "status_message": (
                f"Historical memories exist in {other_desc}. A reindex is recommended "
                "to make past memories searchable with the current embeddings model."
            ),
        }

    if target_count > 0:
        return {
            "collection_name": collection_name,
            "status": "ready",
            "reindex_needed": False,
            "status_message": f"Semantic memory collection '{collection_name}' is active ({target_count} memories indexed).",
        }

    return {
        "collection_name": collection_name,
        "status": "ready",
        "reindex_needed": False,
        "status_message": f"Semantic memory collection '{collection_name}' is ready.",
    }


def get_workspace_diagnostics() -> dict[str, Any]:
    """Evaluates Google Workspace connection and per-service permissions non-sensitively."""
    token_path = get_token_path()
    client_secrets_path = get_oauth_client_secrets_path()

    has_client_secrets = bool(os.path.exists(client_secrets_path) and os.path.getsize(client_secrets_path) > 0)
    token_status, stored_scopes = inspect_workspace_token_metadata(token_path)

    if token_status == "missing":
        service_statuses = {svc: "missing_authorization" for svc in WORKSPACE_SERVICE_SCOPES}
        return {
            "connected": False,
            "status": "missing_authorization",
            "status_message": "Google Workspace is not connected (token.json not found).",
            "client_secrets_configured": has_client_secrets,
            "services": service_statuses,
        }

    if token_status == "malformed":
        service_statuses = {svc: "needs_reconnect" for svc in WORKSPACE_SERVICE_SCOPES}
        return {
            "connected": False,
            "status": "needs_reconnect",
            "status_message": "Google Workspace token is invalid or corrupted. Reconnect required.",
            "client_secrets_configured": has_client_secrets,
            "services": service_statuses,
        }

    service_statuses = {}
    missing_scope_services = []

    if token_status == "valid":
        for svc, required_scopes in WORKSPACE_SERVICE_SCOPES.items():
            missing = check_missing_scopes(required_scopes, stored_scopes)
            if missing:
                service_statuses[svc] = "missing_scope"
                missing_scope_services.append(svc)
            else:
                service_statuses[svc] = "connected"
    else:
        # Legacy token without stored scope metadata
        for svc in WORKSPACE_SERVICE_SCOPES:
            service_statuses[svc] = "connected"

    if missing_scope_services:
        overall_status = "missing_scope"
        missing_str = ", ".join(missing_scope_services)
        msg = f"Google Workspace is connected, but lacks permissions for: {missing_str}."
    else:
        overall_status = "connected"
        msg = "Google Workspace is connected with all required permissions."

    return {
        "connected": True,
        "status": overall_status,
        "status_message": msg,
        "client_secrets_configured": has_client_secrets,
        "services": service_statuses,
    }


def get_system_diagnostics_summary(
    chat_provider: str | None = None,
    embeddings_provider: str | None = None,
    env_snapshot: dict[str, str] | None = None,
    collection_inventory: dict[str, int] | None = None,
) -> dict[str, Any]:
    """Aggregates all subsystem diagnostics for setup wizard and runtime observability."""
    chat = get_chat_provider_diagnostics(chat_provider, env_snapshot=env_snapshot)
    embeddings = get_embeddings_diagnostics(embeddings_provider, chat["provider"], env_snapshot=env_snapshot)
    memory = get_semantic_memory_diagnostics(
        embeddings_provider,
        chat["provider"],
        env_snapshot=env_snapshot,
        collection_inventory=collection_inventory,
    )
    workspace = get_workspace_diagnostics()

    return {
        "chat_provider": chat,
        "embeddings_provider": embeddings,
        "semantic_memory": memory,
        "workspace": workspace,
    }


def format_boot_diagnostics_text(
    chat_provider: str | None = None,
    embeddings_provider: str | None = None,
) -> str:
    """Formats a clean, non-sensitive startup diagnostic block for console output."""
    summary = get_system_diagnostics_summary(chat_provider, embeddings_provider)
    chat = summary["chat_provider"]
    emb = summary["embeddings_provider"]
    mem = summary["semantic_memory"]
    ws = summary["workspace"]

    ws_services_ready = [k for k, v in ws["services"].items() if v == "connected"]
    if ws["connected"] and ws["status"] == "connected":
        ws_text = f"Connected ({len(ws_services_ready)}/{len(ws['services'])} services ready)"
    elif ws["connected"]:
        ws_text = f"Partial ({ws['status_message']})"
    else:
        ws_text = "Not connected"

    resolved_emb = str(emb.get("resolved_provider") or "unconfigured").capitalize()
    lines = [
        "🦞 Astakos Boot Diagnostics:",
        f"  • Chat Provider:       {chat['provider'].capitalize()} (fast: {chat['fast_model']}) [{chat['status'].upper()}]",
        f"  • Embeddings Provider: {resolved_emb} [{emb['status'].upper()}]",
        f"  • Semantic Memory:     {mem['collection_name']} [{mem['status'].upper()}]",
        f"  • Google Workspace:    {ws_text}",
    ]
    return "\n".join(lines)
