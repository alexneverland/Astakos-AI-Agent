import pytest
from unittest.mock import patch, MagicMock

from services.context_extractor import (
    extract_and_update_context_flags,
    _looks_like_future_departure,
    _has_park_live_presence,
    _looks_like_found_them_reply,
    _looks_like_everyone_together,
)
import config

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
    with patch("services.context_extractor.set_context_state") as m_set, \
         patch("services.context_extractor.get_context_state") as m_get:
        m_get.return_value = None
        yield m_set

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
    assert calls.get("partner_with_user") == "true"
    assert calls.get("kid1_with_user") == "true"
    assert calls.get("kid1_with_partner") == "true"
    assert calls.get("kid1_away_from_home") == "false"

def test_context_extractor_found_them_at_park_uses_recent_family_context(mock_gemini, mock_db, mock_reconciler, mock_history):
    # recent context has partner/kid1/park
    mock_history.return_value = [
        {"content": f"η {config.PARTNER_NAME} πήγε τον {config.KID1_NAME} στο πάρκο"}
    ]
    
    user_text = "τώρα στο πάρκο και τους βρήκα"
    extract_and_update_context_flags(user_text)
    
    calls = {call[0][0]: call[0][1] for call in mock_db.call_args_list}
    
    assert calls.get("user_out_of_home") == "true"
    assert calls.get("kid1_with_user") == "true"
    assert calls.get("kid1_away_from_home") == "false"
    assert calls.get("partner_with_user") == "true"
    assert calls.get("kid1_with_partner") == "true"

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
    assert "kid1_with_user" not in calls


def test_future_departure_recognizes_future_plan_markers():
    assert _looks_like_future_departure("αύριο θα βγω για ποτό") is True
    assert _looks_like_future_departure("σήμερα το βράδυ θα πάω έξω") is True
    assert _looks_like_future_departure("θα βρεθώ με φίλους αργότερα") is True


def test_context_extractor_skips_visual_analysis_payload(
    mock_gemini,
    mock_db,
    mock_reconciler,
    mock_history,
):
    user_text = "[VISUAL ANALYSIS]: old photo from a park\nQuestion: what do you see?"

    extract_and_update_context_flags(user_text)

    mock_gemini.assert_not_called()
    mock_db.assert_not_called()

def test_context_extractor_still_here_at_park(mock_gemini, mock_db, mock_reconciler, mock_history):
    user_text = "είμαστε ακόμα εδώ στο πάρκο"
    extract_and_update_context_flags(user_text)
    
    calls = {call[0][0]: call[0][1] for call in mock_db.call_args_list}
    
    # Enriched by _has_park_live_presence
    assert calls.get("user_out_of_home") == "true"


def test_context_extractor_found_them_and_staying(mock_gemini, mock_db, mock_reconciler, mock_history):
    # recent context has partner/kid1
    mock_history.return_value = [
        {"content": f"η {config.PARTNER_NAME} είναι στο πάρκο με τον {config.KID1_NAME}"}
    ]
    
    user_text = "στο πάρκο, τους βρήκα και καθόμαστε κι άλλο"
    extract_and_update_context_flags(user_text)
    
    calls = {call[0][0]: call[0][1] for call in mock_db.call_args_list}
    
    assert calls.get("user_out_of_home") == "true"
    assert calls.get("kid1_with_user") == "true"
    assert calls.get("kid1_away_from_home") == "false"
    assert calls.get("partner_with_user") == "true"
    assert calls.get("kid1_with_partner") == "true"


def test_home_with_partner_does_not_mark_kid1_away_from_home(monkeypatch):
    import services.context_extractor as ce

    calls = {}

    def fake_set_context_state(key, value, expires_at=None):
        calls[key] = value

    class DummyResp:
        text = '{"user_at_work": true, "user_out_of_home": true, "family_at_home": true, "partner_with_user": false, "kid1_with_partner": true}'

    monkeypatch.setattr(ce, "set_context_state", fake_set_context_state)
    monkeypatch.setattr(ce, "safe_gemini_call", lambda prompt: DummyResp())
    monkeypatch.setattr(ce, "reconcile_fact_to_routines", lambda *a, **k: {"scored_directives": []})

    ce.extract_and_update_context_flags(
        f"Εγώ είμαι πρωινή βάρδια αυτή την εβδομάδα και η {config.PARTNER_NAME} σήμερα είναι με τον {config.KID1_NAME} στο σπίτι",
        "",
        "telegram",
    )

    assert calls.get("kid1_with_partner") == "true"
    assert calls.get("kid1_away_from_home") == "false"
    assert calls.get("user_out_of_home") == "false"
    assert calls.get("user_at_work") == "false"

def test_everyone_together_at_home_does_not_mark_user_out_of_home(mock_gemini, mock_db, mock_reconciler, mock_history):
    user_text = "Όλοι ήμαστε σπίτι μαζί τώρα παίζω με τον Αλέξανδρο"

    extract_and_update_context_flags(user_text)

    calls = {call[0][0]: call[0][1] for call in mock_db.call_args_list}

    assert calls.get("family_at_home") == "true"
    assert calls.get("user_out_of_home") == "false"
    assert calls.get("user_at_work") == "false"
    assert calls.get("partner_with_user") == "true"
    assert calls.get("kid1_with_user") == "true"
    assert calls.get("kid1_with_partner") == "true"


def test_no_explicit_kid_mention_does_not_write_false_kid_flags(monkeypatch):
    import services.context_extractor as ce
    calls = {}

    def fake_set_context_state(key, value, expires_at=None):
        calls[key] = value

    class DummyResp:
        text = '{"partner_with_user": true, "kid1_with_user": true, "kid1_with_partner": true}'

    monkeypatch.setattr(ce, "set_context_state", fake_set_context_state)
    monkeypatch.setattr(ce, "safe_gemini_call", lambda prompt: DummyResp())
    monkeypatch.setattr(ce, "reconcile_fact_to_routines", lambda *a, **k: {"scored_directives": []})
    monkeypatch.setattr(ce, "load_recent_context", lambda *a, **k: [])

    ce.extract_and_update_context_flags(
        "Είμαι με τη Σοφία τώρα",
        "",
        "telegram",
    )

    assert calls.get("partner_with_user") == "true"
    assert "kid1_with_user" not in calls
    assert "kid1_with_partner" not in calls
