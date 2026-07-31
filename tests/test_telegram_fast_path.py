from typing import Any

import pytest
from core.utils import (
    get_ultra_light_ack_response,
    is_simple_chat_fast_path_candidate,
    is_medium_web_chat_path_candidate,
    is_ultra_light_ack,
)


def test_fast_path_simple_ack():
    assert is_simple_chat_fast_path_candidate("Οκ") is True
    assert is_simple_chat_fast_path_candidate("ναι φίλε") is True
    assert is_simple_chat_fast_path_candidate("έγινε") is True


def test_fast_path_short_idle_chat():
    assert is_simple_chat_fast_path_candidate("Όχι εντάξει") is True
    assert is_simple_chat_fast_path_candidate("βαριέμαι στην δουλειά") is False


def test_fast_path_family_mention():
    assert is_simple_chat_fast_path_candidate("Ο Kid1 γύρισε") is False


def test_fast_path_work_shift_update():
    assert is_simple_chat_fast_path_candidate("Από αύριο είμαι πρωινός") is False


def test_fast_path_action_request():
    assert is_simple_chat_fast_path_candidate("στείλε μήνυμα στη Partner") is False


def test_fast_path_question():
    assert is_simple_chat_fast_path_candidate("τι κάνει ο Kid1;") is False


def test_ultra_light_ack_basic_cases():
    assert is_ultra_light_ack("ναι") is True
    assert is_ultra_light_ack("οκ") is True
    assert is_ultra_light_ack("έγινε!") is True


def test_ultra_light_ack_rejects_plain_no():
    assert is_ultra_light_ack("όχι") is False
    assert is_ultra_light_ack("οχι") is False


def test_ultra_light_ack_rejects_real_updates():
    assert is_ultra_light_ack("από αύριο είμαι πρωινός") is False
    assert is_ultra_light_ack("στείλε μήνυμα στη Partner") is False


def test_ultra_light_ack_response_is_neutral_confirmation():
    allowed = {"Έγινε.", "ΟΚ.", "Λήφθη.", "Τέλεια.", "✅"}
    assert get_ultra_light_ack_response() in allowed


from unittest.mock import patch


def test_handle_message_ultra_light_ack_sends_reply_without_graph(monkeypatch):
    import clients.telegram_bot as bot
    import core.utils as utils
    import memory.execution_trace as execution_trace
    import memory.pending_assets as pending_assets
    import tools.telegram as telegram

    class DummyTrace:
        def __init__(self, **_kwargs):
            self.agent = ""

        def mark_phase(self, *_args):
            pass

        def process_event(self, *_args):
            pass

        def finalize(self, **_kwargs):
            pass

        def save(self):
            pass

    sent = []
    monkeypatch.setattr(bot, "pending_routine_confirmations", {})
    monkeypatch.setattr(bot, "pending_reflection_confirmations", {})
    monkeypatch.setattr(bot, "pending_exec_command", None)
    monkeypatch.setattr(bot, "pending_photo", None)
    monkeypatch.setattr(bot, "_safe_active_draft_status", lambda: (False, "missing", None))
    monkeypatch.setattr(bot, "_safe_classify_messenger_intent", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(bot, "_build_fast_chat_context", lambda _text: ([], object()))
    monkeypatch.setattr(bot, "_append_to_analytics_log", lambda *_args: None)
    monkeypatch.setattr(bot, "_cache_bot_message", lambda *_args: None)
    monkeypatch.setattr(bot, "enqueue_fast_task", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(bot, "enqueue_slow_task", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        bot.threading,
        "Thread",
        lambda *_args, **_kwargs: type("Thread", (), {"start": lambda self: None})(),
    )
    monkeypatch.setattr(bot.graph, "stream", lambda *_args, **_kwargs: pytest.fail("graph must not run"))
    monkeypatch.setattr(pending_assets, "clear_expired_pending_assets", lambda: None)
    monkeypatch.setattr(pending_assets, "get_latest_pending_asset", lambda *_args: None)
    monkeypatch.setattr(execution_trace, "ExecutionTrace", DummyTrace)
    monkeypatch.setattr(utils, "is_ultra_light_ack", lambda _text: True)
    monkeypatch.setattr(utils, "get_ultra_light_ack_response", lambda: "ACK")
    monkeypatch.setattr(utils, "is_reply_to_recent_mail_prompt", lambda _history: False)
    monkeypatch.setattr(utils, "is_reply_to_recent_linkedin_prompt", lambda _history: False)
    monkeypatch.setattr(telegram, "send_telegram_msg", lambda message: sent.append(message) or 1)

    bot.handle_message("ok", "user123")

    assert sent == ["ACK"]


@patch("memory.pending_assets.get_latest_pending_asset", return_value=None)
@patch("memory.pending_assets.clear_expired_pending_assets")
@patch("core.messenger_draft.active_draft_status", return_value=(False, "missing", None))
@patch("tools.telegram.send_telegram_msg")
@patch("clients.telegram_bot._append_to_analytics_log")
@patch("clients.telegram_bot.graph.stream")
@patch("clients.telegram_bot._safe_classify_messenger_intent")
def test_messenger_intent_clarify_does_not_create_draft(mock_classify, mock_stream, mock_append, mock_send, mock_active, mock_clear_assets, mock_get_asset):
    from clients.telegram_bot import handle_message
    from services.messenger_intent import MessengerIntentResult
    
    mock_classify.return_value = MessengerIntentResult(intent="clarify_draft", confidence=1.0)
    handle_message("Ποιο μήνυμα;", "user123")
    
    # Verify graph.stream was not called (meaning early intercept worked)
    mock_stream.assert_not_called()
    
    # Verify response contains clarification that no draft exists
    args, _ = mock_send.call_args
    sent_text = args[0]
    assert "Δεν υπάρχει ενεργό draft αυτή τη στιγμή. Εννοούσα απλώς σαν ιδέα" in sent_text


@patch("memory.pending_assets.get_latest_pending_asset", return_value=None)
@patch("memory.pending_assets.clear_expired_pending_assets")
@patch("core.messenger_draft.active_draft_status", return_value=(True, "active", {"message": "hello"}))
@patch("core.messenger_draft.clear_draft", return_value=True)
@patch("tools.telegram.send_telegram_msg")
@patch("clients.telegram_bot._append_to_analytics_log")
@patch("clients.telegram_bot.graph.stream")
@patch("clients.telegram_bot._safe_classify_messenger_intent")
def test_messenger_intent_clear_closes_draft(mock_classify, mock_stream, mock_append, mock_send, mock_clear, mock_active, mock_clear_assets, mock_get_asset):
    from clients.telegram_bot import handle_message
    from services.messenger_intent import MessengerIntentResult
    
    mock_classify.return_value = MessengerIntentResult(intent="clear_draft", confidence=1.0)
    handle_message("Αυτό το έχουμε στείλει κλείστο", "user123")
    
    # Verify clear_draft was called
    mock_clear.assert_called_once()
    
    # Verify graph.stream was not called
    mock_stream.assert_not_called()
    
    # Verify response confirms cleanup
    args, _ = mock_send.call_args
    sent_text = args[0]
    assert "The draft is cleared" in sent_text or "Το draft καθαρίστηκε" in sent_text


@patch("memory.pending_assets.get_latest_pending_asset", return_value=None)
@patch("memory.pending_assets.clear_expired_pending_assets")
@patch("core.messenger_draft.active_draft_status", return_value=(False, "missing", None))
@patch("core.messenger_draft.clear_draft", return_value=False)
@patch("tools.telegram.send_telegram_msg")
@patch("clients.telegram_bot._append_to_analytics_log")
@patch("clients.telegram_bot.graph.stream")
@patch("clients.telegram_bot._safe_classify_messenger_intent")
def test_messenger_intent_clear_without_active_draft_stays_out_of_graph(
    mock_classify: Any,
    mock_stream: Any,
    mock_append: Any,
    mock_send: Any,
    mock_clear: Any,
    mock_active: Any,
    mock_clear_assets: Any,
    mock_get_asset: Any,
) -> None:
    """A stale draft-clear request must be handled locally, never by capability routing."""
    from clients.telegram_bot import handle_message
    from services.messenger_intent import MessengerIntentResult

    mock_classify.return_value = MessengerIntentResult(intent="clear_draft", confidence=1.0)
    handle_message("Καθάρισε draft", "user123")

    mock_clear.assert_called_once()
    mock_stream.assert_not_called()


def test_medium_path_candidate_for_telegram_reflective_turn():
    assert is_medium_web_chat_path_candidate('σχολασα φιλε και παω σπιτι') is True


def test_contextual_sofia_not_needed_reply_does_not_decay():
    from clients.telegram_bot import _looks_like_contextual_not_needed_reply
    text = "Δεν θα χρειαστεί σήμερα μήνυμα μόλις μίλησα μαζί της στο τηλέφωνο, κλείνει εδώ"
    assert _looks_like_contextual_not_needed_reply(text) is True

def test_terminal_followup_skip_reason_marks_stale_case():
    from clients.telegram_bot import _looks_terminal_followup_skip_reason
    reason = "Το follow-up αφορά αφύπνιση της προηγούμενης ημέρας και δεν έχει νόημα τώρα."
    assert _looks_terminal_followup_skip_reason(reason) is True
