"""Offline persistence contracts for Matrix document analysis."""

from __future__ import annotations

from pathlib import Path

import pytest

import memory.pending_assets as pending_assets
import services.pending_asset_confirmation as confirmation_module
from clients.matrix_media import MatrixMediaAsset
from memory.conversation_history import load_messages
from services.matrix_document_turn import MatrixDocumentTurnService
from services.pending_asset_confirmation import PendingAssetConfirmationService


@pytest.mark.asyncio
async def test_document_analysis_is_persisted_and_staged_only_for_matrix(
    tmp_path, monkeypatch
) -> None:
    conversation_db = str(tmp_path / "conversation.db")
    monkeypatch.setattr(pending_assets, "STATE_DB", str(tmp_path / "state.db"))
    document_path = tmp_path / "matrix_file.pdf"
    document_path.write_bytes(b"pdf")
    asset = MatrixMediaAsset(
        event_id="$document-1",
        kind="file",
        path=document_path,
        mime_type="application/pdf",
        original_name="../../report`final.pdf",
    )
    persisted_users: list[dict] = []
    completed: list[tuple[str, str, str, str]] = []
    analyzed: list[MatrixMediaAsset] = []

    def analyze(item: MatrixMediaAsset) -> str:
        analyzed.append(item)
        return "Περιέχει τα βασικά οικονομικά στοιχεία."

    service = MatrixDocumentTurnService(
        analyze_document=analyze,
        conversation_db_path=conversation_db,
        on_user_persisted=persisted_users.append,
        on_exchange_completed=lambda *args: completed.append(args),
    )

    reply = await service(asset)

    assert analyzed == [asset]
    assert "reportfinal.pdf" in reply
    assert "../../" not in reply
    assert "Περιέχει τα βασικά" in reply
    assert pending_assets.looks_like_asset_confirmation_prompt(reply)

    stored = load_messages(channel="matrix", db_path=conversation_db)
    assert [item["role"] for item in stored] == ["user", "assistant"]
    assert stored[0]["metadata"]["matrix_event_id"] == "$document-1"
    assert stored[0]["metadata"]["untrusted_external_tool_names"] == [
        "user_provided_asset"
    ]
    assert stored[1]["metadata"]["untrusted_external_tool_names"] == [
        "user_provided_asset"
    ]
    pending = pending_assets.get_latest_pending_asset("matrix", "document")
    assert pending["filename"] == "reportfinal.pdf"
    assert pending["file_path"] == str(document_path)
    assert pending_assets.get_latest_pending_asset("telegram", "document") is None
    assert persisted_users[0]["channel"] == "matrix"
    assert completed == [("reportfinal.pdf", "", "Chat_Agent", "matrix")]

    saved_assets: list[dict] = []

    class FakeMemory:
        def save(self, **kwargs):
            saved_assets.append(kwargs)
            return True

    confirmation = PendingAssetConfirmationService(
        channel="matrix",
        memory_store=FakeMemory(),
        conversation_db_path=conversation_db,
        confirm_reply="Αποθηκεύτηκε.",
        cancel_reply="Δεν αποθηκεύτηκε.",
    )
    documents_dir = tmp_path / "documents_archive"
    monkeypatch.setattr(confirmation_module, "DOCUMENTS_DIR", str(documents_dir))
    assert await confirmation("ναι", "$confirm-1") == "Αποθηκεύτηκε."
    assert saved_assets[0]["memory_type"] == "document"
    assert Path(saved_assets[0]["file_path"]).parent == documents_dir.resolve()
    assert Path(saved_assets[0]["file_path"]).read_bytes() == b"pdf"
    assert saved_assets[0]["analysis"] == "Περιέχει τα βασικά οικονομικά στοιχεία."
    assert saved_assets[0]["caption"] == "reportfinal.pdf"
    assert saved_assets[0]["external_content_sources"] == ["user_provided_asset"]
    assert pending_assets.get_latest_pending_asset("matrix", "document") is None


@pytest.mark.asyncio
async def test_generic_yes_without_recent_matrix_archive_prompt_is_not_consumed(
    tmp_path, monkeypatch
) -> None:
    conversation_db = str(tmp_path / "conversation.db")
    monkeypatch.setattr(pending_assets, "STATE_DB", str(tmp_path / "state.db"))
    pending_assets.init_pending_assets_table()
    pending_assets.create_pending_asset_archive(
        channel="matrix",
        asset_type="document",
        file_path=str(tmp_path / "old.pdf"),
        filename="old.pdf",
        analysis="old",
    )
    service = PendingAssetConfirmationService(
        channel="matrix",
        memory_store=type("Memory", (), {"save": lambda self, **kwargs: None})(),
        conversation_db_path=conversation_db,
        confirm_reply="saved",
        cancel_reply="cancelled",
    )

    assert await service("ναι", "$unrelated") is None


@pytest.mark.asyncio
async def test_non_file_asset_is_rejected(tmp_path) -> None:
    path = tmp_path / "photo.png"
    path.write_bytes(b"png")
    asset = MatrixMediaAsset("$image", "image", path, "image/png", "photo.png")
    service = MatrixDocumentTurnService(
        analyze_document=lambda item: "unused",
        conversation_db_path=str(tmp_path / "conversation.db"),
    )

    with pytest.raises(ValueError, match="file asset"):
        await service(asset)


@pytest.mark.asyncio
async def test_matrix_document_caption_is_preserved_for_analysis_and_archive(
    tmp_path, monkeypatch
) -> None:
    conversation_db = str(tmp_path / "conversation.db")
    monkeypatch.setattr(pending_assets, "STATE_DB", str(tmp_path / "state.db"))
    document_path = tmp_path / "report.pdf"
    document_path.write_bytes(b"pdf")
    asset = MatrixMediaAsset(
        event_id="$captioned-document",
        kind="file",
        path=document_path,
        mime_type="application/pdf",
        original_name="report.pdf",
        caption="Έλεγξε ιδιαίτερα τα σύνολα.",
    )
    seen_captions: list[str] = []

    def analyze(item: MatrixMediaAsset) -> str:
        seen_captions.append(item.caption)
        return "Τα σύνολα ελέγχθηκαν."

    service = MatrixDocumentTurnService(
        analyze_document=analyze,
        conversation_db_path=conversation_db,
    )

    await service(asset)

    pending = pending_assets.get_latest_pending_asset("matrix", "document")
    assert seen_captions == ["Έλεγξε ιδιαίτερα τα σύνολα."]
    assert pending is not None
    assert pending["caption"] == "Έλεγξε ιδιαίτερα τα σύνολα."


@pytest.mark.asyncio
async def test_unreadable_matrix_document_does_not_create_archive_prompt(
    tmp_path, monkeypatch
) -> None:
    from services.document_input import DocumentPreviewError

    monkeypatch.setattr(pending_assets, "STATE_DB", str(tmp_path / "state.db"))
    pending_assets.init_pending_assets_table()
    path = tmp_path / "broken.pdf"
    path.write_bytes(b"broken")
    asset = MatrixMediaAsset(
        "$broken",
        "file",
        path,
        "application/pdf",
        "broken.pdf",
    )
    service = MatrixDocumentTurnService(
        analyze_document=lambda _: (_ for _ in ()).throw(
            DocumentPreviewError("The PDF is unreadable.")
        ),
        conversation_db_path=str(tmp_path / "conversation.db"),
    )

    reply = await service(asset)

    assert "unreadable" in reply
    assert not pending_assets.looks_like_asset_confirmation_prompt(reply)
    assert pending_assets.get_latest_pending_asset("matrix", "document") is None
