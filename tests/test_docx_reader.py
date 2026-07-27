import pytest
import os
import zipfile
from unittest.mock import MagicMock, patch
from core.utils import extract_docx_preview

@pytest.fixture
def mock_i18n(monkeypatch):
    """Ensure translations return predictable values for tests."""
    def mock_t(key, **kwargs):
        if key == "api.server.docx_oversized_uncompressed":
            return "OVERSIZED"
        if key == "api.server.docx_corrupt":
            return "CORRUPT"
        if key == "api.server.docx_unreadable_generic":
            return "UNREADABLE"
        if key == "api.server.docx_empty_or_scanned":
            return "EMPTY_OR_SCANNED"
        if key == "api.server.docx_preview_clipped":
            return "CLIPPED"
        return key
    monkeypatch.setattr("core.i18n.t", mock_t)

def test_extract_docx_oversized_uncompressed(monkeypatch, mock_i18n):
    monkeypatch.setattr("os.path.getsize", lambda x: 1000)
    mock_zip = MagicMock()
    # Simulate a single file that is 60MB uncompressed
    mock_info = MagicMock()
    mock_info.file_size = 60_000_000
    mock_zip.infolist.return_value = [mock_info]

    mock_ZipFile = MagicMock()
    mock_ZipFile.return_value.__enter__.return_value = mock_zip
    monkeypatch.setattr("zipfile.ZipFile", mock_ZipFile)

    mock_doc = MagicMock()
    monkeypatch.setattr("docx.Document", mock_doc)

    res = extract_docx_preview("dummy.docx", max_chars=8000)
    assert res == "OVERSIZED"
    assert not mock_doc.called

def test_extract_docx_corrupt(monkeypatch, mock_i18n):
    monkeypatch.setattr("os.path.getsize", lambda x: 1000)
    def raise_badzip(*args, **kwargs):
        raise zipfile.BadZipFile("Bad zip")

    monkeypatch.setattr("zipfile.ZipFile", raise_badzip)

    mock_doc = MagicMock()
    monkeypatch.setattr("docx.Document", mock_doc)

    res = extract_docx_preview("dummy.docx", max_chars=8000)
    assert res == "CORRUPT"
    assert not mock_doc.called

def test_extract_docx_empty(monkeypatch, mock_i18n):
    monkeypatch.setattr("os.path.getsize", lambda x: 1000)
    mock_zip = MagicMock()
    mock_info = MagicMock()
    mock_info.file_size = 1000
    mock_zip.infolist.return_value = [mock_info]
    mock_ZipFile = MagicMock()
    mock_ZipFile.return_value.__enter__.return_value = mock_zip
    monkeypatch.setattr("zipfile.ZipFile", mock_ZipFile)

    mock_doc_instance = MagicMock()
    mock_doc_instance.paragraphs = []

    mock_Document = MagicMock(return_value=mock_doc_instance)
    monkeypatch.setattr("docx.Document", mock_Document)

    res = extract_docx_preview("dummy.docx", max_chars=8000)
    assert res == "EMPTY_OR_SCANNED"

def test_extract_docx_bounded_extraction(monkeypatch, mock_i18n):
    monkeypatch.setattr("os.path.getsize", lambda x: 1000)
    mock_zip = MagicMock()
    mock_info = MagicMock()
    mock_info.file_size = 1000
    mock_zip.infolist.return_value = [mock_info]
    mock_ZipFile = MagicMock()
    mock_ZipFile.return_value.__enter__.return_value = mock_zip
    monkeypatch.setattr("zipfile.ZipFile", mock_ZipFile)

    class MockParagraph:
        def __init__(self, text):
            self._text = text
            self.accessed = False
        @property
        def text(self):
            self.accessed = True
            return self._text

    p1 = MockParagraph("A" * 5000)
    p2 = MockParagraph("B" * 5000)
    p3 = MockParagraph("C" * 5000) # Should not be accessed

    mock_doc_instance = MagicMock()
    mock_doc_instance.paragraphs = [p1, p2, p3]

    mock_Document = MagicMock(return_value=mock_doc_instance)
    monkeypatch.setattr("docx.Document", mock_Document)

    res = extract_docx_preview("dummy.docx", max_chars=8000)

    assert p1.accessed
    assert p2.accessed
    assert not p3.accessed

    # 5000 from p1, \n, then part of p2. Total length with "CLIPPED" marker must be 8000.
    assert res.endswith("CLIPPED")
    assert len(res) == 8000

def test_extract_docx_max_chars_zero(monkeypatch, mock_i18n):
    res = extract_docx_preview("dummy.docx", max_chars=0)
    assert res == ""

def test_extract_docx_max_chars_tiny(monkeypatch, mock_i18n):
    monkeypatch.setattr("os.path.getsize", lambda x: 1000)
    mock_zip = MagicMock()
    mock_info = MagicMock()
    mock_info.file_size = 1000
    mock_zip.infolist.return_value = [mock_info]
    mock_ZipFile = MagicMock()
    mock_ZipFile.return_value.__enter__.return_value = mock_zip
    monkeypatch.setattr("zipfile.ZipFile", mock_ZipFile)

    class MockParagraph:
        def __init__(self, text):
            self._text = text
            self.accessed = False
        @property
        def text(self):
            self.accessed = True
            return self._text

    p1 = MockParagraph("Hello")
    p2 = MockParagraph("World")

    mock_doc_instance = MagicMock()
    mock_doc_instance.paragraphs = [p1, p2]

    mock_Document = MagicMock(return_value=mock_doc_instance)
    monkeypatch.setattr("docx.Document", mock_Document)

    # max_chars=1 is smaller than the marker length ("CLIPPED" is 7)
    res = extract_docx_preview("dummy.docx", max_chars=1)

    assert p1.accessed
    assert not p2.accessed
    assert res == "H"
    assert len(res) == 1

def test_extract_docx_unreadable_generic(monkeypatch, mock_i18n):
    monkeypatch.setattr("os.path.getsize", lambda x: 1000)
    mock_zip = MagicMock()
    mock_info = MagicMock()
    mock_info.file_size = 1000
    mock_zip.infolist.return_value = [mock_info]
    mock_ZipFile = MagicMock()
    mock_ZipFile.return_value.__enter__.return_value = mock_zip
    monkeypatch.setattr("zipfile.ZipFile", mock_ZipFile)

    def raise_err(*args, **kwargs):
        raise ValueError("Some random parsing error inside DOCX")

    monkeypatch.setattr("docx.Document", raise_err)

    res = extract_docx_preview("dummy.docx", max_chars=8000)
    assert res == "UNREADABLE"

def test_extract_docx_oversized_physical(monkeypatch, mock_i18n):
    monkeypatch.setattr("os.path.getsize", lambda x: 20 * 1024 * 1024 + 1)
    mock_doc = MagicMock()
    monkeypatch.setattr("docx.Document", mock_doc)
    res = extract_docx_preview("dummy.docx", max_chars=8000)
    assert res == "OVERSIZED"
    assert not mock_doc.called

def test_extract_docx_too_many_members(monkeypatch, mock_i18n):
    monkeypatch.setattr("os.path.getsize", lambda x: 1000)
    mock_zip = MagicMock()
    mock_info = MagicMock()
    mock_info.file_size = 100
    mock_zip.infolist.return_value = [mock_info] * 2001

    mock_ZipFile = MagicMock()
    mock_ZipFile.return_value.__enter__.return_value = mock_zip
    monkeypatch.setattr("zipfile.ZipFile", mock_ZipFile)

    mock_doc = MagicMock()
    monkeypatch.setattr("docx.Document", mock_doc)

    res = extract_docx_preview("dummy.docx", max_chars=8000)
    assert res == "OVERSIZED"
    assert not mock_doc.called
