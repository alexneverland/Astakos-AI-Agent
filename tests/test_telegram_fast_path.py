import pytest
from core.utils import is_simple_chat_fast_path_candidate

def test_fast_path_simple_ack():
    assert is_simple_chat_fast_path_candidate("Οκ") is True
    assert is_simple_chat_fast_path_candidate("ναι φίλε") is True
    assert is_simple_chat_fast_path_candidate("έγινε") is True

def test_fast_path_short_idle_chat():
    assert is_simple_chat_fast_path_candidate("Όχι εντάξει") is True
    assert is_simple_chat_fast_path_candidate("βαριέμαι στην δουλειά") is False
    
def test_fast_path_family_mention():
    assert is_simple_chat_fast_path_candidate("Ο Αλέξανδρος γύρισε") is False

def test_fast_path_work_shift_update():
    assert is_simple_chat_fast_path_candidate("Από αύριο είμαι πρωινός") is False

def test_fast_path_action_request():
    assert is_simple_chat_fast_path_candidate("στείλε μήνυμα στη Σοφία") is False

def test_fast_path_question():
    assert is_simple_chat_fast_path_candidate("τι κάνει ο Αλέξανδρος;") is False
