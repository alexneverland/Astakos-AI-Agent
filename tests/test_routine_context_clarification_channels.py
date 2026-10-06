"""Entry-point arbitration owns a consumed context reply before action handlers."""

from types import SimpleNamespace

import pytest

from services.routine_context_clarification import QuestionAnswer


@pytest.fixture(autouse=True)
def offline_only(monkeypatch):
    """Make accidental outbound calls fail rather than touching live transports."""
    import socket
    original_connect = socket.socket.connect

    def forbidden(sock, address):
        # Windows asyncio creates its self-pipe via a loopback socketpair.
        if isinstance(address, tuple) and address[0] in {"127.0.0.1", "::1"}:
            return original_connect(sock, address)
        raise AssertionError("Unexpected outbound network call")

    monkeypatch.setattr(socket.socket, "connect", forbidden)


def test_matrix_background_does_not_extract_consumed_context_twice():
    from services.matrix_background import MatrixBackgroundHooks

    tasks = []
    hooks = MatrixBackgroundHooks(
        enqueue_fast_task=lambda *args, **kwargs: tasks.append(args),
        enqueue_slow_task=lambda *args, **kwargs: tasks.append(args),
    )
    hooks.on_exchange_completed("ναι", "Έγινε", "Routine_Context", "matrix",
                                context_flags_processed=True)
    assert all(task[0].__name__ != "extract_and_update_context_flags" for task in tasks)


def test_matrix_background_extracts_with_matrix_context():
    from services.matrix_background import MatrixBackgroundHooks

    tasks = []
    hooks = MatrixBackgroundHooks(
        enqueue_fast_task=lambda *args, **kwargs: tasks.append(args),
        enqueue_slow_task=lambda *args, **kwargs: tasks.append(args),
    )
    hooks.on_exchange_completed("Γύρισα σπίτι", "Καλώς ήρθες", "Chat_Agent", "matrix")
    extraction = next(task for task in tasks if task[0].__name__ == "extract_and_update_context_flags")
    assert extraction[-1] == "matrix"


def test_telegram_context_reply_does_not_reach_action_or_graph(monkeypatch):
    from clients import telegram_bot as bot
    from services import routine_context_clarification as clarification

    monkeypatch.setattr(bot.config, "TELEGRAM_CHAT_ID", "owner")
    calls, sent = [], []
    monkeypatch.setattr(clarification, "try_context_question_reply",
                        lambda *args, **kwargs: QuestionAnswer(True, "resolved"))
    monkeypatch.setattr(bot, "_append_to_analytics_log", lambda *args, **kwargs: calls.append(args))
    monkeypatch.setattr(bot, "_send_and_record_assistant", lambda *args, **kwargs: sent.append(args))
    monkeypatch.setattr(bot, "enqueue_fast_task", lambda *args, **kwargs: None)
    monkeypatch.setattr(bot, "enqueue_slow_task", lambda *args, **kwargs: None)

    def forbidden(*args, **kwargs):
        raise AssertionError("Context reply cannot enter routine/action interpretation")

    monkeypatch.setattr("services.routine_completion_helper.decide_completion", forbidden)
    bot.handle_message("ναι", "owner")
    assert len(calls) == len(sent) == 1


@pytest.mark.asyncio
async def test_web_context_reply_has_one_history_pair_and_no_graph(monkeypatch):
    from api import server as api
    from services import routine_context_clarification as clarification

    monkeypatch.setattr(clarification, "try_context_question_reply",
                        lambda *args, **kwargs: QuestionAnswer(True, "resolved"))
    rows = []

    def record(role, content, **kwargs):
        rows.append((role, content))
        return {"rowid": len(rows)}

    monkeypatch.setattr(api, "append_to_chat_history", record)
    monkeypatch.setattr(api, "enqueue_fast_task", lambda *args, **kwargs: None)
    monkeypatch.setattr(api, "enqueue_slow_task", lambda *args, **kwargs: None)

    async def body():
        return {"message": "ναι"}

    def forbidden(*args, **kwargs):
        raise AssertionError("No graph/routine execution for consumed reply")

    monkeypatch.setattr(api, "_run_web_graph_stream_sync", forbidden)
    monkeypatch.setattr("services.routine_completion_helper.decide_completion", forbidden)
    response = await api.chat_endpoint(SimpleNamespace(json=body))
    assert response.status_code == 200
    assert [role for role, _ in rows] == ["user", "assistant"]


@pytest.mark.asyncio
async def test_matrix_context_reply_has_one_history_pair_and_skips_confirmation(tmp_path, monkeypatch):
    from services import routine_context_clarification as clarification
    from services.matrix_turn import MatrixTurnService
    from memory.conversation_history import load_messages

    monkeypatch.setattr(clarification, "try_context_question_reply",
                        lambda *args, **kwargs: QuestionAnswer(True, "resolved"))
    hooks = []

    def forbidden(*args, **kwargs):
        raise AssertionError("No graph or routine confirmation for consumed context reply")

    service = MatrixTurnService(
        graph=SimpleNamespace(stream=forbidden), conversation_db_path=str(tmp_path / "history.db"),
        routine_confirmation_handler=forbidden,
        on_exchange_completed=lambda *args, **kwargs: hooks.append(kwargs),
    )
    reply = await service("ναι", "$context-answer")
    assert reply
    assert [row["role"] for row in load_messages(db_path=str(tmp_path / "history.db"))] == [
        "user", "assistant"]
    assert hooks[0]["context_flags_processed"] is True
