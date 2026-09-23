import pytest
from io import BytesIO
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from PIL import Image

from api.server import server, LOCAL_TOKEN


def test_matrix_document_history_hides_internal_path_from_web() -> None:
    from api.server import _render_persisted_asset_markers_for_client

    stored = (
        "[USER_UPLOADED_FILE]: report.pdf\n"
        "[FILE PATH]: C:\\astakos_v2\\matrix_media\\secret.pdf\n"
        "[USER_CAPTION]: Δες το\n"
        "[ANALYSIS]: Private source text"
    )

    rendered = _render_persisted_asset_markers_for_client(stored, "127.0.0.1")

    assert "report.pdf" in rendered
    assert "Δες το" in rendered
    assert "C:\\astakos_v2" not in rendered
    assert "Private source text" not in rendered


def test_plain_user_text_is_not_rewritten_as_document_history() -> None:
    from api.server import _render_persisted_asset_markers_for_client

    text = "[USER_UPLOADED_FILE]: example.pdf is only a quoted example"
    assert _render_persisted_asset_markers_for_client(text, "127.0.0.1") == text

@pytest.fixture
def client():
    return TestClient(server)

def test_pasted_text_upload_reaches_document_summary_without_unbound_error(client, tmp_path):
    """
    Proves that a non-image text upload does not crash with UnboundLocalError
    after the function-local `llm` import was removed from api/server.py.
    """
    # 1. Mock the file system target
    mock_uploads_dir = tmp_path / "uploads"
    mock_uploads_dir.mkdir()

    # 2. Mock external side effects to avoid DB/network
    with patch("config.UPLOADS_DIR", str(mock_uploads_dir)), \
         patch("api.server.safe_llm_invoke") as mock_invoke, \
         patch("api.server.append_to_chat_history") as mock_history, \
         patch("api.server.enqueue_fast_task") as mock_fast_queue, \
         patch("api.server.enqueue_slow_task"), \
         patch("memory.conversation_history.build_asset_context_text", return_value="fake_context"), \
         patch("memory.pending_assets.create_pending_asset_archive"):


        # Make the LLM return a fake response
        fake_resp = MagicMock()
        fake_resp.content = "Fake document summary."
        mock_invoke.return_value = fake_resp
        mock_history.return_value = {"rowid": None}

        # 3. Perform the request
        payload = b"This is a pasted upload text payload. " * 50
        files = {"file": ("paste_123.txt", payload, "text/plain")}
        data = {"message": "Here is my paste"}
        headers = {"Authorization": f"Bearer {LOCAL_TOKEN}"}

        response = client.post("/upload", files=files, data=data, headers=headers)

        # 4. Assert the result
        assert response.status_code == 200
        json_resp = response.json()
        assert json_resp["status"] == "success"
        assert "Fake document summary." in json_resp["ai_message"]
        assert mock_invoke.called
        rendered_prompt = str(mock_invoke.call_args.args[1][0].content)
        assert "[UNTRUSTED EXTERNAL TOOL RESULT]" in rendered_prompt
        assert "Source tool: user_provided_asset" in rendered_prompt
        assistant_call = next(
            call for call in mock_history.call_args_list
            if call.args[:1] == ("assistant",)
        )
        assert assistant_call.kwargs["metadata"] == {
            "untrusted_external_tool_names": ["user_provided_asset"]
        }
        user_call = next(
            call for call in mock_history.call_args_list
            if call.args[:1] == ("user",)
        )
        assert user_call.kwargs["metadata"] == {
            "untrusted_external_tool_names": ["user_provided_asset"]
        }
        assert any(call.args[2] == "" for call in mock_fast_queue.call_args_list)


def test_web_document_upload_mirrors_text_not_file_to_selected_channel(
    client, tmp_path,
) -> None:
    from memory.conversation_history import append_message, load_messages, load_pending_web_mirrors

    mock_uploads_dir = tmp_path / "uploads"
    mock_uploads_dir.mkdir()
    conversation_db = str(tmp_path / "conversation.db")

    def persist_web_history(role: str, content: str, **kwargs):
        kwargs.pop("return_saved", None)
        return append_message(
            role=role, content=content, channel="web", db_path=conversation_db,
            **kwargs,
        )

    headers = {"Authorization": f"Bearer {LOCAL_TOKEN}"}
    with patch("config.UPLOADS_DIR", str(mock_uploads_dir)), \
         patch("core.messaging_channel.resolve_external_channel", return_value="matrix"), \
         patch("api.server.safe_llm_invoke") as mock_invoke, \
         patch("api.server.append_to_chat_history") as mock_history, \
         patch("api.server.enqueue_fast_task"), \
         patch("api.server.enqueue_slow_task"), \
         patch("memory.conversation_history.build_asset_context_text", return_value=""), \
         patch("memory.pending_assets.create_pending_asset_archive"):
        mock_history.side_effect = persist_web_history
        mock_invoke.return_value.content = "Σύντομη ανάλυση εγγράφου."
        response = client.post(
            "/upload",
            files={"file": ("report.txt", b"A report to summarize.", "text/plain")},
            data={"message": "Δες το"},
            headers=headers,
        )

    assert response.status_code == 200
    assert response.json()["status"] == "success"
    saved_rows = load_messages(db_path=conversation_db)
    assert response.json()["user_rowid"] == saved_rows[0]["rowid"]
    assert response.json()["assistant_rowid"] == saved_rows[1]["rowid"]
    assert response.json()["user_message"] == saved_rows[0]["content"]
    assert [call.kwargs.get("mirror_target") for call in mock_history.call_args_list] == [
        "matrix", "matrix",
    ]
    assert "Ανέβασα αρχείο" in mock_history.call_args_list[0].args[1]
    assert "Σύντομη ανάλυση" in mock_history.call_args_list[1].args[1]
    queued = load_pending_web_mirrors("matrix", db_path=conversation_db)
    assert [item["role"] for item in queued] == ["user", "assistant"]
    assert queued[0]["content"] == "📄 Έστειλα αρχείο από το Web."
    assert "Σύντομη ανάλυση" in queued[1]["content"]
    assert "Απάντησέ μου μόνο" not in queued[1]["content"]
    assert "Απάντησέ μου μόνο" in response.json()["ai_message"]


def test_web_photo_upload_queues_description_without_binary_media(
    client, tmp_path,
) -> None:
    from memory.conversation_history import append_message, load_messages, load_pending_web_mirrors

    photo_dir = tmp_path / "photos"
    photo_dir.mkdir()
    conversation_db = str(tmp_path / "conversation.db")
    image_bytes = BytesIO()
    Image.new("RGB", (2, 2), "blue").save(image_bytes, format="PNG")

    def persist_web_history(role: str, content: str, **kwargs):
        kwargs.pop("return_saved", None)
        return append_message(
            role=role, content=content, channel="web", db_path=conversation_db,
            **kwargs,
        )

    with patch("api.server.PHOTOS_DIR", str(photo_dir)), \
         patch("core.messaging_channel.resolve_external_channel", return_value="matrix"), \
         patch("core.brain.get_active_provider_adapter", return_value=MagicMock()), \
         patch("core.brain.safe_adapter_call", return_value="Μια μπλε εικόνα."), \
         patch("api.server.append_to_chat_history", side_effect=persist_web_history), \
         patch("api.server.enqueue_fast_task"), \
         patch("api.server.enqueue_slow_task"), \
         patch("memory.pending_assets.create_pending_asset_archive"):
        response = client.post(
            "/upload",
            files={"file": ("photo.png", image_bytes.getvalue(), "image/png")},
            headers={"Authorization": f"Bearer {LOCAL_TOKEN}"},
        )

    assert response.status_code == 200
    assert response.json()["status"] == "success"
    saved_rows = load_messages(db_path=conversation_db)
    assert response.json()["user_rowid"] == saved_rows[0]["rowid"]
    assert response.json()["assistant_rowid"] == saved_rows[1]["rowid"]
    assert response.json()["user_message"] == saved_rows[0]["content"]
    queued = load_pending_web_mirrors("matrix", db_path=conversation_db)
    assert [item["role"] for item in queued] == ["user", "assistant"]
    assert queued[0]["content"] == "📷 Έστειλα φωτογραφία από το Web."
    assert "Μια μπλε εικόνα" in queued[1]["content"]
    assert "Απάντησέ μου μόνο" not in queued[1]["content"]
    assert "Απάντησέ μου μόνο" in response.json()["ai_message"]
    assert all("data:image" not in item["content"] for item in queued)


def test_unreadable_web_document_is_not_summarized_or_offered_for_archive(
    client, tmp_path
):
    from services.document_input import DocumentPreviewError
    from memory.pending_assets import looks_like_asset_confirmation_prompt

    mock_uploads_dir = tmp_path / "uploads"
    mock_uploads_dir.mkdir()
    headers = {"Authorization": f"Bearer {LOCAL_TOKEN}"}
    with patch("config.UPLOADS_DIR", str(mock_uploads_dir)), \
         patch(
             "api.server._read_document_text_for_analysis",
             side_effect=DocumentPreviewError("The PDF is unreadable."),
         ), \
         patch("api.server.safe_llm_invoke") as mock_invoke, \
         patch("api.server.append_to_chat_history", return_value={"rowid": None}), \
         patch("api.server.enqueue_fast_task"), \
         patch("api.server.enqueue_slow_task"), \
         patch("memory.pending_assets.create_pending_asset_archive") as create_pending:
        response = client.post(
            "/upload",
            files={"file": ("broken.pdf", b"broken", "application/pdf")},
            data={"message": "Read this"},
            headers=headers,
        )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "success"
    assert "unreadable" in body["ai_message"]
    assert not looks_like_asset_confirmation_prompt(body["ai_message"])
    mock_invoke.assert_not_called()
    create_pending.assert_not_called()

def test_lifespan_timeout_race(monkeypatch):
    import asyncio
    import time
    from api.server import lifespan
    from fastapi import FastAPI

    events = []

    def mock_run_session_summary(channel):
        events.append("summary_start")
        time.sleep(0.05)
        events.append("summary_end")

    monkeypatch.setattr("api.server._run_session_summary", mock_run_session_summary)
    import memory.vector_store
    monkeypatch.setattr(memory.vector_store, "close_vector_store", lambda: events.append("close"))

    original_wait_for = asyncio.wait_for
    async def fast_wait_for(fut, timeout):
        return await original_wait_for(fut, timeout=0.01)

    monkeypatch.setattr(asyncio, "wait_for", fast_wait_for)
    monkeypatch.setattr("api.server.fast_queue_worker", lambda: None)
    monkeypatch.setattr("api.server.slow_queue_worker", lambda: None)
    monkeypatch.setattr("api.server.fast_queue.join", lambda: None)
    monkeypatch.setattr("api.server.slow_queue.join", lambda: None)

    async def run_lifespan():
        app = FastAPI()
        async with lifespan(app):
            pass

    asyncio.run(run_lifespan())

    assert events == ["summary_start", "summary_end", "close"]
