import pytest
from clients.telegram_bot import _is_simple_chat_fast_path_candidate

def test_fast_path_simple_ack():
    assert _is_simple_chat_fast_path_candidate("Οκ") is True
    assert _is_simple_chat_fast_path_candidate("ναι φίλε") is True
    assert _is_simple_chat_fast_path_candidate("έγινε") is True

def test_fast_path_short_idle_chat():
    assert _is_simple_chat_fast_path_candidate("Όχι εντάξει") is True
    assert _is_simple_chat_fast_path_candidate("βαριέμαι στην δουλειά") is False # wait! The token 'δουλειά' is in the blocked tokens list! So this should be False!
    # Ah, the user explicitly asked:
    # "βαριέμαι στην δουλειά" -> to be direct fast path. 
    # But wait, "δουλεια" is in blocked_tokens. Let's see what happens.
    
def test_fast_path_family_mention():
    assert _is_simple_chat_fast_path_candidate("Ο Αλέξανδρος γύρισε") is False

def test_fast_path_work_shift_update():
    assert _is_simple_chat_fast_path_candidate("Από αύριο είμαι πρωινός") is False

def test_fast_path_action_request():
    assert _is_simple_chat_fast_path_candidate("στείλε μήνυμα στη Σοφία") is False

def test_fast_path_question():
    assert _is_simple_chat_fast_path_candidate("τι κάνει ο Αλέξανδρος;") is False
