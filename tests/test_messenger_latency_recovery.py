"""Use native graph/store outcomes for repeated preparation recovery."""
from langchain_core.messages import AIMessage
import pytest

from tests.test_messenger_lifecycle_regression import lifecycle, owner_messages
from tests.test_routine_completion_web import client, _post_chat


@pytest.fixture(autouse=True)
def offline_transport(monkeypatch):
    """Block external sockets, retaining Windows asyncio's loopback wakeup pipe."""
    import socket
    original = socket.socket.connect

    def connect(sock, address):
        if isinstance(address, tuple) and address[0] in {"127.0.0.1", "::1", "localhost"}:
            return original(sock, address)
        raise AssertionError("Outbound transport forbidden")

    monkeypatch.setattr(socket.socket, "connect", connect)


def test_web_owner_copy_is_queued_before_context_inference(client, tmp_path, monkeypatch):
    """Slow clarification must not delay persisting the owner's display copy."""
    from memory.conversation_history import append_message, load_pending_web_mirrors, load_messages
    from services.routine_context_clarification import QuestionAnswer
    path = str(tmp_path / "mirror.db")

    def save(role, content, **kwargs):
        return append_message(role=role, content=content, channel="web", db_path=path,
                              mirror_target=kwargs.get("mirror_target"), metadata=kwargs.get("metadata"))

    def classify(*args, **kwargs):
        queued = load_pending_web_mirrors("matrix", db_path=path)
        assert len(queued) == 1 and queued[0]["role"] == "user"
        assert queued[0]["content"] == "Synthetic context reply"
        return QuestionAnswer(True, "resolved")

    monkeypatch.setattr("core.messaging_channel.resolve_external_channel", lambda: "matrix")
    monkeypatch.setattr("services.routine_context_clarification.try_context_question_reply", classify)
    response, _ = _post_chat(client, message="Synthetic context reply", history_writer=save)
    assert response.status_code == 200
    rows = load_messages(db_path=path)
    assert [r["role"] for r in rows] == ["user", "assistant"]
    assert response.json()["user_rowid"] == rows[0]["rowid"]


def test_mirror_reports_queue_age_separately_from_transport_duration(tmp_path, monkeypatch, capsys):
    """A slow queue is distinguishable from a slow network send without text logs."""
    import json
    from datetime import datetime
    from memory.conversation_history import append_message
    from services import web_mirror_delivery as delivery
    from services.external_delivery import ExternalDeliveryRouter
    path = str(tmp_path / "mirror.db")
    queued_at = datetime(2030, 1, 15, 10, 0)
    append_message(role="user", content="PRIVATE DISPLAY TEXT", channel="web",
                   mirror_target="matrix", timestamp=queued_at, db_path=path)
    clock = [20.0]
    monkeypatch.setattr(delivery.time, "time", lambda: queued_at.timestamp() + 300)
    monkeypatch.setattr(delivery.time, "monotonic", lambda: clock[0])

    class Transport:
        def send_text(self, text, *, silent=False):
            clock[0] += 2
            return "$offline-copy"

    router = ExternalDeliveryRouter(channel_selector=lambda: "matrix")
    router.register("matrix", Transport())
    assert delivery.drain_web_mirrors("matrix", router=router, db_path=path) == 1
    lines = capsys.readouterr().out
    rows = [json.loads(line.removeprefix("[WebMirror]: ")) for line in lines.splitlines()
            if line.startswith('[WebMirror]: {')]
    assert rows[0]["queue_age_ms"] == 300000
    assert rows[-1]["duration_ms"] == 2000
    assert rows[-1]["event"] == "mirror_delivered"
    assert "PRIVATE DISPLAY TEXT" not in lines
