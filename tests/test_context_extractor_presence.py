import pytest
from unittest.mock import patch, MagicMock

from services.context_extractor import (
    _has_communication_verb,
    _has_strong_presence,
    extract_and_update_context_flags,
)
from core import nl_config

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


def test_context_phrase_guards_use_external_intent_lists(monkeypatch) -> None:
    """Ensure communication and presence matching follows configured intent lists."""
    monkeypatch.setattr(
        "services.context_extractor.nl_config.CE_COMMUNICATION_VERBS",
        ("configured communication",),
    )
    monkeypatch.setattr(
        "services.context_extractor.nl_config.CE_STRONG_PRESENCE",
        ("configured presence",),
    )

    assert _has_communication_verb("configured communication") is True
    assert _has_communication_verb("unrelated event") is False
    assert _has_strong_presence("configured presence") is True
    assert _has_strong_presence("unrelated event") is False


def test_live_input_guard_lists_include_both_external_languages() -> None:
    """Ensure live input guards retain configured phrases from both language files."""
    communication_markers = nl_config.get_live_input_guard_list(
        "context_extractor",
        "communication_verbs",
    )
    presence_markers = nl_config.get_live_input_guard_list(
        "context_extractor",
        "strong_presence_phrases",
    )

    for language_code in ("el", "en"):
        language_intents = nl_config._load_base_intents(language_code)
        expected_communication = language_intents["context_extractor"]["communication_verbs"]
        expected_presence = language_intents["context_extractor"]["strong_presence_phrases"]

        assert set(expected_communication).issubset(communication_markers)
        assert set(expected_presence).issubset(presence_markers)
        assert all(_has_communication_verb(marker) for marker in expected_communication)
        assert all(_has_strong_presence(marker) for marker in expected_presence)


def test_context_extractor_keeps_kid_partner_flag_for_unaccented_name_variant(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Preserve an explicit child-with-partner flag when the name omits accents."""
    import services.context_extractor as extractor

    calls: dict[str, str] = {}
    response = MagicMock(text='{"kid1_with_partner": true, "kid1_away_from_home": true}')
    monkeypatch.setattr(extractor.nl_config, "CE_KID1_NAMES", ("Νίκος",))
    monkeypatch.setattr(
        extractor,
        "set_context_state",
        lambda key, value, expires_at=None: calls.__setitem__(key, value),
    )
    monkeypatch.setattr(extractor, "get_context_state", lambda key: None)
    monkeypatch.setattr(extractor, "safe_gemini_call", lambda prompt: response)
    monkeypatch.setattr(extractor, "reconcile_fact_to_routines", lambda *args, **kwargs: {})
    monkeypatch.setattr(extractor, "apply_routine_reconciliation_directives", lambda *args, **kwargs: None)
    monkeypatch.setattr(extractor, "load_recent_context", lambda *args, **kwargs: [])

    extractor.extract_and_update_context_flags("Είμαι σπίτι και ο νικοσ είναι στο πάρκο.")

    assert calls.get("kid1_with_partner") == "true"
    assert calls.get("kid1_away_from_home") == "true"
