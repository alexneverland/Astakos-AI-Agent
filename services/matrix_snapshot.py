"""Explicit, guarded standalone-Synapse snapshot collection.

No Docker command or credential read occurs at import. The Matrix bot/watchdog
must already be stopped. Only Synapse is paused, with a restart attempted even
when stop reports an ambiguous failure. PostgreSQL stays online for native dumps.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Callable, Iterator

if TYPE_CHECKING:
    from clients.matrix_bot import MatrixRuntimeConfig

from filelock import FileLock, Timeout

from services.matrix_backup import (
    MatrixBackupError, file_digest, is_reparse_point, secure_directory,
    snapshot_inventory, validate_path,
)


@dataclass(frozen=True)
class SnapshotSettings:
    """Explicit private sources; no automatic environment-file discovery."""

    synapse_dir: Path
    bot_store_dir: Path
    compose_file: Path
    work_dir: Path
    synapse_container: str
    postgres_container: str
    allow_server_pause: bool = False
    deployment_environment_file: Path | None = None
    include_bot_runtime: bool = False


def load_bot_runtime_for_backup() -> MatrixRuntimeConfig:
    """Resolve approved Matrix settings lazily through the production validator."""
    from clients.matrix_bot import load_runtime_config
    from core.messaging_channel import resolve_external_channel

    if resolve_external_channel() != "matrix":
        raise MatrixBackupError("matrix_channel_not_selected")
    return load_runtime_config()


def bot_runtime_payload(runtime: MatrixRuntimeConfig) -> dict:
    """Export a fixed settings allowlist, not arbitrary object/environment data."""
    return {"format_version": 1, "settings": {
        "ASTAKOS_EXTERNAL_CHANNEL": "matrix",
        "MATRIX_HOMESERVER_URL": runtime.homeserver_url,
        "MATRIX_SERVICE_USER_ID": runtime.service_user_id,
        "MATRIX_ACCESS_TOKEN": runtime.access_token,
        "MATRIX_ALLOWED_USER_ID": runtime.allowed_user_id,
        "MATRIX_ALLOWED_DEVICE_IDS": ",".join(runtime.allowed_device_ids),
        "MATRIX_ROOM_ID": runtime.room_id,
        "MATRIX_STORE_PATH": str(runtime.store_path),
        "MATRIX_MEDIA_PATH": str(runtime.media_path),
    }}


def assert_bot_stopped() -> None:
    """Fail closed on Windows if any Matrix bot/watchdog entry point is running.

    This guard checks process identifiers, not conversational phrases. It does
    not signal or terminate anything. Owner must keep writers stopped throughout
    capture; before/after guards and copy hashes detect observed restarts/writes.
    """
    if os.name != "nt":
        raise MatrixBackupError("bot_quiescence_check_not_supported")
    from services.matrix_backup_maintenance import paused_watchdog_ids
    allowed_ids = paused_watchdog_ids()
    # Exemption is narrow: only acknowledged idle watchdog PIDs, never a bot.
    allowed_literal = ",".join(str(pid) for pid in allowed_ids)
    command = (
        "$ErrorActionPreference='Stop'; "
        "$p=Get-CimInstance Win32_Process; "
        r"$r='(?i)(?:^|[\s\x22\x27\\/])(run_matrix\.py|run_external\.py|matrix_bot\.py)(?:[\s\x22\x27]|$)'; "
        f"$allowed=@({allowed_literal}); "
        r"if(@($p | Where-Object { $_.Name -match '^python(?:w|[0-9.]*)?\.exe$' "
        "-and $_.CommandLine -match $r -and ("
        "$_.ProcessId -notin $allowed "
        r"-or $_.CommandLine -match '(?i)(?:^|[\s\x22\x27\\/])matrix_bot\.py(?:[\s\x22\x27]|$)'"
        ") }).Count){exit 2}"
    )
    try:
        result = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
                                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL, timeout=30)
        if result.returncode == 2:
            raise MatrixBackupError("matrix_bot_or_watchdog_running")
        if result.returncode:
            raise MatrixBackupError("bot_quiescence_check_failed")
    except MatrixBackupError:
        raise
    except Exception:
        raise MatrixBackupError("bot_quiescence_check_failed") from None


def tree_inventory(root: Path) -> dict[str, tuple[int, int, str]]:
    """Fingerprint a static tree without database APIs or following reparse points."""
    root = validate_path(root)
    if not root.is_dir():
        raise MatrixBackupError("snapshot_source_missing")
    result = {}
    for path in root.rglob("*"):
        if is_reparse_point(path):
            raise MatrixBackupError("unsafe_snapshot_source")
        if path.is_file():
            info = path.stat()
            result[path.relative_to(root).as_posix()] = (info.st_size, info.st_mtime_ns, file_digest(path))
    return result


def copy_frozen_tree(source: Path, destination: Path) -> None:
    """Copy all stopped-store files, including WAL/SHM, and detect changed bytes."""
    before = tree_inventory(source)
    destination.mkdir()
    for path in source.rglob("*"):
        if is_reparse_point(path):
            raise MatrixBackupError("unsafe_snapshot_source")
        target = destination / path.relative_to(source)
        if path.is_dir():
            target.mkdir(parents=True, exist_ok=True)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, target)
            expected = before.get(path.relative_to(source).as_posix())
            if expected is None or file_digest(target) != expected[2]:
                raise MatrixBackupError("snapshot_source_changed")
    if tree_inventory(source) != before:
        raise MatrixBackupError("snapshot_source_changed")


def copy_frozen_file(source: Path, destination: Path) -> None:
    """Copy explicit deployment inputs and reject changes during the copy."""
    source = validate_path(source)
    info = source.stat()
    before = (info.st_size, info.st_mtime_ns, file_digest(source))
    shutil.copyfile(source, destination)
    info = source.stat()
    after = (info.st_size, info.st_mtime_ns, file_digest(source))
    if before != after or file_digest(destination) != before[2]:
        raise MatrixBackupError("snapshot_source_changed")


def docker_command(arguments: list[str], runner: Callable, *, output: Path | None = None) -> bytes:
    """Keep native binary dump output out of shell redirection and diagnostic logs."""
    if output is None:
        result = runner(["docker", *arguments], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                        stderr=subprocess.DEVNULL, check=False, timeout=180)
    else:
        with output.open("xb") as stream:
            result = runner(["docker", *arguments], stdin=subprocess.DEVNULL, stdout=stream,
                            stderr=subprocess.DEVNULL, check=False, timeout=3600)
            stream.flush()
            os.fsync(stream.fileno())
    if result.returncode:
        raise MatrixBackupError("docker_snapshot_command_failed")
    return result.stdout or b""


def inspect_container(container: str, runner: Callable) -> dict:
    """Select state, version and mounts only; never request environment secrets."""
    template = ('{"running":{{json .State.Running}},"image":{{json .Config.Image}},'
                '"mounts":{{json .Mounts}},"networks":{{json .NetworkSettings.Networks}}}')
    result = json.loads(docker_command(["inspect", "--format", template, container], runner))
    if not isinstance(result, dict) or not isinstance(result.get("running"), bool):
        raise MatrixBackupError("invalid_container_inventory")
    return result


def read_synapse_capture_config(container: str, runner: Callable) -> dict:
    """Resolve actual database/key/media from YAML inside Synapse, not host guesses."""
    program = (
        "import json,yaml; "
        "c=yaml.safe_load(open('/data/homeserver.yaml',encoding='utf-8')); "
        "assert c['database']['name']=='psycopg2'; "
        "a=c['database']['args']; "
        "print(json.dumps({'database':a.get('dbname',a.get('database')),"
        "'database_host':c['database']['args']['host'],"
        "'database_port':c['database']['args'].get('port',5432),"
        "'signing_key_path':c['signing_key_path'],"
        "'media_store_path':c.get('media_store_path','/data/media_store')}))"
    )
    return json.loads(docker_command(["exec", container, "python", "-c", program], runner))


def data_relative_path(value: str) -> Path:
    """Require supported /data paths; never silently omit external mounts."""
    path = PurePosixPath(value)
    if ".." in path.parts or "\\" in value or ":" in value:
        raise MatrixBackupError("unsupported_synapse_data_path")
    if path.is_absolute():
        try:
            path = path.relative_to("/data")
        except ValueError:
            raise MatrixBackupError("unsupported_synapse_data_path") from None
    if not path.parts:
        raise MatrixBackupError("unsupported_synapse_data_path")
    return Path(*path.parts)


@contextmanager
def captured_snapshot(
    settings: SnapshotSettings, *, runner: Callable = subprocess.run,
    bot_guard: Callable[[], None] = assert_bot_stopped,
    runtime_loader: Callable[[], MatrixRuntimeConfig] = load_bot_runtime_for_backup,
) -> Iterator[Path]:
    """Yield a validated snapshot after restarting Synapse; always remove owned plaintext.

    No automatic bot shutdown or task registration. Successful process checks are
    not a lease: the owner must keep the bot/watchdog stopped for the capture.
    Never use this collector with other database writers or external media mounts.
    """
    if not settings.allow_server_pause:
        raise MatrixBackupError("server_pause_not_authorized")
    published = False
    try:
        bot_guard()
        source = validate_path(settings.synapse_dir)
        bot = validate_path(settings.bot_store_dir)
        compose = validate_path(settings.compose_file)
        work = validate_path(settings.work_dir)
        repository = Path(__file__).resolve().parents[1]
        env_file = validate_path(settings.deployment_environment_file) if settings.deployment_environment_file else None
        roots = (source, bot, compose.parent)
        if (any(work.is_relative_to(root) or root.is_relative_to(work) for root in roots)
                or work.is_relative_to(repository)):
            raise MatrixBackupError("overlapping_snapshot_paths")
        if not compose.is_file() or not (source / "homeserver.yaml").is_file() or not (bot / "matrix_store.db").is_file():
            raise MatrixBackupError("snapshot_source_missing")
        if env_file is not None and not env_file.is_file():
            raise MatrixBackupError("deployment_environment_missing")
        runtime_payload = None
        runtime_source = repository / ".env"
        runtime_source_digest = None
        if settings.include_bot_runtime:
            # Fingerprint only; source values never enter logs or the archive.
            if runtime_loader is load_bot_runtime_for_backup and runtime_source.is_file():
                runtime_source_digest = file_digest(validate_path(runtime_source))
            runtime = runtime_loader()
            if validate_path(Path(runtime.store_path)) != bot:
                raise MatrixBackupError("bot_runtime_store_mismatch")
            runtime_payload = bot_runtime_payload(runtime)
        secure_directory(work)
        with FileLock(str(work / "snapshot.lock"), timeout=0):
            synapse = inspect_container(settings.synapse_container, runner)
            postgres = inspect_container(settings.postgres_container, runner)
            if not synapse["running"] or not postgres["running"]:
                raise MatrixBackupError("snapshot_containers_not_running")
            mounts = [m for m in synapse["mounts"] if m.get("Destination") == "/data"]
            if len(mounts) != 1 or mounts[0].get("Type") != "bind" or validate_path(Path(mounts[0]["Source"])) != source:
                raise MatrixBackupError("synapse_mount_mismatch")
            config = read_synapse_capture_config(settings.synapse_container, runner)
            database = config["database"]
            if not isinstance(database, str) or not database or "\x00" in database:
                raise MatrixBackupError("invalid_synapse_database")
            host = config["database_host"]
            common_networks = set(synapse["networks"]) & set(postgres["networks"])
            aliases = {alias for name in common_networks
                       for alias in (postgres["networks"][name].get("Aliases") or [])}
            if config["database_port"] != 5432 or host not in aliases:
                raise MatrixBackupError("postgres_target_mismatch")
            signing = data_relative_path(config["signing_key_path"])
            media = data_relative_path(config["media_store_path"])
            if media != Path("media_store"):
                raise MatrixBackupError("unsupported_synapse_media_layout")
            if not validate_path(source / signing).is_file() or not validate_path(source / media).is_dir():
                raise MatrixBackupError("synapse_key_or_media_missing")
            with tempfile.TemporaryDirectory(prefix="capture-", dir=work) as directory:
                snapshot = Path(directory)
                # Attempt restart after any stop attempt, including an ambiguous failure.
                try:
                    docker_command(["stop", "--time", "60", settings.synapse_container], runner)
                    if inspect_container(settings.synapse_container, runner)["running"]:
                        raise MatrixBackupError("synapse_not_stopped")
                    bot_guard()
                    dump = ('export PGPASSWORD="$POSTGRES_PASSWORD"; '
                            'exec pg_dump --format=custom --no-password --username="$POSTGRES_USER" --dbname="$1"')
                    docker_command(["exec", settings.postgres_container, "sh", "-c", dump,
                                    "astakos-snapshot", database], runner, output=snapshot / "postgres.dump")
                    roles = ('export PGPASSWORD="$POSTGRES_PASSWORD"; '
                             'exec pg_dumpall --roles-only --no-password --username="$POSTGRES_USER"')
                    docker_command(["exec", settings.postgres_container, "sh", "-c", roles], runner,
                                   output=snapshot / "postgres-roles.sql")
                    copy_frozen_tree(source, snapshot / "synapse")
                    copy_frozen_tree(bot, snapshot / "bot-store")
                    copy_frozen_file(compose, snapshot / "compose.yaml")
                    if env_file is not None:
                        copy_frozen_file(env_file, snapshot / "deployment.env")
                    if runtime_payload is not None:
                        if bot_runtime_payload(runtime_loader()) != runtime_payload:
                            raise MatrixBackupError("bot_runtime_changed")
                        if runtime_loader is load_bot_runtime_for_backup:
                            current_digest = file_digest(runtime_source) if runtime_source.is_file() else None
                            if current_digest != runtime_source_digest:
                                raise MatrixBackupError("bot_runtime_changed")
                        runtime_file = snapshot / "bot-runtime.json"
                        with runtime_file.open("x", encoding="utf-8") as stream:
                            json.dump(runtime_payload, stream)
                            stream.flush()
                            os.fsync(stream.fileno())
                        if os.name != "nt":
                            runtime_file.chmod(0o600)
                    bot_guard()
                    if inspect_container(settings.synapse_container, runner)["running"]:
                        raise MatrixBackupError("synapse_restarted_during_capture")
                    metadata = {
                        "format_version": 1, "consistent": True,
                        "captured_at": datetime.now(timezone.utc).isoformat(),
                        "signing_key": (Path("synapse") / signing).as_posix(),
                        "images": {"synapse": synapse["image"], "postgres": postgres["image"]},
                        "capture_mode": "synapse-paused_bot-stopped_native-pg-dump",
                    }
                    (snapshot / "snapshot.json").write_text(json.dumps(metadata), encoding="utf-8")
                    snapshot_inventory(snapshot)
                finally:
                    try:
                        docker_command(["start", settings.synapse_container], runner)
                        if not inspect_container(settings.synapse_container, runner)["running"]:
                            raise MatrixBackupError("synapse_restart_failed")
                    except Exception:
                        raise MatrixBackupError("synapse_restart_failed") from None
                published = True
                yield snapshot
    except Timeout:
        raise MatrixBackupError("snapshot_already_running") from None
    except MatrixBackupError:
        raise
    except Exception:
        if published:
            raise
        raise MatrixBackupError("snapshot_capture_failed") from None
