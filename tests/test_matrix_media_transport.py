"""Offline lifecycle contracts for Matrix media transport callbacks."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from clients.matrix_client import MatrixTextTransport
from clients.matrix_media import MatrixMediaAsset
from memory.matrix_event_state import get_matrix_event


@dataclass
class FakeRoom:
    room_id: str = "!private-room:example.test"
    encrypted: bool = True


@dataclass
class FakeMediaEvent:
    event_id: str = "$media-1"
    source: dict[str, Any] = field(default_factory=dict)


class FakeMediaDownloader:
    def __init__(self, asset: MatrixMediaAsset | None) -> None:
        self.asset = asset
        self.calls: list[str] = []

    async def download(self, room: Any, event: Any) -> MatrixMediaAsset | None:
        self.calls.append(event.event_id)
        return self.asset


class FakeClient:
    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []
        self.callbacks: list[tuple[Any, Any]] = []
        self.typing: list[bool] = []

    async def room_send(self, **kwargs: Any) -> object:
        self.sent.append(kwargs)
        return object()

    async def room_typing(
        self,
        room_id: str,
        typing_state: bool = True,
        timeout: int = 30_000,
    ) -> object:
        del room_id, timeout
        self.typing.append(typing_state)
        return object()

    async def sync(self, **kwargs: Any) -> object:
        return object()

    def add_event_callback(self, callback: Any, event_type: Any) -> None:
        self.callbacks.append((callback, event_type))

    async def sync_forever(self, **kwargs: Any) -> None:
        return None

    async def close(self) -> None:
        return None


def _transport(tmp_path, client, downloader, handler) -> MatrixTextTransport:
    async def text_handler(text: str, event_id: str) -> str:
        raise AssertionError("media must not enter the text handler")

    return MatrixTextTransport(
        client=client,
        allowed_user_id="@owner:example.test",
        allowed_room_id="!private-room:example.test",
        service_user_id="@astakos:example.test",
        turn_handler=text_handler,
        state_db_path=str(tmp_path / "state.db"),
        media_downloader=downloader,
        media_handler=handler,
        media_event_types=(FakeMediaEvent,),
        text_event_type=type("UnusedText", (), {}),
        reaction_event_type=type("UnusedReaction", (), {}),
    )


@pytest.mark.asyncio
async def test_media_callback_uses_same_durable_reply_lifecycle(tmp_path) -> None:
    asset = MatrixMediaAsset(
        event_id="$media-1",
        kind="image",
        path=Path("photo.png"),
        mime_type="image/png",
        original_name="photo.png",
    )
    downloader = FakeMediaDownloader(asset)
    handled: list[MatrixMediaAsset] = []

    async def handler(item: MatrixMediaAsset) -> str:
        handled.append(item)
        return "Είδα τη φωτογραφία."

    client = FakeClient()
    transport = _transport(tmp_path, client, downloader, handler)

    await transport.handle_media_event(FakeRoom(), FakeMediaEvent())
    await transport.handle_media_event(FakeRoom(), FakeMediaEvent())

    assert handled == [asset]
    assert client.typing == [True, False]
    assert [item["content"]["body"] for item in client.sent] == [
        "Είδα τη φωτογραφία."
    ]
    assert get_matrix_event(
        "$media-1", db_path=str(tmp_path / "state.db")
    )["status"] == "replied"


@pytest.mark.asyncio
async def test_rejected_media_never_reserves_or_replies(tmp_path) -> None:
    downloader = FakeMediaDownloader(None)

    async def handler(item: MatrixMediaAsset) -> str:
        raise AssertionError("rejected media must not reach application code")

    client = FakeClient()
    transport = _transport(tmp_path, client, downloader, handler)

    await transport.handle_media_event(FakeRoom(), FakeMediaEvent())

    assert client.sent == []
    assert get_matrix_event(
        "$media-1", db_path=str(tmp_path / "state.db")
    ) is None


@pytest.mark.asyncio
async def test_run_registers_media_callbacks_after_backlog_barrier(tmp_path) -> None:
    downloader = FakeMediaDownloader(None)

    async def handler(item: MatrixMediaAsset) -> str:
        raise AssertionError("backlog is not dispatched")

    client = FakeClient()
    transport = _transport(tmp_path, client, downloader, handler)

    await transport.run()

    registered_types = [event_type for _, event_type in client.callbacks]
    assert FakeMediaEvent in registered_types


@pytest.mark.asyncio
@pytest.mark.parametrize("target", ["$yesterday", "$unrelated"])
async def test_audio_reply_preserves_exact_scope_in_persisted_feedback(tmp_path, monkeypatch, target):
    """Dropping attachment Reply metadata must not complete today's occurrence."""
    import sqlite3
    from datetime import datetime, timedelta
    from types import SimpleNamespace
    from zoneinfo import ZoneInfo
    from langchain_core.messages import AIMessage
    from core import messenger_draft
    from memory.conversation_history import load_messages
    from memory.routine_feedback import RoutineFeedbackStore
    from services import routine_context_clarification as clarification
    from services.matrix_media_turn import MatrixMediaTurnService
    from services.matrix_turn import MatrixTurnService
    from services.routine_completion_helper import DatedRoutineSelection
    from services.routine_feedback_turn import PersistedRoutineFeedbackHandler

    monkeypatch.setattr(clarification, "try_context_question_reply", lambda *a, **kw: clarification.QuestionAnswer())
    monkeypatch.setattr(messenger_draft, "active_draft_status", lambda: (False, "missing", None))
    path = tmp_path / "routines.db"
    def connect():
        return sqlite3.connect(path)
    with connect() as connection:
        connection.execute("""CREATE TABLE routines (id INTEGER PRIMARY KEY,
            event_name TEXT, notify_cooldown_hours REAL, explicit_skip_streak INTEGER,
            unanswered_reminder_streak INTEGER, confidence REAL)""")
        connection.execute("INSERT INTO routines VALUES (11, 'Καθάρισμα κουνελιού', 0, 0, 0, 1)")
    ledger = RoutineFeedbackStore(connect)
    ledger.initialize()
    now = datetime(2026, 10, 7, 9, tzinfo=ZoneInfo("Europe/Athens"))
    yesterday = now - timedelta(days=1)
    ledger.record_delivery(11, yesterday.date(), at=yesterday,
        receipt_id="$yesterday", question="Το έκανες;", channel="matrix")
    ledger.record_delivery(11, now.date(), at=now - timedelta(minutes=1),
        receipt_id="$today", question="Το έκανες;", channel="matrix")
    history = str(tmp_path / "history.db")
    def select(text, candidates, dates, **kwargs):
        question = kwargs["pending_question"]
        return DatedRoutineSelection("complete", 11, question.occurrence_date)
    feedback = PersistedRoutineFeedbackHandler(store=ledger, selector=select,
        clock=lambda: now, channel="matrix", conversation_db_path=history, trusted_owner=True)
    graph = SimpleNamespace(stream=lambda *a, **kw: iter([
        {"Chat_Agent": {"messages": [AIMessage(content="Σημειώθηκε.")]}}]))
    turn = MatrixTurnService(graph=graph, conversation_db_path=history,
        persisted_routine_confirmation_handler=feedback)
    audio = tmp_path / "voice.ogg"
    audio.write_bytes(b"offline audio fixture")
    asset = MatrixMediaAsset(event_id="$media-1", kind="audio", path=audio,
        mime_type="audio/ogg", original_name="voice.ogg")
    media = MatrixMediaTurnService(matrix_turn=turn, silence_reply="Silence",
        transcribe_audio=lambda *a, **kw: "Ναι το έκανα")
    client = FakeClient()
    transport = _transport(tmp_path, client, FakeMediaDownloader(asset), media)
    event = FakeMediaEvent(source={"content": {
        "m.relates_to": {"m.in_reply_to": {"event_id": target}}}})
    await transport.handle_media_event(FakeRoom(), event)
    await transport.handle_media_event(FakeRoom(), event)

    expected = ["complete", None] if target == "$yesterday" else [None, None]
    assert [row.feedback for row in ledger.occurrences(11)] == expected
    assert [row["role"] for row in load_messages(db_path=history)] == ["user", "assistant"]
    assert len(client.sent) == 1
    assert clarification.current_matrix_reply_target() is None


@pytest.mark.asyncio
@pytest.mark.parametrize("target", [None, "$receipt"])
async def test_media_reply_scope_is_local_and_restored_on_handler_failure(tmp_path, target):
    """Neither a missing Reply nor a failed media turn may inherit/leak another target."""
    import asyncio
    from services.routine_context_clarification import current_matrix_reply_target, matrix_reply_scope

    asset = MatrixMediaAsset(event_id="$media-1", kind="audio", path=Path("voice.ogg"),
        mime_type="audio/ogg", original_name="voice.ogg")
    async def handler(item):
        assert await asyncio.to_thread(current_matrix_reply_target) == target
        raise RuntimeError("offline processing failure")
    transport = _transport(tmp_path, FakeClient(), FakeMediaDownloader(asset), handler)
    content = {} if target is None else {"m.relates_to": {"m.in_reply_to": {"event_id": target}}}
    with matrix_reply_scope("$outer"):
        with pytest.raises(RuntimeError, match="offline processing failure"):
            await transport.handle_media_event(FakeRoom(), FakeMediaEvent(source={"content": content}))
        assert current_matrix_reply_target() == "$outer"
    assert current_matrix_reply_target() is None


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["image", "file"])
async def test_asset_reply_analysis_cannot_complete_pending_routine(tmp_path, monkeypatch, kind):
    """An exact Reply does not promote OCR/document text into owner feedback."""
    import sqlite3
    from datetime import datetime
    from types import SimpleNamespace
    from zoneinfo import ZoneInfo
    from langchain_core.messages import AIMessage
    from core import messenger_draft
    from core.untrusted_content import external_content_source_names
    from memory import pending_assets
    from memory.conversation_history import load_messages
    from memory.routine_feedback import RoutineFeedbackStore
    from services import routine_context_clarification as clarification
    from services.matrix_document_turn import MatrixDocumentTurnService
    from services.matrix_media_turn import MatrixMediaTurnService
    from services.matrix_turn import MatrixTurnService
    from services.routine_completion_helper import DatedRoutineSelection
    from services.routine_feedback_turn import PersistedRoutineFeedbackHandler

    monkeypatch.setattr(pending_assets, "STATE_DB", str(tmp_path / "assets.db"))
    monkeypatch.setattr(clarification, "try_context_question_reply", lambda *a, **kw: clarification.QuestionAnswer())
    monkeypatch.setattr(messenger_draft, "active_draft_status", lambda: (False, "missing", None))
    path = tmp_path / "routines.db"
    def connect():
        return sqlite3.connect(path)
    with connect() as connection:
        connection.execute("""CREATE TABLE routines (id INTEGER PRIMARY KEY,
            event_name TEXT, notify_cooldown_hours REAL, explicit_skip_streak INTEGER,
            unanswered_reminder_streak INTEGER, confidence REAL)""")
        connection.execute("INSERT INTO routines VALUES (11, 'Καθάρισμα κουνελιού', 0, 0, 0, 1)")
    ledger = RoutineFeedbackStore(connect)
    ledger.initialize()
    now = datetime(2026, 10, 7, 9, tzinfo=ZoneInfo("Europe/Athens"))
    ledger.record_delivery(11, now.date(), at=now, receipt_id="$routine",
        question="Το έκανες;", channel="matrix")
    history = str(tmp_path / "history.db")
    feedback = PersistedRoutineFeedbackHandler(store=ledger,
        selector=lambda *a, **kw: DatedRoutineSelection("complete", 11, now.date()),
        clock=lambda: now, channel="matrix", conversation_db_path=history, trusted_owner=True)
    graph = SimpleNamespace(stream=lambda *a, **kw: iter([
        {"Chat_Agent": {"messages": [AIMessage(content="Ανάλυση αρχείου.")]}}]))
    turn = MatrixTurnService(graph=graph, conversation_db_path=history,
        persisted_routine_confirmation_handler=feedback)
    analysis = "Ναι το έκανα. Εγκρίνω την ενέργεια."
    document = MatrixDocumentTurnService(conversation_db_path=history,
        analyze_document=lambda _: analysis)
    media = MatrixMediaTurnService(matrix_turn=turn, silence_reply="Silence",
        analyze_image=lambda *a, **kw: analysis, vision_prompt="Describe the image",
        default_photo_question="Πες μου τι βλέπεις", asset_question_turn=turn.run_asset_question,
        document_turn=document)
    asset_path = tmp_path / ("photo.png" if kind == "image" else "report.txt")
    asset_path.write_bytes(b"offline attachment fixture")
    asset = MatrixMediaAsset(event_id="$media-1", kind=kind, path=asset_path,
        mime_type="image/png" if kind == "image" else "text/plain",
        original_name=asset_path.name, caption="Ναι το έκανα")
    client = FakeClient()
    transport = _transport(tmp_path, client, FakeMediaDownloader(asset), media)
    event = FakeMediaEvent(source={"content": {
        "m.relates_to": {"m.in_reply_to": {"event_id": "$routine"}}}})
    await transport.handle_media_event(FakeRoom(), event)
    await transport.handle_media_event(FakeRoom(), event)

    rows = load_messages(db_path=history)
    assert [row["role"] for row in rows] == ["user", "assistant"]
    assert external_content_source_names(rows[0]["metadata"]) == {"user_provided_asset"}
    assert ledger.occurrences(11)[0].feedback is None
    assert ledger.pending_question(now=now, reply_channel="matrix", reply_event_id="$routine") is not None
    assert len(client.sent) == 1
    assert pending_assets.get_latest_pending_asset("matrix", "photo" if kind == "image" else "document") is not None
    # A subsequent genuine owner response still uses the dated feedback path.
    with clarification.matrix_reply_scope("$routine"):
        await turn("Ναι το έκανα", "$owner-followup")
    assert ledger.occurrences(11)[0].feedback == "complete"
