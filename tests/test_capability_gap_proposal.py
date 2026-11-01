import pytest
from unittest.mock import MagicMock
from api.server import _enqueue_capability_gap_web
from clients.telegram_bot import _enqueue_capability_gap_telegram
from memory.working_memory import CapabilityObservation, update_capabilities_from_exchange


def _fake_translate(key: str, **kwargs: str) -> str | list[str]:
    """Render only the small set of proposal strings used by these offline tests."""
    value = {
        "core.approval.capability_proposal_prefix": "New tool proposal:",
        "core.approval.bug_proposal_prefix": "Possible bug in existing behavior:",
        "core.approval.bug_diagnosis_prefix": "Bug diagnosis:",
        "core.approval.bug_proposal": "Possible bug in existing behavior: {description} Ask me to investigate before any fix.",
        "core.approval.draft_markers": ["create draft"],
    }.get(key, key)
    return value.format(**kwargs) if isinstance(value, str) else value

@pytest.fixture
def mock_dependencies(monkeypatch):
    mocks = {
        "update_caps": MagicMock(return_value=CapabilityObservation("missing_capability", "Detected gap: clean cage")),
        "load_messages": MagicMock(return_value=[]),
        "append_chat": MagicMock(),
        "send_and_record": MagicMock(),
        "t": MagicMock(side_effect=_fake_translate),
    }
    monkeypatch.setattr("memory.working_memory.update_capabilities_from_exchange", mocks["update_caps"])
    monkeypatch.setattr("memory.conversation_history.load_messages_after_rowid", mocks["load_messages"])
    monkeypatch.setattr("api.server.append_to_chat_history", mocks["append_chat"])
    monkeypatch.setattr("clients.telegram_bot._send_and_record_assistant", mocks["send_and_record"])
    monkeypatch.setattr("core.i18n.t", mocks["t"])
    monkeypatch.setattr("core.capability_draft.t", mocks["t"])
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


def test_web_wrapper_does_not_duplicate_an_agent_capability_proposal(mock_dependencies):
    _enqueue_capability_gap_web(
        "βιντεο μπορεις?",
        "[23:47] New tool proposal: I can build a video generator.",
        "Chat_Agent",
        "web",
        100,
    )

    mock_dependencies["append_chat"].assert_not_called()


def test_web_wrapper_does_not_reclassify_a_completed_bug_diagnosis(mock_dependencies):
    """The diagnostic report must not generate another offer for the same bug."""
    _enqueue_capability_gap_web(
        "please investigate", "Bug diagnosis: the timestamp is stale.",
        "Dev_Agent", "web", 100,
    )
    mock_dependencies["update_caps"].assert_not_called()
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


def test_telegram_wrapper_does_not_duplicate_an_agent_capability_proposal(mock_dependencies):
    _enqueue_capability_gap_telegram(
        "can you make videos?",
        "[23:47] New tool proposal: I can build a video generator.",
        "Chat_Agent",
        "telegram",
        100,
        "chat123",
    )

    mock_dependencies["send_and_record"].assert_not_called()


def test_telegram_wrapper_does_not_reclassify_a_completed_bug_diagnosis(mock_dependencies):
    """Telegram cannot turn its diagnostic answer into a new proposal."""
    _enqueue_capability_gap_telegram(
        "please investigate", "Bug diagnosis: the timestamp is stale.",
        "Dev_Agent", "telegram", 100, "chat123",
    )
    mock_dependencies["update_caps"].assert_not_called()
    mock_dependencies["send_and_record"].assert_not_called()

def test_detector_returns_missing_capability_only_for_newly_inserted_cannot_do(monkeypatch):
    monkeypatch.setattr("services.gemini.safe_gemini_call", MagicMock(
        return_value=MagicMock(text='```json\n{"issue_type": "missing_capability", "cannot_do": "do X"}\n```')
    ))

    save_cap_mock = MagicMock(return_value="inserted")
    monkeypatch.setattr("memory.working_memory._save_capability", save_cap_mock)

    res = update_capabilities_from_exchange("u", "a", "A")
    assert res == CapabilityObservation("missing_capability", "do X")

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


def test_existing_behavior_bug_does_not_become_cannot_do(monkeypatch):
    monkeypatch.setattr("services.gemini.safe_gemini_call", MagicMock(
        return_value=MagicMock(text='{"issue_type":"existing_behavior_bug","bug":"Astakos misread the latest Kaggle score as one week old"}')
    ))
    save_cap_mock = MagicMock()
    monkeypatch.setattr("memory.working_memory._save_capability", save_cap_mock)

    result = update_capabilities_from_exchange(
        "The Kaggle score 0.06 was updated just now",
        "It has been a week since the update",
        "Chat_Agent",
    )

    assert result == CapabilityObservation(
        "existing_behavior_bug", "Astakos misread the latest Kaggle score as one week old"
    )
    save_cap_mock.assert_not_called()


def test_family_context_bug_still_offers_investigation(monkeypatch):
    """A family-role word in a bug description is not a user-fact capability."""
    monkeypatch.setattr("services.gemini.safe_gemini_call", MagicMock(
        return_value=MagicMock(text='{"issue_type":"existing_behavior_bug","bug":"partner presence is shown incorrectly"}')
    ))
    save_cap_mock = MagicMock()
    monkeypatch.setattr("memory.working_memory._save_capability", save_cap_mock)

    result = update_capabilities_from_exchange(
        "Sofia is home but the partner flag is wrong", "I showed the wrong state", "Chat_Agent"
    )

    assert result == CapabilityObservation(
        "existing_behavior_bug", "partner presence is shown incorrectly"
    )
    save_cap_mock.assert_not_called()


@pytest.mark.parametrize("issue_type", ["transient_failure", "uncertain", "unknown"])
def test_transient_or_uncertain_issue_creates_no_capability_or_proposal(monkeypatch, issue_type):
    monkeypatch.setattr("services.gemini.safe_gemini_call", MagicMock(
        return_value=MagicMock(text=f'{{"issue_type":"{issue_type}","cannot_do":"Astakos cannot answer due to Google 429"}}')
    ))
    save_cap_mock = MagicMock()
    monkeypatch.setattr("memory.working_memory._save_capability", save_cap_mock)

    assert update_capabilities_from_exchange("Why no answer?", "Google returned 429", "Chat_Agent") is None
    save_cap_mock.assert_not_called()


def test_web_bug_proposal_does_not_authorize_a_new_tool_draft(mock_dependencies):
    mock_dependencies["update_caps"].return_value = CapabilityObservation(
        "existing_behavior_bug", "Kaggle timing was misread"
    )
    _enqueue_capability_gap_web("The update was just now", "It was a week ago", "Chat_Agent", "web", 100)

    proposal = mock_dependencies["append_chat"].call_args.args[1]
    assert proposal == "Possible bug in existing behavior: Kaggle timing was misread Ask me to investigate before any fix."
    assert "New tool proposal:" not in proposal
    assert "create draft" not in proposal
    from core.capability_draft import is_capability_proposal_text

    assert not is_capability_proposal_text(proposal)


def test_telegram_bug_proposal_is_delivered_without_draft_marker(mock_dependencies):
    mock_dependencies["update_caps"].return_value = CapabilityObservation(
        "existing_behavior_bug", "Kaggle timing was misread"
    )
    _enqueue_capability_gap_telegram(
        "The update was just now", "It was a week ago", "Chat_Agent", "telegram", 100, "chat123"
    )
    mock_dependencies["send_and_record"].assert_called_once_with(
        "Possible bug in existing behavior: Kaggle timing was misread Ask me to investigate before any fix.",
        "chat123",
        agent="Dev_Agent",
    )


def test_background_does_not_duplicate_an_existing_bug_proposal(mock_dependencies):
    mock_dependencies["update_caps"].return_value = CapabilityObservation(
        "existing_behavior_bug", "Kaggle timing was misread"
    )
    _enqueue_capability_gap_web(
        "score now", "[12:00] Possible bug in existing behavior: timing wrong",
        "Chat_Agent", "web", 100,
    )
    mock_dependencies["append_chat"].assert_not_called()

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
