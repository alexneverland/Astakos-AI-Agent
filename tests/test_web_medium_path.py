from core.utils import is_medium_web_chat_path_candidate


def test_medium_web_path_candidate_for_reflective_update():
    assert is_medium_web_chat_path_candidate("εκλεισα συνεντευξη πρωτη για 15 ιουλιου") is True
    assert is_medium_web_chat_path_candidate("δυσκολα θα αφησω τη σταθερη δουλεια") is True


def test_medium_web_path_rejects_control_intent():
    assert is_medium_web_chat_path_candidate("στείλε μήνυμα στη Partner") is False
    assert is_medium_web_chat_path_candidate("βάλε ρουτίνα για το πάρκο") is False


def test_medium_web_path_rejects_tiny_ack_because_fast_path_handles_it():
    assert is_medium_web_chat_path_candidate("ναι") is False
