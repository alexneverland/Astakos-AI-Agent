"""Durable reminder feedback recovery without repeating approved tool execution."""

from types import SimpleNamespace

import pytest

from core import approval
from clients import matrix_bot
from memory import conversation_history as history
from services.matrix_approval import MatrixApprovalReactionService


@pytest.fixture
def receipt_case(monkeypatch, tmp_path):
    """Use the real reminder tool and history API with isolated storage."""
    from memory.reminder_store import init_reminder_store
    import tools.system as system
    state = str(tmp_path / "state.db")
    history_path = str(tmp_path / "history.db")
    init_reminder_store(state)
    monkeypatch.setattr(system, "STATE_DB", state)
    monkeypatch.setattr(approval, "PENDING_FILE", str(tmp_path / "pending.json"))
    append = history.append_message
    monkeypatch.setattr(history, "append_message", lambda **kw: append(**kw, db_path=history_path))
    calls = []
    def invoke(args):
        calls.append(args)
        return system.set_local_reminder.invoke(args)
    tool = SimpleNamespace(name="set_local_reminder", invoke=invoke)
    approval.save_pending("set_local_reminder", {"task": "test meat", "exact_time": "2099-01-01 19:00",
        "external_content_sources_json": '["browse_url"]'}, "receipt-1", channel="matrix")
    approval.record_pending_delivery("receipt-1", delivery_channel="matrix", external_message_id="$receipt")
    service = MatrixApprovalReactionService(allowed_user_id="@owner:test", allowed_room_id="!room:test",
        tools_provider=lambda: [tool])
    return service, calls, history_path, tool


def execute_case(service):
    """Simulate the already device-verified exact-prompt approval boundary."""
    return service.handle_reaction(room_id="!room:test", sender_id="@owner:test", authenticated=True,
        reacts_to="$receipt", key="✅")


def test_history_failure_retains_durable_result_for_restart_recovery(receipt_case, monkeypatch):
    """A missing history row is retried from disk, never by invoking the tool."""
    service, calls, path, tool = receipt_case
    result = execute_case(service)
    saved = approval.get_pending("receipt-1")
    assert saved is not None and saved["status"] == "executed"
    assert "2099-01-01 19:00" in saved["execution_result"]
    assert approval.list_pending() == []
    text = matrix_bot._approval_result_text(result)
    append = history.append_message
    monkeypatch.setattr(history, "append_message", lambda **kw: (_ for _ in ()).throw(OSError("offline history")))
    matrix_bot._record_web_approval_result(result, text)
    assert approval.get_pending("receipt-1") is not None
    monkeypatch.setattr(history, "append_message", append)
    # Recovery has no tools provider and works after the original result is gone.
    del result
    assert matrix_bot._recover_matrix_reminder_history() == 1
    assert approval.get_pending("receipt-1") is None
    assert matrix_bot._recover_matrix_reminder_history() == 0
    assert len(calls) == 1
    rows = history.load_messages(db_path=path)
    assert len(rows) == 1 and "test meat" in rows[0]["content"]
    assert rows[0]["metadata"]["untrusted_external_tool_names"] == ["browse_url"]


def test_crash_after_execution_before_feedback_is_recoverable(receipt_case):
    """A recorded tool result survives loss of the in-memory approval response."""
    service, calls, path, tool = receipt_case
    execute_case(service)
    assert matrix_bot._recover_matrix_reminder_history() == 1
    assert len(calls) == 1
    assert len(history.load_messages(db_path=path)) == 1


def test_claim_prevents_concurrent_and_uncertain_reexecution(receipt_case):
    """An interrupted tool is never automatically retried from a pending record."""
    service, calls, path, tool = receipt_case
    original = tool.invoke
    def interrupted(args):
        assert approval.get_pending("receipt-1")["status"] == "executing"
        assert not approval.execute_approved_pending("receipt-1", [tool])["ok"]
        original(args)
        raise SystemExit("simulated interruption before result journal")
    tool.invoke = interrupted
    with pytest.raises(SystemExit):
        execute_case(service)
    assert not approval.execute_approved_pending("receipt-1", [tool])["ok"]
    assert len(calls) == 1
    assert approval.list_pending() == []
    assert matrix_bot._recover_matrix_reminder_history() == 0


def test_history_commit_before_receipt_removal_is_idempotent(receipt_case, monkeypatch):
    """A crash between history commit and receipt removal cannot duplicate the row."""
    service, calls, path, tool = receipt_case
    result = execute_case(service)
    complete = approval.complete_matrix_reminder_outcome
    def interrupted(call_id):
        raise OSError("receipt removal unavailable")
    monkeypatch.setattr(approval, "complete_matrix_reminder_outcome", interrupted)
    assert matrix_bot._record_web_approval_result(result, matrix_bot._approval_result_text(result)) is False
    assert len(history.load_messages(db_path=path)) == 1
    assert approval.get_pending("receipt-1") is not None
    monkeypatch.setattr(approval, "complete_matrix_reminder_outcome", complete)
    assert matrix_bot._recover_matrix_reminder_history() == 1
    assert len(history.load_messages(db_path=path)) == 1
    assert len(calls) == 1


def test_completed_receipt_is_not_lost_to_approval_expiry(receipt_case):
    """Approval TTL applies to actionable requests, not undelivered history receipts."""
    service, calls, path, tool = receipt_case
    execute_case(service)
    rows = approval._load_pending()
    rows["receipt-1"]["created_at"] = "2020-01-01T00:00:00"
    approval._save_pending(rows)
    approval.expire_stale_pending()
    assert matrix_bot._recover_matrix_reminder_history() == 1
    assert len(calls) == 1


@pytest.mark.parametrize("fail_before_invoke", [True, False])
def test_pending_file_failure_never_allows_reexecution(receipt_case, monkeypatch, fail_before_invoke):
    """Failed durable claim stops execution; failed result journal keeps the claim."""
    service, calls, path, tool = receipt_case
    save = approval._save_pending_unlocked
    def unavailable(data):
        if fail_before_invoke or data["receipt-1"]["status"] == "executed":
            raise OSError("pending storage unavailable")
        save(data)
    monkeypatch.setattr(approval, "_save_pending_unlocked", unavailable)
    with pytest.raises(OSError):
        execute_case(service)
    assert len(calls) == (0 if fail_before_invoke else 1)
    if not fail_before_invoke:
        monkeypatch.setattr(approval, "_save_pending_unlocked", save)
        assert not approval.execute_approved_pending("receipt-1", [tool])["ok"]
        assert matrix_bot._recover_matrix_reminder_history() == 0


@pytest.mark.asyncio
async def test_startup_retry_loop_continues_after_temporary_storage_failure(monkeypatch):
    """Production recovery runs immediately and keeps retrying without tool access."""
    import asyncio
    attempts = []
    sleeps = []
    def recover():
        attempts.append(True)
        if len(attempts) == 1:
            raise OSError("temporary lock")
        return 0
    async def next_cycle(delay):
        sleeps.append(delay)
        if len(sleeps) == 2:
            raise asyncio.CancelledError
    monkeypatch.setattr(matrix_bot, "_recover_matrix_reminder_history", recover)
    monkeypatch.setattr(matrix_bot.asyncio, "sleep", next_cycle)
    with pytest.raises(asyncio.CancelledError):
        await matrix_bot._retry_matrix_reminder_history()
    assert len(attempts) == 2 and sleeps == [30, 30]
