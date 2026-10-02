"""Atomic cross-process ledger for behavioral conversation delivery."""
from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
from typing import Any

from filelock import FileLock


class InitiativeStore:
    """Hold the lock across decision/send; failed or damaged state fails closed."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def lock(self) -> FileLock:
        """Serialize workers without blocking the scheduler on another worker."""
        return FileLock(str(self.path) + ".lock", timeout=0)

    @staticmethod
    def _validate(state: Any) -> None:
        """Validate persisted delivery identities and receipt lifecycle."""
        if not isinstance(state, dict) or set(state) != {"version", "delivered", "pending", "evaluated"} or state["version"] != 1:
            raise ValueError("Invalid behavioral initiative state")
        evaluation = state["evaluated"]
        if evaluation is not None:
            if not isinstance(evaluation, dict) or set(evaluation) != {"day", "snapshot", "preferences", "context"}:
                raise ValueError("Invalid initiative evaluation")
            from datetime import date
            date.fromisoformat(evaluation["day"])
            if not isinstance(evaluation["snapshot"], list) or not isinstance(evaluation["preferences"], list) or not isinstance(evaluation["context"], dict):
                raise ValueError("Invalid evaluation snapshot")
        if not isinstance(state["delivered"], list) or len(state["delivered"]) > 32:
            raise ValueError("Invalid initiative delivery history")
        records = list(state["delivered"])
        if state["pending"] is not None:
            records.append(state["pending"])
        for item in records:
            keys = {"id", "topic", "channel", "text", "created_at", "snapshot", "preferences", "context", "external_id", "delivered_at"}
            if not isinstance(item, dict) or set(item) != keys:
                raise ValueError("Invalid initiative record")
            if any(not isinstance(item[k], str) or not item[k].strip() for k in ("id", "topic", "text", "created_at")):
                raise ValueError("Invalid initiative text")
            if item["channel"] not in {"matrix", "telegram"} or len(item["text"]) > 500:
                raise ValueError("Invalid initiative transport")
            if not isinstance(item["snapshot"], list) or not isinstance(item["preferences"], list) or not isinstance(item["context"], dict):
                raise ValueError("Invalid initiative snapshot")
            if (item["external_id"] is None) != (item["delivered_at"] is None):
                raise ValueError("Incomplete initiative receipt")
            if item["external_id"] is not None and (not isinstance(item["external_id"], str) or not item["external_id"].strip()):
                raise ValueError("Invalid initiative receipt")
            from datetime import datetime
            datetime.fromisoformat(item["created_at"])
            if item["delivered_at"] is not None:
                datetime.fromisoformat(item["delivered_at"])
        if any(item["external_id"] is None for item in state["delivered"]):
            raise ValueError("Unconfirmed delivery in completed history")

    def load(self) -> dict[str, Any]:
        """Read without initializing data; never replace corrupt state."""
        try:
            state = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {"version": 1, "delivered": [], "pending": None, "evaluated": None}
        self._validate(state)
        return state

    def save(self, state: dict[str, Any]) -> None:
        """Atomically persist under the caller's process lock."""
        self._validate(state)
        descriptor, temporary = tempfile.mkstemp(prefix=".behavioral-initiative-", suffix=".tmp", dir=self.path.parent)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                json.dump(state, stream, ensure_ascii=False)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
