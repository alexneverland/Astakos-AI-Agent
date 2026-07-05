import pytest
from unittest.mock import patch, MagicMock

from services.context_extractor import (
    extract_and_update_context_flags,
    _looks_like_future_departure,
    _has_park_live_presence,
    _looks_like_found_them_reply,
    _looks_like_everyone_together,
)

@pytest.fixture
def mock_gemini():
    with patch("services.context_extractor.safe_gemini_call") as m:
        # Mocking an empty JSON response so the LLM doesn't set any flags.
        # This allows us to test the enrichment block independently.
        mock_response = MagicMock()
        mock_response.text = "{}"
        m.return_value = mock_response
        yield m

@pytest.fixture
def mock_db():
    with patch("services.context_extractor.set_context_state") as m:
        yield m

@pytest.fixture
def mock_reconciler():
    with patch("services.context_extractor.reconcile_fact_to_routines") as m_recon, \
         patch("services.context_extractor.apply_routine_reconciliation_directives") as m_apply:
        m_recon.return_value = {}
        yield m_recon, m_apply

@pytest.fixture
def mock_history():
    with patch("services.context_extractor.load_recent_context") as m:
        m.return_value = []
        yield m

def test_context_extractor_everyone_together_sets_family_flags(mock_gemini, mock_db, mock_reconciler, mock_history):
    user_text = "είμαστε όλοι μαζί στο πάρκο"
    
    extract_and_update_context_flags(user_text)
    
    # Verify the correct flags were set
    calls = {call[0][0]: call[0][1] for call in mock_db.call_args_list}
    
    assert calls.get("user_out_of_home") == "true"
    assert calls.get("sofia_with_user") == "true"
    assert calls.get("alexandros_with_user") == "true"
    assert calls.get("alexandros_with_sofia") == "true"
    assert calls.get("alexandros_away_from_home") == "false"

def test_context_extractor_found_them_at_park_uses_recent_family_context(mock_gemini, mock_db, mock_reconciler, mock_history):
    # recent context has Sofia/Alexandros/park
    mock_history.return_value = [
        {"content": "η σοφία πήγε το μικρό στο πάρκο"}
    ]
    
    user_text = "τώρα στο πάρκο και τους βρήκα"
    extract_and_update_context_flags(user_text)
    
    calls = {call[0][0]: call[0][1] for call in mock_db.call_args_list}
    
    assert calls.get("user_out_of_home") == "true"
    assert calls.get("alexandros_with_user") == "true"
    assert calls.get("alexandros_away_from_home") == "false"
    assert calls.get("sofia_with_user") == "true"
    assert calls.get("alexandros_with_sofia") == "true"

def test_context_extractor_future_departure_still_does_not_set_live_presence(mock_gemini, mock_db, mock_reconciler, mock_history):
    user_text = "σε 15 λεπτά φεύγουμε για πάρκο"
    
    # LLM might return user_out_of_home = true, we want to ensure it gets ignored
    mock_response = MagicMock()
    mock_response.text = '{"user_out_of_home": true}'
    mock_gemini.return_value = mock_response

    extract_and_update_context_flags(user_text)
    
    calls = {call[0][0]: call[0][1] for call in mock_db.call_args_list}
    
    # Because _looks_like_future_departure is true, "user_out_of_home" should NOT be set
    assert "user_out_of_home" not in calls
    assert "alexandros_with_user" not in calls
