"""Offline contracts for channel-neutral confirmed photo storage."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from core.ai_provider import EmbeddingsProviderSetupRequired
import memory.vector_store as vector_store_module
import services.pending_asset_confirmation as confirmation_module
from memory.vector_store import AstakosMemoryManager
from services.pending_asset_confirmation import PendingAssetConfirmationService


class _RecordingMemory:
    def __init__(self) -> None:
        self.saved: list[dict] = []

    def save(self, **kwargs) -> bool:
        self.saved.append(kwargs)
        return True


class _RejectingMemory:
    def save(self, **kwargs) -> bool:
        return False


def _prepare_confirmed_photo(
    monkeypatch: pytest.MonkeyPatch,
    *,
    source: Path,
    photos_dir: Path,
    memory_store=None,
) -> tuple[PendingAssetConfirmationService, object, list[int]]:
    memory = memory_store or _RecordingMemory()
    confirmed: list[int] = []
    pending = {
        "id": 17,
        "asset_type": "photo",
        "file_path": str(source),
        "filename": source.name,
        "analysis": "Ο Αλέξανδρος κρατά την κατασκευή.",
        "caption": "Η κατασκευή μας",
        "external_content_sources": ["user_provided_asset"],
    }
    monkeypatch.setattr(confirmation_module, "PHOTOS_DIR", str(photos_dir), raising=False)
    monkeypatch.setattr(
        confirmation_module,
        "get_latest_pending_asset_any",
        lambda channel: pending,
    )
    monkeypatch.setattr(confirmation_module, "init_pending_assets_table", lambda: None)
    monkeypatch.setattr(confirmation_module, "clear_expired_pending_assets", lambda: None)
    monkeypatch.setattr(confirmation_module, "classify_pending_asset_reply", lambda _: "yes")
    monkeypatch.setattr(
        confirmation_module,
        "is_reply_to_recent_asset_prompt",
        lambda *args, **kwargs: True,
    )
    monkeypatch.setattr(
        confirmation_module,
        "mark_pending_asset_confirmed",
        lambda asset_id: confirmed.append(asset_id),
    )
    monkeypatch.setattr(confirmation_module, "append_message", lambda **kwargs: kwargs)

    service = PendingAssetConfirmationService(
        channel="matrix",
        memory_store=memory,
        confirm_reply="Αποθηκεύτηκε.",
        cancel_reply="Δεν αποθηκεύτηκε.",
        failure_reply="Δεν αποθηκεύτηκε· δοκίμασε ξανά.",
        conversation_db_path=str(photos_dir.parent / "conversation.db"),
    )
    return service, memory, confirmed


@pytest.mark.asyncio
async def test_confirmed_matrix_photo_is_copied_to_common_photo_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    matrix_dir = tmp_path / "matrix_media"
    matrix_dir.mkdir()
    source = matrix_dir / "matrix_event.jpg"
    source.write_bytes(b"matrix-photo-bytes")
    photos_dir = tmp_path / "telegram_photos"
    service, memory, confirmed = _prepare_confirmed_photo(
        monkeypatch,
        source=source,
        photos_dir=photos_dir,
    )

    response = await service("ναι", "$confirm")

    saved_path = Path(memory.saved[0]["file_path"])
    assert response == "Αποθηκεύτηκε."
    assert confirmed == [17]
    assert saved_path.parent == photos_dir.resolve()
    assert saved_path.read_bytes() == b"matrix-photo-bytes"
    assert source.read_bytes() == b"matrix-photo-bytes"


@pytest.mark.asyncio
async def test_confirmed_photo_already_in_common_directory_keeps_same_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    photos_dir = tmp_path / "telegram_photos"
    photos_dir.mkdir()
    source = photos_dir / "photo_20260922_120000.jpg"
    source.write_bytes(b"telegram-photo-bytes")
    service, memory, _ = _prepare_confirmed_photo(
        monkeypatch,
        source=source,
        photos_dir=photos_dir,
    )

    await service("ναι", "$confirm")

    assert Path(memory.saved[0]["file_path"]) == source.resolve()
    assert list(photos_dir.iterdir()) == [source]


@pytest.mark.asyncio
async def test_confirmed_matrix_photo_is_indexed_and_retrievable_from_shared_archive(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tools import system

    matrix_dir = tmp_path / "matrix_media"
    matrix_dir.mkdir()
    source = matrix_dir / "matrix_event.jpg"
    source.write_bytes(b"shared-photo-bytes")
    photos_dir = tmp_path / "telegram_photos"
    index_path = tmp_path / "astakos_photos_index.json"
    add_texts = MagicMock()
    monkeypatch.setattr(vector_store_module, "PHOTOS_INDEX_FILE", str(index_path))
    monkeypatch.setattr(vector_store_module.vector_store, "add_texts", add_texts)
    service, _, _ = _prepare_confirmed_photo(
        monkeypatch,
        source=source,
        photos_dir=photos_dir,
        memory_store=AstakosMemoryManager(),
    )

    await service("ναι", "$confirm")

    canonical_path = next(photos_dir.iterdir()).resolve()
    metadata = add_texts.call_args.kwargs["metadatas"][0]
    assert Path(metadata["photo_path"]) == canonical_path
    archive = json.loads(index_path.read_text(encoding="utf-8"))
    assert Path(archive[0]["file_path"]) == canonical_path

    monkeypatch.setattr(system, "PHOTOS_INDEX_FILE", str(index_path))
    monkeypatch.setattr(
        system.embeddings,
        "embed_query",
        lambda _: (_ for _ in ()).throw(
            EmbeddingsProviderSetupRequired(
                "No provider needed for archive fallback.",
                provider="offline-test",
            )
        ),
    )
    result = system.retrieve_photo.func("Αλέξανδρος κατασκευή")

    assert f"[SEND_PHOTO: {canonical_path}]" in result


@pytest.mark.asyncio
async def test_missing_confirmed_photo_returns_retry_reply_and_remains_pending(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "matrix_media" / "missing.jpg"
    photos_dir = tmp_path / "telegram_photos"
    service, _, confirmed = _prepare_confirmed_photo(
        monkeypatch,
        source=source,
        photos_dir=photos_dir,
    )
    response = await service("ναι", "$confirm")

    assert response == "Δεν αποθηκεύτηκε· δοκίμασε ξανά."
    assert confirmed == []


@pytest.mark.asyncio
async def test_rejected_photo_index_returns_retry_reply_and_remains_pending(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    photos_dir = tmp_path / "telegram_photos"
    photos_dir.mkdir()
    source = photos_dir / "photo.jpg"
    source.write_bytes(b"photo-bytes")
    service, _, confirmed = _prepare_confirmed_photo(
        monkeypatch,
        source=source,
        photos_dir=photos_dir,
        memory_store=_RejectingMemory(),
    )
    response = await service("ναι", "$confirm")

    assert response == "Δεν αποθηκεύτηκε· δοκίμασε ξανά."
    assert confirmed == []


@pytest.mark.asyncio
async def test_confirmed_document_is_copied_to_common_document_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_dir = tmp_path / "matrix_media"
    source_dir.mkdir()
    source = source_dir / "matrix_report.pdf"
    source.write_bytes(b"document-bytes")
    documents_dir = tmp_path / "documents_archive"
    memory = _RecordingMemory()
    confirmed: list[int] = []
    pending = {
        "id": 23,
        "asset_type": "document",
        "file_path": str(source),
        "filename": "quarterly-report.pdf",
        "analysis": "Quarterly report",
        "caption": "Report",
        "external_content_sources": ["user_provided_asset"],
    }
    monkeypatch.setattr(
        confirmation_module, "DOCUMENTS_DIR", str(documents_dir), raising=False
    )
    monkeypatch.setattr(
        confirmation_module,
        "get_latest_pending_asset_any",
        lambda channel: pending,
        raising=False,
    )
    monkeypatch.setattr(confirmation_module, "init_pending_assets_table", lambda: None)
    monkeypatch.setattr(confirmation_module, "clear_expired_pending_assets", lambda: None)
    monkeypatch.setattr(confirmation_module, "classify_pending_asset_reply", lambda _: "yes")
    monkeypatch.setattr(
        confirmation_module,
        "is_reply_to_recent_asset_prompt",
        lambda *args, **kwargs: True,
    )
    monkeypatch.setattr(
        confirmation_module,
        "mark_pending_asset_confirmed",
        lambda asset_id: confirmed.append(asset_id),
    )
    monkeypatch.setattr(confirmation_module, "append_message", lambda **kwargs: kwargs)
    service = PendingAssetConfirmationService(
        channel="matrix",
        memory_store=memory,
        confirm_reply="Saved.",
        cancel_reply="Cancelled.",
        conversation_db_path=str(tmp_path / "conversation.db"),
    )

    assert await service("yes", "$confirm-document") == "Saved."

    saved_path = Path(memory.saved[0]["file_path"])
    assert confirmed == [23]
    assert saved_path.parent == documents_dir.resolve()
    assert saved_path.name.startswith("document_")
    assert saved_path.suffix == ".pdf"
    assert saved_path.read_bytes() == b"document-bytes"
    assert source.read_bytes() == b"document-bytes"
    assert memory.saved[0]["caption"] == "quarterly-report.pdf — Report"


def test_retrieve_document_returns_original_archived_file_without_embeddings(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tools import system

    document = tmp_path / "document_abc.pdf"
    document.write_bytes(b"report")
    index_path = tmp_path / "astakos_docs_index.json"
    index_path.write_text(
        json.dumps(
            [
                {
                    "file_path": str(document),
                    "caption": "Quarterly logistics report",
                    "summary": "Warehouse performance and deliveries",
                    "date": "2026-09-22",
                }
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(system, "DOCS_INDEX_FILE", str(index_path), raising=False)
    monkeypatch.setattr(
        system.embeddings,
        "embed_query",
        lambda _: (_ for _ in ()).throw(
            EmbeddingsProviderSetupRequired("offline", provider="offline-test")
        ),
    )

    result = system.retrieve_document.func("logistics report")

    assert "Quarterly logistics report" in result
    assert f"[CREATED_FILE: {document}]" in result


@pytest.mark.parametrize(
    ("query", "description"),
    [
        ("missing annual budget", "Quarterly logistics report | Warehouse deliveries"),
        ("missing document", "Quarterly logistics report | Warehouse deliveries"),
        ("annual budget", "Annual logistics report | Warehouse deliveries"),
    ],
)
def test_retrieve_document_does_not_deliver_unrelated_semantic_neighbor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    query: str,
    description: str,
) -> None:
    from tools import system

    unrelated = tmp_path / "quarterly-logistics.pdf"
    unrelated.write_bytes(b"report")
    monkeypatch.setattr(system, "DOCS_INDEX_FILE", str(tmp_path / "no-index.json"))
    monkeypatch.setattr(system.embeddings, "embed_query", lambda _: [0.1, 0.2])
    monkeypatch.setattr(
        system.vector_memory,
        "safe_similarity_search",
        lambda *args, **kwargs: [
            SimpleNamespace(
                page_content=f"[DOCUMENT]: {description}",
                metadata={"file_path": str(unrelated)},
            )
        ],
    )

    result = system.retrieve_document.func(query)

    assert result == "System: Document not found."
    assert "[CREATED_FILE:" not in result


def test_retrieve_document_skips_unrelated_neighbor_for_relevant_one(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tools import system

    unrelated = tmp_path / "logistics.pdf"
    relevant = tmp_path / "budget.pdf"
    unrelated.write_bytes(b"logistics")
    relevant.write_bytes(b"budget")
    monkeypatch.setattr(system, "DOCS_INDEX_FILE", str(tmp_path / "no-index.json"))
    monkeypatch.setattr(system.embeddings, "embed_query", lambda _: [0.1, 0.2])
    monkeypatch.setattr(
        system.vector_memory,
        "safe_similarity_search",
        lambda *args, **kwargs: [
            SimpleNamespace(
                page_content="[DOCUMENT]: Annual logistics report | Warehouse deliveries",
                metadata={"file_path": str(unrelated)},
            ),
            SimpleNamespace(
                page_content="[DOCUMENT]: Annual budget | Operating expenses",
                metadata={"file_path": str(relevant)},
            ),
        ],
    )

    result = system.retrieve_document.func("annual budget")

    assert f"[CREATED_FILE: {relevant}]" in result
    assert str(unrelated) not in result


def test_retrieve_document_lexical_fallback_rejects_partial_match(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tools import system

    unrelated = tmp_path / "annual-logistics.pdf"
    unrelated.write_bytes(b"logistics")
    index_path = tmp_path / "documents-index.json"
    index_path.write_text(
        json.dumps([{
            "file_path": str(unrelated),
            "caption": "Annual logistics report",
            "summary": "Warehouse deliveries",
        }]),
        encoding="utf-8",
    )
    monkeypatch.setattr(system, "DOCS_INDEX_FILE", str(index_path))
    monkeypatch.setattr(
        system.embeddings,
        "embed_query",
        lambda _: (_ for _ in ()).throw(
            EmbeddingsProviderSetupRequired("offline", provider="offline-test")
        ),
    )

    result = system.retrieve_document.func("annual budget")

    assert result == "System: Document not found."
