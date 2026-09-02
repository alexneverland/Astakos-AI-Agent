"""Regression coverage for local Debug Dashboard goal deletion."""

import asyncio
from contextlib import nullcontext
from pathlib import Path


def test_goal_delete_attempts_local_request_before_prompting_for_token() -> None:
    """Local dashboard users are not prompted unless the server returns 401."""
    dashboard = (Path(__file__).parents[1] / "api" / "debug_dashboard.html").read_text(
        encoding="utf-8",
    )
    start = dashboard.index("async function deleteGoal(project)")
    end = dashboard.index("function toggleAppliedReflections()", start)
    delete_goal = dashboard[start:end]

    assert "res.status === 401" in delete_goal
    assert delete_goal.index("fetch('/debug/goals/'") < delete_goal.index("prompt('Bearer token:')")


def test_delete_goal_uses_a_chroma_and_filter(monkeypatch) -> None:
    """Goal deletion finds its Chroma record with a valid two-field metadata filter."""
    import api.server as server
    import memory.vector_store as vector_module

    class _Collection:
        """In-memory collection double enforcing Chroma's explicit AND contract."""

        def __init__(self) -> None:
            """Initialize the captured delete operation."""
            self.deleted_ids: list[str] = []

        def get(self, *, where: dict) -> dict:
            """Return one matching goal only for the valid composite filter."""
            assert where == {
                "$and": [{"category": "goal"}, {"project": "Astakos"}],
            }
            return {"ids": ["goal-1"]}

        def delete(self, *, ids: list[str]) -> None:
            """Record the deleted Chroma identifier."""
            self.deleted_ids = ids

    collection = _Collection()
    fake_store = type("_Store", (), {"_collection": collection})()
    monkeypatch.setattr(vector_module, "vector_store", fake_store)
    monkeypatch.setattr(vector_module, "vector_lock", nullcontext())

    result = asyncio.run(server.delete_goal("Astakos", None))

    assert result == {"ok": True, "deleted": "Astakos"}
    assert collection.deleted_ids == ["goal-1"]
