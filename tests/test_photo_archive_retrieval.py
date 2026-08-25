import json
import threading

from core.ai_provider import EmbeddingsProviderSetupRequired


def test_retrieve_photo_uses_archive_when_embeddings_are_unavailable(monkeypatch, tmp_path):
    """Confirmed archived photos remain retrievable without semantic embeddings."""
    from tools import system

    photo_path = tmp_path / "alexander-park.jpg"
    photo_path.write_bytes(b"photo")
    index_path = tmp_path / "photos_index.json"
    index_path.write_text(
        json.dumps([
            {
                "file_path": str(photo_path),
                "caption": "Ο Αλέξανδρος στο πάρκο",
                "analysis": "Ο Αλέξανδρος παίζει μπάλα στο πάρκο.",
                "date": "2026-08-25",
            },
        ], ensure_ascii=False),
        encoding="utf-8",
    )

    monkeypatch.setattr(system, "PHOTOS_INDEX_FILE", str(index_path))
    monkeypatch.setattr(system, "vector_lock", threading.Lock())
    monkeypatch.setattr(
        system.vector_memory,
        "safe_similarity_search",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            EmbeddingsProviderSetupRequired(
                "Configure an embeddings provider.",
                provider="anthropic",
            ),
        ),
    )

    result = system.retrieve_photo.func("φωτογραφία Αλέξανδρος πάρκο")

    assert "matched from the local photo archive" in result
    assert f"[SEND_PHOTO: {photo_path}]" in result
