import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

from api.server import server, LOCAL_TOKEN

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
         patch("api.server.append_to_chat_history"), \
         patch("api.server.enqueue_fast_task"), \
         patch("api.server.enqueue_slow_task"), \
         patch("memory.conversation_history.build_asset_context_text", return_value="fake_context"), \
         patch("memory.pending_assets.create_pending_asset_archive"):


        # Make the LLM return a fake response
        fake_resp = MagicMock()
        fake_resp.content = "Fake document summary."
        mock_invoke.return_value = fake_resp

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
