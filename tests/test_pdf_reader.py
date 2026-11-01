import pytest
import pypdf
import os
from unittest.mock import MagicMock, patch
from core.utils import extract_pdf_preview

@pytest.fixture
def mock_i18n(monkeypatch):
    """Ensure translations return predictable values for tests."""
    def mock_t(key, **kwargs):
        if key == "api.server.pdf_encrypted":
            return "ENCRYPTED"
        if key == "api.server.pdf_empty_or_scanned":
            return "EMPTY_OR_SCANNED"
        if key == "api.server.pdf_unreadable_generic":
            return "UNREADABLE"
        if key == "api.server.pdf_page_meta":
            return f"[Meta: {kwargs.get('extracted')} of {kwargs.get('total')}]"
        return key
    monkeypatch.setattr("core.i18n.t", mock_t)

def test_extract_pdf_encrypted_failure(monkeypatch, mock_i18n):
    mock_reader = MagicMock()
    mock_reader.is_encrypted = True
    mock_reader.decrypt.return_value = 0 # Falsy
    monkeypatch.setattr("pypdf.PdfReader", lambda x: mock_reader)

    res = extract_pdf_preview("dummy.pdf")
    assert res == "ENCRYPTED"
    mock_reader.decrypt.assert_called_once_with("")
    assert not mock_reader.pages.called

def test_extract_pdf_encrypted_success(monkeypatch, mock_i18n):
    mock_page1 = MagicMock()
    mock_page1.extract_text.return_value = "Secret content"

    mock_reader = MagicMock()
    mock_reader.is_encrypted = True
    mock_reader.decrypt.return_value = 1 # Truthy PasswordType
    mock_reader.pages = [mock_page1]
    monkeypatch.setattr("pypdf.PdfReader", lambda x: mock_reader)

    res = extract_pdf_preview("dummy.pdf", max_chars=8000)
    assert "Secret content" in res
    assert res != "ENCRYPTED"

def test_extract_pdf_empty_or_scanned(monkeypatch, mock_i18n):
    mock_page = MagicMock()
    mock_page.extract_text.return_value = "   "

    mock_reader = MagicMock()
    mock_reader.is_encrypted = False
    mock_reader.pages = [mock_page]
    monkeypatch.setattr("pypdf.PdfReader", lambda x: mock_reader)

    res = extract_pdf_preview("dummy.pdf")
    assert res == "EMPTY_OR_SCANNED"

def test_extract_pdf_malformed(monkeypatch, mock_i18n):
    def raise_error(x):
        raise ValueError("Bad PDF")

    monkeypatch.setattr("pypdf.PdfReader", raise_error)

    res = extract_pdf_preview("dummy.pdf")
    assert res == "UNREADABLE"

def test_extract_pdf_bounded_extraction(monkeypatch, mock_i18n):
    mock_page1 = MagicMock()
    mock_page1.extract_text.return_value = "A" * 5000

    mock_page2 = MagicMock()
    mock_page2.extract_text.return_value = "B" * 5000

    mock_page3 = MagicMock() # Should not be reached
    mock_page3.extract_text.side_effect = Exception("Should not be called")

    mock_reader = MagicMock()
    mock_reader.is_encrypted = False
    mock_reader.pages = [mock_page1, mock_page2, mock_page3]

    monkeypatch.setattr("pypdf.PdfReader", lambda x: mock_reader)

    res = extract_pdf_preview("dummy.pdf", max_chars=8000)

    assert mock_page1.extract_text.called
    assert mock_page2.extract_text.called
    assert not mock_page3.extract_text.called

    # 5000 from page1, 3000 from page 2 = 8000
    # But wait, metadata also needs to be included!
    meta = "[Meta: 2 of 3]"
    assert res.endswith(meta)

    # Check max length
    assert len(res) == 8000
    assert res.startswith("A" * 5000 + "\n" + "B" * (8000 - 5000 - len(meta) - 2))

def test_extract_pdf_successful_metadata(monkeypatch, mock_i18n):
    mock_page1 = MagicMock()
    mock_page1.extract_text.return_value = "Hello world"

    mock_reader = MagicMock()
    mock_reader.is_encrypted = False
    mock_reader.pages = [mock_page1]

    monkeypatch.setattr("pypdf.PdfReader", lambda x: mock_reader)

    res = extract_pdf_preview("dummy.pdf", max_chars=8000)

    assert "Hello world" in res
    assert "[Meta: 1 of 1]" in res
    assert len(res) <= 8000

def test_extract_pdf_page_exception(monkeypatch, mock_i18n):
    mock_page1 = MagicMock()
    mock_page1.extract_text.side_effect = Exception("Corrupt page")

    mock_reader = MagicMock()
    mock_reader.is_encrypted = False
    mock_reader.pages = [mock_page1]

    monkeypatch.setattr("pypdf.PdfReader", lambda x: mock_reader)

    res = extract_pdf_preview("dummy.pdf", max_chars=8000)

    assert res == "UNREADABLE"

def test_extract_pdf_leading_whitespace_retained(monkeypatch, mock_i18n):
    mock_page1 = MagicMock()
    # String with leading whitespace
    mock_page1.extract_text.return_value = "   \n\t  Hello world  "

    mock_reader = MagicMock()
    mock_reader.is_encrypted = False
    mock_reader.pages = [mock_page1]

    monkeypatch.setattr("pypdf.PdfReader", lambda x: mock_reader)

    res = extract_pdf_preview("dummy.pdf", max_chars=8000)

    assert res.startswith("   \n\t  Hello world")
    assert res.endswith("[Meta: 1 of 1]")
    # Should not end with trailing space before meta because of rstrip()
    assert "Hello world\n[Meta" in res
