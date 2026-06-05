"""
Tests για core/tool_risk.py — get_risk() και core/approval.py — is_critical().
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.tool_risk import get_risk
from core.approval import is_critical


# -- get_risk -----------------------------------------------------

def test_github_manager_is_critical():
    assert get_risk("github_manager") == "CRITICAL"

def test_mail_manager_is_critical():
    assert get_risk("mail_manager") == "CRITICAL"

def test_relay_local_payload_is_warning():
    assert get_risk("relay_local_payload") == "WARNING"

def test_execute_local_pipeline_is_critical():
    assert get_risk("execute_local_pipeline") == "CRITICAL"

def test_register_tool_is_critical():
    assert get_risk("register_tool") == "CRITICAL"

def test_process_and_clear_linkedin_post_is_critical():
    assert get_risk("process_and_clear_linkedin_post") == "CRITICAL"

def test_save_to_memory_is_warning():
    assert get_risk("save_to_memory") == "WARNING"

def test_update_pending_linkedin_post_is_warning():
    assert get_risk("update_pending_linkedin_post") == "WARNING"

def test_drive_manager_is_warning():
    assert get_risk("drive_manager") == "WARNING"

def test_search_memory_is_safe():
    assert get_risk("search_memory") == "SAFE"

def test_get_news_is_safe():
    assert get_risk("get_news") == "SAFE"

def test_unknown_tool_defaults_to_warning():
    # Άγνωστο tool → WARNING (safe default)
    assert get_risk("some_unknown_tool_xyz") == "WARNING"


# -- is_critical --------------------------------------------------

def test_is_critical_github():
    tc = {"name": "github_manager", "args": {}, "id": "abc"}
    assert is_critical(tc) is True

def test_is_critical_mail():
    tc = {"name": "mail_manager", "args": {}, "id": "abc"}
    assert is_critical(tc) is True

def test_is_critical_process_and_clear_linkedin_post():
    tc = {"name": "process_and_clear_linkedin_post", "args": {}, "id": "abc"}
    assert is_critical(tc) is True

def test_relay_local_payload_is_not_critical():
    tc = {"name": "relay_local_payload", "args": {}, "id": "abc"}
    assert is_critical(tc) is False

def test_is_critical_execute_local_pipeline():
    tc = {"name": "execute_local_pipeline", "args": {}, "id": "abc"}
    assert is_critical(tc) is True

def test_drive_delete_is_critical():
    tc = {"name": "drive_manager", "args": {"action": "delete"}, "id": "abc"}
    assert is_critical(tc) is True

def test_drive_share_is_critical():
    tc = {"name": "drive_manager", "args": {"action": "share"}, "id": "abc"}
    assert is_critical(tc) is True

def test_drive_download_is_not_critical():
    tc = {"name": "drive_manager", "args": {"action": "download"}, "id": "abc"}
    assert is_critical(tc) is False

def test_drive_list_files_is_not_critical():
    tc = {"name": "drive_manager", "args": {"action": "list_files"}, "id": "abc"}
    assert is_critical(tc) is False

def test_not_critical_search_memory():
    tc = {"name": "search_memory", "args": {}, "id": "abc"}
    assert is_critical(tc) is False

def test_not_critical_get_news():
    tc = {"name": "get_news", "args": {}, "id": "abc"}
    assert is_critical(tc) is False

def test_is_critical_compute_score():
    """
    Memory scoring test — compute_score returns float in [0,1].
    """
    from memory.vector_store import compute_score
    meta = {
        "importance": 10,
        "retrieval_count": 5,
        "confidence": 0.9,
        "last_accessed": __import__("time").time(),
    }
    score = compute_score(meta)
    assert 0.0 <= score <= 1.0
    assert score > 0.5  # high importance/confidence → high score
