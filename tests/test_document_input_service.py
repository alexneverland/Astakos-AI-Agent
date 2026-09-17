"""Offline contracts for shared uploaded-document extraction."""

from __future__ import annotations

from pathlib import Path

import pytest

from services.document_input import (
    SUPPORTED_DOCUMENT_EXTENSIONS,
    extract_document_preview,
)


@pytest.mark.parametrize(
    ("suffix", "extractor_name"),
    [
        (".txt", "extract_text_preview"),
        (".csv", "extract_text_preview"),
        (".json", "extract_text_preview"),
        (".md", "extract_text_preview"),
        (".pdf", "extract_pdf_preview"),
        (".docx", "extract_docx_preview"),
        (".xlsx", "extract_xlsx_preview"),
        (".xls", "extract_xlsx_preview"),
    ],
)
def test_supported_suffix_uses_existing_bounded_extractor(
    tmp_path, monkeypatch, suffix, extractor_name
) -> None:
    path = tmp_path / f"document{suffix}"
    path.write_bytes(b"content")
    calls: list[tuple[str, int]] = []

    def extractor(file_path: str, max_chars: int) -> str:
        calls.append((file_path, max_chars))
        return f"preview:{suffix}"

    monkeypatch.setattr(f"core.utils.{extractor_name}", extractor)

    assert extract_document_preview(path, max_chars=8000) == f"preview:{suffix}"
    assert calls == [(str(path), 8000)]
    assert suffix in SUPPORTED_DOCUMENT_EXTENSIONS


def test_unsupported_document_suffix_is_rejected(tmp_path) -> None:
    path = tmp_path / "payload.exe"
    path.write_bytes(b"content")

    with pytest.raises(ValueError, match="Unsupported document type"):
        extract_document_preview(path)


def test_missing_document_is_rejected(tmp_path) -> None:
    with pytest.raises(FileNotFoundError):
        extract_document_preview(tmp_path / "missing.pdf")
