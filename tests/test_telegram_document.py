import pytest
import os
from clients.telegram_bot import handle_document
from core.i18n import t

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

    monkeypatch.setattr("clients.telegram_bot.send_telegram_msg", mock_send)

    monkeypatch.setattr("pypdf.PdfReader", lambda x: type("MockReader", (), {"pages": []}))

    class MockLLMResponse:
        content = "Mocked LLM Analysis"
    monkeypatch.setattr("clients.telegram_bot.safe_llm_invoke", lambda *args, **kwargs: MockLLMResponse())
    monkeypatch.setattr("memory.conversation_history.build_asset_context_text", lambda *args, **kwargs: "context")
    monkeypatch.setattr("memory.conversation_history.append_message", lambda *args, **kwargs: mocks.append_message.append(args))
    monkeypatch.setattr("memory.pending_assets.create_pending_asset_archive", lambda *args, **kwargs: mocks.create_archive.append(kwargs))
    monkeypatch.setattr("clients.telegram_bot.enqueue_fast_task", lambda *args, **kwargs: mocks.fast_tasks.append(args))
    monkeypatch.setattr("clients.telegram_bot.enqueue_slow_task", lambda *args, **kwargs: mocks.slow_tasks.append(args))

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
    assert any("yes or no" in msg for msg in mock_telegram_api.sent_messages)
    assert len(mock_telegram_api.append_message) == 2
    assert len(mock_telegram_api.fast_tasks) == 3
    assert len(mock_telegram_api.slow_tasks) == 3
    assert len(mock_telegram_api.create_archive) == 1
    assert mock_telegram_api.create_archive[0].get("filename") == "report.pdf"

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
