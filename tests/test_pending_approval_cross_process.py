"""Concurrent approval writes from Web and Matrix remain intact."""

from __future__ import annotations

from multiprocessing import get_context

import core.approval as approval


def _write_pending_calls(path: str, prefix: str, count: int) -> None:
    """Write a batch from one independent process."""
    approval.PENDING_FILE = path
    for index in range(count):
        approval.save_pending("mail_manager", {}, f"{prefix}-{index}", channel="web")


def test_two_processes_do_not_lose_pending_approvals(tmp_path, monkeypatch) -> None:
    """The shared approval state must serialize independent writers."""
    path = str(tmp_path / "pending.json")
    monkeypatch.setattr(approval, "PENDING_FILE", path)
    context = get_context("spawn")
    processes = [
        context.Process(target=_write_pending_calls, args=(path, prefix, 12))
        for prefix in ("web", "matrix")
    ]
    for process in processes:
        process.start()
    for process in processes:
        process.join(timeout=30)
        assert process.exitcode == 0

    assert {
        item["tool_call_id"] for item in approval.list_pending()
    } == {
        f"{prefix}-{index}"
        for prefix in ("web", "matrix")
        for index in range(12)
    }
