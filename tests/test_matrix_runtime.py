"""Offline contract tests for the production Matrix process wiring."""

from __future__ import annotations

import signal
from types import SimpleNamespace

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


def test_matrix_runtime_uses_portable_sqlite_trust_store() -> None:
    """Matrix IDs with colons never become Windows trust-state filenames."""
    from nio.store import SqliteStore

    from clients.matrix_bot import _build_client_config

    config = _build_client_config()

    assert config.store is SqliteStore
    assert config.store_name == "matrix_store.db"


def test_matrix_shutdown_drains_queues_and_closes_persistent_memory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A watched restart preserves queued memory work and closes Chroma cleanly."""
    from clients.matrix_bot import _graceful_shutdown_shared_runtime

    calls: list[str] = []

    class FakeEvent:
        def set(self) -> None:
            calls.append("shutdown")

    class FakeQueue:
        def __init__(self, name: str) -> None:
            self.name = name

        def join(self) -> None:
            calls.append(self.name)

    runtime = SimpleNamespace(
        shutdown_event=FakeEvent(),
        _external_worker_stop_event=FakeEvent(),
        fast_queue=FakeQueue("fast"),
        slow_queue=FakeQueue("slow"),
    )
    monkeypatch.setattr(
        "memory.vector_store.close_vector_store",
        lambda: calls.append("close_vector_store"),
    )
    monkeypatch.setattr(
        "services.session_end.finalize_session",
        lambda *, channel: calls.append(f"finalize:{channel}"),
    )

    result = _graceful_shutdown_shared_runtime(
        runtime,
        channel="matrix",
        drain_timeout=1,
    )

    assert result is True
    assert calls[0] == "shutdown"
    assert set(calls[1:3]) == {"fast", "slow"}
    assert calls[3:] == ["shutdown", "finalize:matrix", "close_vector_store"]


def test_matrix_shutdown_finishes_work_queued_behind_active_memory_task(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A watched restart must not abandon work waiting behind an active task."""
    import queue
    import threading

    from clients import telegram_bot as runtime
    from clients.matrix_bot import _graceful_shutdown_shared_runtime

    started = threading.Event()
    release = threading.Event()
    completed: list[str] = []
    fast_queue: queue.Queue = queue.Queue()
    monkeypatch.setattr(runtime, "fast_queue", fast_queue)
    monkeypatch.setattr(runtime, "slow_queue", queue.Queue())
    monkeypatch.setattr(runtime, "shutdown_event", threading.Event())
    worker_stop_event = threading.Event()
    monkeypatch.setattr(runtime, "_external_worker_stop_event", worker_stop_event)
    monkeypatch.setattr(runtime, "_external_scheduler_thread", None, raising=False)
    monkeypatch.setattr(
        "services.session_end.finalize_session",
        lambda *, channel: completed.append(f"finalize:{channel}"),
    )
    monkeypatch.setattr(
        "memory.vector_store.close_vector_store",
        lambda: completed.append("close"),
    )

    def first_task() -> None:
        started.set()
        assert release.wait(timeout=2)
        completed.append("first")

    def second_task() -> None:
        completed.append("second")

    fast_queue.put((first_task, ()))
    fast_queue.put((second_task, ()))
    worker = threading.Thread(
        target=runtime.fast_queue_worker,
        args=(worker_stop_event,),
        daemon=True,
    )
    worker.start()
    assert started.wait(timeout=1)

    result: list[bool] = []
    cleanup = threading.Thread(
        target=lambda: result.append(
            _graceful_shutdown_shared_runtime(runtime, channel="matrix", drain_timeout=1)
        ),
        daemon=True,
    )
    cleanup.start()
    assert runtime.shutdown_event.wait(timeout=1)
    release.set()
    cleanup.join(timeout=2)
    worker_stop_event.set()
    worker.join(timeout=3)

    assert result == [True]
    assert completed == ["first", "second", "finalize:matrix", "close"]


def test_matrix_shutdown_does_not_archive_while_queue_is_still_busy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A timed-out drain must not claim success or close storage under a writer."""
    import threading

    from clients.matrix_bot import _graceful_shutdown_shared_runtime

    release = threading.Event()
    archive_calls: list[str] = []

    class BusyQueue:
        def join(self) -> None:
            release.wait(timeout=2)

    class EmptyQueue:
        def join(self) -> None:
            return None

    runtime = SimpleNamespace(
        shutdown_event=threading.Event(),
        _external_worker_stop_event=threading.Event(),
        fast_queue=BusyQueue(),
        slow_queue=EmptyQueue(),
    )
    monkeypatch.setattr(
        "services.session_end.finalize_session",
        lambda *, channel: archive_calls.append("finalize"),
    )
    monkeypatch.setattr(
        "memory.vector_store.close_vector_store",
        lambda: archive_calls.append("close"),
    )

    try:
        result = _graceful_shutdown_shared_runtime(
            runtime,
            channel="matrix",
            drain_timeout=0.05,
        )
    finally:
        release.set()

    assert result is False
    assert archive_calls == []
    assert not runtime._external_worker_stop_event.is_set()


def test_shutdown_waits_for_auto_summary_save_before_closing_store(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    """A summary spawned by the final exchange must persist before Chroma closes."""
    import json
    import queue
    import threading

    from memory import session_memory
    from services.external_runtime_shutdown import drain_and_archive_external_runtime

    exchanges = [
        {
            "id": f"exchange-{index}",
            "time": "10:00",
            "channel": "matrix",
            "agent": "Chat_Agent",
            "user": f"question {index}",
            "ai": f"answer {index}",
        }
        for index in range(20)
    ]
    save_started = threading.Event()
    allow_save = threading.Event()
    store_closed = threading.Event()
    persisted: list[str] = []
    marked: list[str] = []
    working_memory = tmp_path / "working_memory.txt"
    working_memory.write_text("active context", encoding="utf-8")

    class Response:
        text = json.dumps({
            "date": "2026-09-23 10:00",
            "summary": "Conversation archived",
            "pending": [],
            "next_session_hint": "",
            "mood": "neutral",
        })

    def save_summary(**kwargs: object) -> bool:
        save_started.set()
        if not allow_save.wait(timeout=3):
            return False
        persisted.append(str(kwargs["session_text"]))
        return True

    def mark_summarized(ids: list[str]) -> None:
        marked.extend(ids)
        exchanges.clear()

    monkeypatch.setattr(session_memory, "_auto_summary_lock", threading.Lock())
    monkeypatch.setattr(session_memory, "SESSION_LOGS", [])
    monkeypatch.setattr(session_memory, "is_summarizing", False)
    monkeypatch.setattr(
        session_memory,
        "load_unsummarized_exchanges",
        lambda limit=200: exchanges[:limit],
    )
    monkeypatch.setattr(session_memory, "safe_gemini_call", lambda prompt: Response())
    monkeypatch.setattr(session_memory, "append_exchange", lambda **kwargs: {"id": "last"})
    monkeypatch.setattr(session_memory.memory, "save", save_summary)
    monkeypatch.setattr(session_memory, "mark_exchanges_summarized", mark_summarized)
    monkeypatch.setattr(session_memory.bus, "emit", lambda *args, **kwargs: None)
    monkeypatch.setattr("config.WORKING_MEMORY_FILE", working_memory)
    monkeypatch.setattr("memory.vector_store.close_vector_store", store_closed.set)

    runtime = SimpleNamespace(
        shutdown_event=threading.Event(),
        _external_worker_stop_event=threading.Event(),
        fast_queue=queue.Queue(),
        slow_queue=queue.Queue(),
    )
    session_memory.log_exchange("last question", "last answer", "Chat_Agent", channel="matrix")
    assert save_started.wait(timeout=1)

    results: list[bool] = []
    cleanup = threading.Thread(
        target=lambda: results.append(
            drain_and_archive_external_runtime(runtime, channel="matrix", drain_timeout=2)
        ),
        daemon=True,
    )
    cleanup.start()
    try:
        assert runtime.shutdown_event.wait(timeout=1)
        assert not store_closed.wait(timeout=0.1)
    finally:
        allow_save.set()
        cleanup.join(timeout=3)
        assert session_memory._auto_summary_lock.acquire(timeout=3)
        session_memory._auto_summary_lock.release()

    assert results == [True]
    assert len(persisted) == 1
    assert len(marked) == 20
    assert store_closed.is_set()
    assert working_memory.read_text(encoding="utf-8") != "active context"


def test_shutdown_skips_archive_and_close_when_auto_summary_exceeds_drain_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A stuck auto-summary must not race with finalization or Chroma close."""
    import queue
    import threading

    from memory import session_memory
    from services.external_runtime_shutdown import drain_and_archive_external_runtime

    summary_lock = threading.Lock()
    summary_lock.acquire()
    monkeypatch.setattr(session_memory, "_auto_summary_lock", summary_lock)
    archive_calls: list[str] = []
    monkeypatch.setattr(
        "services.session_end.finalize_session",
        lambda *, channel: archive_calls.append("finalize"),
    )
    monkeypatch.setattr(
        "memory.vector_store.close_vector_store",
        lambda: archive_calls.append("close"),
    )
    runtime = SimpleNamespace(
        shutdown_event=threading.Event(),
        _external_worker_stop_event=threading.Event(),
        fast_queue=queue.Queue(),
        slow_queue=queue.Queue(),
    )

    try:
        success = drain_and_archive_external_runtime(
            runtime, channel="matrix", drain_timeout=0.05
        )
    finally:
        summary_lock.release()

    assert success is False
    assert archive_calls == []
    assert not runtime._external_worker_stop_event.is_set()


@pytest.mark.asyncio
async def test_matrix_shutdown_notifies_before_and_after_archiving(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Element receives the same visible archive lifecycle as Telegram."""
    from clients.matrix_bot import _archive_matrix_session_with_notifications

    calls: list[tuple[str, object]] = []

    async def send_text(message: str) -> str:
        calls.append(("send", message))
        return "$event"

    def cleanup(runtime: object, *, channel: str) -> bool:
        calls.append(("cleanup", (runtime, channel)))
        return True

    monkeypatch.setattr("core.i18n.t", lambda key: key)
    runtime = object()

    await _archive_matrix_session_with_notifications(
        send_text=send_text,
        runtime=runtime,
        cleanup=cleanup,
    )

    assert calls == [
        ("send", "clients.matrix_bot.session_archiving"),
        ("cleanup", (runtime, "matrix")),
        ("send", "clients.matrix_bot.session_archived"),
    ]


def test_matrix_shutdown_signal_requests_clean_sync_exit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The watchdog signal stops sync without cancelling archive notifications."""
    from clients.matrix_bot import _graceful_shutdown_signals

    callbacks: list[object] = []
    installed: list[tuple[int, object]] = []

    class FakeLoop:
        def call_soon_threadsafe(self, callback: object) -> None:
            callbacks.append(callback)

    previous_handler = object()
    monkeypatch.setattr(signal, "getsignal", lambda signal_number: previous_handler)
    monkeypatch.setattr(
        signal,
        "signal",
        lambda signal_number, handler: installed.append((signal_number, handler)),
    )

    requested: list[str] = []
    watched_signals = [signal.SIGTERM, signal.SIGINT]
    if hasattr(signal, "SIGBREAK"):
        watched_signals.append(signal.SIGBREAK)
    watched_signals = tuple(watched_signals)
    with _graceful_shutdown_signals(
        loop=FakeLoop(),
        request_shutdown=lambda: requested.append("stop"),
        signal_numbers=watched_signals,
    ):
        active_handler = installed[0][1]
        active_handler(watched_signals[-1], None)
        callbacks[-1]()

    assert requested == ["stop"]
    signal_count = len(watched_signals)
    assert installed[:signal_count] == [
        (signal_number, active_handler) for signal_number in watched_signals
    ]
    assert installed[signal_count:] == [
        (signal_number, previous_handler) for signal_number in watched_signals
    ]


@pytest.mark.asyncio
async def test_matrix_shutdown_reports_failed_archive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Element never claims that persistence succeeded when cleanup failed."""
    from clients.matrix_bot import _archive_matrix_session_with_notifications

    messages: list[str] = []

    async def send_text(message: str) -> str:
        messages.append(message)
        return "$event"

    monkeypatch.setattr("core.i18n.t", lambda key: key)

    await _archive_matrix_session_with_notifications(
        send_text=send_text,
        runtime=object(),
        cleanup=lambda runtime, *, channel: False,
    )

    assert messages == [
        "clients.matrix_bot.session_archiving",
        "clients.matrix_bot.session_archive_failed",
    ]


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
