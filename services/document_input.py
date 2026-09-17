"""Channel-neutral document preview extraction for user uploads."""

from __future__ import annotations

from pathlib import Path


SUPPORTED_DOCUMENT_EXTENSIONS = frozenset(
    {".txt", ".csv", ".json", ".md", ".pdf", ".docx", ".xlsx", ".xls"}
)


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
    return extractor(str(path), max_chars=max_chars)
