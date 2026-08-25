# ================================================================
# Project: Astakos AI Agent 🦞
# Description: Modular LLM-agnostic multi-agent framework
# Copyright (c) 2026 - All Rights Reserved
# ================================================================

import os
import json
import time
import socket
import struct
import base64
import hashlib
import hmac
import queue
import signal
import asyncio
import threading
import ipaddress
import html
from core.i18n import t
import sys
import re
import secrets
import logging
from collections.abc import Callable, Mapping
from urllib.parse import quote, unquote, urlencode
from api.path_security import resolve_allowed_file
from contextlib import asynccontextmanager
from datetime import datetime
from fastapi.staticfiles import StaticFiles
from starlette.datastructures import Headers, QueryParams
from starlette.responses import Response
from starlette.types import Scope
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect, File, UploadFile, HTTPException, Depends, Form, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
from rich.console import Console
from zoneinfo import ZoneInfo

from core.brain import llm, safe_llm_invoke
from core.graph import graph, AgentState
from core.agents import clean_message
from memory.working_memory import update_working_memory, update_capabilities_from_exchange
from services.context_extractor import extract_and_update_context_flags
from memory.pending_followups import (
    process_followup_exchange,
    find_pending_followups,
)
def _enqueue_followup_pipeline(user_text, ai_text, agent_name, channel):
    process_followup_exchange(
        user_text=user_text,
        ai_text=ai_text,
        agent_name=agent_name,
        channel=channel,
    )

from memory.session_memory import log_exchange, _run_session_summary
from tools.telegram import send_telegram_msg
import uuid
from PIL import Image
from google import genai
from fastapi.staticfiles import StaticFiles
from config import PHOTOS_DIR
from core.brain import vertex_client, FAST_MODEL, llm
from core.utils import detect_prompt_injection
console = Console()
from core.brain import FAST_MODEL
# ────────────────────────────────────────────────────────────────
# GLOBALS
# ────────────────────────────────────────────────────────────────
shutdown_event  = threading.Event()
fast_queue      = queue.Queue()
slow_queue      = queue.Queue()
memory_lock     = threading.Lock()
last_interaction_time = time.time()

# ── Local Bearer Token Auth ───────────────────────────────────
_TOKEN_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".astakos_token")

def _get_or_create_token() -> str:
    """Loads or generates a random local bearer token."""
    if os.path.exists(_TOKEN_FILE):
        with open(_TOKEN_FILE, "r") as f:
            t = f.read().strip()
            if t:
                return t
    t = secrets.token_hex(32)
    with open(_TOKEN_FILE, "w") as f:
        f.write(t)
    print(f"\033[93m[Security]: New local token created → {_TOKEN_FILE}\033[0m")
    return t

LOCAL_TOKEN = _get_or_create_token()
_bearer = HTTPBearer(auto_error=False)
ASSET_TOKEN_TTL_SECONDS = 300

def _is_container_environment() -> bool:
    """Returns True if the application is running inside a Docker or container runtime."""
    if os.getenv("ASTAKOS_CONTAINER") in ("1", "true", "True"):
        return True
    return os.path.exists("/.dockerenv") or os.path.exists("/run/.containerenv")


def _get_default_gateway_linux() -> str | None:
    """Reads default gateway IP from /proc/net/route in a Linux container."""
    try:
        if os.path.exists("/proc/net/route"):
            with open("/proc/net/route", "r") as f:
                for line in f:
                    fields = line.strip().split()
                    if len(fields) >= 3 and fields[1] == "00000000":
                        val = int(fields[2], 16)
                        return socket.inet_ntoa(struct.pack("<L", val))
    except (OSError, ValueError, struct.error):
        pass
    return None


def _is_docker_bridge_gateway(host: str) -> bool:
    """
    Checks if a client host IP exactly matches the container's verified default gateway
    when running inside a container environment. Fails closed if the gateway is indeterminate.
    """
    if not _is_container_environment() or not host:
        return False

    gw = _get_default_gateway_linux()
    if not gw:
        return False

    return host == gw


def _is_trusted_client_host(host: str) -> bool:
    """Checks whether the client host is trusted without a token (loopback or verified Docker bridge gateway)."""
    if host in ("127.0.0.1", "::1", "localhost"):
        return True
    return _is_docker_bridge_gateway(host)


def _validate_token_string(token: str | None) -> bool:
    """Safely validates a bearer/query token against LOCAL_TOKEN in constant time."""
    if not token or not LOCAL_TOKEN:
        return False
    return secrets.compare_digest(token, LOCAL_TOKEN)


def _extract_token_from_query_and_headers(
    query_params: Mapping[str, str],
    headers: Mapping[str, str],
) -> str | None:
    """Extract a query token first, otherwise a bearer token from headers."""
    token = query_params.get("token")
    if token:
        return token

    return _extract_bearer_token(headers)


def _extract_bearer_token(headers: Mapping[str, str]) -> str | None:
    """Extract a bearer token from headers without accepting URL credentials."""
    authorization = headers.get("authorization", "")
    if authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    return None


def _asset_request_path(mount_path: str, relative_path: str) -> str:
    """Return a normalized same-origin static path for a mounted asset."""
    return f"/{mount_path.strip('/')}/{quote(relative_path.lstrip('/'), safe='/')}"


def _create_asset_access_token(asset_path: str, *, now: int | None = None) -> str:
    """Create a short-lived token restricted to one static asset path."""
    issued_at = int(time.time()) if now is None else now
    expires_at = issued_at + ASSET_TOKEN_TTL_SECONDS
    payload = f"{expires_at}:{asset_path}".encode("utf-8")
    signature = hmac.new(LOCAL_TOKEN.encode("utf-8"), payload, hashlib.sha256).digest()
    encoded_signature = base64.urlsafe_b64encode(signature).decode("ascii").rstrip("=")
    return f"{expires_at}.{encoded_signature}"


def _validate_asset_access_token(
    token: str | None,
    asset_path: str,
    *,
    now: int | None = None,
) -> bool:
    """Validate a short-lived token for exactly one static asset path."""
    if not token or not LOCAL_TOKEN:
        return False
    try:
        expires_text, supplied_signature = token.split(".", 1)
        expires_at = int(expires_text)
    except (TypeError, ValueError):
        return False

    current_time = int(time.time()) if now is None else now
    if expires_at <= current_time:
        return False
    payload = f"{expires_at}:{asset_path}".encode("utf-8")
    expected_signature = base64.urlsafe_b64encode(
        hmac.new(LOCAL_TOKEN.encode("utf-8"), payload, hashlib.sha256).digest(),
    ).decode("ascii").rstrip("=")
    return hmac.compare_digest(supplied_signature, expected_signature)


def _private_asset_url_for_client_host(host: str, mount_path: str, filename: str) -> str:
    """Build a same-origin asset URL with a scoped token for one client host."""
    asset_url = _asset_request_path(mount_path, filename)
    if _is_trusted_client_host(host):
        return asset_url
    return f"{asset_url}?{urlencode({'asset_token': _create_asset_access_token(asset_url)})}"


def _private_asset_url(request: Request, mount_path: str, filename: str) -> str:
    """Build a same-origin asset URL with a scoped token for an HTTP client."""
    host = request.client.host if request.client else ""
    return _private_asset_url_for_client_host(host, mount_path, filename)


def _asset_history_marker(mount_path: str, filename: str) -> str:
    """Return the stable, token-free asset reference persisted in chat history."""
    return f"[ASTAKOS_ASSET:{_asset_request_path(mount_path, filename)}]"


def _replace_bracketed_markers(
    content: str,
    prefix: str,
    transform: Callable[[str], str | None],
) -> str:
    """Replace bounded ``[PREFIX:value]`` markers without regex backtracking."""
    cursor = 0
    parts: list[str] = []
    while True:
        marker_start = content.find(prefix, cursor)
        if marker_start < 0:
            parts.append(content[cursor:])
            return "".join(parts)
        value_start = marker_start + len(prefix)
        marker_end = content.find("]", value_start)
        if marker_end < 0:
            parts.append(content[cursor:])
            return "".join(parts)
        parts.append(content[cursor:marker_start])
        marker = content[marker_start:marker_end + 1]
        replacement = transform(content[value_start:marker_end])
        parts.append(marker if replacement is None else replacement)
        cursor = marker_end + 1


def _asset_url_from_history_marker(client_host: str, asset_path: str) -> str | None:
    """Mint a fresh URL only for a canonical, persisted private-asset reference."""
    for mount_path in ("photos", "outputs", "avatars"):
        prefix = f"/{mount_path}/"
        if not asset_path.startswith(prefix):
            continue
        filename = unquote(asset_path[len(prefix):])
        if not filename or filename != os.path.basename(filename):
            return None
        if _asset_request_path(mount_path, filename) != asset_path:
            return None
        return _private_asset_url_for_client_host(client_host, mount_path, filename)
    return None


def _asset_history_marker_from_legacy_photo_path(file_path: str) -> str:
    """Translate a legacy Telegram photo marker into a stable private-asset reference."""
    normalized_path = file_path.strip().replace("\\", "/")
    filename = normalized_path.rsplit("/", 1)[-1]
    mount_path = "outputs" if "outputs" in normalized_path.lower() else "photos"
    return _asset_history_marker(mount_path, filename)


def _render_persisted_asset_markers_for_client(
    content: str,
    client_host: str,
) -> str:
    """Mint per-client URLs from stable or legacy image references for the Web UI."""
    normalized_content = _replace_bracketed_markers(
        content,
        "[SEND_PHOTO:",
        lambda file_path: _asset_history_marker_from_legacy_photo_path(file_path),
    )

    def replace_marker(asset_path: str) -> str | None:
        image_url = _asset_url_from_history_marker(client_host, asset_path)
        if not image_url:
            return None
        return f"[ASTAKOS_ASSET_URL:{html.escape(image_url, quote=True)}]"

    return _replace_bracketed_markers(
        normalized_content,
        "[ASTAKOS_ASSET:",
        replace_marker,
    )


def _render_persisted_asset_markers(content: str, request: Request) -> str:
    """Mint fresh client-facing image URLs for an HTTP request."""
    host = request.client.host if request.client else ""
    return _render_persisted_asset_markers_for_client(content, host)


class AuthenticatedStaticFiles(StaticFiles):
    """Serve private assets only to trusted local clients or token holders."""

    def __init__(self, *, directory: str, mount_path: str) -> None:
        super().__init__(directory=directory)
        self._mount_path = mount_path.strip("/")

    async def get_response(self, path: str, scope: Scope) -> Response:
        client = scope.get("client")
        host = str(client[0]) if client else ""
        if _is_trusted_client_host(host):
            return await super().get_response(path, scope)

        query_string = scope.get("query_string", b"")
        query_text = (
            query_string.decode("latin-1")
            if isinstance(query_string, bytes)
            else str(query_string)
        )
        query_params = QueryParams(query_text)
        asset_token = query_params.get("asset_token")
        if asset_token and _validate_asset_access_token(
            asset_token,
            _asset_request_path(self._mount_path, path),
        ):
            return await super().get_response(path, scope)

        if asset_token or not _validate_token_string(_extract_bearer_token(Headers(scope=scope))):
            return JSONResponse(
                {"detail": "Unauthorized"},
                status_code=status.HTTP_401_UNAUTHORIZED,
            )
        return await super().get_response(path, scope)


async def require_token(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(_bearer),
) -> None:
    """Dependency: checks the bearer token. Allows trusted local loopback and Docker bridge gateway."""
    host = request.client.host if request.client else ""
    if _is_trusted_client_host(host):
        return  # loopback always allowed (Web UI on the same computer)

    token = credentials.credentials if credentials else None
    if not _validate_token_string(token):
        raise HTTPException(status_code=401, detail="Unauthorized")


async def require_ws_token(websocket: WebSocket) -> bool:
    """
    Validates WebSocket client against trusted origins or Bearer/Query token.
    Closes connection with WS_1008_POLICY_VIOLATION if unauthorized.
    """
    host = websocket.client.host if websocket.client else ""
    if _is_trusted_client_host(host):
        return True

    if _validate_token_string(
        _extract_token_from_query_and_headers(
            websocket.query_params,
            websocket.headers,
        ),
    ):
        return True

    # Unauthorized: terminate WebSocket connection with policy violation code (1008)
    await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Unauthorized")
    return False

# ── WebSocket log streaming ────────────────────────────────────
active_websockets: list = []
server_loop = None


def _broadcast_ws(payload: dict):
    """Sends a JSON event to all clients, minting asset URLs per recipient."""
    import json as _json
    if not server_loop or not active_websockets:
        return
    for ws in active_websockets:
        try:
            message_payload = payload.copy()
            content = message_payload.get("content")
            if isinstance(content, str):
                client = getattr(ws, "client", None)
                client_host = str(getattr(client, "host", ""))
                message_payload["content"] = _render_persisted_asset_markers_for_client(
                    content,
                    client_host,
                )
            message = _json.dumps(message_payload, ensure_ascii=False)
            asyncio.run_coroutine_threadsafe(ws.send_text(message), server_loop)
        except Exception:
            pass

class WsLogger:
    """Intercepts print() output and streams it live to Web UI via WebSocket."""
    def __init__(self, orig):
        self.orig = orig
    def write(self, msg):
        clean_msg = re.sub(r'\x1b\[[0-9;]*m', '', msg)
        output_msg = msg
        ws_msg = clean_msg

        # Keep terminal/websocket logs readable when a backend path emits an
        # unexpectedly huge single-line payload.
        if clean_msg.strip() and len(clean_msg) > 600:
            truncated = clean_msg[:600].rstrip()
            suffix = f" ... [truncated {len(clean_msg) - 600} chars]"
            output_msg = truncated + suffix + ("\n" if clean_msg.endswith("\n") else "")
            ws_msg = output_msg

        self.orig.write(output_msg)
        self.orig.flush()
        if clean_msg.strip() and server_loop and active_websockets:
            for ws in active_websockets:
                try:
                    asyncio.run_coroutine_threadsafe(ws.send_text(ws_msg), server_loop)
                except Exception:
                    pass
    def flush(self):
        self.orig.flush()

from core.graph import build_graph as _build_graph
app_graph = _build_graph()

def append_to_chat_history(
    role: str,
    content: str,
    agent: str | None = None,
    *,
    return_saved: bool = False,
    metadata: dict | None = None,
):
    """Add message to the shared SQLite conversation history (web channel) and websocket push."""
    now = datetime.now()
    shared_message_id = None
    shared_message_rowid = None
    try:
        from memory.conversation_history import append_message
        saved = append_message(
            role=role,
            content=content,
            channel="web",
            agent=agent,
            metadata=metadata,
            timestamp=now,
        )
        shared_message_id = saved.get("id")
        shared_message_rowid = saved.get("rowid")
        if role == "user":
            from services.behavioral_event_scheduler import schedule_persisted_user_intake

            schedule_persisted_user_intake(
                rowid=shared_message_rowid,
                metadata=metadata,
                enqueue_slow_task=enqueue_slow_task,
            )
        
        _broadcast_ws({
            "type": "new_message",
            "channel": "web",
            "id": shared_message_id,
            "rowid": shared_message_rowid,
            "role": role,
            "agent": agent,
            "time": now.strftime("%H:%M"),
            "content": content,
        })
    except Exception as e:
        print(f"[ConversationHistory/web]: Error shared write: {e}")
    if return_saved:
        return {"id": shared_message_id, "rowid": shared_message_rowid}
    return shared_message_id


def notify_telegram_message(
    role: str,
    content: str,
    agent: str | None = None,
    *,
    metadata: dict | None = None,
    return_saved: bool = False,
) -> int | dict[str, int | None] | None:
    """
    Called by the Telegram handler when a message arrives/is sent.
    Saves to the shared SQLite database and notifies the Web UI via WebSocket.
    Returns the display message id, or the persisted-row result when requested.
    """
    now = datetime.now()
    try:
        from memory.conversation_history import append_message
        from memory.conversation_history import get_max_rowid
        saved = append_message(
            role=role,
            content=content,
            channel="telegram",
            timestamp=now,
            agent=agent,
            metadata=metadata,
        )
        msg_id = saved.get("rowid") or get_max_rowid()
        _broadcast_ws({
            "type": "new_message",
            "channel": "telegram",
            "id": msg_id,
            "rowid": msg_id,
            "role": role,
            "agent": agent,
            "time": now.strftime("%H:%M"),
            "content": content,
        })
        if return_saved:
            return {"rowid": saved.get("rowid"), "message_id": msg_id}
        return msg_id
    except Exception as e:
        print(f"[ConversationHistory/telegram]: Error write: {e}")
        return None


def _load_shared_context_messages(channel: str, exclude_message_id: str | None = None) -> list:
    """Loads mixed shared context. If it fails, the caller falls back to legacy history."""
    try:
        from memory.conversation_history import load_recent_context
        entries = load_recent_context(channel=channel, global_limit=12, channel_limit=10, total_limit=20)
    except Exception as e:
        print(f"[ConversationHistory/{channel}]: Error shared read: {e}")
        return []

    context_msgs = []
    from core.untrusted_content import (
        format_untrusted_persisted_content,
        history_message_additional_kwargs,
    )
    for entry in entries:
        if exclude_message_id and entry.get("id") == exclude_message_id:
            continue
        content = entry.get("content", "")
        if not content:
            continue
        prefix = f"[{entry.get('date', '')} {entry.get('time', '')} / {entry.get('channel', '')}] "
        content = format_untrusted_persisted_content(
            f"{prefix}{content}",
            entry.get("metadata"),
        )
        if entry.get("role") in ("user", "human", "Human"):
            context_msgs.append(HumanMessage(
                content=content,
                additional_kwargs=history_message_additional_kwargs(entry.get("metadata")),
            ))
        else:
            context_msgs.append(AIMessage(
                content=content,
                additional_kwargs=history_message_additional_kwargs(entry.get("metadata")),
            ))
    return context_msgs


def _tool_results_fallback_response(user_text: str, tool_results: list[str]) -> str:
    """Synthesizes a final answer when the graph returned only tool results."""
    clean_results = [clean_message(r).strip() for r in tool_results if clean_message(r).strip()]
    if not clean_results:
        return ""

    joined_results = "\n\n---\n\n".join(clean_results[-5:])[:6000]
    from core.utils import load_agent_prompt
    base_prompt = load_agent_prompt("server_tool_fallback")
    prompt = base_prompt.format(user_text=user_text, joined_results=joined_results)
    try:
        response = safe_llm_invoke(llm, [HumanMessage(content=prompt)])
        content = clean_message(getattr(response, "content", "")).strip()
        if content and not content.startswith("[Tool Call:"):
            return content
    except Exception as e:
        print(f"\033[93m[Web ToolFallback]: synthesis failed — {e}\033[0m")

    return t("api.server.synthesis_failed") + joined_results[:1800]


def _load_shared_history_entries(
    channel: str | None = None,
    limit: int = 200,
    request: Request | None = None,
) -> list:
    try:
        from memory.conversation_history import load_messages
        entries = load_messages(channel=channel, limit=limit)
    except Exception as e:
        label = channel or "all"
        print(f"[ConversationHistory/{label}]: Error shared history read: {e}")
        return []

    history = []
    for entry in entries:
        content = entry.get("content", "")
        if not content:
            continue
        role = entry.get("role", "")
        if role in ("human", "Human"):
            role = "user"
        elif role in ("ai", "bot"):
            role = "assistant"
        if request is not None:
            content = _render_persisted_asset_markers(content, request)
        history.append({
            "role": role,
            "content": content,
            "time": entry.get("time", ""),
            "date": entry.get("date", ""),
            "channel": entry.get("channel", channel or ""),
            "id": entry.get("id", ""),
            "rowid": entry.get("rowid"),
            "agent": entry.get("agent") or "",
        })
    return history


def _run_web_graph_stream_sync(messages_for_graph: list, limit: int, trace):
    """
    Runs the synchronous LangGraph stream off the main event loop.
    Returns extracted response, handling agent, fallback tool outputs and elapsed ms.
    """
    from time import perf_counter

    final_ai_response = ""
    handling_agent = "Chat_Agent"
    tool_result_fallbacks: list[str] = []
    external_tool_names: set[str] = set()
    tool_args_by_id: dict[str, dict] = {}

    t_graph_0 = perf_counter()
    for event in graph.stream(
        {"messages": messages_for_graph, "channel": "web"},
        {"recursion_limit": limit},
    ):
        trace.process_event(event)
        for node, data in event.items():
            if data is None:
                continue
            for event_message in data.get("messages", []):
                for tool_call in getattr(event_message, "tool_calls", None) or []:
                    tool_call_id = str(tool_call.get("id", ""))
                    tool_args = tool_call.get("args", {})
                    if tool_call_id and isinstance(tool_args, dict):
                        tool_args_by_id[tool_call_id] = tool_args

            if node == "tools":
                t_tools_0 = perf_counter()
                for msg in data.get("messages", []):
                    if getattr(msg, "type", "") == "tool":
                        from core.untrusted_content import (
                            format_untrusted_tool_result,
                            is_untrusted_external_tool_call,
                        )
                        tool_name = str(getattr(msg, "name", ""))
                        tool_args = tool_args_by_id.get(str(getattr(msg, "tool_call_id", "")), {})
                        is_external = is_untrusted_external_tool_call(tool_name, tool_args)
                        if is_external:
                            external_tool_names.add(tool_name)
                        tool_content = clean_message(getattr(msg, "content", "")).strip()
                        if is_external:
                            tool_content = format_untrusted_tool_result(tool_name, tool_content)
                        if tool_content:
                            tool_result_fallbacks.append(tool_content)
                trace.mark_phase(
                    "tool_message_collect_ms",
                    trace.phase_timings.get("tool_message_collect_ms", 0)
                    + int((perf_counter() - t_tools_0) * 1000),
                )

            if node not in ["supervisor", "tools"]:
                t_extract_0 = perf_counter()

                handling_agent = node
                msgs = data.get("messages", [])
                if msgs and hasattr(msgs[-1], "content"):
                    last_msg = msgs[-1]
                    if getattr(last_msg, "tool_calls", None):
                        pass
                    else:
                        candidate = clean_message(msgs[-1].content).strip()
                        if candidate and not candidate.startswith("[Tool Call:"):
                            final_ai_response = candidate
                            print(f"\033[90m[Web->Graph]: Agent '{handling_agent}' responded ({len(candidate)} chars)\033[0m")

                trace.mark_phase(
                    "graph_result_extract_ms",
                    trace.phase_timings.get("graph_result_extract_ms", 0)
                    + int((perf_counter() - t_extract_0) * 1000),
                )

    graph_elapsed_ms = int((perf_counter() - t_graph_0) * 1000)
    return {
        "final_ai_response": final_ai_response,
        "handling_agent": handling_agent,
        "tool_result_fallbacks": tool_result_fallbacks,
        "external_tool_names": sorted(external_tool_names),
        "graph_elapsed_ms": graph_elapsed_ms,
    }

# ────────────────────────────────────────────────────────────────
# QUEUE SYSTEM
# ────────────────────────────────────────────────────────────────

def fast_queue_worker():
    """Executes fast background tasks (e.g., UI updates, deterministic memory)."""
    print("\033[90m[System]: Fast Queue Worker Started!\033[0m")
    while not shutdown_event.is_set():
        try:
            task_func, args = fast_queue.get(timeout=2)
            try:
                print(f"\033[90m[FastQueue]: {task_func.__name__}\033[0m")
                task_func(*args)
            except Exception as e:
                print(f"\033[91m[Fast Queue Error in {task_func.__name__}]: {e}\033[0m")
            finally:
                fast_queue.task_done()
        except queue.Empty:
            continue

def slow_queue_worker():
    """Performs slow background tasks (e.g., LLM memory sifting)."""
    print("\033[90m[System]: Slow Queue Worker Started!\033[0m")
    while not shutdown_event.is_set():
        try:
            task_func, args = slow_queue.get(timeout=2)
            try:
                print(f"\033[90m[SlowQueue]: {task_func.__name__}\033[0m")
                task_func(*args)
            except Exception as e:
                print(f"\033[91m[Slow Queue Error in {task_func.__name__}]: {e}\033[0m")
            finally:
                slow_queue.task_done()
        except queue.Empty:
            continue

def enqueue_fast_task(func, *args):
    fast_queue.put((func, args))

def enqueue_slow_task(func, *args):
    slow_queue.put((func, args))

def _enqueue_slow_memory_sifter(
    user_text: str,
    ai_text: str,
    handling_agent: str,
    channel: str,
    external_content_sources: set[str] | None = None,
    trusted_user_only: bool = False,
) -> None:
    """Queue memory sifting, optionally using only trusted user-originated text."""
    if external_content_sources:
        print("[MemorySifterSlow]: external-derived exchange - skip automatic memory write")
        return
    from memory.session_memory import run_memory_sifter_fast, run_memory_sifter_slow
    safe_ai_text = "" if trusted_user_only else ai_text
    seed_facts = run_memory_sifter_fast(user_text, safe_ai_text, handling_agent, channel)
    enqueue_slow_task(
        run_memory_sifter_slow,
        user_text,
        safe_ai_text,
        handling_agent,
        channel,
        seed_facts,
        not trusted_user_only,
    )

# ────────────────────────────────────────────────────────────────
# PROACTIVE WORKER
# ────────────────────────────────────────────────────────────────

# ────────────────────────────────────────────────────────────────
# FASTAPI LIFESPAN
# ────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Starts workers, waits, terminates cleanly."""
    global server_loop
    server_loop = asyncio.get_running_loop()
    sys.stdout = WsLogger(sys.stdout)
    threads = [
        # reminder_worker and proactive_worker run ONLY in telegram_bot.py
        # Here we only keep the fast/slow workers for the background memory tasks
        threading.Thread(target=fast_queue_worker, daemon=True),
        threading.Thread(target=slow_queue_worker, daemon=True),
    ]
    for t in threads:
        t.start()

    print("\n--- Astakos API Server: Started ---")
    try:
        from memory.pending_assets import init_pending_assets_table
        from memory.list_store import init_list_store
        from memory.reminder_store import init_reminder_store
        init_pending_assets_table()
        init_list_store()
        init_reminder_store()
    except Exception as e:
        print(f"[PendingAssets]: Init failed: {e}")
        
    yield  # Server runs here

    print("\n[Server]: Terminating...")

    # Drain queue first (max 5s)
    try:
        import threading as _th
        _done = _th.Event()
        def _drain(): 
            fast_queue.join()
            slow_queue.join()
            _done.set()
        _th.Thread(target=_drain, daemon=True).start()
        _done.wait(timeout=5)
    except Exception:
        pass

    shutdown_event.set()

    loop = asyncio.get_event_loop()
    summary_future = loop.run_in_executor(None, lambda: _run_session_summary("web"))
    try:
        await asyncio.wait_for(asyncio.shield(summary_future), timeout=10.0)
    except asyncio.TimeoutError:
        print("\033[93m[System]: Summary timeout — skipping.\033[0m")
        try:
            await summary_future
        except Exception:
            pass
    except Exception:
        print("\033[93m[System]: Summary timeout — skipping.\033[0m")

    # Graceful ChromaDB shutdown
    try:
        from memory.vector_store import close_vector_store
        close_vector_store()
    except Exception:
        pass
# ────────────────────────────────────────────────────────────────
# FASTAPI APP & MIDDLEWARE
# ────────────────────────────────────────────────────────────────

server = FastAPI(lifespan=lifespan)

def _api_internal_error(operation: str) -> str:
    logging.exception("API %s failed", operation)
    return t("api.server.internal_error")

# Keep terminal output useful: app debug prints stay visible, noisy polling access logs do not.
logging.getLogger("uvicorn.access").disabled = True
server.mount("/photos", AuthenticatedStaticFiles(directory=PHOTOS_DIR, mount_path="photos"), name="photos")

# --- [MASTRO-ROUTE]: Allow downloading from the outputs folder ---
from config import BASE_DIR
outputs_dir = os.path.join(BASE_DIR, "outputs")
os.makedirs(outputs_dir, exist_ok=True)
server.mount("/outputs", AuthenticatedStaticFiles(directory=outputs_dir, mount_path="outputs"), name="outputs")

# --- [MASTRO-FIX]: Separate folder for the UI faces ---
avatars_dir = os.path.join(BASE_DIR, "avatars")
os.makedirs(avatars_dir, exist_ok=True)
server.mount("/avatars", AuthenticatedStaticFiles(directory=avatars_dir, mount_path="avatars"), name="avatars")

# CORS — localhost only (no external source can call the server)
server.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:8000", "http://127.0.0.1:8000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)



# ────────────────────────────────────────────────────────────────
# ENDPOINTS
# ────────────────────────────────────────────────────────────────
# [MASTRO-FIX]: Add the endpoint for the Web UI button
@server.post("/end_session")
async def manual_session_save(_=Depends(require_token)):
    """Allows the Web UI to request manual archiving (Button)"""
    from memory.session_memory import _run_session_summary
    import threading
    
    # Execution in a separate thread to prevent the API from freezing
    threading.Thread(target=_run_session_summary, args=("web",), daemon=True).start()
    return JSONResponse({"status": "Archiving started!"})

def _enqueue_capability_gap_web(user_text: str, ai_text: str, agent: str, channel: str, correlation_rowid: int):
    from memory.working_memory import update_capabilities_from_exchange
    description = update_capabilities_from_exchange(user_text, ai_text, agent)
    if not description:
        return

    from memory.conversation_history import load_messages_after_rowid
    newer = load_messages_after_rowid(after_rowid=correlation_rowid, channel=channel)
    if any(m.get("role") == "user" for m in newer):
        return

    from core.i18n import t
    prefix = t("core.approval.capability_proposal_prefix")
    marker = t("core.approval.draft_markers")[0]
    proposal = f"{prefix} {description} {marker}"

    append_to_chat_history("assistant", proposal, agent="Dev_Agent")


@server.post("/chat")
async def chat_endpoint(request: Request, _=Depends(require_token)):
    global last_interaction_time

    body       = await request.json()
    user_input = body.get("message", "").strip()
    routine_completion_context: SystemMessage | None = None
    routine_draft_offer_context: SystemMessage | None = None
    routine_action_consumed = False

    # (Mastro-Shield): Avoid null or strange paths
    photo_path = resolve_allowed_file(
        body.get("photo_path"),
        (PHOTOS_DIR,),
    ) or ""

    if not user_input:
        return JSONResponse({"error": t("api.server.empty_message")}, status_code=400)

    # 1. --- PROMPT INJECTION FIREWALL ---
    # We catch malicious intents before they ever touch the LLM or cost API tokens.
    if detect_prompt_injection(user_input):
        print(f"\033[91m🛡️ [SECURITY INTERCEPT]: Blocked malicious input -> {user_input}\033[0m")
        return JSONResponse({
            "agent": "Security_Firewall",
            "response": "🛡️ [SECURITY OVERRIDE]: Prohibited command detected."
        })

    # 2. --- XML CONTEXT ISOLATION ---
    # Web/Telegram are trusted local user channels.
    # We do NOT wrap in isolated_data — otherwise the user's commands
    # are blocked by the security prompt itself.
    isolated_user_input = user_input

    recent_asset = None
    recent_asset_doc_text = ""
    try:
        from memory.pending_assets import get_latest_recent_asset
        recent_asset = get_latest_recent_asset("web", max_age_minutes=20)
    
        if recent_asset and _looks_like_recent_asset_followup(user_input):
            recent_path = str(recent_asset.get("file_path") or "").strip()
            recent_name = str(recent_asset.get("filename") or "").strip()
            recent_ext = os.path.splitext(recent_name)[1].lower()
    
            if recent_path and os.path.exists(recent_path):
                recent_asset_doc_text = _read_document_text_for_analysis(recent_path, recent_ext)
                isolated_user_input = (
                    f"[USER_REFERENCING_RECENT_FILE]: {recent_name}\n"
                    f"[USER_REQUEST]: {user_input}\n"
                    f"[ORIGINAL_CAPTION]: {recent_asset.get('caption', '')}\n\n"
                    f"<untrusted_document filename=\"{recent_name}\">\n"
                    f"{recent_asset_doc_text}\n"
                    f"</untrusted_document>"
                )
                print(f"[RecentAssetFollowup]: attached recent file context -> {recent_name}")
    except Exception as e:
        print(f"[RecentAssetFollowup]: {e}")

    # ── Routine Completion Decision from Web UI ─────────────────────
    try:
        from core.messenger_draft import active_draft_status
        from memory.routine_db import (
            acknowledge_pending_draft_offer,
            load_pending_confirmations,
        )
        from services.routine_completion_helper import decide_completion
        from services.routine_completion_selector import select_routine as _completion_selector
        from services.routine_completion_context import accept_pending_messenger_draft_offer

        # Web and Telegram run in separate processes. The database is the shared
        # pending-confirmation source of truth; importing the bot's RAM mapping
        # here would always miss offers created by the Telegram scheduler.
        pending_routine_confirmations = load_pending_confirmations()
        if pending_routine_confirmations:
            pending_candidates = {
                rid: (pdata.get("event", "") if isinstance(pdata, dict) else str(pdata))
                for rid, pdata in pending_routine_confirmations.items()
            }
            active_draft, _, _ = active_draft_status()
            accepted_draft_offer = None
            draft_offer_consumed = False
            if not active_draft:
                accepted_draft_offer = accept_pending_messenger_draft_offer(
                    pending_routine_confirmations,
                    user_input,
                )
                if accepted_draft_offer is not None:
                    pending_data = pending_routine_confirmations.get(
                        accepted_draft_offer.routine_id,
                        {},
                    )
                    draft_offer_consumed = acknowledge_pending_draft_offer(
                        accepted_draft_offer.routine_id,
                        pending_data.get("sent_at"),
                    )
                    if not draft_offer_consumed:
                        accepted_draft_offer = None
            if accepted_draft_offer is not None:
                from services.routine_completion_helper import RoutineSelection

                decision = RoutineSelection(
                    action="acknowledge",
                    routine_id=accepted_draft_offer.routine_id,
                )
            else:
                decision = decide_completion(
                    user_text=user_input,
                    candidates=pending_candidates,
                    pool="pending",
                    semantic_selector=_completion_selector,
                )

            if decision.action == "complete" and decision.routine_id is not None:
                from memory.routine_db import (
                    confirm_routine,
                    mark_routine_responded,
                    mark_routine_triggered_today,
                    remove_pending_confirmation,
                )
                from memory.event_log import log_event

                rid = decision.routine_id
                pdata = pending_routine_confirmations.get(rid, {})
                ev = pdata.get("event", "?") if isinstance(pdata, dict) else str(pdata)

                confirm_routine(rid)
                mark_routine_responded(rid)
                mark_routine_triggered_today(rid)
                remove_pending_confirmation(rid)
                log_event(
                    "routines", "confirmed",
                    routine_id=rid, event=ev,
                )
                print(f"✅ [Web Routine Confirmed]: {pdata}")
                pending_routine_confirmations.pop(rid, None)

                from services.routine_completion_context import build_routine_completion_context
                routine_completion_context = build_routine_completion_context()
                routine_action_consumed = True

            elif decision.action == "acknowledge" and decision.routine_id is not None:
                from memory.routine_db import mark_routine_acknowledged, remove_pending_confirmation
                from memory.event_log import log_event

                rid = decision.routine_id
                pdata = pending_routine_confirmations.get(rid, {})
                ev = pdata.get("event", "?") if isinstance(pdata, dict) else str(pdata)

                if not draft_offer_consumed:
                    mark_routine_acknowledged(rid)
                    remove_pending_confirmation(rid)
                log_event("routines", "routine_acknowledged", routine_id=rid, event=ev)
                print(f"[Web Routine Acknowledged]: {pdata}")
                pending_routine_confirmations.pop(rid, None)
                from services.routine_completion_context import build_routine_completion_context
                routine_completion_context = build_routine_completion_context()
                if accepted_draft_offer is not None and accepted_draft_offer.routine_id == rid:
                    routine_draft_offer_context = accepted_draft_offer.context
                routine_action_consumed = True

            elif decision.action == "skip_today" and decision.routine_id is not None:
                from memory.routine_db import record_routine_skip_today, remove_pending_confirmation
                from memory.event_log import log_event

                rid = decision.routine_id
                pdata = pending_routine_confirmations.get(rid, {})
                ev = pdata.get("event", "?") if isinstance(pdata, dict) else str(pdata)
                skip_result = record_routine_skip_today(rid)
                remove_pending_confirmation(rid)
                log_event(
                    "routines", "routine_skipped_today", routine_id=rid, event=ev,
                    skip_streak=skip_result["skip_streak"],
                    cooldown_applied=skip_result["cooldown_applied"],
                )
                print(f"[Web Routine Skipped Today]: {pdata}")
                pending_routine_confirmations.pop(rid, None)
                from services.routine_completion_context import build_routine_completion_context
                routine_completion_context = build_routine_completion_context()
                routine_action_consumed = True

            elif decision.action == "pause" and decision.routine_id is not None:
                from memory.routine_db import pause_routine_indefinitely, remove_pending_confirmation
                from memory.event_log import log_event

                rid = decision.routine_id
                pdata = pending_routine_confirmations.get(rid, {})
                ev = pdata.get("event", "?") if isinstance(pdata, dict) else str(pdata)
                pause_routine_indefinitely(rid)
                remove_pending_confirmation(rid)
                log_event("routines", "routine_paused", routine_id=rid, event=ev)
                print(f"[Web Routine Paused]: {pdata}")
                pending_routine_confirmations.pop(rid, None)
                from services.routine_completion_context import build_routine_completion_context
                routine_completion_context = build_routine_completion_context()
                routine_action_consumed = True

            # pass_through → continue to normal processing.
        if not routine_action_consumed:
            # ── Pre-emptive today-pool completion (no consumed pending action) ──
            from datetime import datetime as _dt_now
            from memory.routine_db import get_eligible_preemptive_routines_for_day, mark_routine_triggered_today

            day_name = _dt_now.now().strftime("%A")
            today_routines = get_eligible_preemptive_routines_for_day(day_name)
            if today_routines:
                today_candidates = {r["id"]: r["event"] for r in today_routines}
                decision = decide_completion(
                    user_text=user_input,
                    candidates=today_candidates,
                    pool="today",
                    semantic_selector=_completion_selector,
                )

                if decision.action == "complete" and decision.routine_id is not None:
                    from memory.event_log import log_event

                    rid = decision.routine_id
                    ev = today_candidates.get(rid, "?")
                    mark_routine_triggered_today(rid)
                    log_event(
                        "routines", "preemptive_completed",
                        routine_id=rid, event=ev,
                    )
                    print(f"✅ [Web Routine Pre-emptive Completed]: #{rid} {ev}")
                    from services.routine_completion_context import build_routine_completion_context
                    routine_completion_context = build_routine_completion_context()
                    routine_action_consumed = True
                elif decision.action == "acknowledge" and decision.routine_id is not None:
                    from memory.event_log import log_event
                    from memory.routine_db import mark_routine_acknowledged

                    rid = decision.routine_id
                    ev = today_candidates.get(rid, "?")
                    mark_routine_acknowledged(rid)
                    log_event("routines", "routine_acknowledged", routine_id=rid, event=ev)
                    print(f"[Web Routine Acknowledged]: #{rid} {ev}")
                    from services.routine_completion_context import build_routine_completion_context
                    routine_completion_context = build_routine_completion_context()
                    routine_action_consumed = True
                elif decision.action == "skip_today" and decision.routine_id is not None:
                    from memory.event_log import log_event
                    from memory.routine_db import record_routine_skip_today

                    rid = decision.routine_id
                    ev = today_candidates.get(rid, "?")
                    skip_result = record_routine_skip_today(rid)
                    log_event(
                        "routines", "routine_skipped_today", routine_id=rid, event=ev,
                        skip_streak=skip_result["skip_streak"],
                        cooldown_applied=skip_result["cooldown_applied"],
                    )
                    print(f"[Web Routine Skipped Today]: #{rid} {ev}")
                    from services.routine_completion_context import build_routine_completion_context
                    routine_completion_context = build_routine_completion_context()
                    routine_action_consumed = True
                elif decision.action == "pause" and decision.routine_id is not None:
                    from memory.event_log import log_event
                    from memory.routine_db import pause_routine_indefinitely

                    rid = decision.routine_id
                    ev = today_candidates.get(rid, "?")
                    pause_routine_indefinitely(rid)
                    log_event("routines", "routine_paused", routine_id=rid, event=ev)
                    print(f"[Web Routine Paused]: #{rid} {ev}")
                    from services.routine_completion_context import build_routine_completion_context
                    routine_completion_context = build_routine_completion_context()
                    routine_action_consumed = True
                # pass_through → continue to normal processing.
            if not routine_action_consumed:
                from memory.routine_db import get_active_routine_catalog, pause_routine_indefinitely
                from services.routine_completion_helper import relevant_catalog_candidates

                catalog = {
                    routine["id"]: routine["event"]
                    for routine in get_active_routine_catalog()
                }
                pause_candidates = relevant_catalog_candidates(user_input, catalog)
                decision = decide_completion(
                    user_text=user_input,
                    candidates=pause_candidates,
                    pool="catalog",
                    semantic_selector=_completion_selector,
                )
                if decision.action == "pause" and decision.routine_id is not None:
                    from memory.event_log import log_event

                    rid = decision.routine_id
                    ev = pause_candidates[rid]
                    pause_routine_indefinitely(rid)
                    log_event("routines", "routine_paused", routine_id=rid, event=ev)
                    print(f"[Web Routine Paused]: #{rid} {ev}")
                    from services.routine_completion_context import build_routine_completion_context
                    routine_completion_context = build_routine_completion_context()
                    routine_action_consumed = True
    except Exception as _rce:
        print(f"[Web Routine Completion]: {_rce}")


    # ── Pending Asset Confirmation from Web UI ───────────────────
    try:
        from memory.pending_assets import (
            clear_expired_pending_assets,
            get_latest_pending_asset,
            mark_pending_asset_confirmed,
            mark_pending_asset_cancelled,
            classify_pending_asset_reply,
            looks_like_asset_confirmation_prompt,
        )
        clear_expired_pending_assets()
        from memory.pending_assets import is_reply_to_recent_asset_prompt
        pending_photo_asset = get_latest_pending_asset("web", "photo")
        pending_doc_asset = get_latest_pending_asset("web", "document")
        pending_asset = None if routine_action_consumed else (pending_photo_asset or pending_doc_asset)
        reply_kind = classify_pending_asset_reply(user_input) if pending_asset else None
        asset_prompt_active = is_reply_to_recent_asset_prompt("web") if pending_asset else False

        if pending_asset and reply_kind in {"yes", "no"} and not asset_prompt_active:
            print("[PendingAssetGuard]: ignored generic yes/no because no recent archive prompt was active")

        if pending_asset and reply_kind == "yes" and asset_prompt_active:
            from memory.vector_store import memory
            if pending_asset["asset_type"] == "photo":
                memory.save(
                    memory_type="photo",
                    file_path=pending_asset["file_path"],
                    analysis=pending_asset.get("analysis", ""),
                    caption=pending_asset.get("caption", "") or pending_asset["filename"],
                    external_content_sources=pending_asset.get("external_content_sources", []),
                )
            else:
                memory.save(
                    memory_type="document",
                    file_path=pending_asset["file_path"],
                    analysis=pending_asset.get("analysis", ""),
                    caption=pending_asset.get("caption", "") or pending_asset["filename"],
                    external_content_sources=pending_asset.get("external_content_sources", []),
                )
                
            mark_pending_asset_confirmed(pending_asset["id"])

            reply = t("api.server.saved_to_memory")
            from core.utils import sanitize_messenger_draft_claims, strip_operational_assistant_paragraphs
            reply = sanitize_messenger_draft_claims(reply)
            reply = strip_operational_assistant_paragraphs(reply).strip() or reply
            append_to_chat_history("user", user_input)
            append_to_chat_history("assistant", reply, agent="Chat_Agent")
            enqueue_fast_task(log_exchange, user_input, reply, "Chat_Agent", "web")
            enqueue_fast_task(update_working_memory, user_input, reply)
            enqueue_fast_task(_enqueue_slow_memory_sifter, user_input, reply, "Chat_Agent", "web")
            enqueue_slow_task(update_capabilities_from_exchange, user_input, reply, "Chat_Agent")
            enqueue_slow_task(_enqueue_followup_pipeline, user_input, reply, "Chat_Agent", "web")
            enqueue_slow_task(extract_and_update_context_flags, user_input, reply, "web")
            return JSONResponse({"agent": "Chat_Agent", "response": reply})

        if pending_asset and reply_kind == "no" and asset_prompt_active:
            mark_pending_asset_cancelled(pending_asset["id"])

            reply = t("api.server.not_saved_permanently")
            from core.utils import sanitize_messenger_draft_claims, strip_operational_assistant_paragraphs
            reply = sanitize_messenger_draft_claims(reply)
            reply = strip_operational_assistant_paragraphs(reply).strip() or reply
            append_to_chat_history("user", user_input)
            append_to_chat_history("assistant", reply, agent="Chat_Agent")
            enqueue_fast_task(log_exchange, user_input, reply, "Chat_Agent", "web")
            enqueue_fast_task(update_working_memory, user_input, reply)
            enqueue_fast_task(_enqueue_slow_memory_sifter, user_input, reply, "Chat_Agent", "web")
            enqueue_slow_task(update_capabilities_from_exchange, user_input, reply, "Chat_Agent")
            enqueue_slow_task(_enqueue_followup_pipeline, user_input, reply, "Chat_Agent", "web")
            enqueue_slow_task(extract_and_update_context_flags, user_input, reply, "web")
            return JSONResponse({"agent": "Chat_Agent", "response": reply})
    except Exception as e:
        print(f"[PendingAssets]: Web text handler error: {e}")

    # ── Messenger Draft Intent Guard (Web UI parity with Telegram) ─────────────
    try:
        from core.messenger_draft import active_draft_status, clear_draft
        from services.messenger_intent import classify_messenger_intent
        from memory.execution_trace import ExecutionTrace

        draft_active, _, draft_data = active_draft_status()
        draft_intent = (
            classify_messenger_intent(user_input, has_active_draft=draft_active)
            if not routine_action_consumed
            else None
        )

        if draft_intent and draft_intent.intent == "clear_draft":
            cleared = bool(clear_draft())
            reply = (
                t("server.draft_cleared")
                if cleared
                else t("api.server.no_active_draft_to_clear")
            )
            from core.utils import sanitize_messenger_draft_claims, strip_operational_assistant_paragraphs
            reply = sanitize_messenger_draft_claims(reply)
            reply = strip_operational_assistant_paragraphs(reply).strip() or reply

            append_to_chat_history("user", user_input)
            append_to_chat_history("assistant", reply, agent="Chat_Agent")
            enqueue_fast_task(log_exchange, user_input, reply, "Chat_Agent", "web")
            enqueue_fast_task(update_working_memory, user_input, reply)
            enqueue_fast_task(_enqueue_slow_memory_sifter, user_input, reply, "Chat_Agent", "web")
            enqueue_slow_task(update_capabilities_from_exchange, user_input, reply, "Chat_Agent")
            enqueue_slow_task(_enqueue_followup_pipeline, user_input, reply, "Chat_Agent", "web")
            enqueue_slow_task(extract_and_update_context_flags, user_input, reply, "web")

            _trace = ExecutionTrace(channel="web", user_message=user_input)
            _trace.mark_phase("messenger_intent_clear_intercept", 1)
            _trace.finalize(response=reply)
            _trace.save()
            return JSONResponse({"agent": "Chat_Agent", "response": reply})

        if draft_intent and draft_intent.intent == "clarify_draft":
            if draft_active and draft_data and draft_data.get("message"):
                draft_message = str(draft_data.get("message") or "").strip()
                reply = (
                    t("api.server.draft_preview") +
                    f"{draft_message}\n\n" +
                    t("api.server.draft_action_prompt")
                )
            else:
                reply = (
                    t("api.server.no_active_draft") +
                    t("server.draft_clarification")
                )

            from core.utils import sanitize_messenger_draft_claims, strip_operational_assistant_paragraphs
            reply = sanitize_messenger_draft_claims(reply)
            reply = strip_operational_assistant_paragraphs(reply).strip() or reply

            append_to_chat_history("user", user_input)
            append_to_chat_history("assistant", reply, agent="Chat_Agent")
            enqueue_fast_task(log_exchange, user_input, reply, "Chat_Agent", "web")
            enqueue_fast_task(update_working_memory, user_input, reply)
            enqueue_fast_task(_enqueue_slow_memory_sifter, user_input, reply, "Chat_Agent", "web")
            enqueue_slow_task(update_capabilities_from_exchange, user_input, reply, "Chat_Agent")
            enqueue_slow_task(_enqueue_followup_pipeline, user_input, reply, "Chat_Agent", "web")
            enqueue_slow_task(extract_and_update_context_flags, user_input, reply, "web")

            _trace = ExecutionTrace(channel="web", user_message=user_input)
            _trace.mark_phase("messenger_intent_clarify_intercept", 1)
            _trace.finalize(response=reply)
            _trace.save()
            return JSONResponse({"agent": "Chat_Agent", "response": reply})
    except Exception as e:
        print(f"[MessengerIntent Web]: {e}")

    with memory_lock:
        last_interaction_time = time.time()

    # ── Save user message to history ────────────────────
    # Note: We save the original `user_input` to the UI chat history, 
    # not the XML-wrapped version, to keep the frontend looking clean.
    current_history_saved = append_to_chat_history("user", user_input, return_saved=True)
    current_history_id = current_history_saved.get("id")
    current_history_rowid = current_history_saved.get("rowid")

    final_ai_response = ""
    handling_agent    = "Chat_Agent"

    try:
        # ── Multimodal message if a file exists ───────────
        if photo_path and os.path.exists(photo_path):
            import base64
            filename = os.path.basename(photo_path)
            ext = os.path.splitext(filename)[1].lower()
            image_exts = [".jpg", ".jpeg", ".png", ".webp", ".gif"]
            file_size = os.path.getsize(photo_path)
            print(f"\033[92m[Upload]: Received file for analysis: {filename} ({file_size} bytes)\033[0m")

            # We inject the isolated input into the enhanced string
            enhanced_user_input = f"[USER_UPLOADED_FILE]: {filename}\n{isolated_user_input}"

            # If it is an IMAGE, we convert it to Base64 and send it as image_url
            if ext in image_exts:
                print(f"\033[94m[Vision]: Encoding image to base64 ({ext})...\033[0m")
                with open(photo_path, "rb") as f:
                    img_b64 = base64.b64encode(f.read()).decode("utf-8")

                mime = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                        ".gif": "image/gif", ".webp": "image/webp"}.get(ext, "image/jpeg")

                from core.untrusted_content import (
                    USER_PROVIDED_ASSET_SOURCE,
                    external_content_history_metadata,
                    format_untrusted_asset_vision_prompt,
                )
                human_msg = HumanMessage(content=[
                    {
                        "type": "text",
                        "text": format_untrusted_asset_vision_prompt(enhanced_user_input),
                    },
                    {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{img_b64}"}}
                ], additional_kwargs=external_content_history_metadata([
                    USER_PROVIDED_ASSET_SOURCE,
                ]))
                print(f"\033[92m[Chat]: Multimodal message (Image): {filename}\033[0m")
                print(f"\033[94m[Vision]: Ready for analysis by LLM — message: '{isolated_user_input[:120]}'\033[0m")

            # If it is a DOCUMENT (PDF, Word, Excel), we send it only as text/name
            else:
                human_msg = HumanMessage(content=enhanced_user_input)
                print(f"\033[94m[Chat]: Text message with document reference: {filename}\033[0m")

        # ── Standard text message ────────────────────────────────
        else:
            # We feed the LangGraph state the isolated XML payload
            human_msg = HumanMessage(content=isolated_user_input)

        # Timestamp on the current message
        now_ts = datetime.now().strftime("%H:%M")
        if isinstance(human_msg.content, str):
            human_msg = HumanMessage(
                content=f"[{now_ts}] {human_msg.content}",
                additional_kwargs=human_msg.additional_kwargs,
            )
        elif isinstance(human_msg.content, list):
            parts = list(human_msg.content)
            for i, p in enumerate(parts):
                if isinstance(p, dict) and p.get("type") == "text":
                    parts[i] = {"type": "text", "text": f"[{now_ts}] {p['text']}"}
                    break
            human_msg = HumanMessage(
                content=parts,
                additional_kwargs=human_msg.additional_kwargs,
            )
        # ── Running LangGraph ─────────────────────────────────
        import tools.system as _ts; _ts._CURRENT_CHANNEL = "web"
        if photo_path and os.path.exists(photo_path):
            print(f"\033[95m[Web->Graph]: Forwarding multimodal message to graph — '{isolated_user_input[:120]}'\033[0m")
        else:
            print(f"\033[95m[Web->Graph]: Forwarding message to graph — '{isolated_user_input[:120]}'\033[0m")
        
        from memory.execution_trace import ExecutionTrace
        from time import perf_counter
        _trace = ExecutionTrace(channel="web", user_message=user_input)

        t_context_0 = perf_counter()
        context_msgs = _load_shared_context_messages("web", exclude_message_id=current_history_id)
        _trace.mark_phase("context_load_ms", int((perf_counter() - t_context_0) * 1000))

        from core.utils import (
            is_simple_chat_fast_path_candidate,
            is_medium_web_chat_path_candidate,
            is_ultra_light_ack,
            get_ultra_light_ack_response,
            is_reply_to_recent_mail_prompt,
            is_reply_to_recent_linkedin_prompt,
            looks_like_terminal_linkedin_draft_result,
            build_linkedin_draft_ready_reply,
            should_attach_linkedin_draft_reply,
            looks_like_terminal_messenger_draft_result,
            build_messenger_draft_ready_reply,
        )
        
        is_ultra_ack = is_ultra_light_ack(isolated_user_input)
        tool_result_fallbacks = []
        external_tool_names: list[str] = []
        provenance_messages_for_reply: list = []

        from core.planner import get_fresh_pending_plan_confirmation

        pending_plan_confirmation = not routine_action_consumed and bool(
            get_fresh_pending_plan_confirmation(
                {"channel": "web"},
                isolated_user_input,
            )
        )
        _trace.mark_phase(
            "pending_plan_confirmation_active",
            1 if pending_plan_confirmation else 0,
        )

        mail_prompt_active = is_reply_to_recent_mail_prompt(context_msgs)
        linkedin_prompt_active = is_reply_to_recent_linkedin_prompt(context_msgs)

        if (
            is_ultra_ack
            and routine_completion_context is None
            and not mail_prompt_active
            and not pending_plan_confirmation
        ):
            _trace.mark_phase("ultra_light_ack_used", 1)
            final_ai_response = get_ultra_light_ack_response()
            handling_agent = "UltraLightACK"
            print(f"\033[92m[Web->UltraLightACK]: Instant reply in '{isolated_user_input}'\033[0m")
        else:
            medium_path_used = is_medium_web_chat_path_candidate(isolated_user_input)
            fast_path_used = (
                not pending_plan_confirmation
                and not medium_path_used
                and is_simple_chat_fast_path_candidate(isolated_user_input)
            )
            _trace.mark_phase("fast_path_candidate", 1 if fast_path_used else 0)
            _trace.mark_phase("fast_path_used", 1 if fast_path_used else 0)
            _trace.mark_phase("medium_path_candidate", 1 if medium_path_used else 0)
            _trace.mark_phase("medium_path_used", 1 if medium_path_used else 0)
            from services.routine_completion_context import append_routine_completion_context

            if pending_plan_confirmation:
                limit = 100
                messages_for_graph = append_routine_completion_context(context_msgs, routine_completion_context, routine_draft_offer_context) + [human_msg]
            elif fast_path_used:
                limit = 12
                messages_for_graph = append_routine_completion_context(context_msgs[-6:], routine_completion_context, routine_draft_offer_context) + [human_msg]
            elif medium_path_used:
                limit = 24
                messages_for_graph = append_routine_completion_context(context_msgs[-8:], routine_completion_context, routine_draft_offer_context) + [human_msg]
            else:
                limit = 100
                messages_for_graph = append_routine_completion_context(context_msgs, routine_completion_context, routine_draft_offer_context) + [human_msg]

            _trace.mark_phase("web_graph_budget", limit)

            provenance_messages_for_reply = messages_for_graph
            graph_result = await asyncio.to_thread(
                _run_web_graph_stream_sync,
                messages_for_graph,
                limit,
                _trace,
            )
            final_ai_response = graph_result["final_ai_response"]
            handling_agent = graph_result["handling_agent"]
            tool_result_fallbacks = graph_result["tool_result_fallbacks"]
            external_tool_names = graph_result["external_tool_names"]
            graph_elapsed_ms = graph_result["graph_elapsed_ms"]
            _trace.mark_phase("graph_call_ms", graph_elapsed_ms)
            _trace.mark_phase("graph_stream_ms", graph_elapsed_ms)

        t_build_0 = perf_counter()

        if should_attach_linkedin_draft_reply(
            isolated_user_input,
            tool_result_fallbacks,
            recent_linkedin_prompt_active=linkedin_prompt_active,
        ):
            final_ai_response = build_linkedin_draft_ready_reply(tool_result_fallbacks)

        if any(looks_like_terminal_messenger_draft_result(r) for r in tool_result_fallbacks):
            final_ai_response = build_messenger_draft_ready_reply(tool_result_fallbacks)

        if not final_ai_response:
            final_ai_response = _tool_results_fallback_response(isolated_user_input, tool_result_fallbacks)

        # --- [MASTRO-FIX]: Additional cleaning BEFORE saving ---
        # We use the raw user_input for memory extraction so Astakos 
        # doesn't memorize the XML tags as part of your data.
        clean_user = clean_message(user_input)
        clean_ai   = clean_message(final_ai_response)

        # 1. --- MASTER INTERCEPTOR FOR REGISTRATION LINKS (Web UI) ---
        file_match = re.search(r"\[CREATED_FILE:\s*(.*?)\]", clean_ai)
        if file_match:
            file_path = file_match.group(1).strip()
            filename  = os.path.basename(file_path)
            base_url  = str(request.base_url).rstrip("/")

            # File card with a button that uploads to Drive on-demand
            import json as _json
            safe_path = _json.dumps(file_path)  # properly escaped JSON string
            file_card = (
                f'<br><br><div style="display:flex;align-items:center;gap:10px;'
                f'padding:10px 14px;background:#f8f9fa;border-radius:8px;border:1px solid #dee2e6;">'
                f'<span style="font-size:1.3em;">📎</span>'
                f'<span style="flex:1;font-weight:bold;color:#333;">{filename}</span>'
                f'<button onclick="window.astakosOpenDrive(this)" data-path={safe_path} '
                f'style="padding:6px 16px;background:#1a73e8;color:#fff;border:none;'
                f'border-radius:6px;cursor:pointer;font-weight:bold;font-size:.9em;">'
                f'📂 Google Drive</button>'
                f'</div>'
            )
            clean_ai = re.sub(r"\[CREATED_FILE:\s*(.*?)\]", lambda m: file_card, clean_ai)

        # 2. --- MASTRO INTERCEPTOR FOR IMAGES (Web UI) ---
        # Persist stable references. Fresh client-specific URLs are rendered only
        # when returning the response or replaying history.
        clean_ai = _replace_bracketed_markers(
            clean_ai,
            "[SEND_PHOTO:",
            lambda file_path: _asset_history_marker_from_legacy_photo_path(file_path),
        )

        if final_ai_response:
            # We store the CLEAN strings everywhere (including the Link/Img if it exists)
            _trace.mark_phase("final_response_build_ms", int((perf_counter() - t_build_0) * 1000))
            _trace.agent = handling_agent
            from core.utils import sanitize_messenger_draft_claims, strip_operational_assistant_paragraphs
            clean_ai = sanitize_messenger_draft_claims(clean_ai)
            clean_ai = strip_operational_assistant_paragraphs(clean_ai).strip() or clean_ai
            client_ai = _render_persisted_asset_markers(clean_ai, request)
            from core.untrusted_content import derived_external_content_history_metadata
            assistant_metadata = derived_external_content_history_metadata(
                provenance_messages_for_reply,
                external_tool_names,
            )
            _trace.finalize(response=client_ai)
            
            assistant_history_kwargs = {
                "agent": handling_agent,
                "return_saved": True,
            }
            if assistant_metadata:
                assistant_history_kwargs["metadata"] = assistant_metadata
            assistant_history_saved = append_to_chat_history(
                "assistant",
                clean_ai,
                **assistant_history_kwargs,
            )
            assistant_history_rowid = assistant_history_saved.get("rowid")
            
            t_bg_0 = perf_counter()
            from core.untrusted_content import external_content_source_names
            external_content_sources = external_content_source_names(assistant_metadata)
            if external_content_sources:
                print("[Security]: external-derived reply - use trusted user text only for background state")
                enqueue_fast_task(log_exchange,                  clean_user, "", handling_agent, "web")
                enqueue_fast_task(update_working_memory,         clean_user, "")
                enqueue_fast_task(_enqueue_slow_memory_sifter,   clean_user, "", handling_agent, "web", None, True)
                enqueue_slow_task(_enqueue_followup_pipeline, clean_user, "", handling_agent, "web")
                enqueue_slow_task(extract_and_update_context_flags, clean_user, "", "web")
            else:
                enqueue_fast_task(log_exchange,                  clean_user, clean_ai, handling_agent, "web")
                enqueue_fast_task(update_working_memory,         clean_user, clean_ai, external_content_sources)
                enqueue_fast_task(_enqueue_slow_memory_sifter,   clean_user, clean_ai, handling_agent, "web", external_content_sources)
                enqueue_slow_task(_enqueue_capability_gap_web,   clean_user, clean_ai, handling_agent, "web", current_history_rowid)
                enqueue_slow_task(_enqueue_followup_pipeline, clean_user, clean_ai, handling_agent, "web")
                enqueue_slow_task(extract_and_update_context_flags, clean_user, clean_ai, "web")
            _trace.mark_phase("background_enqueue_ms", int((perf_counter() - t_bg_0) * 1000))

            _trace.save()

        return JSONResponse({
            "agent":    handling_agent,
            "response": client_ai if final_ai_response else clean_ai,
            "user_rowid": current_history_rowid,
            "assistant_rowid": assistant_history_rowid if final_ai_response else None,
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        err = str(e).lower()
        if "429" in err or "resource exhausted" in err or "quota" in err:
            return JSONResponse(
                {"error": "Model quota exhausted right now. Please retry shortly."},
                status_code=503,
            )
        return JSONResponse({"error": _api_internal_error("chat")}, status_code=500)

@server.post("/voice")
async def process_web_voice(file: UploadFile = File(...), _=Depends(require_token)):
    """Accepts audio from the Web UI, transcribes it to text using Gemini, and returns it."""
    try:
        audio_data = await file.read()
        debug_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "debug_voice.webm")
        with open(debug_path, "wb") as f:
            f.write(audio_data)
        print(f"\033[96m[Web Voice]: Decoding audio ({len(audio_data)} bytes)...\033[0m")
        import config
        _provider = getattr(config, "LLM_PROVIDER", "vertex").lower()
        
        if _provider in ["vertex", "gemini"]:
            from core.brain import vertex_client
            client = vertex_client
            response = client.models.generate_content(
                model=FAST_MODEL,
                contents=[
                    {"inline_data": {"mime_type": "audio/webm", "data": audio_data}},
                    t("prompts.ext_speech_to_text")
                ]
            )
            transcription = response.text.strip() if response.text else ""
            if not transcription or "[SILENCE]" in transcription:
                return JSONResponse({"error": t("api.server.no_audio_heard")})
                
        elif _provider == "openai":
            import requests
            headers = {"Authorization": f"Bearer {config.OPENAI_API_KEY}"}
            files = {"file": ("audio.webm", audio_data, "audio/webm")}
            data = {"model": "whisper-1"}
            resp = requests.post("https://api.openai.com/v1/audio/transcriptions", headers=headers, files=files, data=data)
            resp_json = resp.json()
            if "error" in resp_json:
                return JSONResponse({"error": str(resp_json["error"])}, status_code=500)
            transcription = resp_json.get("text", "").strip()
            if not transcription:
                return JSONResponse({"error": t("api.server.no_audio_heard")})
                
        else:
            return JSONResponse({"error": "Voice input is not supported for this LLM Provider (Anthropic). Please use Text."})
        print(f"\033[92m[Web Voice]: {config.USER_NAME} said -> {transcription}\033[0m")
        return JSONResponse({"transcription": transcription})
    except Exception as e:
        return JSONResponse({"error": _api_internal_error("voice")}, status_code=500)


import edge_tts
import io

@server.post("/tts")
async def text_to_speech(request: Request, _=Depends(require_token)):
    try:
        body = await request.json()
        text = body.get("text", "").strip()
        if not text:
            return JSONResponse({"error": t("api.server.empty_text_for_tts")}, status_code=400)
        text = re.sub(r'[*#`]', '', text)
        text = re.sub(r'\[.*?\]\(.*?\)', '', text)
        text = _replace_bracketed_markers(text, "[SEND_PHOTO:", lambda _: "")
        text = _replace_bracketed_markers(text, "[ASTAKOS_ASSET:", lambda _: "")
        text = _replace_bracketed_markers(text, "[ASTAKOS_ASSET_URL:", lambda _: "")
        text = text.strip()
        from core.i18n import CURRENT_LOCALE
        voice = "el-GR-NestorasNeural" if CURRENT_LOCALE == "el" else "en-US-ChristopherNeural"
        communicate = edge_tts.Communicate(text, voice, rate="-10%", volume="+10%")
        audio_buffer = io.BytesIO()
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                audio_buffer.write(chunk["data"])
        audio_buffer.seek(0)
        audio_bytes = audio_buffer.read()
        if not audio_bytes:
            return JSONResponse({"error": t("api.server.tts_creation_failed")}, status_code=500)
        print(f"\033[95m[TTS]: Voice generated ({len(audio_bytes)} bytes)\033[0m")
        from fastapi.responses import Response
        return Response(
            content=audio_bytes,
            media_type="audio/mpeg",
            headers={"Content-Disposition": "inline; filename=response.mp3"}
        )
    except Exception as e:
        return JSONResponse({"error": _api_internal_error("tts")}, status_code=500)


MAX_UPLOAD_BYTES = 20 * 1024 * 1024  # 20 MB limit
ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".pdf", ".docx", ".xlsx", ".xls", ".txt", ".csv", ".json", ".py", ".md", ".log"}

def _prepare_document_excerpt(text: str, max_chars: int = 16000, head_chars: int = 9000, tail_chars: int = 5000) -> str:
    raw = str(text or "")
    if len(raw) <= max_chars:
        return raw

    head = raw[:head_chars].rstrip()
    tail = raw[-tail_chars:].lstrip()
    omitted = len(raw) - len(head) - len(tail)

    return (
        f"{head}\n\n"
        f"[... omitted {omitted} characters from the middle ...]\n\n"
        f"{tail}"
    )

def _normalize_followup_text(text: str) -> str:
    import unicodedata
    raw = str(text or "").strip().lower()
    normalized = unicodedata.normalize("NFD", raw)
    return "".join(ch for ch in normalized if not unicodedata.combining(ch))

def _looks_like_recent_asset_followup(text: str) -> bool:
    t = _normalize_followup_text(text)
    if not t:
        return False

    from config import NLP_CONFIG
    intents = NLP_CONFIG.get("intents", {})
    asset_tokens = intents.get("asset_tokens", [])
    inspect_tokens = intents.get("inspect_tokens", [])

    has_asset = any(tok in t for tok in asset_tokens)
    has_inspect = any(tok in t for tok in inspect_tokens)

    if has_asset and has_inspect:
        return True

    short_followup_markers = intents.get("short_followup_markers", [])
    return any(m in t for m in short_followup_markers)

def _read_document_text_for_analysis(file_path: str, file_ext: str) -> str:
    doc_text = ""
    try:
        if file_ext in (".txt", ".csv", ".json", ".py", ".md", ".log"):
            from core.utils import extract_text_preview
            doc_text = _prepare_document_excerpt(extract_text_preview(file_path, max_chars=16000))
        elif file_ext == ".pdf":
            from core.utils import extract_pdf_preview
            doc_text = _prepare_document_excerpt(extract_pdf_preview(file_path, max_chars=16000))
        elif file_ext in (".docx",):
            from core.utils import extract_docx_preview
            doc_text = _prepare_document_excerpt(extract_docx_preview(file_path, max_chars=16000))
        elif file_ext in (".xlsx", ".xls"):
            from core.utils import extract_xlsx_preview
            doc_text = _prepare_document_excerpt(extract_xlsx_preview(file_path, max_chars=16000))
        else:
            doc_text = t("api.server.unsupported_inline_type", file_ext=file_ext)
    except Exception as read_err:
        doc_text = t("api.server.unreadable_content", read_err=read_err)
    return doc_text

@server.post("/upload")
async def upload_file(
    request: Request,
    file: UploadFile = File(...),
    message: str = Form(""),
    _=Depends(require_token),
):
    """Endpoint for uploading files (photos & documents) from the Web UI."""
    try:
        file_ext  = os.path.splitext(file.filename or "")[1].lower() or ".jpg"
        if file_ext not in ALLOWED_EXTENSIONS:
            return JSONResponse({"status": "error", "message": t("api.server.invalid_file_type", file_ext=file_ext)}, status_code=400)
        filename  = f"web_{uuid.uuid4().hex}{file_ext}"
        image_exts = [".jpg", ".jpeg", ".png", ".webp", ".gif"]
        doc_exts   = [".pdf", ".docx", ".xlsx", ".xls", ".txt", ".csv", ".json", ".py", ".md", ".log"]
        is_image   = file_ext in image_exts
        if is_image:
            target_dir = PHOTOS_DIR
        else:
            from config import UPLOADS_DIR
            target_dir = UPLOADS_DIR
        file_path = os.path.join(target_dir, filename)
        content = await file.read()
        user_caption = str(message or "").strip()
        is_virtual_paste = (file.filename or "").startswith("paste_")
        if len(content) > MAX_UPLOAD_BYTES:
            return JSONResponse({"status": "error", "message": t("api.server.file_too_large")}, status_code=413)
        with open(file_path, "wb") as buffer:
            buffer.write(content)
        print(f"\033[92m[Upload]: Saved → {filename}\033[0m")
        memory_analysis = ""
        detailed_analysis = ""
        if is_image:
            from langchain_core.messages import HumanMessage
            import base64
            import io
            
            img = Image.open(file_path)
            if img.mode == 'RGBA':
                img = img.convert('RGB')
            img.thumbnail((1024, 1024))
            
            img_byte_arr = io.BytesIO()
            img.save(img_byte_arr, format='JPEG')
            img_b64 = base64.b64encode(img_byte_arr.getvalue()).decode("utf-8")
            
            from core.untrusted_content import (
                USER_PROVIDED_ASSET_SOURCE,
                format_untrusted_asset_vision_prompt,
            )

            def analyze_img(prompt_text: str) -> str:
                """Analyze an uploaded image with an explicit untrusted-data boundary."""
                msg = HumanMessage(
                    content=[
                        {
                            "type": "text",
                            "text": format_untrusted_asset_vision_prompt(prompt_text),
                        },
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"}}
                    ]
                )
                resp = llm.invoke([msg])
                from core.utils import clean_message
                return clean_message(resp.content) if resp and resp.content else ""
                
            memory_analysis = analyze_img("Describe what you see in Greek, concisely, 1-2 sentences.")
            if not memory_analysis:
                memory_analysis = "No analysis available."
                
            detailed_analysis = analyze_img("Analyze the photo in detail in Greek, with humor and liveliness.")
            if not detailed_analysis:
                detailed_analysis = memory_analysis
            chat_ai_msg = (
                t("api.server.photo_received", filename=filename) +
                f"{detailed_analysis}\n\n" +
                t("api.server.save_prompt").split("\n")[0] + "\n" +
                t("api.server.save_prompt").split("\n")[1]
            )
            user_log_msg = f"[USER_UPLOADED_PHOTO]: {filename}\n[PHOTO PATH]: {file_path}\n[ANALYSIS]: {memory_analysis}"
        elif file_ext in doc_exts:
            # We read the content of the document
            doc_text = _read_document_text_for_analysis(file_path, file_ext)
            from core.untrusted_content import (
                USER_PROVIDED_ASSET_SOURCE,
                format_untrusted_tool_result,
            )
            doc_text = format_untrusted_tool_result(USER_PROVIDED_ASSET_SOURCE, doc_text)

            # We send to the LLM for summary/analysis
            from memory.conversation_history import build_asset_context_text
            conversation_context = build_asset_context_text("web")

            caption_text = user_caption or t("api.server.no_caption_provided")

            from core.i18n import load_prompt
            sum_prompt = load_prompt("web_document_context.md").format(
                conversation_context=conversation_context or "No recent context exists.",
                caption_text=caption_text,
                summary_rules=t('api.server.summary_rules'),
                file_filename=file.filename,
                doc_text=doc_text
            )
            from langchain_core.messages import HumanMessage as _HM
            sum_resp = safe_llm_invoke(llm, [_HM(content=sum_prompt)])
            detailed_analysis = clean_message(sum_resp.content).strip() if sum_resp and sum_resp.content else t("api.server.analysis_failed")
            memory_analysis = detailed_analysis[:500]

            asset_label = t("api.server.asset_text") if is_virtual_paste else t("api.server.asset_doc")

            chat_ai_msg = (
                f"📄 **{asset_label}:** `{file.filename}`\n\n" +
                f"{detailed_analysis}\n\n" +
                t("api.server.save_prompt").split("\n")[0] + "\n" +
                t("api.server.save_prompt").split("\n")[1]
            )
            source_tag = "pasted_text" if is_virtual_paste else "uploaded_document"
            user_log_msg = (
                f"[USER_UPLOADED_FILE]: {filename}\n" +
                f"[FILE PATH]: {file_path}\n" +
                f"[USER_CAPTION]: {user_caption}\n" +
                t("api.server.visual_analysis_prefix", memory_analysis=memory_analysis) +
                f"[CONTENT_SOURCE]: {source_tag}"
            )
        else:
            memory_analysis = t("api.server.memory_analysis_format", file_ext=file_ext, filename=file.filename)
            detailed_analysis = t("api.server.detailed_analysis_format", file_ext=file_ext)
            chat_ai_msg = (
                t("api.server.file_received", filename=filename) +
                f"{detailed_analysis}\n\n" +
                t("api.server.file_action_prompt")
            )
            user_log_msg = f"[USER_UPLOADED_FILE]: {filename}\n[FILE PATH]: {file_path}\n[ANALYSIS]: {memory_analysis}"
        upload_history_msg = t("api.server.upload_history_msg", filename=filename)
        if user_caption:
            upload_history_msg += t("api.server.upload_history_caption", user_caption=user_caption)
        from core.untrusted_content import (
            USER_PROVIDED_ASSET_SOURCE,
            external_content_history_metadata,
        )
        asset_metadata = external_content_history_metadata([USER_PROVIDED_ASSET_SOURCE])
        append_to_chat_history("user", upload_history_msg, metadata=asset_metadata)
        append_to_chat_history("assistant", chat_ai_msg, metadata=asset_metadata)
        print("[Security]: upload-derived reply - use trusted user text only for background state")
        enqueue_fast_task(log_exchange, user_caption, "", "Chat_Agent", "web")
        enqueue_fast_task(update_working_memory, user_caption, "")
        enqueue_fast_task(_enqueue_slow_memory_sifter, user_caption, "", "Chat_Agent", "web", None, True)
        enqueue_slow_task(_enqueue_followup_pipeline, user_caption, "", "Chat_Agent", "web")
        enqueue_slow_task(extract_and_update_context_flags, user_caption, "", "web")

        from memory.pending_assets import looks_like_asset_confirmation_prompt
        if looks_like_asset_confirmation_prompt(chat_ai_msg):
            try:
                from memory.pending_assets import create_pending_asset_archive
                asset_type = "photo" if is_image else "document"
                create_pending_asset_archive(
                    channel="web",
                    asset_type=asset_type,
                    file_path=file_path,
                    filename=filename,
                    analysis=memory_analysis,
                    caption=user_caption,
                    external_content_sources=[USER_PROVIDED_ASSET_SOURCE],
                )
            except Exception as e:
                print(f"[PendingAssets]: Web upload error: {e}")
        return JSONResponse({
            "status":    "success",
            "filename":  filename,
            "file_path": file_path,
            "url":       _private_asset_url(request, "photos", filename) if is_image else None,
            "ai_message": chat_ai_msg,
            "analysis":  memory_analysis,
        })
    except Exception as e:
        return JSONResponse({"status": "error", "message": _api_internal_error("upload")}, status_code=500)


@server.get("/")
async def read_index():
    """Serves the Web UI (index.html)."""
    from fastapi.responses import FileResponse
    return FileResponse('index.html')


@server.get("/health")
async def health():
    return {"status": "ok", "time": datetime.now().isoformat()}


@server.get("/messages/poll")
async def poll_messages(request: Request, after_id: int = 0, channel: str | None = None, _=Depends(require_token)):
    """
    Polling endpoint for the Web UI.
    Returns messages with id > after_id (default: 0 = all).
    Usage: GET /messages/poll?after_id=42&channel=telegram
    """
    try:
        from memory.conversation_history import load_messages_after_rowid, get_max_rowid
        messages = load_messages_after_rowid(after_rowid=after_id, channel=channel or None, limit=50)
        for message in messages:
            message["content"] = _render_persisted_asset_markers(
                str(message.get("content", "")),
                request,
            )
        current_max = get_max_rowid()
        return {"messages": messages, "max_id": current_max}
    except Exception as e:
        return {"messages": [], "max_id": after_id, "error": _api_internal_error("poll")}


@server.get("/history")
async def get_history(request: Request, _=Depends(require_token)):
    """Provides the history to the Web UI from the shared SQLite."""
    history = _load_shared_history_entries(limit=200, request=request)
    return {"history": history}


@server.websocket("/ws/logs")
async def websocket_logs(websocket: WebSocket):
    """Keeps the channel open — sends live print() output to the Web UI."""
    if not await require_ws_token(websocket):
        return

    await websocket.accept()
    active_websockets.append(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    except Exception:
        logging.exception("Unexpected error in /ws/logs handler")
    finally:
        if websocket in active_websockets:
            active_websockets.remove(websocket)


# ────────────────────────────────────────────────────────────────
# OBSERVABILITY: /debug/runtime + /debug + /debug/traces
# ────────────────────────────────────────────────────────────────

def _read_json_file(path: str, default):
    try:
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return default


def _debug_condition_state_details(flag_name: str, effective_value, raw_states: dict, now_dt) -> dict:
    raw_item = raw_states.get(flag_name) or {}
    raw_value = raw_item.get("value")
    raw_expires = raw_item.get("expires_at")
    today = now_dt.strftime("%Y-%m-%d")

    reason = None

    if raw_expires and raw_expires < today:
        reason = f"expired at {raw_expires}"
    elif flag_name == "user_out_of_home":
        try:
            from services.routine_context import _recent_gps_status
            gps_status = _recent_gps_status(now_dt)
        except Exception:
            gps_status = None

        raw_bool = str(raw_value).strip().lower() == "true"
        raw_updated = str(raw_item.get("updated_at") or "").strip()
        if raw_bool and effective_value is True and gps_status == "home" and raw_updated:
            reason = "recent live message override over GPS-home"
        elif raw_bool and effective_value is False and gps_status == "home":
            reason = "GPS says home"
        elif raw_bool and effective_value is True and gps_status == "away":
            reason = "GPS confirms away"
    elif flag_name == "current_shift":
        if now_dt.weekday() >= 5 and str(raw_value or "").lower() in {"morning", "afternoon", "night"} and effective_value == "off":
            reason = "weekend override"
    elif flag_name == "state:kid1:outing":
        if raw_value and effective_value is None and raw_expires and raw_expires < today:
            reason = f"expired outing state from {raw_expires}"

    return {
        "stored_value": raw_value,
        "stored_expires_at": raw_expires,
        "effective_value": effective_value,
        "reason": reason,
    }


_ROUTINE_OUTCOME_LABELS = {
    "routine_triggered": "Sent",
    "deferred_followup": "Sent: deferred follow-up",
    "preemptive_completed": "Completed today",
    "confirmed": "Confirmed",
    "dismissed": "Dismissed",
    "pending_cleared_muted": "Notifications muted",
    "routine_condition_blocked": "Blocked by condition",
    "routine_condition_allowed": "Condition passed",
    "routine_cooldown_skip": "Skipped: cooldown",
    "routine_silent_skip": "Skipped: silent",
    "routine_context_skip": "Skipped: context",
    "routine_rate_limit_skip": "Skipped: rate limit",
    "routine_inactive_skip": "Skipped: inactive",
    "routine_timeout_decay": "Timed out",
    "routine_pending_stale_cleared": "Stale pending cleared",
}

_ROUTINE_OUTCOME_I18N_KEYS = {
    "routine_acknowledged": "api.server.routine_outcome_acknowledged",
    "routine_skipped_today": "api.server.routine_outcome_skipped_today",
    "routine_paused": "api.server.routine_outcome_paused",
    "routine_response_window_expired": "api.server.routine_outcome_response_window_expired",
    "routine_unanswered_decay": "api.server.routine_outcome_unanswered_decay",
}


def _routine_outcome_label(action: str) -> str:
    """Return a readable Debug label for any routine lifecycle event action."""
    localized_key = _ROUTINE_OUTCOME_I18N_KEYS.get(action)
    if localized_key:
        return t(localized_key)
    return _ROUTINE_OUTCOME_LABELS.get(
        action,
        f"Recorded: {action.replace('_', ' ').capitalize()}",
    )


def _latest_routine_outcome(events: list[dict], routine_id: int) -> dict | None:
    """Return the latest valid routine event for one routine from today's event log."""
    outcomes = [
        event for event in events
        if event.get("routine_id") == routine_id
        and isinstance(event.get("action"), str)
        and event["action"]
    ]
    return outcomes[-1] if outcomes else None


def _routine_outcome_fields(events: list[dict], routine_id: int) -> dict[str, str | None]:
    """Build the Dashboard outcome fields shared by active and non-active routines."""
    latest = _latest_routine_outcome(events, routine_id)
    if not latest:
        return {
            "last_outcome_action": None,
            "last_outcome_label": "Not evaluated",
            "last_outcome_ts": None,
            "last_outcome_reason": None,
        }

    action = latest["action"]
    return {
        "last_outcome_action": action,
        "last_outcome_label": _routine_outcome_label(action),
        "last_outcome_ts": latest.get("timestamp"),
        "last_outcome_reason": latest.get("reason") or latest.get("debug_effect"),
    }


@server.get("/debug/runtime")
async def debug_runtime(_=Depends(require_token)):
    """
    Live runtime snapshot — reads from:
      • runtime_snapshot.json   (scheduler jobs — written every 10s by telegram_bot)
      • scheduler_state.json    (override state)
      • astakos_routines.db     (active routines, pending confirmations, cooldowns)
      • logs/events/YYYY-MM-DD.json  (event throughput, last errors)
    """
    base = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")

    # ── 1. Scheduler snapshot ────────────────────────────────────
    snapshot     = _read_json_file(os.path.join(base, "runtime_snapshot.json"), {})
    override     = _read_json_file(os.path.join(base, "scheduler_state.json"), {})
    memory_context = _read_json_file(os.path.join(base, "runtime_memory_context.json"), {})

    # ── 2. DB: routines + pending confirmations ──────────────────
    import sqlite3 as _sqlite3
    import config
    db_path      = config.ROUTINES_DB
    active_routines   = []
    pending_from_db   = []
    cooldown_info     = []

    try:
        from services.routine_context import build_runtime_routine_context
        from services.routine_conditions import evaluate_routine_conditions
        from memory.routine_db import get_routine_conditions
        ctx = build_runtime_routine_context(datetime.now())
    except ImportError:
        ctx = {}
        evaluate_routine_conditions = lambda c_list, cx: {"allowed": True, "results": []}
        get_routine_conditions = lambda rid: []

    raw_context_states = {}
    try:
        from memory.routine_db import get_context_states
        raw_context_states = get_context_states([
            "kid1_away_from_home",
            "kid1_with_user",
            "kid1_with_partner",
            "current_shift",
            "user_out_of_home",
            "state:kid1:outing",
            "user_at_work",
            "family_at_home",
            "partner_with_user",
        ])
    except Exception:
        raw_context_states = {}

    try:
        conn   = _sqlite3.connect(db_path, check_same_thread=False)
        cursor = conn.cursor()

        from memory.event_log import get_events
        today_str = datetime.now().strftime("%Y-%m-%d")
        today_events = get_events(today_str, job="routines")

        # Active routines
        cursor.execute("""
            SELECT id, day_of_week, time_str, event_name, confidence,
                   mention_count, notify_cooldown_hours, last_notified_ts, state,
                   condition_type, condition_payload, condition_mode,
                    priority, source_memory_ref, conflict_group, paused_until, pause_reason, muted_until,
                    paused_indefinitely
            FROM routines
            WHERE state='active'
            ORDER BY day_of_week, time_str
        """)
        for row in cursor.fetchall():
            r_id, day, tstr, ev, conf, mentions, cd_h, last_ts, state, c_type, c_payload, c_mode, priority, memory_ref, conflict_group, paused_until, pause_reason, muted_until, paused_indefinitely = row
            now_dt = datetime.now()
            cooldown_remaining = None
            if last_ts:
                try:
                    last_dt = datetime.fromisoformat(last_ts)
                    elapsed = (now_dt - last_dt).total_seconds()
                    cd_secs = (cd_h or 20.0) * 3600
                    remaining_secs = cd_secs - elapsed
                    cooldown_remaining = max(0, round(remaining_secs / 3600, 1))
                except Exception:
                    pass
            
            cond_res = None
            cond_matched = None
            cond_reason = None
            cond_actual_value = None
            conditions_list = get_routine_conditions(r_id)
            eval_result = evaluate_routine_conditions(conditions_list, ctx)
            cond_res = eval_result.get("allowed", True)
            cond_results = eval_result.get("results", [])
            for idx, res in enumerate(cond_results):
                try:
                    flag_name = None

                    payload = None
                    if idx < len(conditions_list):
                        payload = conditions_list[idx].get("condition_payload")
                        if isinstance(payload, str):
                            import json
                            payload = json.loads(payload)

                    if isinstance(payload, dict):
                        flag_name = payload.get("flag")

                    if flag_name:
                        details = _debug_condition_state_details(
                            flag_name=flag_name,
                            effective_value=res.get("actual_value"),
                            raw_states=raw_context_states,
                            now_dt=now_dt,
                        )
                        res["debug_stored_value"] = details["stored_value"]
                        res["debug_stored_expires_at"] = details["stored_expires_at"]
                        res["debug_reason"] = details["reason"]
                except Exception:
                    pass

            # Extract an actual value for UI if the first condition has a 'flag' (context_flag, shift_mode)
            if conditions_list and conditions_list[0].get("condition_type") in ("context_flag", "shift_mode"):
                import json
                try:
                    payload = conditions_list[0].get("condition_payload")
                    if isinstance(payload, str):
                        payload = json.loads(payload)
                    flag_name = payload.get("flag")
                    if flag_name:
                        cond_actual_value = ctx.get(flag_name)
                except Exception:
                    pass

            outcome_fields = _routine_outcome_fields(today_events, r_id)

            if not memory_ref and conditions_list:
                memory_ref = conditions_list[0].get("source_memory_ref")

            active_routines.append({
                "id":                r_id,
                "day":               day,
                "time":              tstr,
                "event":             ev,
                "confidence":        round(conf or 0, 2),
                "mentions":          mentions or 1,
                "cooldown_hours":    cd_h or 20.0,
                "last_notified":     last_ts,
                "cooldown_remaining_h": cooldown_remaining,
                "state":             state,
                "conditions":        conditions_list,
                "condition_type":    c_type,
                "condition_payload": c_payload,
                "condition_mode":    c_mode,
                "condition_eval":    cond_res,
                "condition_results": cond_results,
                "condition_actual_value": cond_actual_value,
                "priority":          priority,
                "conflict_group":    conflict_group,
                "source_memory_ref": memory_ref,
                "paused_until":      paused_until,
                "paused_indefinitely": bool(paused_indefinitely),
                "pause_reason":      pause_reason,
                "condition_reason": cond_reason,
                "muted_until": muted_until,
                **outcome_fields,
            })

        # Pending confirmations
        cursor.execute("SELECT routine_id, event_name, sent_at FROM pending_confirmations")
        for row in cursor.fetchall():
            rid, ev, sent_at_str = row
            try:
                sent_dt  = datetime.fromisoformat(sent_at_str)
                elapsed  = round((datetime.now() - sent_dt).total_seconds() / 60, 1)
            except Exception:
                elapsed  = None
            pending_from_db.append({
                "routine_id": rid,
                "event":      ev,
                "sent_at":    sent_at_str,
                "elapsed_min": elapsed,
                "timeout_in_min": round(max(0, 30 - (elapsed or 0)), 1),
            })

        # Routines in non-active states (LEARNED, TRIGGER_PENDING, DISMISSED, DECAYED, etc.)
        cursor.execute("""
            SELECT id, day_of_week, time_str, event_name, state, confidence,
                   condition_type, condition_payload, condition_mode,
                   priority, source_memory_ref, conflict_group,
                   paused_until, pause_reason, muted_until
            FROM routines
            WHERE state != 'active' AND state != 'archived'
            ORDER BY state, day_of_week, time_str
        """)
        for row in cursor.fetchall():
            r_id, day, tstr, ev, state, conf, c_type, c_payload, c_mode, priority, memory_ref, conflict_group, paused_until, pause_reason, muted_until = row
            
            cond_res = None
            cond_matched = None
            cond_reason = None
            cond_actual_value = None
            conditions_list = get_routine_conditions(r_id)
            eval_result = evaluate_routine_conditions(conditions_list, ctx)
            cond_res = eval_result.get("allowed", True)
            cond_results = eval_result.get("results", [])
            for idx, res in enumerate(cond_results):
                try:
                    flag_name = None

                    payload = None
                    if idx < len(conditions_list):
                        payload = conditions_list[idx].get("condition_payload")
                        if isinstance(payload, str):
                            import json
                            payload = json.loads(payload)

                    if isinstance(payload, dict):
                        flag_name = payload.get("flag")

                    if flag_name:
                        details = _debug_condition_state_details(
                            flag_name=flag_name,
                            effective_value=res.get("actual_value"),
                            raw_states=raw_context_states,
                            now_dt=now_dt,
                        )
                        res["debug_stored_value"] = details["stored_value"]
                        res["debug_stored_expires_at"] = details["stored_expires_at"]
                        res["debug_reason"] = details["reason"]
                except Exception:
                    pass

            # Extract an actual value for UI if the first condition has a 'flag' (context_flag, shift_mode)
            if conditions_list and conditions_list[0].get("condition_type") in ("context_flag", "shift_mode"):
                import json
                try:
                    payload = conditions_list[0].get("condition_payload")
                    if isinstance(payload, str):
                        payload = json.loads(payload)
                    flag_name = payload.get("flag")
                    if flag_name:
                        cond_actual_value = ctx.get(flag_name)
                except Exception:
                    pass

            if not memory_ref and conditions_list:
                memory_ref = conditions_list[0].get("source_memory_ref")

            outcome_fields = _routine_outcome_fields(today_events, r_id)

            cooldown_info.append({
                "id": r_id, "day": day, "time": tstr,
                "event": ev, "state": state,
                "confidence": round(conf or 0, 2),
                "conditions":        conditions_list,
                "condition_type":    c_type,
                "condition_payload": c_payload,
                "condition_mode":    c_mode,
                "condition_eval":    cond_res,
                "condition_results": cond_results,
                "condition_actual_value": cond_actual_value,
                "priority":          priority,
                "conflict_group":    conflict_group,
                "source_memory_ref": memory_ref,
                "paused_until":      paused_until,
                "pause_reason":      pause_reason,
                "muted_until":       muted_until,
                **outcome_fields,
            })

        # Stats
        cursor.execute("SELECT state, COUNT(*) FROM routines GROUP BY state")
        state_counts = dict(cursor.fetchall())

        conn.close()
    except Exception as e:
        state_counts = {}
        active_routines.append({"error": _api_internal_error("debug_runtime")})

    # ── 3. Today's event log: throughput + last errors ───────────
    today      = datetime.now().strftime("%Y-%m-%d")
    log_file   = os.path.join(base, "logs", "events", f"{today}.json")
    events     = _read_json_file(log_file, [])

    # Throughput: count per (job, action) in last 1h
    from datetime import timedelta
    one_hour_ago = datetime.now() - timedelta(hours=1)
    throughput = {}
    last_errors = []
    for ev in events:
        try:
            ts  = datetime.fromisoformat(ev.get("timestamp", ""))
            job = ev.get("job", "?")
            act = ev.get("action", "?")
            key = f"{job}/{act}"
            if ts >= one_hour_ago:
                throughput[key] = throughput.get(key, 0) + 1
            if act in ("error", "db_error", "disabled") and ts >= one_hour_ago:
                last_errors.append({
                    "time":  ev.get("timestamp", "")[-8:],
                    "job":   job,
                    "error": str(ev.get("error", ""))[:120],
                })
        except Exception:
            pass
    last_errors = last_errors[-10:]  # max 10

    # ── 4. Assemble response ─────────────────────────────────────
    sleep_until = override.get("sleep_until")
    sleeping    = sleep_until and time.time() < sleep_until
    sleep_until_str = datetime.fromtimestamp(sleep_until).strftime("%H:%M") if sleeping else None
    routine_pause_until = override.get("routine_pause_until")
    try:
        routine_pause_until = float(routine_pause_until)
    except (TypeError, ValueError):
        routine_pause_until = None
    routines_paused = bool(routine_pause_until and time.time() < routine_pause_until)
    routine_pause_until_str = (
        datetime.fromtimestamp(routine_pause_until).strftime("%d/%m %H:%M")
        if routines_paused
        else None
    )
    routine_pause_remaining_days = (
        max(1, int((routine_pause_until - time.time() + 86399) // 86400))
        if routines_paused
        else None
    )

    # ── 5. Heartbeat health ──────────────────────────────────────
    snap_age = round(time.time() - datetime.fromisoformat(snapshot["written_at"]).timestamp(), 0) \
               if snapshot.get("written_at") else None
    scheduler_alive = snap_age is not None and snap_age < 30

    # ── 6. Channel sessions ──────────────────────────────────────
    try:
        from memory.conversation_history import (
            load_conversation_stats,
            load_last_user_activity,
            seconds_since_last_user_activity,
        )
        from memory.session_memory import AUTO_SESSION_SUMMARY_EXCHANGE_THRESHOLD, SESSION_LOGS

        history_stats = load_conversation_stats()
        last_user_activity = load_last_user_activity()
        seconds_since_activity = seconds_since_last_user_activity()
        channel_sessions = {"all": len(SESSION_LOGS)}
        conversation_debug = {
            "ok": True,
            "db_path": history_stats["db_path"],
            "messages_total": history_stats["messages_total"],
            "messages_by_channel": history_stats["messages_by_channel"],
            "messages_by_role": history_stats["messages_by_role"],
            "last_user_activity": last_user_activity,
            "seconds_since_last_user_activity": seconds_since_activity,
        }
        session_debug = {
            "ok": True,
            "memory_log_count": len(SESSION_LOGS),
            "persistent_exchanges_total": history_stats["session_exchanges_total"],
            "persistent_unsummarized": history_stats["unsummarized_exchanges"],
            "unsummarized_by_channel": history_stats["unsummarized_by_channel"],
            "auto_summary_threshold": AUTO_SESSION_SUMMARY_EXCHANGE_THRESHOLD,
            "auto_summary_due": (
                history_stats["unsummarized_exchanges"] >= AUTO_SESSION_SUMMARY_EXCHANGE_THRESHOLD
            ),
        }
    except Exception as e:
        channel_sessions = {}
        conversation_debug = {"ok": False, "error": _api_internal_error("debug_runtime")}
        session_debug = {"ok": False, "error": _api_internal_error("debug_runtime")}

    pending_actions = _get_pending_actions()
    messenger_draft = _get_messenger_draft_debug()

    return JSONResponse({
        "snapshot_age_s":  snap_age,
        "scheduler_alive": scheduler_alive,
        "channel_sessions": channel_sessions,
        "conversation": conversation_debug,
        "session": session_debug,
        "memory_context": memory_context,
        "approvals": {
            "pending_count": len(pending_actions),
            "pending_tools": [a.get("tool_name") for a in pending_actions],
        },
        "messenger_draft": messenger_draft,
        "scheduler": {
            "written_at":         snapshot.get("written_at"),
            "jobs":               snapshot.get("jobs", []),
            "queue_size":         snapshot.get("queue_size", "?"),
            "quiet_hours":        snapshot.get("quiet_hours"),
            "proactive_muted":    snapshot.get("proactive_muted"),
            "reminders_paused":   snapshot.get("reminders_paused"),
            "routines_paused":    snapshot.get("routines_paused"),
            "routine_pause_until": snapshot.get("routine_pause_until"),
            "routine_pause_remaining_days": snapshot.get("routine_pause_remaining_days"),
            "proactive_this_hour": snapshot.get("proactive_this_hour", 0),
            "pending_count":      snapshot.get("pending_confirmations", 0),
        },
        "overrides": {
            "pause_reminders": bool(override.get("pause_reminders")),
            "mute_proactive":  bool(override.get("mute_proactive")),
            "sleeping":        bool(sleeping),
            "sleep_until":     sleep_until_str,
            "routines_paused": routines_paused,
            "routine_pause_until": routine_pause_until_str,
            "routine_pause_remaining_days": routine_pause_remaining_days,
        },
        "routines": {
            "state_counts":    state_counts,
            "active":          active_routines,
            "non_active":      cooldown_info,
        },
        "pending_confirmations": pending_from_db,
        "pending_followups": find_pending_followups(limit=20, active_only=True),
        "pending_actions":       pending_actions,
        "events_1h": {
            "throughput":  throughput,
            "last_errors": last_errors,
            "total_today": len(events),
            "recent_logs": events[-100:],
        },
    })


def _get_pending_actions() -> list:
    """Returns CRITICAL tool calls pending approve/reject."""
    try:
        from core.approval import list_pending
        actions = []
        for item in list_pending():
            action = dict(item)
            requested_at = action.get("requested_at") or action.get("created_at")
            action["requested_at"] = requested_at
            action["age_seconds"] = _age_seconds(requested_at)
            actions.append(action)
        return actions
    except Exception:
        return []


def _age_seconds(iso_value: str | None) -> int | None:
    if not iso_value:
        return None
    try:
        return int((datetime.now() - datetime.fromisoformat(iso_value)).total_seconds())
    except Exception:
        return None


def _get_messenger_draft_debug() -> dict:
    try:
        from core.messenger_draft import debug_draft_state
        return debug_draft_state()
    except Exception as e:
        return {"exists": False, "active": False, "reason": "error", "error": _api_internal_error("messenger_draft_debug")}


@server.post("/debug/action/{tool_call_id}/approve")
async def approve_action(tool_call_id: str, _=Depends(require_token)):
    """Approves and executes CRITICAL pending action — pop only if successful."""
    try:
        from core.approval import execute_approved_pending
        from tools.system import all_tools
        execution = execute_approved_pending(tool_call_id, all_tools)
        if not execution["ok"]:
            return {"ok": False, "status": execution["status"], "error": execution["error"]}

        tool_name = execution["tool"]
        result = execution["result"]
        from tools.telegram import send_telegram_msg_full
        send_telegram_msg_full(str(result), prefix=t("api.server.dashboard_action_success", tool_name=tool_name))
        return {"ok": True, "status": "executed", "tool": tool_name, "result": str(result)}
    except Exception as e:
        return {"ok": False, "error": _api_internal_error("approve_action")}


@server.post("/debug/action/{tool_call_id}/reject")
async def reject_action(tool_call_id: str, _=Depends(require_token)):
    """Rejects CRITICAL pending action."""
    try:
        from core.approval import pop_pending
        from tools.telegram import send_telegram_msg
        item = pop_pending(tool_call_id)
        if item:
            send_telegram_msg(t("api.server.dashboard_action_cancelled", tool_name=item["tool_name"]))
        return {"ok": True, "status": "rejected"}
    except Exception as e:
        return {"ok": False, "error": _api_internal_error("reject_action")}

def _decorate_debug_event(ev: dict) -> dict:
    ev = dict(ev)

    ev.setdefault("debug_type", "")
    ev.setdefault("debug_source", "")
    ev.setdefault("debug_effect", "")

    action = (ev.get("action") or "").lower()

    if not ev["debug_type"]:
        if action in {"confirmed", "dismissed"}:
            ev["debug_type"] = "manual_control"
        elif action in {"pending_stale_cleared", "timeout_decay"}:
            ev["debug_type"] = "pending_cleanup"
        elif action in {"triggered", "silent_skip", "context_skip"}:
            ev["debug_type"] = "proactive_decision"
        elif "condition" in action:
            ev["debug_type"] = "condition_eval"

    if not ev["debug_source"]:
        if ev["debug_type"] == "manual_control":
            ev["debug_source"] = "user_message"
        elif ev["debug_type"] in {"proactive_decision", "condition_eval"}:
            ev["debug_source"] = "scheduler"
        elif ev["debug_type"] == "pending_cleanup":
            ev["debug_source"] = "timeout_guard"
        elif ev["debug_type"] == "reconciler_applied":
            ev["debug_source"] = "reconciler"

    if not ev["debug_effect"]:
        if action == "triggered":
            ev["debug_effect"] = "notification_sent"
        elif action in {"silent_skip", "context_skip"}:
            ev["debug_effect"] = "notification_skipped"
        elif action == "pending_stale_cleared":
            ev["debug_effect"] = "pending_cleared"
        elif action == "timeout_decay":
            ev["debug_effect"] = "cooldown_changed"
        elif action in {"confirmed", "dismissed"}:
            ev["debug_effect"] = "routine_changed"
        else:
            ev["debug_effect"] = "no_change"

    return ev


@server.get("/debug/replay")
async def debug_replay(days: int = 2, _=Depends(require_token)):
    from memory.event_log import get_routine_timeline
    try:
        events = get_routine_timeline(routine_id=None, days=days)
        events = [_decorate_debug_event(e) for e in events]
        return {"events": events, "count": len(events), "days": days}
    except Exception as e:
        return {"events": [], "error": _api_internal_error("routine_timeline")}

@server.delete("/debug/routine/{routine_id}")
async def delete_routine(routine_id: int, _=Depends(require_token)):
    """Deletes a routine from the database."""
    import sqlite3 as _sqlite3
    import config; db_path = config.ROUTINES_DB
    try:
        conn = _sqlite3.connect(db_path)
        conn.execute("DELETE FROM routines WHERE id=?", (routine_id,))
        conn.commit()
        conn.close()
        return {"ok": True, "deleted": routine_id}
    except Exception as e:
        return {"ok": False, "error": _api_internal_error("delete_routine")}

@server.post("/debug/routine/{routine_id}/reset-cooldown")
async def reset_routine_cooldown(routine_id: int, _=Depends(require_token)):
    """Reset cooldown → alerts immediately on the next cycle."""
    import sqlite3 as _sqlite3
    import config; db_path = config.ROUTINES_DB
    try:
        conn = _sqlite3.connect(db_path)
        conn.execute(
            "UPDATE routines SET last_notified_ts=NULL, notify_cooldown_hours=20 WHERE id=?",
            (routine_id,)
        )
        conn.commit()
        conn.close()
        return {"ok": True, "routine_id": routine_id}
    except Exception as e:
        return {"ok": False, "error": _api_internal_error("reset_routine_cooldown")}

@server.post("/debug/routine/{routine_id}/confirm")
async def force_confirm_routine(routine_id: int, _=Depends(require_token)):
    """Force-confirm a stuck TRIGGER_PENDING routine → ACTIVE."""
    try:
        from memory.routine_db import confirm_routine, mark_routine_responded, \
            remove_pending_confirmation, get_routine_state
        from core.routine_state import RoutineState
        state = get_routine_state(routine_id)
        if state != RoutineState.TRIGGER_PENDING:
            return {"ok": False, "error": f"Routine #{routine_id} is '{state.value}', not trigger_pending"}
        confirm_routine(routine_id)
        mark_routine_responded(routine_id)
        remove_pending_confirmation(routine_id)
        return {"ok": True, "confirmed": routine_id, "new_state": "active"}
    except Exception as e:
        return {"ok": False, "error": _api_internal_error("confirm_routine")}

@server.patch("/debug/routine/{routine_id}/state")
async def force_routine_state(routine_id: int, request: Request, _=Depends(require_token)):
    """Force state change for debug — e.g. {\"state\": \"active\"}."""
    import sqlite3 as _sqlite3
    body = await request.json()
    new_state = body.get("state", "").strip().lower()
    allowed = {"active", "learned", "decayed", "archived"}
    if new_state not in allowed:
        return {"ok": False, "error": f"Allowed states: {allowed}"}
    import config; db_path = config.ROUTINES_DB
    try:
        conn = _sqlite3.connect(db_path)
        is_active = 1 if new_state == "active" else 0
        conn.execute(
            "UPDATE routines SET state=?, is_active=? WHERE id=?",
            (new_state, is_active, routine_id)
        )
        conn.commit()
        conn.close()
        return {"ok": True, "routine_id": routine_id, "new_state": new_state}
    except Exception as e:
        return {"ok": False, "error": _api_internal_error("routine_state")}

@server.post("/debug/routine/{routine_id}/activate")
async def activate_routine(routine_id: int, _=Depends(require_token)):
    """Makes a routine LEARNED → ACTIVE."""
    import sqlite3 as _sqlite3
    import config; db_path = config.ROUTINES_DB
    try:
        conn = _sqlite3.connect(db_path)
        conn.execute("UPDATE routines SET state='active' WHERE id=?", (routine_id,))
        conn.commit()
        conn.close()
        return {"ok": True, "activated": routine_id}
    except Exception as e:
        return {"ok": False, "error": _api_internal_error("activate_routine")}

@server.patch("/debug/routine/{routine_id}")
async def edit_routine(routine_id: int, request: Request, _=Depends(require_token)):
    """Process day/time/event_name of a routine."""
    import sqlite3 as _sqlite3
    import config; db_path = config.ROUTINES_DB
    try:
        body = await request.json()
        day   = body.get("day")
        time  = body.get("time")
        event = body.get("event")
        if not any([day, time, event]):
            return {"ok": False, "error": t("api.server.no_fields_to_update")}
        conn = _sqlite3.connect(db_path)
        if day:
            conn.execute("UPDATE routines SET day_of_week=? WHERE id=?", (day, routine_id))
        if time:
            conn.execute("UPDATE routines SET time_str=? WHERE id=?", (time, routine_id))
        if event:
            conn.execute("UPDATE routines SET event_name=? WHERE id=?", (event, routine_id))
        if "conflict_group" in body:
            conn.execute("UPDATE routines SET conflict_group=? WHERE id=?", (body["conflict_group"], routine_id))
        if "priority" in body:
            conn.execute("UPDATE routines SET priority=? WHERE id=?", (int(body["priority"]), routine_id))
        conn.commit()
        conn.close()
        return {"ok": True, "updated": routine_id}
    except Exception as e:
        return {"ok": False, "error": _api_internal_error("edit_routine")}

@server.get("/debug/reflections")
async def get_reflections(_=Depends(require_token)):
    """Returns the last 20 reflections from the database."""
    import sqlite3 as _sqlite3
    import config; db_path = config.ROUTINES_DB
    try:
        conn = _sqlite3.connect(db_path)
        conn.row_factory = _sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM reflections ORDER BY created_at DESC LIMIT 20"
        ).fetchall()
        conn.close()
        return {"reflections": [dict(r) for r in rows]}
    except Exception as e:
        return {"reflections": [], "error": _api_internal_error("get_reflections")}

@server.post("/debug/reflection/{reflection_id}/apply")
async def apply_reflection(reflection_id: int, _=Depends(require_token)):
    """Manually applies a pending reflection."""
    import sqlite3 as _sqlite3
    import config; db_path = config.ROUTINES_DB
    try:
        conn   = _sqlite3.connect(db_path)
        conn.row_factory = _sqlite3.Row
        row    = conn.execute("SELECT * FROM reflections WHERE id=?", (reflection_id,)).fetchone()
        conn.close()
        if not row:
            return {"ok": False, "error": "Not found"}
        from services.reflection_engine import _apply_action
        r = dict(row)
        success = _apply_action(r)
        if success:
            conn2 = _sqlite3.connect(db_path)
            conn2.execute(
                "UPDATE reflections SET applied=1, applied_at=? WHERE id=?",
                (datetime.now().isoformat(timespec="seconds"), reflection_id)
            )
            conn2.commit()
            conn2.close()
        return {"ok": success}
    except Exception as e:
        return {"ok": False, "error": _api_internal_error("apply_reflection")}


@server.post("/upload-to-drive")
async def upload_to_drive_endpoint(request: Request, _=Depends(require_token)):
    """Uploads a local file to Google Drive, returns the shareable URL."""
    try:
        body     = await request.json()
        from config import UPLOADS_DIR

        filepath = resolve_allowed_file(
            body.get("path"),
            (PHOTOS_DIR, UPLOADS_DIR),
        )
        if not filepath:
            return JSONResponse({"ok": False, "error": t("api.server.file_not_found")}, status_code=404)
        from tools.gdrive import upload_to_drive
        url = upload_to_drive(filepath)
        if url:
            return {"ok": True, "url": url}
        return JSONResponse({"ok": False, "error": t("api.server.drive_upload_failed")}, status_code=500)
    except Exception as e:
        return JSONResponse({"ok": False, "error": _api_internal_error("upload_to_drive")}, status_code=500)


@server.delete("/debug/reflection/{reflection_id}")
async def delete_reflection(reflection_id: int, _=Depends(require_token)):
    """Deletes a reflection."""
    import sqlite3 as _sqlite3
    import config; db_path = config.ROUTINES_DB
    try:
        conn = _sqlite3.connect(db_path)
        conn.execute("DELETE FROM reflections WHERE id=?", (reflection_id,))
        conn.commit()
        conn.close()
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": _api_internal_error("delete_reflection")}


@server.get("/debug/goals")
async def debug_goals(_=Depends(require_token)):
    """Returns all long-term goals."""
    try:
        from memory.vector_store import vector_store, vector_lock
        with vector_lock:
            results = vector_store._collection.get(where={"category": "goal"})
        goals = []
        docs = results.get("documents", [])
        metas = results.get("metadatas", [])
        ids = results.get("ids", [])
        for i, (doc, meta) in enumerate(zip(docs, metas)):
            goals.append({
                "project":     meta.get("project", ""),
                "description": doc.split(": ", 1)[-1].replace("[GOAL] ", ""),
                "status":      meta.get("status", "active"),
                "date":        meta.get("date", ""),
                "progress":    meta.get("progress", 0),
                "milestones":  meta.get("milestones", ""),
                "chroma_id":   ids[i] if i < len(ids) else "",
            })
        goals.sort(key=lambda g: (g["status"] != "active", g["date"]))
        return {"goals": goals, "count": len(goals)}
    except Exception as e:
        return {"goals": [], "error": _api_internal_error("get_goals")}


@server.delete("/debug/goals/{project}")
async def delete_goal(project: str, _=Depends(require_token)):
    """Deletes a goal based on the project name."""
    try:
        from memory.vector_store import vector_store, vector_lock
        with vector_lock:
            existing = vector_store._collection.get(
                where={"category": "goal", "project": project}
            )
            if not existing["ids"]:
                return {"ok": False, "error": f"Goal not found"}
            vector_store._collection.delete(ids=existing["ids"])
        return {"ok": True, "deleted": project}
    except Exception as e:
        return {"ok": False, "error": _api_internal_error("delete_goal")}

@server.get("/debug/traces")
async def debug_traces(date: str | None = None, limit: int = 50, _=Depends(require_token)):
    """
    Returns execution traces (agent routing + tool calls) for debugging.
    ?date=YYYY-MM-DD  (default: today)
    ?limit=N           (default: 50, max 200)
    """
    from memory.execution_trace import load_traces
    limit = min(int(limit), 200)
    try:
        traces = load_traces(date=date, limit=limit)
        return {"traces": traces, "count": len(traces), "date": date or "today"}
    except Exception as e:
        return {"error": _api_internal_error("debug_traces"), "traces": []}


@server.get("/debug/memory-audit")
async def debug_memory_audit(days: int = 1, _=Depends(require_token)):
    """Returns the memory audit log (add/overwrite/skip/reflection) for N days."""
    from config import MEMORY_AUDIT_DIR
    from datetime import date, timedelta
    import json as _json
    entries = []
    today = date.today()
    for i in range(min(int(days), 7)):
        day = today - timedelta(days=i)
        path = os.path.join(MEMORY_AUDIT_DIR, f"{day.isoformat()}.json")
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = _json.load(f)
                    if isinstance(data, list):
                        for e in data:
                            e["date"] = day.isoformat()
                        entries.extend(data)
            except Exception:
                pass
    return {"entries": entries, "count": len(entries)}


@server.get("/debug/behavioral-patterns")
async def debug_behavioral_patterns(
    _: None = Depends(require_token),
) -> dict[str, object]:
    """Return read-only pattern candidates from confirmed behavioral events."""
    try:
        from memory.behavioral_event_state import list_events
        from services.behavioral_pattern_aggregator import (
            aggregate_behavioral_pattern_candidates,
        )

        candidates = aggregate_behavioral_pattern_candidates(
            list_events(record_state="confirmed", initialize=False),
        )
        return {"candidates": candidates, "count": len(candidates)}
    except Exception:
        return {
            "candidates": [],
            "count": 0,
            "error": _api_internal_error("debug_behavioral_patterns"),
        }


@server.get("/debug")
async def debug_panel(_=Depends(require_token)):
    """Observability HTML dashboard — auto-refresh every 5s."""
    from fastapi.responses import HTMLResponse
    _dir = os.path.dirname(os.path.abspath(__file__))
    html_path = os.path.join(_dir, "debug_dashboard.html")
    try:
        with open(html_path, "r", encoding="utf-8") as f:
            html = f.read()
    except FileNotFoundError:
        html = "<h1>debug_dashboard.html not found</h1>"
    return HTMLResponse(content=html)

