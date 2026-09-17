"""Offline contracts for Matrix background memory and behavior hooks."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from langchain_core.messages import AIMessage
import pytest

from clients.matrix_media import MatrixMediaAsset


@pytest.fixture(autouse=True)
def isolate_matrix_routine_confirmations(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep composition tests away from the user's live routine database."""
    import services.matrix_routine_completion as routine_completion

    monkeypatch.setattr(
        routine_completion,
        "process_pending_routine_confirmation",
        lambda user_text: None,
    )


@dataclass
class CapturingQueue:
    tasks: list[tuple[Any, tuple[Any, ...]]] = field(default_factory=list)

    def __call__(self, function, *args) -> None:
        self.tasks.append((function, args))


def test_persisted_matrix_user_schedules_behavioral_intake(monkeypatch) -> None:
    import services.matrix_background as background

    scheduled: list[dict[str, Any]] = []
    slow = CapturingQueue()
    monkeypatch.setattr(
        background,
        "schedule_persisted_user_intake",
        lambda **kwargs: scheduled.append(kwargs) or True,
    )
    hooks = background.MatrixBackgroundHooks(
        enqueue_fast_task=CapturingQueue(),
        enqueue_slow_task=slow,
    )

    hooks.on_user_persisted(
        {
            "rowid": 42,
            "channel": "matrix",
            "metadata": {"transport": "matrix", "matrix_event_id": "$evt"},
        }
    )

    assert scheduled == [
        {
            "rowid": 42,
            "metadata": {"transport": "matrix", "matrix_event_id": "$evt"},
            "enqueue_slow_task": slow,
        }
    ]


def test_completed_matrix_exchange_queues_all_existing_background_pipelines(
    monkeypatch,
) -> None:
    import services.matrix_background as background

    fast = CapturingQueue()
    slow = CapturingQueue()
    hooks = background.MatrixBackgroundHooks(
        enqueue_fast_task=fast,
        enqueue_slow_task=slow,
    )

    hooks.on_exchange_completed(
        "τι κάνουμε σήμερα;",
        "Έχουμε δύο δουλειές.",
        "Home_Agent",
        "matrix",
    )

    assert [(fn.__name__, args) for fn, args in fast.tasks] == [
        (
            "log_exchange",
            (
                "τι κάνουμε σήμερα;",
                "Έχουμε δύο δουλειές.",
                "Home_Agent",
                "matrix",
            ),
        ),
        (
            "update_working_memory",
            ("τι κάνουμε σήμερα;", "Έχουμε δύο δουλειές."),
        ),
        (
            "run_slow_memory_pipeline",
            (
                "τι κάνουμε σήμερα;",
                "Έχουμε δύο δουλειές.",
                "Home_Agent",
                "matrix",
                slow,
            ),
        ),
    ]
    assert [(fn.__name__, args) for fn, args in slow.tasks] == [
        (
            "run_followup_pipeline",
            (
                "τι κάνουμε σήμερα;",
                "Έχουμε δύο δουλειές.",
                "Home_Agent",
                "matrix",
            ),
        ),
        (
            "extract_and_update_context_flags",
            ("τι κάνουμε σήμερα;", "Έχουμε δύο δουλειές."),
        ),
    ]


def test_background_hooks_reject_non_matrix_channel() -> None:
    import pytest

    from services.matrix_background import MatrixBackgroundHooks

    hooks = MatrixBackgroundHooks(
        enqueue_fast_task=CapturingQueue(),
        enqueue_slow_task=CapturingQueue(),
    )

    with pytest.raises(ValueError, match="matrix"):
        hooks.on_exchange_completed("user", "assistant", "Chat_Agent", "telegram")


def test_matrix_turn_factory_cannot_omit_background_hooks(tmp_path) -> None:
    from services.matrix_background import build_matrix_turn_service
    from services.behavioral_event_scheduler import _reset_scheduler_for_tests

    class FakeGraph:
        def stream(self, state, config):
            del state, config
            yield {"Chat_Agent": {"messages": [AIMessage(content="απάντηση")]}}

    fast = CapturingQueue()
    slow = CapturingQueue()
    _reset_scheduler_for_tests()
    try:
        service = build_matrix_turn_service(
            graph=FakeGraph(),
            conversation_db_path=str(tmp_path / "conversation.db"),
            enqueue_fast_task=fast,
            enqueue_slow_task=slow,
        )

        import asyncio

        assert asyncio.run(service("μήνυμα", "$factory-event")) == "απάντηση"
        assert any(function.__name__ == "log_exchange" for function, _ in fast.tasks)
        assert any(
            function.__name__ == "run_background_behavioral_event_intake"
            for function, _ in slow.tasks
        )
        assert any(function.__name__ == "run_followup_pipeline" for function, _ in slow.tasks)
    finally:
        _reset_scheduler_for_tests()


@pytest.mark.asyncio
async def test_matrix_channel_factory_connects_photo_to_next_text_turn(
    tmp_path, monkeypatch
) -> None:
    from services.matrix_background import build_matrix_channel_services
    from services.behavioral_event_scheduler import _reset_scheduler_for_tests
    import memory.pending_assets as pending_assets

    class FakeGraph:
        def __init__(self) -> None:
            self.states = []

        def stream(self, state, config):
            self.states.append(state)
            yield {"Chat_Agent": {"messages": [AIMessage(content="Είναι σφήκα.")]}}

    class FakeMemory:
        def save(self, **kwargs) -> None:
            raise AssertionError("no archive confirmation occurred")

    graph = FakeGraph()
    monkeypatch.setattr(pending_assets, "STATE_DB", str(tmp_path / "state.db"))
    image_path = tmp_path / "photo.png"
    image_path.write_bytes(b"png")
    asset = MatrixMediaAsset(
        "$photo",
        "image",
        image_path,
        "image/png",
        "photo.png",
    )
    _reset_scheduler_for_tests()
    try:
        services = build_matrix_channel_services(
            graph=graph,
            conversation_db_path=str(tmp_path / "conversation.db"),
            enqueue_fast_task=CapturingQueue(),
            enqueue_slow_task=CapturingQueue(),
            analyze_image=lambda data, *, mime_type, prompt: "μεγάλη σφήκα",
            transcribe_audio=lambda data, *, mime_type: "φωνητικό",
            analyze_document=lambda item: "έγγραφο",
            memory_store=FakeMemory(),
        )

        assert "Φωτό" in await services.media_handler(asset)
        assert await services.text_handler("Τι είναι;", "$question") == "Είναι σφήκα."
        assert len(graph.states) == 1
        assert "USER_UPLOADED_PHOTO" in str(graph.states[0]["messages"][-1].content)
    finally:
        _reset_scheduler_for_tests()


@pytest.mark.asyncio
async def test_matrix_channel_factory_applies_voice_mode_to_normal_turns(
    tmp_path, monkeypatch
) -> None:
    from clients.matrix_client import MatrixReply
    from services.matrix_background import build_matrix_channel_services
    from services.behavioral_event_scheduler import _reset_scheduler_for_tests
    import memory.pending_assets as pending_assets

    class FakeGraph:
        def stream(self, state, config):
            yield {"Chat_Agent": {"messages": [AIMessage(content="απάντηση")]}}

    class FakeMemory:
        def save(self, **kwargs) -> None:
            return None

    monkeypatch.setattr(pending_assets, "STATE_DB", str(tmp_path / "state.db"))
    _reset_scheduler_for_tests()
    try:
        services = build_matrix_channel_services(
            graph=FakeGraph(),
            conversation_db_path=str(tmp_path / "conversation.db"),
            enqueue_fast_task=CapturingQueue(),
            enqueue_slow_task=CapturingQueue(),
            analyze_image=lambda data, *, mime_type, prompt: "image",
            transcribe_audio=lambda data, *, mime_type: "audio transcript",
            analyze_document=lambda item: "document",
            memory_store=FakeMemory(),
        )

        toggle = await services.text_handler("/voice", "$toggle")
        reply = await services.text_handler("γεια", "$text")

        assert isinstance(toggle, MatrixReply) and toggle.mode == "text"
        assert reply == MatrixReply("απάντηση", "voice")
    finally:
        _reset_scheduler_for_tests()


@pytest.mark.asyncio
async def test_matrix_channel_factory_finalizes_session_for_exact_end_command(
    tmp_path,
) -> None:
    from services.matrix_background import build_matrix_channel_services
    from services.behavioral_event_scheduler import _reset_scheduler_for_tests

    finalized: list[str] = []
    delegated: list[str] = []

    def command_handler(text: str) -> str | None:
        delegated.append(text)
        return "delegated"

    _reset_scheduler_for_tests()
    try:
        services = build_matrix_channel_services(
            conversation_db_path=str(tmp_path / "conversation.db"),
            enqueue_fast_task=CapturingQueue(),
            enqueue_slow_task=CapturingQueue(),
            command_handler=command_handler,
            session_finalizer=lambda *, channel: finalized.append(channel),
            memory_store=object(),
        )

        reply = await services.text_handler(" /END ", "$end")
        nearby_reply = await services.text_handler("/ending", "$nearby")

        assert "αρχειοθετήθηκε" in reply.text
        assert reply.mode == "text"
        assert finalized == ["matrix"]
        assert nearby_reply.text == "delegated"
        assert delegated == ["/ending"]
    finally:
        _reset_scheduler_for_tests()


@pytest.mark.asyncio
async def test_matrix_channel_factory_returns_story_with_encrypted_attachments(
    tmp_path,
) -> None:
    from clients.matrix_client import MatrixReply
    from services.matrix_background import build_matrix_channel_services
    from services.behavioral_event_scheduler import _reset_scheduler_for_tests

    first = tmp_path / "one.png"
    second = tmp_path / "two.png"
    first.write_bytes(b"one")
    second.write_bytes(b"two")
    story_calls: list[tuple[str, str]] = []

    def make_story(theme: str, characters: str):
        story_calls.append((theme, characters))
        return {"story": "Μια ιστορία.", "images": [str(first), str(second)]}

    _reset_scheduler_for_tests()
    try:
        services = build_matrix_channel_services(
            conversation_db_path=str(tmp_path / "conversation.db"),
            enqueue_fast_task=CapturingQueue(),
            enqueue_slow_task=CapturingQueue(),
            command_handler=lambda text: f"delegated:{text}",
            story_maker=make_story,
            memory_store=object(),
        )

        reply = await services.text_handler("/story δάσος | Άλεξ", "$story")
        nearby = await services.text_handler("/storybook", "$nearby")

        assert isinstance(reply, MatrixReply)
        assert "Μια ιστορία." in reply.text
        assert reply.attachment_paths == (str(first), str(second))
        assert story_calls == [("δάσος", "Άλεξ")]
        assert nearby.text == "delegated:/storybook"
    finally:
        _reset_scheduler_for_tests()


@pytest.mark.asyncio
async def test_matrix_channel_factory_exposes_location_application_handler(
    tmp_path,
) -> None:
    from services.matrix_background import build_matrix_channel_services
    from services.behavioral_event_scheduler import _reset_scheduler_for_tests

    recorded: list[tuple[float, float, bool]] = []

    def record(latitude: float, longitude: float, *, live_update: bool):
        recorded.append((latitude, longitude, live_update))
        return None if live_update else "location saved"

    _reset_scheduler_for_tests()
    try:
        services = build_matrix_channel_services(
            conversation_db_path=str(tmp_path / "conversation.db"),
            enqueue_fast_task=CapturingQueue(),
            enqueue_slow_task=CapturingQueue(),
            record_location=record,
            memory_store=object(),
        )

        assert await services.location_handler(40.64, 22.94, False) == "location saved"
        assert await services.location_handler(40.65, 22.95, True) is None
        assert recorded == [(40.64, 22.94, False), (40.65, 22.95, True)]
    finally:
        _reset_scheduler_for_tests()
