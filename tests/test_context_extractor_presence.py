import pytest
from unittest.mock import patch, MagicMock

from services.context_extractor import extract_and_update_context_flags

@pytest.fixture
def mock_gemini():
    with patch("services.context_extractor.safe_gemini_call") as m:
        mock_response = MagicMock()
        mock_response.text = "{}"
        m.return_value = mock_response
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

def test_context_extractor_presence_rules(mock_gemini, mock_reconciler, mock_history):
    with patch("services.context_extractor.set_context_state") as mock_set, \
         patch("services.context_extractor.get_context_state") as mock_get:
        
        mock_get.return_value = None # No existing work state

        # Test 1: "Μίλησα μαζί της τώρα"
        mock_gemini.return_value.text = '{"partner_with_user": true, "kid1_with_user": true}'
        extract_and_update_context_flags("Μίλησα μαζί της τώρα")
        calls = {call[0][0]: call[0][1] for call in mock_set.call_args_list}
        assert "partner_with_user" not in calls
        assert "kid1_with_user" not in calls
        mock_set.reset_mock()

        # Test 1.5: explicit false from LLM for comms message
        mock_gemini.return_value.text = '{"partner_with_user": false}'
        extract_and_update_context_flags("Στείλε ένα μήνυμα στη Σοφία, μαζί ήμαστε αλλά της αρέσουν τα μηνύματα")
        calls = {call[0][0]: call[0][1] for call in mock_set.call_args_list}
        assert "partner_with_user" not in calls
        mock_set.reset_mock()

        # Test 2: "Μίλησα στο τηλέφωνο με τη Partner"
        mock_gemini.return_value.text = '{"partner_with_user": true}'
        extract_and_update_context_flags("Μίλησα στο τηλέφωνο με τη Partner")
        calls = {call[0][0]: call[0][1] for call in mock_set.call_args_list}
        assert "partner_with_user" not in calls
        mock_set.reset_mock()

        # Test 3: "Είμαι μαζί της τώρα"
        mock_gemini.return_value.text = '{"partner_with_user": true}'
        extract_and_update_context_flags("Είμαι μαζί της τώρα")
        calls = {call[0][0]: call[0][1] for call in mock_set.call_args_list}
        assert calls.get("partner_with_user") == "true"
        mock_set.reset_mock()

        # Test 4: "Είμαστε όλοι μαζί τώρα"
        mock_gemini.return_value.text = '{}'
        extract_and_update_context_flags("Είμαστε όλοι μαζί τώρα")
        calls = {call[0][0]: call[0][1] for call in mock_set.call_args_list}
        assert calls.get("partner_with_user") == "true"
        assert calls.get("kid1_with_user") == "true"
        mock_set.reset_mock()

        # Test 5: "Μίλησα μαζί της τώρα, εγώ είμαι ακόμα στη δουλειά"
        mock_get.return_value = {"value": "true"}
        mock_gemini.return_value.text = '{"partner_with_user": true}'
        extract_and_update_context_flags("Μίλησα μαζί της τώρα, εγώ είμαι ακόμα στη δουλειά")
        calls = {call[0][0]: call[0][1] for call in mock_set.call_args_list}
        assert calls.get("partner_with_user") == "false"
        mock_set.reset_mock()
