"""Owner-operated exact-ID Chroma maintenance, outside conversational tool bindings."""
from __future__ import annotations

from pathlib import Path
from typing import TypedDict
import uuid

from filelock import FileLock
from services.daily_backup_runtime import assert_quiescent, pause_held


class ReviewedMemory(TypedDict):
    """A complete reviewed record, with the reason authorizing its removal."""
    id: str
    document: str
    metadata: dict
    reason: str


def _record_map(data: dict) -> dict[str, tuple[str, dict]]:
    """Reject incomplete managed reads rather than accepting a partial inventory."""
    if data.get("_error") or not all(key in data for key in ("ids", "documents", "metadatas")):
        raise RuntimeError("maintenance_read_failed")
    if len(data["ids"]) != len(data["documents"]) or len(data["ids"]) != len(data["metadatas"]):
        raise RuntimeError("maintenance_read_failed")
    return {ident: (document, metadata or {}) for ident, document, metadata
            in zip(data["ids"], data["documents"], data["metadatas"])}


def delete_reviewed_memories(
    records: list[ReviewedMemory], *, collection_name: str, keeper_ids: list[str],
    owner_approved: bool = False,
) -> dict:
    """Delete reviewed IDs with durable intent, strict verification and a receipt.

    Caller must hold the native cold pause, exclude new launchers, and retain a
    verified pre-apply backup. Failures after the intent may require recovery;
    they never imply that deletion was rolled back. Structured profile data,
    conversation history and linked assets are not mutated by this operation.
    """
    if owner_approved is not True:
        raise ValueError("owner_authorization_required")
    if not records or not isinstance(collection_name, str) or not collection_name:
        raise ValueError("invalid_maintenance_plan")
    for row in records:
        if (not isinstance(row, dict) or not isinstance(row.get("id"), str) or not row["id"]
                or not isinstance(row.get("document"), str) or not isinstance(row.get("metadata"), dict)
                or not isinstance(row.get("reason"), str) or not row["reason"].strip()):
            raise ValueError("invalid_reviewed_record")
    ids = [row["id"] for row in records]
    if len(set(ids)) != len(ids) or not isinstance(keeper_ids, list) or any(not isinstance(ident, str) or not ident for ident in keeper_ids):
        raise ValueError("invalid_maintenance_ids")
    if set(ids) & set(keeper_ids):
        raise ValueError("keeper_selected_for_deletion")
    if not pause_held():
        raise RuntimeError("maintenance_pause_required")
    assert_quiescent()
    # Resolve the existing managed handle only after maintenance preconditions.
    from memory import vector_store as vs
    if vs.vector_store._collection.name != collection_name:
        raise ValueError("maintenance_collection_mismatch")
    with FileLock(str(Path(vs.CHROMA_DB_DIR) / ".maintenance.lock"), timeout=0), vs.vector_lock, vs.memory_lock:
        assert_quiescent()
        before = _record_map(vs._safe_chroma_get(include=["documents", "metadatas"]))
        if not set(keeper_ids) <= before.keys():
            raise ValueError("maintenance_keeper_missing")
        if any(before.get(row["id"]) != (row["document"], row["metadata"]) for row in records):
            raise ValueError("reviewed_record_changed")
        operation_id = uuid.uuid4().hex
        audit = {"operation_id": operation_id, "collection": collection_name, "ids": ids,
                 "reasons": {row["id"]: row["reason"] for row in records}, "keeper_ids": keeper_ids,
                 "before_count": len(before), "agent": "OwnerApprovedMaintenance"}
        if not vs._audit_log("maintenance_delete_prepare", require_valid_log=True, **audit):
            raise RuntimeError("audit_prepare_failed")
        assert_quiescent()
        if not vs._safe_chroma_delete(ids):
            raise RuntimeError("maintenance_delete_failed")
        after = _record_map(vs._safe_chroma_get(include=["documents", "metadatas"]))
        expected = {ident: value for ident, value in before.items() if ident not in set(ids)}
        if after != expected:
            raise RuntimeError("maintenance_verification_failed")
        assert_quiescent()
        if not vs._audit_log("maintenance_delete", require_valid_log=True, after_count=len(after), **audit):
            raise RuntimeError("audit_completion_failed")
        return {"operation_id": operation_id, "deleted_ids": ids, "before_count": len(before), "after_count": len(after)}
