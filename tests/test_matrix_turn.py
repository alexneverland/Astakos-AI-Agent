"""Offline contracts for Matrix turns through the Astakos graph."""

from __future__ import annotations

from typing import Any

import pytest
from langchain_core.messages import AIMessage, SystemMessage

from clients.matrix_client import MatrixReply
from memory.conversation_history import append_message, load_messages
from services.matrix_turn import MatrixTurnService


class FakeGraph:
    def __init__(self, reply: str = "Απάντηση από τον Αστακό") -> None:
        self.reply = reply
        self.states: list[dict[str, Any]] = []
        self.configs: list[dict[str, Any]] = []

    def stream(self, state: dict[str, Any], config: dict[str, Any]):
        self.states.append(state)
        self.configs.append(config)
        yield {"Chat_Agent": {"messages": [AIMessage(content=self.reply)]}}


@pytest.mark.asyncio
async def test_matrix_turn_uses_matrix_only_context_and_channel_state(tmp_path) -> None:
    db_path = str(tmp_path / "conversation.db")
    append_message(role="user", content="web context", channel="web", db_path=db_path)
    append_message(
        role="user", content="telegram context", channel="telegram", db_path=db_path
    )
    append_message(
        role="assistant", content="matrix previous", channel="matrix", db_path=db_path
    )
    graph = FakeGraph()
    selected_channels: list[str] = []
    service = MatrixTurnService(
        graph=graph,
        conversation_db_path=db_path,
        select_tool_channel=selected_channels.append,
    )

    reply = await service("καινούριο matrix μήνυμα", "$event-context")

    assert reply == "Απάντηση από τον Αστακό"
    assert selected_channels == ["matrix"]
    assert graph.states[0]["channel"] == "matrix"
    graph_text = [str(message.content) for message in graph.states[0]["messages"]]
    assert any("matrix previous" in text for text in graph_text)
    assert any("καινούριο matrix μήνυμα" in text for text in graph_text)
    assert all("web context" not in text for text in graph_text)
    assert all("telegram context" not in text for text in graph_text)


@pytest.mark.asyncio
async def test_matrix_turn_persists_both_sides_with_matrix_provenance(tmp_path) -> None:
    db_path = str(tmp_path / "conversation.db")
    graph = FakeGraph()
    persisted_users: list[dict[str, Any]] = []
    completed: list[tuple[str, str, str, str]] = []
    service = MatrixTurnService(
        graph=graph,
        conversation_db_path=db_path,
        on_user_persisted=persisted_users.append,
        on_exchange_completed=lambda user, ai, agent, channel: completed.append(
            (user, ai, agent, channel)
        ),
    )

    await service("δοκιμή", "$event-persist")

    stored = load_messages(db_path=db_path)
    assert [(item["channel"], item["role"], item["content"]) for item in stored] == [
        ("matrix", "user", "δοκιμή"),
        ("matrix", "assistant", "Απάντηση από τον Αστακό"),
    ]
    assert persisted_users[0]["channel"] == "matrix"
    assert persisted_users[0]["metadata"]["matrix_event_id"] == "$event-persist"
    assert completed == [
        ("δοκιμή", "Απάντηση από τον Αστακό", "Chat_Agent", "matrix")
    ]


@pytest.mark.asyncio
async def test_matrix_turn_returns_exactly_one_final_agent_reply(tmp_path) -> None:
    class MultiEventGraph(FakeGraph):
        def stream(self, state: dict[str, Any], config: dict[str, Any]):
            self.states.append(state)
            yield {"supervisor": {"messages": [AIMessage(content="internal")]}}
            yield {"Web_Agent": {"messages": [AIMessage(content="first")]}}
            yield {"tools": {"messages": []}}
            yield {"Web_Agent": {"messages": [AIMessage(content="final")]}}

    service = MatrixTurnService(
        graph=MultiEventGraph(),
        conversation_db_path=str(tmp_path / "conversation.db"),
    )

    assert await service("ψάξε κάτι", "$event-final") == "final"
    stored = load_messages(channel="matrix", db_path=str(tmp_path / "conversation.db"))
    assert [item["content"] for item in stored] == ["ψάξε κάτι", "final"]


@pytest.mark.asyncio
async def test_matrix_turn_extracts_generated_files_before_history_persistence(
    tmp_path,
) -> None:
    db_path = str(tmp_path / "conversation.db")
    graph = FakeGraph(
        reply=(
            "Έτοιμο το αρχείο.\n"
            "[CREATED_FILE: C:\\astakos_v2\\outputs\\report.pdf]"
        )
    )
    service = MatrixTurnService(graph=graph, conversation_db_path=db_path)

    reply = await service("φτιάξε αναφορά", "$event-file")

    assert reply == MatrixReply(
        "Έτοιμο το αρχείο.",
        attachment_paths=("C:\\astakos_v2\\outputs\\report.pdf",),
    )
    stored = load_messages(channel="matrix", db_path=db_path)
    assert stored[-1]["content"] == "Έτοιμο το αρχείο."
    assert "CREATED_FILE" not in stored[-1]["content"]


@pytest.mark.asyncio
async def test_matrix_turn_fails_closed_when_graph_has_no_user_reply(tmp_path) -> None:
    class EmptyGraph(FakeGraph):
        def stream(self, state: dict[str, Any], config: dict[str, Any]):
            yield {"supervisor": {"messages": []}}

    db_path = str(tmp_path / "conversation.db")
    service = MatrixTurnService(graph=EmptyGraph(), conversation_db_path=db_path)

    with pytest.raises(RuntimeError, match="no final reply"):
        await service("δοκιμή", "$event-empty")

    stored = load_messages(channel="matrix", db_path=db_path)
    assert [(item["role"], item["content"]) for item in stored] == [
        ("user", "δοκιμή")
    ]


@pytest.mark.asyncio
async def test_identical_matrix_text_with_distinct_event_ids_is_persisted_twice(tmp_path) -> None:
    db_path = str(tmp_path / "conversation.db")
    service = MatrixTurnService(graph=FakeGraph(), conversation_db_path=db_path)

    await service("ίδιο μήνυμα", "$event-a")
    await service("ίδιο μήνυμα", "$event-b")

    users = [
        item
        for item in load_messages(channel="matrix", db_path=db_path)
        if item["role"] == "user"
    ]
    assert [item["metadata"]["matrix_event_id"] for item in users] == [
        "$event-a",
        "$event-b",
    ]


@pytest.mark.asyncio
async def test_matrix_admin_command_bypasses_graph_and_conversation_history(
    tmp_path,
) -> None:
    db_path = str(tmp_path / "conversation.db")
    graph = FakeGraph()
    commands: list[str] = []
    service = MatrixTurnService(
        graph=graph,
        conversation_db_path=db_path,
        command_handler=lambda text: commands.append(text) or "scheduler status",
    )

    reply = await service("/status", "$event-command")

    assert reply == "scheduler status"
    assert commands == ["/status"]
    assert graph.states == []
    assert load_messages(channel="matrix", db_path=db_path) == []


@pytest.mark.asyncio
async def test_unhandled_matrix_command_continues_to_graph(tmp_path) -> None:
    graph = FakeGraph()
    service = MatrixTurnService(
        graph=graph,
        conversation_db_path=str(tmp_path / "conversation.db"),
        command_handler=lambda text: None,
    )

    reply = await service("/unknown", "$event-unknown-command")

    assert reply == "Απάντηση από τον Αστακό"
    assert len(graph.states) == 1


@pytest.mark.asyncio
async def test_matrix_routine_confirmation_is_resolved_before_graph(tmp_path) -> None:
    """A pending routine response mutates routine state before normal Matrix chat."""
    graph = FakeGraph()
    handled: list[str] = []
    completion_context = SystemMessage(content="trusted routine completion")
    service = MatrixTurnService(
        graph=graph,
        conversation_db_path=str(tmp_path / "conversation.db"),
        routine_confirmation_handler=lambda text: handled.append(text) or completion_context,
    )

    reply = await service("Το έκανα", "$event-routine-complete")

    assert reply == "Απάντηση από τον Αστακό"
    assert handled == ["Το έκανα"]
    assert completion_context in graph.states[0]["messages"]


@pytest.mark.asyncio
async def test_matrix_draft_offer_is_consumed_only_after_draft_tool_success(
    tmp_path,
    monkeypatch,
) -> None:
    """Matrix carries trusted draft authorization and consumes it after tool success."""
    from datetime import datetime

    from langchain_core.messages import ToolMessage
    import memory.routine_db as routine_db
    from services.matrix_routine_completion import MatrixRoutineDraftOffer

    class DraftGraph(FakeGraph):
        def stream(self, state: dict[str, Any], config: dict[str, Any]):
            self.states.append(state)
            self.configs.append(config)
            yield {
                "tools": {
                    "messages": [
                        ToolMessage(
                            content="Draft created successfully",
                            tool_call_id="draft-call",
                            name="relay_local_payload",
                        )
                    ]
                }
            }
            yield {"Chat_Agent": {"messages": [AIMessage(content=self.reply)]}}

    sent_at = datetime(2026, 9, 17, 8, 0)
    offer_context = SystemMessage(content="trusted draft offer")
    handled = MatrixRoutineDraftOffer(
        routine_id=5,
        sent_at=sent_at,
        event_name="Message Sofia",
        context=offer_context,
    )
    acknowledged: list[tuple[int, datetime]] = []
    import core.utils as core_utils
    monkeypatch.setattr(
        core_utils,
        "looks_like_terminal_messenger_draft_result",
        lambda text: text == "Draft created successfully",
    )
    monkeypatch.setattr(
        routine_db,
        "acknowledge_pending_draft_offer",
        lambda routine_id, offered_at: acknowledged.append((routine_id, offered_at)) or True,
    )
    graph = DraftGraph()
    service = MatrixTurnService(
        graph=graph,
        conversation_db_path=str(tmp_path / "conversation.db"),
        routine_confirmation_handler=lambda text: handled,
    )

    await service("Ετοίμασέ το", "$event-draft")

    assert graph.states[0]["routine_draft_offer_authorized"] is True
    assert offer_context in graph.states[0]["messages"]
    assert acknowledged == [(5, sent_at)]


@pytest.mark.asyncio
async def test_matrix_asset_question_persists_clean_question_with_model_only_context(
    tmp_path, monkeypatch
) -> None:
    import memory.pending_assets as pending_assets

    monkeypatch.setattr(pending_assets, "STATE_DB", str(tmp_path / "state.db"))
    db_path = str(tmp_path / "conversation.db")
    graph = FakeGraph(reply="Είναι μια σφήκα.")
    completed: list[tuple[str, str, str, str]] = []
    service = MatrixTurnService(
        graph=graph,
        conversation_db_path=db_path,
        on_exchange_completed=lambda *args: completed.append(args),
    )

    reply = await service.run_asset_question(
        question="Τι είναι;",
        event_id="$question-1",
        filename="photo.png",
        file_path="C:/safe/photo.png",
        analysis="Μεγάλη κοκκινοκαφέ σφήκα.",
    )

    assert str(reply).startswith("Είναι μια σφήκα.")
    assert pending_assets.looks_like_asset_confirmation_prompt(str(reply))
    graph_text = [str(message.content) for message in graph.states[0]["messages"]]
    assert any("&#91;USER_UPLOADED_PHOTO&#93;: photo.png" in text for text in graph_text)
    assert any("Question: Τι είναι;" in text for text in graph_text)

    stored = load_messages(channel="matrix", db_path=db_path)
    assert [item["content"] for item in stored] == ["Τι είναι;", str(reply)]
    assert stored[0]["metadata"]["matrix_event_id"] == "$question-1"
    assert stored[0]["metadata"]["astakos_model_asset_context"]["analysis"] == (
        "Μεγάλη κοκκινοκαφέ σφήκα."
    )
    assert "astakos_model_asset_context" not in stored[1]["metadata"]
    assert completed == [("Τι είναι;", "", "Chat_Agent", "matrix")]
    assert pending_assets.get_latest_pending_asset("matrix", "photo") is not None

    await service("Κι εμένα μου έκανε εντύπωση το χρώμα της.", "$followup")
    followup_history = [
        str(message.content) for message in graph.states[1]["messages"]
    ]
    assert any("Μεγάλη κοκκινοκαφέ σφήκα." in text for text in followup_history)


@pytest.mark.asyncio
async def test_matrix_photo_archive_prompt_creates_matrix_only_pending_asset(
    tmp_path, monkeypatch
) -> None:
    import memory.pending_assets as pending_assets
    from services.pending_asset_confirmation import build_asset_archive_prompt

    monkeypatch.setattr(pending_assets, "STATE_DB", str(tmp_path / "state.db"))
    graph = FakeGraph(
        reply="Είναι μια σφήκα." + build_asset_archive_prompt("photo")
    )
    service = MatrixTurnService(
        graph=graph,
        conversation_db_path=str(tmp_path / "conversation.db"),
    )

    await service.run_asset_question(
        question="Τι είναι;",
        event_id="$question-photo",
        filename="../../photo`bad.png",
        file_path=str(tmp_path / "safe.png"),
        analysis="σφήκα",
    )

    pending = pending_assets.get_latest_pending_asset("matrix", "photo")
    assert pending["filename"] == "photobad.png"
    assert pending["caption"] == "Τι είναι;"
    assert pending_assets.get_latest_pending_asset("telegram", "photo") is None
