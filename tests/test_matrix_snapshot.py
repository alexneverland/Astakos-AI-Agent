"""Synthetic collector tests: no real Docker, credentials or user stores."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from services import matrix_snapshot as capture
from services import matrix_backup as backup


@pytest.fixture
def environment(tmp_path, monkeypatch):
    """Emulate stopped bot state and a bind-mounted Synapse data directory."""
    project = tmp_path / "deployment"
    source = project / "synapse"
    (source / "media_store").mkdir(parents=True)
    (source / "homeserver.yaml").write_text("fixture config")
    (source / "server.signing.key").write_text("fixture signing")
    (source / "media_store" / "image.bin").write_bytes(b"fixture media")
    project.joinpath("compose.yaml").write_text("services: {}")
    bot = tmp_path / "bot"
    bot.mkdir()
    (bot / "matrix_store.db").write_bytes(b"fixture DB")
    (bot / "matrix_store.db-wal").write_bytes(b"fixture WAL")
    settings = capture.SnapshotSettings(source, bot, project / "compose.yaml", tmp_path / "work",
                                        "fixture-synapse", "fixture-postgres", allow_server_pause=True)
    monkeypatch.setattr(capture, "secure_directory", lambda path: path.mkdir(exist_ok=True))
    state = {"running": True, "calls": [], "fail": None, "restart_fail": False}
    def runner(args, **kwargs):
        state["calls"].append(args)
        if args[1] == "inspect":
            server = args[-1] == "fixture-synapse"
            data = {"running": state["running"] if server else True,
                    "image": "fixture:1" if server else "fixture:17",
                    "networks": {"fixture-network": {"Aliases": ["fixture-synapse" if server else "fixture-postgres"]}},
                    "mounts": [{"Destination": "/data", "Source": str(source), "Type": "bind"}] if server else []}
            return subprocess.CompletedProcess(args, 0, json.dumps(data).encode())
        if args[1] == "stop":
            state["running"] = False
            return subprocess.CompletedProcess(args, 1 if state["fail"] == "stop" else 0)
        if args[1] == "start":
            state["running"] = not state["restart_fail"]
            return subprocess.CompletedProcess(args, 1 if state["restart_fail"] else 0)
        if args[1] == "exec" and args[2] == "fixture-synapse":
            return subprocess.CompletedProcess(args, 0, json.dumps({"database": "actual_fixture_database",
                "database_host": "fixture-postgres", "database_port": 5432,
                "signing_key_path": "/data/server.signing.key", "media_store_path": "/data/media_store"}).encode())
        if "pg_dumpall" in " ".join(args):
            kwargs["stdout"].write(b"-- fixture roles")
            return subprocess.CompletedProcess(args, 1 if state["fail"] == "roles" else 0)
        if "pg_dump" in " ".join(args):
            kwargs["stdout"].write(b"PGDMPfixture" if state["fail"] != "bad_dump" else b"bad")
            return subprocess.CompletedProcess(args, 1 if state["fail"] == "dump" else 0)
        pytest.fail(f"Unexpected mocked command: {args[:2]}")
    return settings, state, runner


def quiet() -> None:
    """Fixture bot is stopped; no process discovery runs in tests."""


def runtime_fixture(settings):
    """Synthetic canonical resolver result; never import live configuration."""
    from types import SimpleNamespace
    return SimpleNamespace(
        homeserver_url="https://fixture.invalid", service_user_id="@bot:fixture",
        access_token="fixture-token", allowed_user_id="@owner:fixture",
        allowed_device_ids=("FIXTURE",), room_id="!room:fixture",
        store_path=settings.bot_store_dir, media_path=settings.bot_store_dir.parent / "media",
        unrelated_provider_key="must-not-export",
    )


def test_bot_runtime_opt_in_exports_only_matrix_fields(environment):
    from dataclasses import replace
    settings, state, runner = environment
    with capture.captured_snapshot(replace(settings, include_bot_runtime=True), runner=runner,
                                   bot_guard=quiet, runtime_loader=lambda: runtime_fixture(settings)) as snapshot:
        payload = json.loads((snapshot / "bot-runtime.json").read_text())
        assert payload["settings"]["MATRIX_ACCESS_TOKEN"] == "fixture-token"
        assert payload["settings"]["ASTAKOS_EXTERNAL_CHANNEL"] == "matrix"
        assert len(payload["settings"]) == 9
        assert "must-not-export" not in json.dumps(payload)
        assert "bot-runtime.json" in backup.snapshot_inventory(snapshot)
    assert not snapshot.exists() and state["running"]


def test_bot_runtime_opt_out_never_resolves_credentials(environment):
    settings, state, runner = environment
    with capture.captured_snapshot(settings, runner=runner, bot_guard=quiet,
                                   runtime_loader=lambda: pytest.fail("No credential discovery")) as snapshot:
        assert not (snapshot / "bot-runtime.json").exists()


def test_bot_runtime_wrong_store_fails_before_pause(environment):
    from dataclasses import replace
    settings, state, runner = environment
    runtime = runtime_fixture(settings)
    runtime.store_path = settings.bot_store_dir.parent / "other"
    with pytest.raises(backup.MatrixBackupError, match="bot_runtime_store_mismatch"):
        with capture.captured_snapshot(replace(settings, include_bot_runtime=True), runner=runner,
                                       bot_guard=quiet, runtime_loader=lambda: runtime):
            pytest.fail("Wrong crypto store")
    assert not any(cmd[1] == "stop" for cmd in state["calls"])


def test_bot_runtime_changed_token_restarts_and_cleans(environment):
    from dataclasses import replace
    settings, state, runner = environment
    calls = 0
    def loader():
        nonlocal calls
        calls += 1
        runtime = runtime_fixture(settings)
        if calls > 1:
            runtime.access_token = "changed-fixture-token"
        return runtime
    with pytest.raises(backup.MatrixBackupError, match="bot_runtime_changed"):
        with capture.captured_snapshot(replace(settings, include_bot_runtime=True), runner=runner,
                                       bot_guard=quiet, runtime_loader=loader):
            pytest.fail("Changed settings")
    assert state["running"] and not list(settings.work_dir.glob("capture-*"))


def test_bot_runtime_error_is_sanitized_before_pause(environment):
    from dataclasses import replace
    settings, state, runner = environment
    def loader():
        raise ValueError("SECRET fixture-token")
    with pytest.raises(backup.MatrixBackupError) as error:
        with capture.captured_snapshot(replace(settings, include_bot_runtime=True), runner=runner,
                                       bot_guard=quiet, runtime_loader=loader):
            pytest.fail("Invalid settings")
    assert "SECRET" not in str(error.value)
    assert not any(cmd[1] == "stop" for cmd in state["calls"])


def test_bot_guard_filters_python_not_coordinating_shell(monkeypatch):
    """A shell containing restart instructions is not itself a running bot."""
    monkeypatch.setattr(capture.os, "name", "nt")
    def runner(args, **kwargs):
        assert "Name -match" in args[-1]
        return subprocess.CompletedProcess(args, 0)
    monkeypatch.setattr(capture.subprocess, "run", runner)
    capture.assert_bot_stopped()


@pytest.mark.parametrize("database_key", ["dbname", "database"])
def test_config_reader_resolves_postgres_database_argument(database_key):
    """Run the exact container program on synthetic YAML through a fake file API."""
    import io
    import sys
    import types
    values = {"database": {"name": "psycopg2", "args": {
        database_key: "fixture-db", "host": "fixture-postgres"}},
        "signing_key_path": "/data/key"}
    def runner(args, **kwargs):
        previous = sys.modules.get("yaml")
        sys.modules["yaml"] = types.SimpleNamespace(safe_load=lambda stream: values)
        output = io.StringIO()
        try:
            exec(args[-1], {"open": lambda *a, **kw: io.StringIO("fixture"),
                            "print": lambda value: output.write(value)})
        finally:
            if previous is None:
                del sys.modules["yaml"]
            else:
                sys.modules["yaml"] = previous
        return subprocess.CompletedProcess(args, 0, output.getvalue().encode())
    assert capture.read_synapse_capture_config("fixture", runner)["database"] == "fixture-db"


def test_snapshot_is_complete_restores_server_and_cleans_plaintext(environment):
    settings, state, runner = environment
    with capture.captured_snapshot(settings, runner=runner, bot_guard=quiet) as snapshot:
        assert state["running"]
        assert (snapshot / "bot-store/matrix_store.db-wal").read_bytes() == b"fixture WAL"
        assert (snapshot / "synapse/media_store/image.bin").read_bytes() == b"fixture media"
        assert backup.snapshot_inventory(snapshot)
        metadata = json.loads((snapshot / "snapshot.json").read_text())
        assert metadata["consistent"] is True
        dump_command = next(cmd for cmd in state["calls"] if "pg_dump --format" in " ".join(cmd))
        assert dump_command[-1] == "actual_fixture_database"
    assert not snapshot.exists()
    assert not list(settings.work_dir.glob("capture-*"))


@pytest.mark.parametrize("failure", ["stop", "dump", "roles", "bad_dump"])
def test_failed_capture_restarts_server_and_never_yields(environment, failure):
    settings, state, runner = environment
    state["fail"] = failure
    with pytest.raises(backup.MatrixBackupError):
        with capture.captured_snapshot(settings, runner=runner, bot_guard=quiet):
            pytest.fail("Failed snapshot must never be published")
    assert state["running"]
    assert not list(settings.work_dir.glob("capture-*"))


def test_restart_failure_blocks_snapshot(environment):
    settings, state, runner = environment
    state["restart_fail"] = True
    with pytest.raises(backup.MatrixBackupError, match="synapse_restart_failed"):
        with capture.captured_snapshot(settings, runner=runner, bot_guard=quiet):
            pytest.fail("No snapshot after failed recovery")


def test_bot_running_blocks_every_docker_command(environment):
    settings, state, runner = environment
    def active():
        raise backup.MatrixBackupError("matrix_bot_or_watchdog_running")
    with pytest.raises(backup.MatrixBackupError):
        with capture.captured_snapshot(settings, runner=runner, bot_guard=active):
            pytest.fail("No active-store capture")
    assert not state["calls"]


def test_runtime_pause_requires_explicit_flag(environment):
    from dataclasses import replace
    settings, state, runner = environment
    with pytest.raises(backup.MatrixBackupError, match="server_pause_not_authorized"):
        with capture.captured_snapshot(replace(settings, allow_server_pause=False), runner=runner, bot_guard=quiet):
            pytest.fail("No implicit pause")
    assert not state["calls"]


def test_unsupported_media_mount_refuses_to_pause(environment):
    settings, state, runner = environment
    def incorrect(args, **kwargs):
        result = runner(args, **kwargs)
        if args[1] == "exec" and args[2] == "fixture-synapse":
            payload = json.loads(result.stdout)
            payload["media_store_path"] = "/other/media"
            result.stdout = json.dumps(payload).encode()
        return result
    with pytest.raises(backup.MatrixBackupError):
        with capture.captured_snapshot(settings, runner=incorrect, bot_guard=quiet):
            pytest.fail("No missing media")
    assert not any(cmd[1] == "stop" for cmd in state["calls"])


def test_consumer_failure_cleans_snapshot_after_server_restarted(environment):
    settings, state, runner = environment
    with pytest.raises(RuntimeError, match="consumer"):
        with capture.captured_snapshot(settings, runner=runner, bot_guard=quiet) as snapshot:
            raise RuntimeError("consumer")
    assert state["running"]
    assert not snapshot.exists()


def test_copy_failure_does_not_echo_private_error(environment, monkeypatch):
    settings, state, runner = environment
    def fail(*args):
        raise OSError("SENSITIVE config contents")
    monkeypatch.setattr(capture, "copy_frozen_tree", fail)
    with pytest.raises(backup.MatrixBackupError) as error:
        with capture.captured_snapshot(settings, runner=runner, bot_guard=quiet):
            pytest.fail("No partial snapshot")
    assert "SENSITIVE" not in str(error.value)
    assert state["running"]


def test_bot_restart_during_capture_invalidates_snapshot(environment):
    settings, state, runner = environment
    calls = 0
    def guard():
        nonlocal calls
        calls += 1
        if calls > 1:
            raise backup.MatrixBackupError("matrix_bot_or_watchdog_running")
    with pytest.raises(backup.MatrixBackupError):
        with capture.captured_snapshot(settings, runner=runner, bot_guard=guard):
            pytest.fail("No restarted bot snapshot")
    assert state["running"]


def test_copy_rejects_source_changes(tmp_path, monkeypatch):
    source = tmp_path / "source"
    source.mkdir()
    source.joinpath("file").write_bytes(b"before")
    original = capture.shutil.copyfile
    def changed(src, dst):
        original(src, dst)
        Path(src).write_bytes(b"after")
    monkeypatch.setattr(capture.shutil, "copyfile", changed)
    with pytest.raises(backup.MatrixBackupError):
        capture.copy_frozen_tree(source, tmp_path / "dest")


def test_deployment_file_mutation_is_rejected(tmp_path, monkeypatch):
    """Configuration inputs use the same consistency boundary as store files."""
    source = tmp_path / "compose.yaml"
    source.write_bytes(b"before")
    original = capture.shutil.copyfile
    def changed(src, dst):
        original(src, dst)
        Path(src).write_bytes(b"after")
    monkeypatch.setattr(capture.shutil, "copyfile", changed)
    with pytest.raises(backup.MatrixBackupError, match="snapshot_source_changed"):
        capture.copy_frozen_file(source, tmp_path / "copied.yaml")


def test_wrong_mount_refuses_to_pause(environment):
    """A valid but unrelated deployment path cannot select the wrong instance."""
    settings, state, runner = environment
    def wrong_mount(args, **kwargs):
        result = runner(args, **kwargs)
        if args[1] == "inspect" and args[-1] == "fixture-synapse":
            payload = json.loads(result.stdout)
            payload["mounts"][0]["Source"] = str(settings.bot_store_dir)
            result.stdout = json.dumps(payload).encode()
        return result
    with pytest.raises(backup.MatrixBackupError, match="synapse_mount_mismatch"):
        with capture.captured_snapshot(settings, runner=wrong_mount, bot_guard=quiet):
            pytest.fail("Wrong deployment must not be captured")
    assert not any(cmd[1] == "stop" for cmd in state["calls"])


def test_other_postgres_host_refuses_to_pause(environment):
    """Same database name does not establish that it is the configured server."""
    settings, state, runner = environment
    def wrong_host(args, **kwargs):
        result = runner(args, **kwargs)
        if args[1] == "exec" and args[2] == "fixture-synapse":
            payload = json.loads(result.stdout)
            payload["database_host"] = "other-postgres"
            result.stdout = json.dumps(payload).encode()
        return result
    with pytest.raises(backup.MatrixBackupError, match="postgres_target_mismatch"):
        with capture.captured_snapshot(settings, runner=wrong_host, bot_guard=quiet):
            pytest.fail("Wrong database server")
    assert not any(cmd[1] == "stop" for cmd in state["calls"])


@pytest.mark.parametrize("upload", [False, True])
def test_cli_capture_packages_after_restart_and_removes_plaintext(environment, monkeypatch, capsys, upload):
    """Exercise CLI -> real collector -> real packager with outbound boundaries mocked."""
    import tarfile
    from scripts import backup_matrix as cli
    settings, state, runner = environment
    recipient = settings.work_dir.parent / "recipient.txt"
    recipient.write_text("age1fixture", encoding="ascii")
    mkdir = lambda path: path.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(capture, "secure_directory", mkdir)
    monkeypatch.setattr(backup, "secure_directory", mkdir)
    monkeypatch.setattr(cli, "captured_snapshot", lambda options: capture.captured_snapshot(
        options, runner=runner, bot_guard=quiet, runtime_loader=lambda: runtime_fixture(settings)))
    def encrypt(args, **kwargs):
        assert state["running"]
        with tarfile.open(args[-1]) as archive:
            assert "bot-store/matrix_store.db-wal" in archive.getnames()
            assert "postgres.dump" in archive.getnames()
            payload = json.load(archive.extractfile("bot-runtime.json"))
            assert payload["settings"]["MATRIX_ACCESS_TOKEN"] == "fixture-token"
            assert "must-not-export" not in json.dumps(payload)
            manifest = json.load(archive.extractfile("backup-manifest.json"))
            assert "bot-runtime.json" in manifest["files"]
        Path(args[args.index("-o") + 1]).write_bytes(b"age-encryption.org/v1\nfixture")
        return subprocess.CompletedProcess(args, 0)
    monkeypatch.setattr(cli, "create_encrypted_backup", lambda options, **kwargs:
                        backup.create_encrypted_backup(options, runner=encrypt, **kwargs))
    sent = []
    def send(path, folder, digest):
        assert state["running"] and path.suffix == ".age"
        assert b"fixture-token" not in path.read_bytes()
        sent.append(path)
        return "fixture-id"
    monkeypatch.setattr(cli, "upload_encrypted_artifact", send)
    arguments = ["--capture", "--include-bot-runtime", "--allow-server-pause", "--synapse-dir", str(settings.synapse_dir),
                 "--bot-store-dir", str(settings.bot_store_dir), "--compose-file", str(settings.compose_file),
                 "--synapse-container", settings.synapse_container, "--postgres-container", settings.postgres_container,
                 "--work-dir", str(settings.work_dir), "--recipient-file", str(recipient)]
    if upload:
        arguments += ["--upload", "--drive-folder", "fixture-folder"]
    assert cli.main(arguments) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == ("uploaded" if upload else "encrypted_local_only")
    assert Path(result["artifact"]).exists()
    assert len(sent) == int(upload)
    assert not list((settings.work_dir / "capture").glob("capture-*"))
    assert not list((settings.work_dir / "packages").glob("stage-*"))


def test_cli_capture_without_pause_flag_has_no_side_effects(monkeypatch):
    """Missing explicit pause consent is an argument error before capture."""
    from scripts import backup_matrix as cli
    monkeypatch.setattr(cli, "captured_snapshot", lambda *args: pytest.fail("No implicit capture"))
    with pytest.raises(SystemExit) as result:
        cli.main(["--capture"])
    assert result.value.code == 2


def test_cli_runtime_capture_requires_capture_mode():
    """Prepared snapshots cannot trigger unrelated credential discovery."""
    from scripts import backup_matrix as cli
    with pytest.raises(SystemExit) as result:
        cli.main(["--retry-artifact", "fixture.age", "--include-bot-runtime"])
    assert result.value.code == 2
