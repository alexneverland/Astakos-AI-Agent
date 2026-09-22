"""Channel-neutral document preview extraction for user uploads."""

from __future__ import annotations

from pathlib import Path


SUPPORTED_DOCUMENT_EXTENSIONS = frozenset(
    {".txt", ".csv", ".json", ".md", ".pdf", ".docx", ".xlsx", ".xls"}
)


class DocumentPreviewError(ValueError):
    """The uploaded document exists but cannot provide trustworthy preview text."""


def ensure_document_preview_readable(preview: str) -> str:
    """Convert the existing localized extractor failure values into typed failure."""
    from core.i18n import t

    failure_keys = (
        "api.server.pdf_encrypted",
        "api.server.pdf_empty_or_scanned",
        "api.server.pdf_unreadable_generic",
        "api.server.docx_oversized_uncompressed",
        "api.server.docx_unreadable_generic",
        "api.server.docx_corrupt",
        "api.server.docx_empty_or_scanned",
        "api.server.text_empty",
        "api.server.text_unreadable_generic",
        "api.server.xlsx_oversized_uncompressed",
        "api.server.xlsx_unreadable_generic",
        "api.server.xlsx_corrupt",
    )
    normalized = str(preview or "").strip()
    if not normalized or normalized in {str(t(key)).strip() for key in failure_keys}:
        raise DocumentPreviewError(normalized or str(t("api.server.text_empty")))
    return preview


def extract_document_preview(
    file_path: str | Path,
    *,
    max_chars: int = 8000,
) -> str:
    """Use the existing bounded extractor selected by the local file suffix."""
    path = Path(file_path)
    if not path.is_file():
        raise FileNotFoundError(str(path))
    suffix = path.suffix.lower()
    if suffix not in SUPPORTED_DOCUMENT_EXTENSIONS:
        raise ValueError(f"Unsupported document type: {suffix or '(none)'}")

    from core.utils import (
        extract_docx_preview,
        extract_pdf_preview,
        extract_text_preview,
        extract_xlsx_preview,
    )

    if suffix in {".txt", ".csv", ".json", ".md"}:
        extractor = extract_text_preview
    elif suffix == ".pdf":
        extractor = extract_pdf_preview
    elif suffix == ".docx":
        extractor = extract_docx_preview
    else:
        extractor = extract_xlsx_preview
    preview = extractor(str(path), max_chars=max_chars)
    return ensure_document_preview_readable(preview)
