"""Production entrypoint for the private encrypted Matrix channel."""

from __future__ import annotations

import asyncio
import os
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv


ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))
load_dotenv(ROOT_DIR / ".env")


class MatrixRuntimeConfigurationError(ValueError):
    """Raised before connecting when the private Matrix setup is incomplete."""


@dataclass(frozen=True)
class MatrixRuntimeConfig:
    """Validated settings required by the production Matrix process."""

    homeserver_url: str
    service_user_id: str
    access_token: str
    allowed_user_id: str
    room_id: str
    store_path: Path
    media_path: Path


def load_runtime_config(
    env: Mapping[str, str] = os.environ,
    *,
    base_dir: str | Path = ROOT_DIR,
) -> MatrixRuntimeConfig:
    """Load a complete one-room Matrix setup without exposing credentials."""
    required = (
        "MATRIX_HOMESERVER_URL",
        "MATRIX_SERVICE_USER_ID",
        "MATRIX_ACCESS_TOKEN",
        "MATRIX_ALLOWED_USER_ID",
        "MATRIX_ROOM_ID",
        "MATRIX_STORE_PATH",
    )
    values = {name: str(env.get(name, "") or "").strip() for name in required}
    missing = [name for name, value in values.items() if not value]
    if missing:
        raise MatrixRuntimeConfigurationError(
            "Matrix runtime requires: " + ", ".join(missing)
        )

    homeserver_url = values["MATRIX_HOMESERVER_URL"].rstrip("/")
    parsed = urlparse(homeserver_url)
    loopback = parsed.hostname in {"localhost", "127.0.0.1", "::1"}
    if not parsed.netloc or (
        parsed.scheme != "https" and not (parsed.scheme == "http" and loopback)
    ):
        raise MatrixRuntimeConfigurationError(
            "Matrix homeserver must use HTTPS (HTTP is allowed only for loopback)."
        )

    root = Path(base_dir).resolve()

    def runtime_path(raw_path: str) -> Path:
        candidate = Path(raw_path)
        return (root / candidate).resolve() if not candidate.is_absolute() else candidate.resolve()

    media_value = str(env.get("MATRIX_MEDIA_PATH", "matrix_media") or "").strip()
    if not media_value:
        media_value = "matrix_media"
    return MatrixRuntimeConfig(
        homeserver_url=homeserver_url,
        service_user_id=values["MATRIX_SERVICE_USER_ID"],
        access_token=values["MATRIX_ACCESS_TOKEN"],
        allowed_user_id=values["MATRIX_ALLOWED_USER_ID"],
        room_id=values["MATRIX_ROOM_ID"],
        store_path=runtime_path(values["MATRIX_STORE_PATH"]),
        media_path=runtime_path(media_value),
    )


async def _discover_device_id(settings: MatrixRuntimeConfig) -> str:
    """Resolve the access token's device id before opening its crypto store."""
    from nio import AsyncClient, WhoamiError

    probe = AsyncClient(settings.homeserver_url, settings.service_user_id)
    probe.access_token = settings.access_token
    try:
        response = await probe.whoami()
        if isinstance(response, WhoamiError):
            raise RuntimeError("Matrix credentials were rejected by the homeserver")
        device_id = str(getattr(response, "device_id", "") or "").strip()
        if not device_id:
            raise RuntimeError("Matrix homeserver did not return an access-token device id")
        return device_id
    finally:
        await probe.close()


def _approval_result_text(result: object | None) -> str | None:
    """Render a bounded acknowledgement for one trusted approval reaction."""
    if result is None:
        return None
    status = str(getattr(result, "status", "") or "").strip()
    tool_name = str(getattr(result, "tool_name", "") or "action").strip()
    if status == "executed":
        return f"✅ `{tool_name}` executed."
    if status == "rejected":
        return f"❌ `{tool_name}` rejected."
    return f"⚠️ `{tool_name}` could not be executed ({status or 'failed'})."


async def run_matrix() -> None:
    """Compose the existing Matrix adapters and run the encrypted sync loop."""
    from nio import AsyncClient, AsyncClientConfig, RoomSendError, SyncError

    import config
    from clients.matrix_attachment import MatrixAttachmentSender
    from clients.matrix_client import MatrixTextTransport
    from clients.matrix_delivery import MatrixExternalTransport
    from clients.matrix_media import MatrixMediaDownloader
    from clients.matrix_voice import MatrixVoiceSender
    from clients import telegram_bot as shared_runtime
    from services.external_delivery import external_delivery_router
    from services.matrix_approval import MatrixApprovalReactionService
    from services.matrix_background import build_matrix_channel_services
    from tools.system import all_tools

    settings = load_runtime_config(base_dir=config.BASE_DIR)
    settings.store_path.mkdir(parents=True, exist_ok=True)
    settings.media_path.mkdir(parents=True, exist_ok=True)
    device_id = await _discover_device_id(settings)

    client_config = AsyncClientConfig(
        encryption_enabled=True,
        store_sync_tokens=True,
    )
    client = AsyncClient(
        settings.homeserver_url,
        settings.service_user_id,
        device_id=device_id,
        store_path=str(settings.store_path),
        config=client_config,
    )
    client.restore_login(
        user_id=settings.service_user_id,
        device_id=device_id,
        access_token=settings.access_token,
    )
    initial_sync = await client.sync(timeout=0, full_state=True)
    if isinstance(initial_sync, SyncError):
        await client.close()
        raise RuntimeError("Matrix initial encrypted sync failed")
    loop = asyncio.get_running_loop()

    async def send_room_text(text: str) -> str:
        response = await client.room_send(
            room_id=settings.room_id,
            message_type="m.room.message",
            content={"msgtype": "m.text", "body": text},
            ignore_unverified_devices=True,
        )
        if isinstance(response, RoomSendError):
            raise RuntimeError("Matrix text delivery failed")
        event_id = str(getattr(response, "event_id", "") or "").strip()
        if not event_id:
            raise RuntimeError("Matrix text delivery returned no event id")
        return event_id

    def send_text_from_worker(text: str) -> str:
        future = asyncio.run_coroutine_threadsafe(send_room_text(text), loop)
        return future.result(timeout=30)

    approval_service = MatrixApprovalReactionService(
        allowed_user_id=settings.allowed_user_id,
        allowed_room_id=settings.room_id,
        tools_provider=lambda: all_tools,
    )

    async def handle_approval_reaction(**kwargs: object) -> str | None:
        result = await asyncio.to_thread(approval_service.handle_reaction, **kwargs)
        return _approval_result_text(result)

    external_delivery_router.register(
        "matrix",
        MatrixExternalTransport(
            send_text=send_text_from_worker,
            approval_reaction_hint="React with ✅ to execute or ❌ to reject.",
        ),
    )
    channel_services = build_matrix_channel_services(
        enqueue_fast_task=shared_runtime.enqueue_fast_task,
        enqueue_slow_task=shared_runtime.enqueue_slow_task,
        graph=shared_runtime.graph,
        conversation_db_path=config.CONVERSATION_DB_FILE,
        command_handler=shared_runtime.handle_external_admin_command,
    )
    media_downloader = MatrixMediaDownloader(
        client=client,
        allowed_user_id=settings.allowed_user_id,
        allowed_room_id=settings.room_id,
        service_user_id=settings.service_user_id,
        storage_dir=settings.media_path,
    )
    attachment_sender = MatrixAttachmentSender(
        client=client,
        room_id=settings.room_id,
        allowed_root=Path(config.BASE_DIR) / "outputs",
    )
    voice_sender = MatrixVoiceSender(
        client=client,
        room_id=settings.room_id,
        locale="el-GR" if config.RESPONSE_LANGUAGE.lower() == "greek" else "en-US",
    )
    transport = MatrixTextTransport(
        client=client,
        allowed_user_id=settings.allowed_user_id,
        allowed_room_id=settings.room_id,
        service_user_id=settings.service_user_id,
        turn_handler=channel_services.text_handler,
        state_db_path=config.STATE_DB,
        approval_reaction_handler=handle_approval_reaction,
        media_downloader=media_downloader,
        media_handler=channel_services.media_handler,
        voice_sender=voice_sender.send,
        attachment_sender=attachment_sender.send,
        location_handler=channel_services.location_handler,
    )

    shared_runtime.start_external_background_runtime("matrix")
    print("🦞 [Matrix]: Encrypted Element channel started.")
    try:
        await transport.run()
    finally:
        shared_runtime.shutdown_event.set()
        external_delivery_router.unregister("matrix")


def main() -> None:
    """Run the Matrix process and expose only safe startup failures."""
    try:
        asyncio.run(run_matrix())
    except KeyboardInterrupt:
        pass
    except Exception as exc:
        print(f"❌ [Matrix]: Startup failed: {type(exc).__name__}: {exc}")
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
