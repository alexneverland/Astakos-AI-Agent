"""Regression coverage for local Debug Dashboard goal deletion."""

import asyncio
from contextlib import nullcontext
import json
from pathlib import Path
import subprocess


def _run_dashboard_goal_delete(scenario: str) -> dict:
    """Execute the dashboard delete flow in an offline mocked browser environment."""
    dashboard_path = Path(__file__).parents[1] / "api" / "debug_dashboard.html"
    harness = r"""
const fs = require("fs");
const vm = require("vm");

const dashboard = fs.readFileSync(process.argv[1], "utf8");
const scenario = process.argv[2];
const start = dashboard.indexOf("async function deleteGoal(project)");
const end = dashboard.indexOf("function toggleAppliedReflections()", start);
const deleteGoalSource = dashboard.slice(start, end);
const events = [];
const calls = [];
const stored = new Map();
const responsesByScenario = {
  local_success: [
    { status: 200, body: { ok: true } },
    { status: 200, body: { goals: [] } },
  ],
  unauthorized_then_retry: [
    { status: 401, body: { ok: false } },
    { status: 200, body: { ok: true } },
    { status: 200, body: { goals: [] } },
  ],
  unauthorized_then_cancel: [
    { status: 401, body: { ok: false } },
  ],
};
const responses = [...responsesByScenario[scenario]];
const sandbox = {
  confirm: () => true,
  prompt: () => {
    events.push("prompt");
    return scenario === "unauthorized_then_retry" ? "retry-token" : null;
  },
  localStorage: {
    getItem: (key) => stored.get(key) || null,
    setItem: (key, value) => stored.set(key, value),
  },
  fetch: async (url, options = {}) => {
    events.push("fetch");
    calls.push({
      url,
      method: options.method || "GET",
      authorization: (options.headers || {}).Authorization || null,
    });
    const response = responses.shift();
    if (!response) throw new Error("unexpected fetch");
    return { status: response.status, json: async () => response.body };
  },
  alert: () => { throw new Error("unexpected alert"); },
  renderGoals: () => events.push("render"),
};

vm.createContext(sandbox);
vm.runInContext(`${deleteGoalSource}\nglobalThis.runDeleteGoal = deleteGoal;`, sandbox);
(async () => {
  await sandbox.runDeleteGoal("Astakos");
  console.log(JSON.stringify({ events, calls, stored: Object.fromEntries(stored) }));
})().catch((error) => { console.error(error); process.exit(1); });
"""
    result = subprocess.run(
        ["node", "-e", harness, str(dashboard_path), scenario],
        capture_output=True,
        check=True,
        text=True,
    )
    return json.loads(result.stdout)


def test_goal_delete_skips_token_prompt_after_successful_local_request() -> None:
    """A local successful deletion performs its DELETE before any token prompt."""
    result = _run_dashboard_goal_delete("local_success")

    assert result["events"] == ["fetch", "fetch", "render"]
    assert result["calls"][0] == {
        "url": "/debug/goals/Astakos",
        "method": "DELETE",
        "authorization": None,
    }


def test_goal_delete_prompts_and_retries_only_after_unauthorized_response() -> None:
    """A 401 prompts once and retries the same DELETE with the supplied token."""
    result = _run_dashboard_goal_delete("unauthorized_then_retry")

    assert result["events"] == ["fetch", "prompt", "fetch", "fetch", "render"]
    assert result["calls"][:2] == [
        {
            "url": "/debug/goals/Astakos",
            "method": "DELETE",
            "authorization": None,
        },
        {
            "url": "/debug/goals/Astakos",
            "method": "DELETE",
            "authorization": "Bearer retry-token",
        },
    ]
    assert result["stored"] == {"astakos_token": "retry-token"}


def test_goal_delete_stops_when_token_prompt_is_cancelled() -> None:
    """Cancelling the post-401 prompt does not retry the deletion."""
    result = _run_dashboard_goal_delete("unauthorized_then_cancel")

    assert result["events"] == ["fetch", "prompt"]
    assert len(result["calls"]) == 1


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
