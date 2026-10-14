"""Owner-approved maintenance against real temporary Chroma; no live stores/network."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Iterator

import pytest
from langchain_chroma import Chroma
from chromadb.config import Settings
from memory import maintenance, vector_store as vs


@pytest.fixture
def store(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, offline_behavioral_io: None) -> Iterator[Chroma]:
    """Bind the managed primitives to an isolated real collection and audit directory."""
    chroma = Chroma(collection_name="maintenance_fixture", persist_directory=str(tmp_path / "chroma"),
                    client_settings=Settings(anonymized_telemetry=False))
    monkeypatch.setattr(vs, "vector_store", chroma)
    monkeypatch.setattr(vs, "CHROMA_DB_DIR", str(tmp_path / "chroma"))
    monkeypatch.setattr(vs, "MEMORY_AUDIT_DIR", str(tmp_path / "audit"))
    monkeypatch.setattr(maintenance, "pause_held", lambda: True)
    monkeypatch.setattr(maintenance, "assert_quiescent", lambda: None)
    vs._safe_chroma_add_texts(["Synthetic duplicate", "Synthetic duplicate", "Synthetic retained"],
                             ids=["remove", "keep", "other"],
                             metadatas=[{"category": "preferences", "date": "2026-01-01"}] * 3,
                             embeddings=[[0.1, 0.2, 0.3]] * 3)
    yield chroma
    chroma._client.close()


def plan() -> list[dict]:
    """Return one exact reviewed fixture record with a deletion reason."""
    return [{"id": "remove", "document": "Synthetic duplicate",
             "metadata": {"category": "preferences", "date": "2026-01-01"}, "reason": "verified duplicate"}]


def apply(records: list[dict] | None = None, **kwargs: object) -> dict:
    """Exercise the public operator entry point with fixture authorization."""
    return maintenance.delete_reviewed_memories(plan() if records is None else records,
        collection_name="maintenance_fixture", keeper_ids=["keep"], owner_approved=True, **kwargs)


def receipts() -> list[dict]:
    """Read only the temporary audit journal produced by the operation."""
    return json.loads((Path(vs.MEMORY_AUDIT_DIR) / f"{datetime.now().date().isoformat()}.json").read_text())


def test_exact_delete_preserves_profile_and_unselected_records_with_audit(store: Chroma) -> None:
    """Final persisted Chroma/profile state and correlated receipts agree."""
    assert vs.AstakosMemoryManager()._save_fact_profile_only(
        fact="Synthetic duplicate", category="preferences", agent_name="offline_fixture")
    profile_before = vs.get_profile_facts("preferences")
    before = store._collection.get(include=["documents", "metadatas"])
    result = apply()
    after = store._collection.get(include=["documents", "metadatas"])
    assert set(after["ids"]) == {"keep", "other"}
    for ident, doc, meta in zip(after["ids"], after["documents"], after["metadatas"]):
        index = before["ids"].index(ident)
        assert (doc, meta) == (before["documents"][index], before["metadatas"][index])
    assert vs.get_profile_facts("preferences") == profile_before
    assert result["deleted_ids"] == ["remove"]
    journal = receipts()
    assert [entry["op"] for entry in journal] == ["maintenance_delete_prepare", "maintenance_delete"]
    assert {entry["operation_id"] for entry in journal} == {result["operation_id"]}
    assert journal[0]["ids"] == ["remove"]
    assert journal[0]["reasons"] == {"remove": "verified duplicate"}


@pytest.mark.parametrize("case", ["not_approved", "no_pause", "wrong_collection", "duplicate_ids",
                                 "changed_record", "missing_keeper", "keeper_selected"])
def test_invalid_plan_preserves_every_record(store: Chroma, monkeypatch: pytest.MonkeyPatch, case: str) -> None:
    """Authorization, maintenance state and provenance failures never mutate Chroma."""
    records = plan()
    options = {"collection_name": "maintenance_fixture", "keeper_ids": ["keep"], "owner_approved": True}
    if case == "not_approved": options["owner_approved"] = False
    if case == "no_pause": monkeypatch.setattr(maintenance, "pause_held", lambda: False)
    if case == "wrong_collection": options["collection_name"] = "another_collection"
    if case == "duplicate_ids": records += plan()
    if case == "changed_record": records[0]["metadata"]["date"] = "2026-02-01"
    if case == "missing_keeper": options["keeper_ids"] = ["missing"]
    if case == "keeper_selected": options["keeper_ids"] = ["remove"]
    with pytest.raises((ValueError, RuntimeError)):
        maintenance.delete_reviewed_memories(records, **options)
    assert set(store._collection.get()["ids"]) == {"remove", "keep", "other"}


def test_audit_prepare_failure_prevents_deletion(store: Chroma, monkeypatch: pytest.MonkeyPatch) -> None:
    """A failed durable intent stops deletion before the managed writer is called."""
    monkeypatch.setattr(vs, "_audit_log", lambda *args, **kwargs: False)
    with pytest.raises(RuntimeError, match="audit_prepare_failed"):
        apply()
    assert set(store._collection.get()["ids"]) == {"remove", "keep", "other"}


def test_corrupt_audit_is_not_overwritten_and_records_survive(store: Chroma) -> None:
    """Strict maintenance logging does not silently replace a corrupt journal."""
    audit = Path(vs.MEMORY_AUDIT_DIR) / f"{datetime.now().date().isoformat()}.json"
    audit.parent.mkdir()
    audit.write_text("not valid JSON")
    with pytest.raises(RuntimeError, match="audit_prepare_failed"):
        apply()
    assert audit.read_text() == "not valid JSON"
    assert store._collection.count() == 3


def test_completion_failure_leaves_durable_intent_for_recovery(store: Chroma, monkeypatch: pytest.MonkeyPatch) -> None:
    """An uncertain completion signals failure while retaining the pre-delete receipt."""
    original = vs._audit_log
    monkeypatch.setattr(vs, "_audit_log", lambda op, **kwargs: False if op == "maintenance_delete" else original(op, **kwargs))
    with pytest.raises(RuntimeError, match="audit_completion_failed"):
        apply()
    assert set(store._collection.get()["ids"]) == {"keep", "other"}
    assert [entry["op"] for entry in receipts()] == ["maintenance_delete_prepare"]
