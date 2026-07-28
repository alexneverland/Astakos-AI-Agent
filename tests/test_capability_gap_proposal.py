import pytest
from unittest.mock import MagicMock
from api.server import _enqueue_capability_gap_web
from clients.telegram_bot import _enqueue_capability_gap_telegram
from memory.working_memory import update_capabilities_from_exchange

@pytest.fixture
def mock_dependencies(monkeypatch):
    mocks = {
        "update_caps": MagicMock(return_value="Detected gap: clean cage"),
        "load_messages": MagicMock(return_value=[]),
        "append_chat": MagicMock(),
        "send_and_record": MagicMock(),
        "t": MagicMock(side_effect=lambda k, **kwargs: {
            "core.approval.capability_proposal_prefix": "New tool proposal:",
            "core.approval.draft_markers": ["create draft"]
        }.get(k, k))
    }
    monkeypatch.setattr("memory.working_memory.update_capabilities_from_exchange", mocks["update_caps"])
    monkeypatch.setattr("memory.conversation_history.load_messages_after_rowid", mocks["load_messages"])
    monkeypatch.setattr("api.server.append_to_chat_history", mocks["append_chat"])
    monkeypatch.setattr("clients.telegram_bot._send_and_record_assistant", mocks["send_and_record"])
    monkeypatch.setattr("core.i18n.t", mocks["t"])
    return mocks

def test_web_wrapper_emits_proposal_when_no_newer_user_message(mock_dependencies):
    _enqueue_capability_gap_web("user text", "ai text", "Chat_Agent", "web", 100)

    mock_dependencies["load_messages"].assert_called_once_with(after_rowid=100, channel="web")
    mock_dependencies["append_chat"].assert_called_once_with(
        "assistant",
        "New tool proposal: Detected gap: clean cage create draft",
        agent="Dev_Agent"
    )

def test_web_wrapper_emits_nothing_when_newer_user_message_exists(mock_dependencies):
    mock_dependencies["load_messages"].return_value = [{"role": "user", "content": "newer"}]
    _enqueue_capability_gap_web("user text", "ai text", "Chat_Agent", "web", 100)
    mock_dependencies["load_messages"].assert_called_once_with(after_rowid=100, channel="web")
    mock_dependencies["append_chat"].assert_not_called()

def test_telegram_wrapper_records_only_after_send_success(mock_dependencies):
    _enqueue_capability_gap_telegram("user text", "ai text", "Chat_Agent", "telegram", 100, "chat123")

    mock_dependencies["load_messages"].assert_called_once_with(after_rowid=100, channel="telegram")
    mock_dependencies["send_and_record"].assert_called_once_with(
        "New tool proposal: Detected gap: clean cage create draft",
        "chat123",
        agent="Dev_Agent"
    )

def test_telegram_wrapper_emits_nothing_for_duplicate_or_stale(mock_dependencies):
    # Stale context
    mock_dependencies["load_messages"].return_value = [{"role": "user"}]
    _enqueue_capability_gap_telegram("user text", "ai text", "Chat_Agent", "telegram", 100, "chat123")
    mock_dependencies["send_and_record"].assert_not_called()

    # Duplicate (returns None)
    mock_dependencies["load_messages"].return_value = []
    mock_dependencies["update_caps"].return_value = None
    _enqueue_capability_gap_telegram("user text", "ai text", "Chat_Agent", "telegram", 100, "chat123")
    mock_dependencies["send_and_record"].assert_not_called()

def test_detector_returns_description_only_for_newly_inserted_cannot_do(monkeypatch):
    monkeypatch.setattr("services.gemini.safe_gemini_call", MagicMock(
        return_value=MagicMock(text='```json\n{"cannot_do": "do X"}\n```')
    ))

    save_cap_mock = MagicMock(return_value="inserted")
    monkeypatch.setattr("memory.working_memory._save_capability", save_cap_mock)

    res = update_capabilities_from_exchange("u", "a", "A")
    assert res == "do X"

    # Duplicate
    save_cap_mock.return_value = "duplicate"
    res2 = update_capabilities_from_exchange("u", "a", "A")
    assert res2 is None

    # can_do only
    monkeypatch.setattr("services.gemini.safe_gemini_call", MagicMock(
        return_value=MagicMock(text='```json\n{"can_do": "do X"}\n```')
    ))
    save_cap_mock.return_value = "inserted"
    res3 = update_capabilities_from_exchange("u", "a", "A")
    assert res3 is None

def test_telegram_scheduling_seam_handles_rowid_correctly(monkeypatch):
    import clients.telegram_bot as tb
    enqueue_mock = MagicMock()
    monkeypatch.setattr(tb, "enqueue_slow_task", enqueue_mock)

    # None rowid -> fail closed
    tb._schedule_capability_gap_if_valid("u", "a", "agent", None, "chat123")
    enqueue_mock.assert_not_called()

    # Valid rowid -> exact enqueue once
    tb._schedule_capability_gap_if_valid("u", "a", "agent", 999, "chat123")
    enqueue_mock.assert_called_once_with(
        tb._enqueue_capability_gap_telegram, "u", "a", "agent", "telegram", 999, "chat123"
    )
