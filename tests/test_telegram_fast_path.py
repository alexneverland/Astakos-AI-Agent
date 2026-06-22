import pytest
from core.utils import (
    get_ultra_light_ack_response,
    is_simple_chat_fast_path_candidate,
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
    assert is_simple_chat_fast_path_candidate("Ο Αλέξανδρος γύρισε") is False


def test_fast_path_work_shift_update():
    assert is_simple_chat_fast_path_candidate("Από αύριο είμαι πρωινός") is False


def test_fast_path_action_request():
    assert is_simple_chat_fast_path_candidate("στείλε μήνυμα στη Σοφία") is False


def test_fast_path_question():
    assert is_simple_chat_fast_path_candidate("τι κάνει ο Αλέξανδρος;") is False


def test_ultra_light_ack_basic_cases():
    assert is_ultra_light_ack("ναι") is True
    assert is_ultra_light_ack("οκ") is True
    assert is_ultra_light_ack("έγινε!") is True


def test_ultra_light_ack_rejects_plain_no():
    assert is_ultra_light_ack("όχι") is False
    assert is_ultra_light_ack("οχι") is False


def test_ultra_light_ack_rejects_real_updates():
    assert is_ultra_light_ack("από αύριο είμαι πρωινός") is False
    assert is_ultra_light_ack("στείλε μήνυμα στη Σοφία") is False


def test_ultra_light_ack_response_is_neutral_confirmation():
    allowed = {"Έγινε.", "ΟΚ.", "Λήφθη.", "Τέλεια.", "✅"}
    assert get_ultra_light_ack_response() in allowed
