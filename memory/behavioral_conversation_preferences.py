"""Shared local topic opt-outs, independent of routines and vector memory."""
from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
from uuid import uuid4

from filelock import FileLock


class PreferenceStore:
    """Serialize atomic preference updates across channel processes.

    A stale snapshot is rejected instead of overwriting a concurrent update.
    Constructing/reading a missing store never creates the data file.
    """

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def load(self) -> list[dict[str, str]]:
        """Read validated preferences; damaged files must fail closed."""
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return []
        if not isinstance(raw, dict) or raw.get("version") != 1:
            raise ValueError("Invalid behavioral preference store")
        prefs = raw.get("preferences")
        if not isinstance(prefs, list) or len(prefs) > 100:
            raise ValueError("Invalid behavioral preferences")
        seen: set[str] = set()
        for pref in prefs:
            if not isinstance(pref, dict) or set(pref) != {"id", "scope"}:
                raise ValueError("Invalid preference entry")
            if not all(isinstance(pref[k], str) and pref[k].strip() for k in ("id", "scope")):
                raise ValueError("Invalid preference text")
            if len(pref["id"]) > 64 or len(pref["scope"]) > 500 or pref["id"] in seen:
                raise ValueError("Invalid preference identity")
            seen.add(pref["id"])
        return prefs

    def update(
        self, expected: list[dict[str, str]], *, suppress: str | None, allow_ids: list[str]
    ) -> list[dict[str, str]] | None:
        """Commit explicit semantic changes or return None for a stale snapshot."""
        with FileLock(str(self.path) + ".lock", timeout=5):
            current = self.load()
            if current != expected:
                return None
            known = {pref["id"] for pref in current}
            if not set(allow_ids) <= known:
                raise ValueError("Unknown preference identity")
            if suppress is not None and (not isinstance(suppress, str) or not suppress.strip() or len(suppress) > 500):
                raise ValueError("Invalid suppression scope")
            updated = [pref for pref in current if pref["id"] not in allow_ids]
            if suppress and not any(pref["scope"] == suppress for pref in updated):
                if len(updated) >= 100:
                    raise ValueError("Preference capacity reached")
                updated.append({"id": uuid4().hex, "scope": suppress})
            if updated == current:
                return current
            descriptor, temporary = tempfile.mkstemp(prefix=".behavioral-prefs-", suffix=".tmp", dir=self.path.parent)
            try:
                with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                    json.dump({"version": 1, "preferences": updated}, stream, ensure_ascii=False)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, self.path)
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)
            return updated
