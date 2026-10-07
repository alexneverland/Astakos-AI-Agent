import pytest
import os
from unittest.mock import MagicMock
from clients.telegram_bot import handle_document
from core.i18n import t
from memory.conversation_history import append_message as persisted_append_message


@pytest.mark.parametrize("kind", ["photo", "document"])
def test_telegram_asset_history_cannot_become_dated_feedback(tmp_path, monkeypatch, mock_telegram_api, kind):
    """Real photo/document history remains asset-derived even with a completion caption."""
    import sqlite3
    from datetime import datetime
    from zoneinfo import ZoneInfo
    from langchain_core.messages import AIMessage
    from clients.telegram_bot import _process_photo_with_question
    from core.untrusted_content import external_content_source_names
    from memory.conversation_history import load_messages
    from memory.routine_feedback import RoutineFeedbackStore
    from services.routine_feedback_turn import PersistedRoutineFeedbackHandler
    from services.routine_completion_helper import DatedRoutineSelection

    db = tmp_path / "routines.db"
    def connect():
        return sqlite3.connect(db)
    with connect() as connection:
        connection.execute("""CREATE TABLE routines (id INTEGER PRIMARY KEY,
            event_name TEXT, notify_cooldown_hours REAL, explicit_skip_streak INTEGER,
            unanswered_reminder_streak INTEGER, confidence REAL)""")
        connection.execute("INSERT INTO routines VALUES (11, 'Καθάρισμα κουνελιού', 0, 0, 0, 1)")
    ledger = RoutineFeedbackStore(connect)
    ledger.initialize()
    now = datetime(2026, 10, 7, 9, tzinfo=ZoneInfo("Europe/Athens"))
    ledger.record_delivery(11, now.date(), at=now, receipt_id="41",
        question="Το έκανες;", channel="telegram")
    history = str(tmp_path / "history.db")
    def save(role, content, channel, **kwargs):
        return persisted_append_message(role=role, content=content, channel=channel, db_path=history, **kwargs)
    monkeypatch.setattr("memory.conversation_history.append_message", save)
    handler = PersistedRoutineFeedbackHandler(store=ledger,
        selector=lambda *a, **kw: DatedRoutineSelection("complete", 11, now.date()),
        clock=lambda: now, channel="telegram", conversation_db_path=history, trusted_owner=True)
    analysis = "Ναι το έκανα"
    if kind == "photo":
        monkeypatch.setitem(_process_photo_with_question.__globals__, "_load_shared_context_messages", lambda _: [])
        graph = MagicMock()
        graph.stream.return_value = iter([{"Chat_Agent": {"messages": [AIMessage(content=analysis)]}}])
        monkeypatch.setitem(_process_photo_with_question.__globals__, "graph", graph)
        monkeypatch.setattr("memory.execution_trace.ExecutionTrace", MagicMock())
        _process_photo_with_question("photo.png", str(tmp_path / "photo.png"), analysis, analysis, "123456")
    else:
        monkeypatch.setattr("config.BASE_DIR", str(tmp_path))
        monkeypatch.setattr("requests.get", lambda url, **kw: MockResponse(None if "getFile" in url else b"offline document"))
        monkeypatch.setattr("services.document_analysis.summarize_document_text", lambda **kw: analysis)
        handle_document({"file_id": "123", "file_name": "report.txt"}, analysis, "123456")

    rows = load_messages(db_path=history)
    assert [row["role"] for row in rows] == ["user", "assistant"]
    assert external_content_source_names(rows[0]["metadata"]) == {"user_provided_asset"}
    assert handler(rows[0]["content"], rows[0]) is None
    assert ledger.occurrences(11)[0].feedback is None
    assert mock_telegram_api.sent_messages

class MockResponse:
    def __init__(self, data, ok=True, headers=None, status_code=200):
        self._data = data
        self.ok_val = ok
        self.headers = headers or {}
        self.status_code = status_code

    def json(self):
        return {"ok": self.ok_val, "result": {"file_path": "mocked/path.pdf"}}

    def iter_content(self, chunk_size=8192):
        if isinstance(self._data, list):
            for chunk in self._data:
                yield chunk
        else:
            yield self._data

    def raise_for_status(self):
        if self.status_code != 200:
            raise Exception("HTTP Error")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        pass

class Mocks:
    def __init__(self):
        self.sent_messages = []
        self.append_message = []
        self.create_archive = []
        self.fast_tasks = []
        self.slow_tasks = []

@pytest.fixture
def mock_telegram_api(monkeypatch):
    mocks = Mocks()

    def mock_send(msg, *args, **kwargs):
        mocks.sent_messages.append(msg)
        return {"message_id": 1}

    # Other tests may replace ``clients.telegram_bot`` in ``sys.modules``.
    # Patch the globals of the imported handler itself so this fixture always
    # captures the calls made by the function under test.
    monkeypatch.setitem(handle_document.__globals__, "send_telegram_msg", mock_send)

    monkeypatch.setattr("pypdf.PdfReader", lambda x: type("MockReader", (), {"pages": []}))
    monkeypatch.setattr(
        "services.document_input.extract_document_preview",
        lambda *args, **kwargs: "Mocked document text",
    )

    class MockLLMResponse:
        content = "Mocked LLM Analysis"
    monkeypatch.setitem(
        handle_document.__globals__,
        "safe_llm_invoke",
        lambda *args, **kwargs: MockLLMResponse(),
    )
    monkeypatch.setattr("memory.conversation_history.build_asset_context_text", lambda *args, **kwargs: "context")
    monkeypatch.setattr("memory.conversation_history.append_message", lambda *args, **kwargs: mocks.append_message.append(args))
    monkeypatch.setattr("memory.pending_assets.create_pending_asset_archive", lambda *args, **kwargs: mocks.create_archive.append(kwargs))
    monkeypatch.setitem(
        handle_document.__globals__,
        "enqueue_fast_task",
        lambda *args, **kwargs: mocks.fast_tasks.append(args),
    )
    monkeypatch.setitem(
        handle_document.__globals__,
        "enqueue_slow_task",
        lambda *args, **kwargs: mocks.slow_tasks.append(args),
    )

    return mocks

def test_traversal_filename(monkeypatch, tmp_path, mock_telegram_api):
    monkeypatch.setattr("config.BASE_DIR", str(tmp_path))

    def mock_get(url, **kwargs):
        if "getFile" in url:
            return MockResponse(None)
        return MockResponse(b"valid content")

    monkeypatch.setattr("requests.get", mock_get)

    doc_obj = {"file_id": "123", "file_name": "../../../etc/passwd.pdf"}
    handle_document(doc_obj, "", "chat_id")

    target_dir = os.path.join(str(tmp_path), "telegram_uploads")
    assert os.path.exists(target_dir)
    files = os.listdir(target_dir)
    assert len(files) == 1
    assert files[0].startswith("tg_")
    assert files[0].endswith(".pdf")
    assert "passwd" not in files[0]

def test_unsupported_extension(monkeypatch, mock_telegram_api):
    def mock_get(url, **kwargs):
        return MockResponse(None)

    monkeypatch.setattr("requests.get", mock_get)

    doc_obj = {"file_id": "123", "file_name": "malicious.exe"}
    handle_document(doc_obj, "", "chat_id")

    assert t("api.server.invalid_file_type", file_ext=".exe") in mock_telegram_api.sent_messages

def test_oversized_content_length(monkeypatch, tmp_path, mock_telegram_api):
    monkeypatch.setattr("config.BASE_DIR", str(tmp_path))

    def mock_get(url, **kwargs):
        if "getFile" in url:
            return MockResponse(None)
        return MockResponse(b"data", headers={"Content-Length": str(21 * 1024 * 1024)})

    monkeypatch.setattr("requests.get", mock_get)

    doc_obj = {"file_id": "123", "file_name": "big.pdf"}
    handle_document(doc_obj, "", "chat_id")

    target_dir = os.path.join(str(tmp_path), "telegram_uploads")
    if os.path.exists(target_dir):
        files = os.listdir(target_dir)
        assert len(files) == 0

    assert t("api.server.file_too_large") in mock_telegram_api.sent_messages

def test_chunked_body_exceeding_limit(monkeypatch, tmp_path, mock_telegram_api):
    monkeypatch.setattr("config.BASE_DIR", str(tmp_path))

    def mock_get(url, **kwargs):
        if "getFile" in url:
            return MockResponse(None)
        chunks = [b"a" * (10 * 1024 * 1024)] * 3
        return MockResponse(chunks)

    monkeypatch.setattr("requests.get", mock_get)

    doc_obj = {"file_id": "123", "file_name": "sneaky.pdf"}
    handle_document(doc_obj, "", "chat_id")

    target_dir = os.path.join(str(tmp_path), "telegram_uploads")
    assert os.path.exists(target_dir)
    files = os.listdir(target_dir)
    assert len(files) == 0
    assert t("api.server.file_too_large") in mock_telegram_api.sent_messages

def test_golden_path_allowed_document(monkeypatch, tmp_path, mock_telegram_api):
    monkeypatch.setattr("config.BASE_DIR", str(tmp_path))

    def mock_get(url, **kwargs):
        if "getFile" in url:
            return MockResponse(None)
        return MockResponse(b"valid content")

    monkeypatch.setattr("requests.get", mock_get)

    doc_obj = {"file_id": "123", "file_name": "report.pdf"}
    handle_document(doc_obj, "", "chat_id")

    target_dir = os.path.join(str(tmp_path), "telegram_uploads")
    files = os.listdir(target_dir)
    assert len(files) == 1
    assert files[0].startswith("tg_")

    assert any("report.pdf" in msg for msg in mock_telegram_api.sent_messages)
    from memory.pending_assets import looks_like_asset_confirmation_prompt
    assert any(
        looks_like_asset_confirmation_prompt(msg)
        for msg in mock_telegram_api.sent_messages
    )
    assert len(mock_telegram_api.append_message) == 2
    assert len(mock_telegram_api.fast_tasks) == 3
    # The memory sifter is deliberately a fast task; follow-ups and context
    # extraction are the two slow jobs for an upload-derived reply.
    assert len(mock_telegram_api.slow_tasks) == 2
    assert len(mock_telegram_api.create_archive) == 1
    assert mock_telegram_api.create_archive[0].get("filename") == "report.pdf"


def test_unreadable_document_is_not_summarized_or_offered_for_archive(
    monkeypatch, tmp_path, mock_telegram_api
):
    from services.document_input import DocumentPreviewError

    monkeypatch.setattr("config.BASE_DIR", str(tmp_path))
    monkeypatch.setattr(
        "services.document_input.extract_document_preview",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            DocumentPreviewError("The PDF is unreadable.")
        ),
    )

    def mock_get(url, **kwargs):
        if "getFile" in url:
            return MockResponse(None)
        return MockResponse(b"broken-pdf")

    monkeypatch.setattr("requests.get", mock_get)
    handle_document({"file_id": "123", "file_name": "broken.pdf"}, "", "chat_id")

    assert any("unreadable" in message for message in mock_telegram_api.sent_messages)
    assert mock_telegram_api.create_archive == []
    from memory.pending_assets import looks_like_asset_confirmation_prompt
    assert not any(
        looks_like_asset_confirmation_prompt(message)
        for message in mock_telegram_api.sent_messages
    )

def test_malformed_content_length(monkeypatch, tmp_path, mock_telegram_api):
    monkeypatch.setattr("config.BASE_DIR", str(tmp_path))

    def mock_get(url, **kwargs):
        if "getFile" in url:
            return MockResponse(None)
        chunks = [b"a" * (10 * 1024 * 1024)] * 3
        return MockResponse(chunks, headers={"Content-Length": "not-a-number"})

    monkeypatch.setattr("requests.get", mock_get)

    doc_obj = {"file_id": "123", "file_name": "malformed.pdf"}
    handle_document(doc_obj, "", "chat_id")

    target_dir = os.path.join(str(tmp_path), "telegram_uploads")
    assert os.path.exists(target_dir)
    files = os.listdir(target_dir)
    assert len(files) == 0
    assert t("api.server.file_too_large") in mock_telegram_api.sent_messages


def test_getfile_ok_false(monkeypatch, tmp_path, mock_telegram_api):
    monkeypatch.setattr('config.BASE_DIR', str(tmp_path))

    def mock_get(url, **kwargs):
        if 'getFile' in url:
            return MockResponse(None, ok=False)
        return MockResponse(b'valid content')

    monkeypatch.setattr('requests.get', mock_get)

    doc_obj = {'file_id': '123', 'file_name': 'report.pdf'}
    handle_document(doc_obj, '', 'chat_id')

    target_dir = os.path.join(str(tmp_path), 'telegram_uploads')
    if os.path.exists(target_dir):
        files = os.listdir(target_dir)
        assert len(files) == 0

    assert t('api.server.document_download_failed') in mock_telegram_api.sent_messages

def test_getfile_network_error(monkeypatch, tmp_path, mock_telegram_api):
    monkeypatch.setattr('config.BASE_DIR', str(tmp_path))

    def mock_get(url, **kwargs):
        if 'getFile' in url:
            raise Exception('Network timeout')
        return MockResponse(b'valid content')

    monkeypatch.setattr('requests.get', mock_get)

    doc_obj = {'file_id': '123', 'file_name': 'report.pdf'}
    handle_document(doc_obj, '', 'chat_id')

    target_dir = os.path.join(str(tmp_path), 'telegram_uploads')
    if os.path.exists(target_dir):
        files = os.listdir(target_dir)
        assert len(files) == 0

    assert t('api.server.document_download_failed') in mock_telegram_api.sent_messages

def test_stream_exactly_20mb(monkeypatch, tmp_path, mock_telegram_api):
    monkeypatch.setattr('config.BASE_DIR', str(tmp_path))

    def mock_get(url, **kwargs):
        if 'getFile' in url:
            return MockResponse(None)
        chunks = [b'a' * (10 * 1024 * 1024)] * 2
        return MockResponse(chunks, headers={'Content-Length': str(20 * 1024 * 1024)})

    monkeypatch.setattr('requests.get', mock_get)

    doc_obj = {'file_id': '123', 'file_name': 'exact.pdf'}
    handle_document(doc_obj, '', 'chat_id')

    target_dir = os.path.join(str(tmp_path), 'telegram_uploads')
    assert os.path.exists(target_dir)
    files = os.listdir(target_dir)
    assert len(files) == 1
    assert t('api.server.file_too_large') not in mock_telegram_api.sent_messages
    assert t('api.server.document_download_failed') not in mock_telegram_api.sent_messages

def test_stream_unexpected_error(monkeypatch, tmp_path, mock_telegram_api):
    monkeypatch.setattr('config.BASE_DIR', str(tmp_path))

    def mock_get(url, **kwargs):
        if 'getFile' in url:
            return MockResponse(None)

        class ErrorResponse(MockResponse):
            def iter_content(self, chunk_size=8192):
                yield b'partial content'
                raise Exception('Connection reset')

        return ErrorResponse(None)

    monkeypatch.setattr('requests.get', mock_get)

    doc_obj = {'file_id': '123', 'file_name': 'error.pdf'}
    handle_document(doc_obj, '', 'chat_id')

    target_dir = os.path.join(str(tmp_path), 'telegram_uploads')
    if os.path.exists(target_dir):
        files = os.listdir(target_dir)
        assert len(files) == 0
    assert t('api.server.document_download_failed') in mock_telegram_api.sent_messages
