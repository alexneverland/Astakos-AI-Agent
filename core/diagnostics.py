# ================================================================
# Project: Astakos AI Agent 🦞
# Description: Modular LLM-agnostic multi-agent framework
# Module: Core System Diagnostics & Setup Observability
# Copyright (c) 2026 - All Rights Reserved
# ================================================================

from __future__ import annotations

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


def is_chat_provider_configured(provider_name: str) -> bool:
    """Checks if the required API keys or credentials for the chat provider are present."""
    p = (provider_name or "").strip().lower()
    if p == "openai":
        return bool(os.environ.get("OPENAI_API_KEY") or getattr(config, "OPENAI_API_KEY", ""))
    elif p == "anthropic":
        return bool(os.environ.get("ANTHROPIC_API_KEY") or getattr(config, "ANTHROPIC_API_KEY", ""))
    elif p == "gemini":
        return bool(
            os.environ.get("GEMINI_API_KEY")
            or getattr(config, "GEMINI_API_KEY", "")
            or os.environ.get("GOOGLE_API_KEY")
            or getattr(config, "GOOGLE_API_KEY", "")
        )
    elif p == "vertex":
        adc_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS") or getattr(config, "CREDENTIALS_PATH", "")
        root_cred = os.path.join(config.BASE_DIR, "credentials.json")
        nested_cred = os.path.join(config.BASE_DIR, "credentials", "credentials.json")
        return bool(
            (adc_path and os.path.exists(adc_path))
            or os.path.exists(root_cred)
            or os.path.exists(nested_cred)
            or os.environ.get("PROJECT_ID")
            or getattr(config, "PROJECT_ID", None)
        )
    return False


def get_chat_provider_diagnostics(chat_provider_name: str | None = None) -> dict[str, Any]:
    """Evaluates chat provider readiness without leaking keys or credentials."""
    provider = (chat_provider_name or getattr(config, "LLM_PROVIDER", "vertex")).strip().lower()
    fast_model, heavy_model = resolve_provider_models(provider)
    configured = is_chat_provider_configured(provider)

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
) -> dict[str, Any]:
    """Evaluates embeddings backend readiness independently from chat."""
    configured_raw = embeddings_provider_name
    if configured_raw is None:
        configured_raw = os.environ.get("EMBEDDINGS_PROVIDER", "auto")
    configured_raw = configured_raw.strip().lower()

    chat_provider = (chat_provider_name or getattr(config, "LLM_PROVIDER", "vertex")).strip().lower()

    try:
        resolved = resolve_embeddings_provider(configured_raw, chat_provider)
    except EmbeddingsProviderSetupRequired as exc:
        if chat_provider == "anthropic" and configured_raw == "auto":
            msg = (
                "Anthropic has no native embeddings. Semantic memory needs a separate "
                "embeddings provider (Vertex, Gemini API, OpenAI, or Local Multilingual E5)."
            )
        else:
            msg = str(exc)
        return {
            "configured_provider": configured_raw,
            "resolved_provider": None,
            "backend_identity": None,
            "status": "setup_required",
            "status_message": msg,
            "available_choices": AVAILABLE_EMBEDDINGS_CHOICES,
        }

    # If resolved to local, test local installation state without triggering background download
    if resolved == "local":
        try:
            import importlib.util
            st_spec = importlib.util.find_spec("sentence_transformers")
            if st_spec is None:
                return {
                    "configured_provider": configured_raw,
                    "resolved_provider": "local",
                    "backend_identity": f"local:{DEFAULT_LOCAL_EMBEDDING_MODEL}",
                    "status": "unavailable",
                    "status_message": (
                        "Local E5 embeddings are selected, but 'sentence-transformers' is not installed. "
                        "Please install sentence-transformers manually before selecting local embeddings."
                    ),
                    "available_choices": AVAILABLE_EMBEDDINGS_CHOICES,
                }
            from sentence_transformers import SentenceTransformer
            try:
                SentenceTransformer(DEFAULT_LOCAL_EMBEDDING_MODEL, local_files_only=True)
                return {
                    "configured_provider": configured_raw,
                    "resolved_provider": "local",
                    "backend_identity": f"local:{DEFAULT_LOCAL_EMBEDDING_MODEL}",
                    "status": "ready",
                    "status_message": f"Local multilingual E5 embeddings ({DEFAULT_LOCAL_EMBEDDING_MODEL}) ready.",
                    "available_choices": AVAILABLE_EMBEDDINGS_CHOICES,
                }
            except Exception:
                return {
                    "configured_provider": configured_raw,
                    "resolved_provider": "local",
                    "backend_identity": f"local:{DEFAULT_LOCAL_EMBEDDING_MODEL}",
                    "status": "unavailable",
                    "status_message": (
                        f"Local model '{DEFAULT_LOCAL_EMBEDDING_MODEL}' is not found locally. "
                        "Please download the model explicitly before selecting local embeddings."
                    ),
                    "available_choices": AVAILABLE_EMBEDDINGS_CHOICES,
                }
        except Exception as exc:
            return {
                "configured_provider": configured_raw,
                "resolved_provider": "local",
                "backend_identity": f"local:{DEFAULT_LOCAL_EMBEDDING_MODEL}",
                "status": "unavailable",
                "status_message": f"Local embeddings unavailable: {exc}",
                "available_choices": AVAILABLE_EMBEDDINGS_CHOICES,
            }

    # Cloud provider embeddings (vertex, gemini, openai)
    configured_creds = is_chat_provider_configured(resolved)
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


def get_semantic_memory_diagnostics(
    embeddings_provider_name: str | None = None,
    chat_provider_name: str | None = None,
) -> dict[str, Any]:
    """Evaluates semantic memory collection status and reindex requirements."""
    configured_raw = embeddings_provider_name
    if configured_raw is None:
        configured_raw = os.environ.get("EMBEDDINGS_PROVIDER", "auto")

    chat_provider = (chat_provider_name or getattr(config, "LLM_PROVIDER", "vertex")).strip().lower()

    try:
        collection_name = get_embeddings_collection_name(configured_raw, chat_provider)
        emb_diag = get_embeddings_diagnostics(configured_raw, chat_provider)
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
                f"Semantic memory is degraded ({emb_diag['status_message']}). "
                "Basic chat and tools remain operational."
            ),
        }

    is_legacy_vertex = (collection_name == "astakos_long_term")
    reindex_needed = not is_legacy_vertex

    if is_legacy_vertex:
        msg = "Semantic memory is connected to the primary Vertex collection."
        status = "ready"
    else:
        msg = (
            f"Semantic memory is using an isolated collection ('{collection_name}'). "
            "Historical memories from other providers are preserved and require an "
            "explicit user-triggered reindex to be searched with the new embeddings model."
        )
        status = "reindex_needed"

    return {
        "collection_name": collection_name,
        "status": status,
        "reindex_needed": reindex_needed,
        "status_message": msg,
    }


def get_workspace_diagnostics() -> dict[str, Any]:
    """Evaluates Google Workspace connection and per-service permissions non-sensitively."""
    token_path = get_token_path()
    client_secrets_path = get_oauth_client_secrets_path()

    has_client_secrets = bool(os.path.exists(client_secrets_path) and os.path.getsize(client_secrets_path) > 0)
    has_token = is_workspace_connected()

    if not has_token:
        service_statuses = {svc: "missing_authorization" for svc in WORKSPACE_SERVICE_SCOPES}
        return {
            "connected": False,
            "status": "missing_authorization",
            "status_message": "Google Workspace is not connected (token.json not found).",
            "client_secrets_configured": has_client_secrets,
            "services": service_statuses,
        }

    stored_scopes = read_stored_token_scopes(token_path)
    service_statuses = {}
    missing_scope_services = []

    for svc, required_scopes in WORKSPACE_SERVICE_SCOPES.items():
        if stored_scopes:
            missing = check_missing_scopes(required_scopes, stored_scopes)
            if missing:
                service_statuses[svc] = "missing_scope"
                missing_scope_services.append(svc)
            else:
                service_statuses[svc] = "connected"
        else:
            # Legacy token without stored scope metadata
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
) -> dict[str, Any]:
    """Aggregates all subsystem diagnostics for setup wizard and runtime observability."""
    chat = get_chat_provider_diagnostics(chat_provider)
    embeddings = get_embeddings_diagnostics(embeddings_provider, chat["provider"])
    memory = get_semantic_memory_diagnostics(embeddings_provider, chat["provider"])
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
