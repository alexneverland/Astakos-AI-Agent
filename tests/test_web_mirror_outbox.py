"""Offline delivery contracts for Web text mirrored to the selected channel."""

from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from memory.conversation_history import append_message, load_messages
from services.external_delivery import ExternalDeliveryRouter


class FakeTransport:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.sent: list[str] = []

    def send_text(self, text: str, *, silent: bool = False) -> int:
        assert silent is True
        if self.fail:
            raise RuntimeError("offline transport failure")
        self.sent.append(text)
        return len(self.sent)


def test_web_chat_rows_enqueue_only_the_selected_channel(tmp_path) -> None:
    from memory.conversation_history import load_pending_web_mirrors

    db_path = str(tmp_path / "conversation.db")
    user = append_message(
        role="user", content="From Web", channel="web",
        mirror_target="matrix", db_path=db_path,
    )
    reply = append_message(
        role="assistant", content="Answer", channel="web",
        mirror_target="matrix", db_path=db_path,
    )
    append_message(role="user", content="Voice only", channel="web", db_path=db_path)

    pending = load_pending_web_mirrors("matrix", db_path=db_path)
    assert [(item["message_id"], item["role"], item["content"]) for item in pending] == [
        (user["id"], "user", "From Web"),
        (reply["id"], "assistant", "Answer"),
    ]
    assert load_pending_web_mirrors("telegram", db_path=db_path) == []
    assert len(load_messages(db_path=db_path)) == 3


@pytest.mark.parametrize("role", ["user", "assistant"])
def test_repeated_web_turns_each_get_a_persisted_row_and_mirror(tmp_path, role: str) -> None:
    from memory.conversation_history import load_pending_web_mirrors

    db_path = str(tmp_path / "conversation.db")
    first = append_message(
        role=role, content="ίδιο", channel="web",
        mirror_target="matrix", db_path=db_path,
    )
    second = append_message(
        role=role, content="ίδιο", channel="web",
        mirror_target="matrix", db_path=db_path,
    )

    assert first["rowid"] != second["rowid"]
    assert len(load_messages(db_path=db_path)) == 2
    assert [item["message_id"] for item in load_pending_web_mirrors("matrix", db_path=db_path)] == [
        first["id"], second["id"],
    ]


def test_pending_mirror_keeps_original_target_after_channel_switch(tmp_path) -> None:
    from memory.conversation_history import load_pending_web_mirrors

    db_path = str(tmp_path / "conversation.db")
    append_message(
        role="user", content="Earlier", channel="web",
        mirror_target="matrix", db_path=db_path,
    )
    append_message(
        role="user", content="Later", channel="web",
        mirror_target="telegram", db_path=db_path,
    )

    assert [item["content"] for item in load_pending_web_mirrors("matrix", db_path=db_path)] == ["Earlier"]
    assert [item["content"] for item in load_pending_web_mirrors("telegram", db_path=db_path)] == ["Later"]


def test_drain_retries_after_failure_without_duplicating_history(tmp_path) -> None:
    from memory.conversation_history import load_pending_web_mirrors
    from services.web_mirror_delivery import drain_web_mirrors

    db_path = str(tmp_path / "conversation.db")
    append_message(role="user", content="Web question", channel="web", mirror_target="matrix", db_path=db_path)
    append_message(role="assistant", content="Web answer", channel="web", mirror_target="matrix", db_path=db_path)
    transport = FakeTransport(fail=True)
    router = ExternalDeliveryRouter(channel_selector=lambda: "matrix")
    router.register("matrix", transport)

    assert drain_web_mirrors("matrix", router=router, db_path=db_path) == 0
    assert len(load_pending_web_mirrors("matrix", db_path=db_path)) == 2
    transport.fail = False
    assert drain_web_mirrors("matrix", router=router, db_path=db_path) == 2
    assert drain_web_mirrors("matrix", router=router, db_path=db_path) == 0
    assert len(transport.sent) == 2
    assert transport.sent[0].startswith("Web / ")
    assert "[services.web_mirror_delivery" not in transport.sent[0]
    assert "Web question" in transport.sent[0]
    assert "Web answer" in transport.sent[1]
    assert load_pending_web_mirrors("matrix", db_path=db_path) == []
    assert len(load_messages(db_path=db_path)) == 2


def test_drain_never_falls_back_to_inactive_channel(tmp_path) -> None:
    from memory.conversation_history import load_pending_web_mirrors
    from services.web_mirror_delivery import drain_web_mirrors

    db_path = str(tmp_path / "conversation.db")
    append_message(role="user", content="For Element", channel="web", mirror_target="matrix", db_path=db_path)
    telegram = FakeTransport()
    router = ExternalDeliveryRouter(channel_selector=lambda: "telegram")
    router.register("telegram", telegram)

    assert drain_web_mirrors("matrix", router=router, db_path=db_path) == 0
    assert telegram.sent == []
    assert len(load_pending_web_mirrors("matrix", db_path=db_path)) == 1


def test_invalid_mirror_target_does_not_persist_message(tmp_path) -> None:
    db_path = str(tmp_path / "conversation.db")
    with pytest.raises(ValueError, match="Web mirror"):
        append_message(
            role="user", content="Not deliverable", channel="web",
            mirror_target="unknown", db_path=db_path,
        )
    assert load_messages(db_path=db_path) == []


def test_mirror_preserves_full_web_text_when_history_is_summarized(tmp_path) -> None:
    from memory.conversation_history import load_pending_web_mirrors

    db_path = str(tmp_path / "conversation.db")
    response = "Summary\n\n```diff\n" + ("+ detail\n" * 100)
    append_message(
        role="assistant", content=response, channel="web",
        mirror_target="telegram", db_path=db_path,
    )

    assert load_messages(db_path=db_path)[0]["content"] != response
    assert load_pending_web_mirrors("telegram", db_path=db_path)[0]["content"] == response


def test_web_chat_route_marks_every_text_history_write_for_mirroring() -> None:
    """Inspect routing without importing the stateful live API module."""
    source = Path(__file__).resolve().parents[1] / "api" / "server.py"
    module = ast.parse(source.read_text(encoding="utf-8"))
    route = next(
        node for node in module.body
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "chat_endpoint"
    )
    writes = [
        node for node in ast.walk(route)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "append_to_chat_history"
    ]
    assert len(writes) >= 2
    assert all(any(key.arg == "mirror_target" for key in call.keywords) for call in writes)


@pytest.mark.parametrize("mode", ["yes", "no", "clear_draft", "clarify_draft"])
def test_web_chat_early_saved_replies_return_both_history_row_ids(mode: str) -> None:
    """Exercise all four early /chat replies without a live DB or transport."""
    from api.server import LOCAL_TOKEN, server
    from services.routine_completion_helper import RoutineSelection

    saved_roles: list[str] = []

    def save_history(role: str, _content: str, **kwargs: object) -> dict[str, int]:
        assert kwargs["return_saved"] is True
        saved_roles.append(role)
        return {"rowid": 700 + len(saved_roles)}

    is_asset = mode in {"yes", "no"}
    with (
        patch("core.messaging_channel.resolve_external_channel", return_value="matrix"),
        patch("memory.pending_assets.get_latest_recent_asset", return_value=None),
        patch("memory.routine_db.load_pending_confirmations", return_value={}),
        patch("memory.routine_db.get_eligible_preemptive_routines_for_day", return_value=[]),
        patch("memory.routine_db.get_active_routine_catalog", return_value=[]),
        patch("services.routine_completion_helper.decide_completion", return_value=RoutineSelection(action="none", routine_id=None)),
        patch("memory.pending_assets.clear_expired_pending_assets"),
        patch("memory.pending_assets.get_latest_pending_asset_any", return_value={"id": 1} if is_asset else None),
        patch("memory.pending_assets.classify_pending_asset_reply", return_value=mode if is_asset else None),
        patch("memory.pending_assets.is_reply_to_recent_asset_prompt", return_value=is_asset),
        patch("memory.pending_assets.mark_pending_asset_confirmed"),
        patch("memory.pending_assets.mark_pending_asset_cancelled"),
        patch("services.pending_asset_confirmation.save_confirmed_asset"),
        patch("core.messenger_draft.active_draft_status", return_value=(True, "active", {"message": "Draft"})),
        patch("core.messenger_draft.clear_draft", return_value=True),
        patch("services.messenger_intent.classify_messenger_intent", return_value=SimpleNamespace(intent=mode)),
        patch("memory.execution_trace.ExecutionTrace.save"),
        patch("api.server.append_to_chat_history", side_effect=save_history),
        patch("api.server.enqueue_fast_task"),
        patch("api.server.enqueue_slow_task"),
    ):
        response = TestClient(server).post(
            "/chat", json={"message": "Ναι" if mode == "yes" else "Όχι"},
            headers={"Authorization": f"Bearer {LOCAL_TOKEN}"},
        )

    assert response.status_code == 200
    assert response.json()["user_rowid"] == 701
    assert response.json()["assistant_rowid"] == 702
    assert saved_roles == ["user", "assistant"]


def test_external_scheduler_registers_mirror_consumer_without_importing_bot() -> None:
    """Guard Matrix/Telegram shared scheduler wiring without starting the bot."""
    source = Path(__file__).resolve().parents[1] / "clients" / "telegram_bot.py"
    module = ast.parse(source.read_text(encoding="utf-8"))
    builder = next(
        node for node in module.body
        if isinstance(node, ast.FunctionDef) and node.name == "_build_external_scheduler"
    )
    jobs = [
        node for node in ast.walk(builder)
        if isinstance(node, ast.Call)
        and any(key.arg == "name" and isinstance(key.value, ast.Constant)
                and key.value.value == "web_mirror" for key in node.keywords)
    ]
    assert len(jobs) == 1
