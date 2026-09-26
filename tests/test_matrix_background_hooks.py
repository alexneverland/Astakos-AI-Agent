"""Offline contracts for Matrix background memory and behavior hooks."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from langchain_core.messages import AIMessage
import pytest

from clients.matrix_media import MatrixMediaAsset
from memory.conversation_history import append_message, load_messages_after_rowid
from memory.working_memory import CapabilityObservation


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


def test_matrix_capability_followup_is_queued_with_persisted_turn_id(tmp_path) -> None:
    """Only a completed ordinary Matrix turn schedules one classified proposal."""
    from services.matrix_background import MatrixBackgroundHooks

    slow = CapturingQueue()
    hooks = MatrixBackgroundHooks(
        enqueue_fast_task=CapturingQueue(),
        enqueue_slow_task=slow,
        conversation_db_path=str(tmp_path / "conversation.db"),
    )
    hooks.on_exchange_completed(
        "Can you do this?", "I cannot yet.", "Chat_Agent", "matrix",
        correlation_rowid=42,
    )
    queued = [(fn.__name__, args) for fn, args in slow.tasks]
    assert queued.count((
        "run_matrix_capability_followup",
        ("Can you do this?", "I cannot yet.", "Chat_Agent", 42,
         str(tmp_path / "conversation.db")),
    )) == 1

    external = CapturingQueue()
    external_hooks = MatrixBackgroundHooks(
        enqueue_fast_task=CapturingQueue(), enqueue_slow_task=external,
    )
    external_hooks.on_exchange_completed(
        "Summarize this file", "", "Chat_Agent", "matrix",
        external_content_sources=["user_provided_asset"], correlation_rowid=42,
    )
    assert not any(fn.__name__ == "run_matrix_capability_followup" for fn, _ in external.tasks)


@pytest.mark.parametrize("kind", ["missing_capability", "existing_behavior_bug"])
def test_matrix_capability_followup_sends_once_and_persists_proposal(
    tmp_path, monkeypatch, kind
) -> None:
    """A classified proposal uses the Matrix transport and becomes visible in history."""
    import services.matrix_background as background
    from core.i18n import t
    from services.external_delivery import DeliveryReceipt

    db_path = str(tmp_path / "conversation.db")
    user = append_message(role="user", content="My request", channel="matrix", db_path=db_path)
    append_message(role="assistant", content="Original answer", channel="matrix", db_path=db_path)
    description = "Astakos cannot do X" if kind == "missing_capability" else "partner state is wrong"
    monkeypatch.setattr(
        background, "update_capabilities_from_exchange",
        lambda *args, **kwargs: CapabilityObservation(kind, description), raising=False,
    )
    monkeypatch.setattr(background, "record_missing_capability", lambda description: "inserted")

    class FakeRouter:
        sent: list[tuple[str, str]] = []

        def send_text_to(self, channel, text):
            self.sent.append((channel, text))
            return DeliveryReceipt(channel="matrix", external_id="$proposal")

    router = FakeRouter()
    monkeypatch.setattr(background, "external_delivery_router", router, raising=False)
    background.run_matrix_capability_followup(
        "My request", "Original answer", "Chat_Agent", user["rowid"], db_path
    )

    assert len(router.sent) == 1
    assert router.sent[0][0] == "matrix"
    expected_prefix = (
        t("core.approval.capability_proposal_prefix") if kind == "missing_capability"
        else t("core.approval.bug_proposal_prefix")
    )
    assert router.sent[0][1].startswith(expected_prefix)
    if kind == "existing_behavior_bug":
        assert t("core.approval.draft_markers")[0] not in router.sent[0][1]
    saved = load_messages_after_rowid(after_rowid=user["rowid"], channel="matrix", db_path=db_path)
    assert saved[-1]["content"] == router.sent[0][1]
    assert saved[-1]["agent"] == "Dev_Agent"
    assert saved[-1]["metadata"]["matrix_event_id"] == "$proposal"

    background.run_matrix_capability_followup(
        "My request", "Original answer", "Chat_Agent", user["rowid"], db_path
    )
    assert len(router.sent) == 1


def test_matrix_capability_followup_does_not_reclassify_bug_diagnosis(
    tmp_path, monkeypatch
) -> None:
    """A final diagnostic report must not trigger another Matrix bug offer."""
    import services.matrix_background as background
    from core.i18n import t

    db_path = str(tmp_path / "conversation.db")
    user = append_message(role="user", content="please investigate", channel="matrix", db_path=db_path)

    def fail_classifier(*args, **kwargs):
        raise AssertionError("diagnosis must not be classified again")

    monkeypatch.setattr(background, "update_capabilities_from_exchange", fail_classifier)
    background.run_matrix_capability_followup(
        "please investigate", f"{t('core.approval.bug_diagnosis_prefix')} the timestamp is stale.",
        "Dev_Agent", user["rowid"], db_path,
    )


def test_matrix_capability_followup_skips_stale_turn_and_uncertain_classification(
    tmp_path, monkeypatch
) -> None:
    """A newer owner turn or non-actionable observation cannot send a proposal."""
    import services.matrix_background as background

    db_path = str(tmp_path / "conversation.db")
    user = append_message(role="user", content="First", channel="matrix", db_path=db_path)
    append_message(role="user", content="Newer", channel="matrix", db_path=db_path)

    class FailRouter:
        def send_text_to(self, *args, **kwargs):
            raise AssertionError("unexpected Matrix delivery")

    monkeypatch.setattr(background, "external_delivery_router", FailRouter(), raising=False)
    monkeypatch.setattr(
        background, "update_capabilities_from_exchange",
        lambda *args, **kwargs: CapabilityObservation("missing_capability", "Astakos cannot do X"),
        raising=False,
    )
    background.run_matrix_capability_followup("First", "answer", "Chat_Agent", user["rowid"], db_path)

    newer = append_message(role="user", content="Third", channel="matrix", db_path=db_path)
    monkeypatch.setattr(
        background, "update_capabilities_from_exchange", lambda *args, **kwargs: None,
        raising=False,
    )
    background.run_matrix_capability_followup("Third", "answer", "Chat_Agent", newer["rowid"], db_path)


def test_matrix_capability_followup_skips_user_turn_arriving_during_classification(
    tmp_path, monkeypatch
) -> None:
    """A slow classifier cannot send a proposal after a newer owner message."""
    import services.matrix_background as background

    db_path = str(tmp_path / "conversation.db")
    user = append_message(role="user", content="First", channel="matrix", db_path=db_path)

    def classify(*args, **kwargs):
        append_message(role="user", content="Newer", channel="matrix", db_path=db_path)
        return CapabilityObservation("existing_behavior_bug", "partner flag is wrong")

    class FailRouter:
        def send_text_to(self, *args, **kwargs):
            raise AssertionError("stale Matrix proposal was sent")

    monkeypatch.setattr(background, "update_capabilities_from_exchange", classify)
    monkeypatch.setattr(background, "external_delivery_router", FailRouter())
    background.run_matrix_capability_followup("First", "answer", "Chat_Agent", user["rowid"], db_path)


def test_matrix_capability_followup_retries_missing_capability_after_failed_send(
    tmp_path, monkeypatch
) -> None:
    """A failed send leaves the real capability registry uncommitted for retry."""
    import sqlite3
    from unittest.mock import MagicMock

    import memory.working_memory as working_memory
    import services.matrix_background as background
    from services.external_delivery import DeliveryReceipt

    db_path = str(tmp_path / "conversation.db")
    capability_db = tmp_path / "capabilities.db"
    with sqlite3.connect(capability_db) as conn:
        conn.execute(
            "CREATE TABLE capabilities (id INTEGER PRIMARY KEY, type TEXT NOT NULL, "
            "description TEXT NOT NULL UNIQUE, created_at TEXT DEFAULT CURRENT_TIMESTAMP)"
        )
    monkeypatch.setattr(working_memory, "STATE_DB", str(capability_db))
    monkeypatch.setattr(
        working_memory, "is_semantically_duplicate",
        lambda description, existing, **kwargs: description in existing,
    )
    monkeypatch.setattr(
        "services.gemini.safe_gemini_call",
        MagicMock(return_value=MagicMock(text='{"issue_type":"missing_capability","cannot_do":"Astakos cannot do X"}')),
    )

    user = append_message(role="user", content="Need X", channel="matrix", db_path=db_path)

    class Router:
        fail = True
        sent: list[str] = []

        def send_text_to(self, channel, text):
            if self.fail:
                raise RuntimeError("offline transport failure")
            self.sent.append(text)
            return DeliveryReceipt(channel="matrix", external_id="$proposal")

    router = Router()
    monkeypatch.setattr(background, "external_delivery_router", router)
    with pytest.raises(RuntimeError, match="offline transport failure"):
        background.run_matrix_capability_followup(
            "Need X", "cannot do X", "Chat_Agent", user["rowid"], db_path
        )
    assert working_memory._load_capabilities()["cannot_do"] == []

    router.fail = False
    background.run_matrix_capability_followup(
        "Need X", "cannot do X", "Chat_Agent", user["rowid"], db_path
    )
    assert len(router.sent) == 1
    assert working_memory._load_capabilities()["cannot_do"] == ["Astakos cannot do X"]

    newer = append_message(role="user", content="Need X again", channel="matrix", db_path=db_path)
    background.run_matrix_capability_followup(
        "Need X again", "cannot do X", "Chat_Agent", newer["rowid"], db_path
    )
    assert len(router.sent) == 1


def test_matrix_capability_followup_does_not_persist_failed_delivery(
    tmp_path, monkeypatch
) -> None:
    """A failed encrypted send must not appear as a delivered proposal in history."""
    import services.matrix_background as background

    db_path = str(tmp_path / "conversation.db")
    user = append_message(role="user", content="Need help", channel="matrix", db_path=db_path)
    monkeypatch.setattr(
        background, "update_capabilities_from_exchange",
        lambda *args, **kwargs: CapabilityObservation("existing_behavior_bug", "partner flag is wrong"),
    )

    class FailingRouter:
        def send_text_to(self, channel, text):
            raise RuntimeError("offline transport failure")

    monkeypatch.setattr(background, "external_delivery_router", FailingRouter())
    with pytest.raises(RuntimeError, match="offline transport failure"):
        background.run_matrix_capability_followup(
            "Need help", "answer", "Chat_Agent", user["rowid"], db_path
        )
    assert load_messages_after_rowid(
        after_rowid=user["rowid"], channel="matrix", db_path=db_path
    ) == []


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
        assert any(
            function.__name__ == "run_matrix_capability_followup"
            for function, _ in slow.tasks
        )
    finally:
        _reset_scheduler_for_tests()


@pytest.mark.asyncio
async def test_matrix_channel_factory_comments_on_photo_then_keeps_followup_context(
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

        immediate_reply = await services.media_handler(asset)
        assert immediate_reply.startswith("Είναι σφήκα.")
        assert pending_assets.looks_like_asset_confirmation_prompt(immediate_reply)
        followup_reply = await services.text_handler("Τι είναι;", "$question")
        assert getattr(followup_reply, "text", followup_reply) == "Είναι σφήκα."
        assert len(graph.states) == 2
        assert "USER_UPLOADED_PHOTO" in str(graph.states[0]["messages"][-1].content)
        assert any(
            "USER_UPLOADED_PHOTO" in str(message.content)
            for message in graph.states[1]["messages"]
        )
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
async def test_matrix_help_reports_matrix_voice_mode_not_telegram(
    tmp_path, monkeypatch,
) -> None:
    """Matrix /help follows its own /voice toggle without changing Telegram state."""
    import clients.telegram_bot as telegram_bot
    from services.matrix_background import build_matrix_channel_services
    from services.behavioral_event_scheduler import _reset_scheduler_for_tests

    monkeypatch.setattr(telegram_bot, "voice_mode_enabled", False)
    _reset_scheduler_for_tests()
    try:
        services = build_matrix_channel_services(
            conversation_db_path=str(tmp_path / "conversation.db"),
            enqueue_fast_task=CapturingQueue(),
            enqueue_slow_task=CapturingQueue(),
            command_handler=telegram_bot.handle_external_admin_command,
            memory_store=object(),
        )

        off = await services.text_handler("/help", "$help-off")
        await services.text_handler("/voice", "$voice-on")
        on = await services.text_handler("/help", "$help-on")

        assert "✍️ OFF" in off.text
        assert "🔊 ON" in on.text
        assert "/confirm" not in on.text
        assert telegram_bot.voice_mode_enabled is False
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


@pytest.mark.asyncio
async def test_matrix_channel_factory_default_location_delivers_home_reminder(
    tmp_path, monkeypatch
) -> None:
    import config
    from services.matrix_background import build_matrix_channel_services
    from services.behavioral_event_scheduler import _reset_scheduler_for_tests
    from tests.test_reminders_sql import _make_reminders_db, _row_status

    state_db = tmp_path / "state.db"
    _make_reminders_db(
        str(state_db), [{"task": "Βγάλε το κουνέλι", "time": "loc:home"}]
    )
    monkeypatch.setattr(config, "STATE_DB", str(state_db))
    monkeypatch.setattr(config, "GPS_STORAGE_FILE", str(tmp_path / "gps.json"))
    monkeypatch.setattr(config, "HOME_COORDS", (40.0, 22.0))
    monkeypatch.setattr(config, "HOME_RADIUS_M", 150)
    delivered: list[tuple[str, str]] = []
    monkeypatch.setattr(
        "services.external_assistant_delivery.deliver_external_assistant_text",
        lambda message, *, agent: delivered.append((message, agent)),
    )

    _reset_scheduler_for_tests()
    try:
        services = build_matrix_channel_services(
            conversation_db_path=str(tmp_path / "conversation.db"),
            enqueue_fast_task=CapturingQueue(),
            enqueue_slow_task=CapturingQueue(),
            memory_store=object(),
        )
        await services.location_handler(40.0, 22.0, False)
    finally:
        _reset_scheduler_for_tests()

    assert len(delivered) == 1
    assert "Βγάλε το κουνέλι" in delivered[0][0]
    assert delivered[0][1] == "Reminder_Agent"
    assert _row_status(str(state_db), "Βγάλε το κουνέλι") == "done"
