from unittest.mock import patch
import memory.session_memory as sm


def test_temporary_candidate_wins_over_event_candidate():
    event_candidate = {"memory_type": "fact", "fact": "[USER_FACT]: Στις 2026-06-17, πήγαμε κάπου", "category": "family"}
    temporary_candidate = {"memory_type": "fact", "fact": "[USER_FACT]: Στις 2026-06-17, ο Αλέξανδρος είναι στην κατασκήνωση", "category": "family"}

    with patch.object(sm, "_extract_event_memory_candidate", return_value=event_candidate), \
         patch.object(sm, "_extract_temporary_family_memory_candidate", return_value=temporary_candidate), \
         patch.object(sm, "_extract_confirmed_memory_candidate", return_value=None), \
         patch.object(sm, "safe_gemini_call") as mock_llm, \
         patch.object(sm.memory, "save") as mock_save:

        mock_llm.return_value.text = "ΚΕΝΟ"
        sm._run_memory_sifter("user", "ai", "TestAgent", "telegram")

    assert mock_save.call_count == 1
    saved_kwargs = mock_save.call_args.kwargs
    assert saved_kwargs["fact"] == temporary_candidate["fact"]

def test_confirmed_candidate_not_saved_twice_when_same_as_temporary():
    temporary_candidate = {"memory_type": "fact", "fact": "[USER_FACT]: Στις 2026-06-17, ο Αλέξανδρος γυρνάει από την κατασκήνωση", "category": "family"}
    confirmed_candidate = {"memory_type": "fact", "fact": "[USER_FACT]: Στις 2026-06-17, ο Αλέξανδρος γυρνάει από την κατασκήνωση", "category": "family"}

    with patch.object(sm, "_extract_event_memory_candidate", return_value=None), \
         patch.object(sm, "_extract_temporary_family_memory_candidate", return_value=temporary_candidate), \
         patch.object(sm, "_extract_confirmed_memory_candidate", return_value=confirmed_candidate), \
         patch.object(sm, "safe_gemini_call") as mock_llm, \
         patch.object(sm.memory, "save") as mock_save:

        mock_llm.return_value.text = "ΚΕΝΟ"
        sm._run_memory_sifter("user", "ai", "TestAgent", "telegram")

    assert mock_save.call_count == 1
    saved_kwargs = mock_save.call_args.kwargs
    assert saved_kwargs["fact"] == temporary_candidate["fact"]

def test_confirmed_candidate_not_saved_twice_with_slight_overlap():
    temporary_candidate = {"memory_type": "fact", "fact": "[USER_FACT]: Στις 2026-06-17, ο Αλέξανδρος γυρνάει από την κατασκήνωση", "category": "family"}
    confirmed_candidate = {"memory_type": "fact", "fact": "[USER_FACT]: Στις 2026-06-17, ο Αλέξανδρος επιστρέφει σπίτι από την κατασκήνωση", "category": "family"}

    with patch.object(sm, "_extract_event_memory_candidate", return_value=None), \
         patch.object(sm, "_extract_temporary_family_memory_candidate", return_value=temporary_candidate), \
         patch.object(sm, "_extract_confirmed_memory_candidate", return_value=confirmed_candidate), \
         patch.object(sm, "safe_gemini_call") as mock_llm, \
         patch.object(sm.memory, "save") as mock_save:

        mock_llm.return_value.text = "ΚΕΝΟ"
        sm._run_memory_sifter("user", "ai", "TestAgent", "telegram")

    assert mock_save.call_count == 2
    
def test_confirmed_candidate_not_saved_twice_when_contained():
    temporary_candidate = {"memory_type": "fact", "fact": "[USER_FACT]: Στις 2026-06-17, πάμε κατασκήνωση", "category": "family"}
    confirmed_candidate = {"memory_type": "fact", "fact": "κατασκήνωση", "category": "family"}

    with patch.object(sm, "_extract_event_memory_candidate", return_value=None), \
         patch.object(sm, "_extract_temporary_family_memory_candidate", return_value=temporary_candidate), \
         patch.object(sm, "_extract_confirmed_memory_candidate", return_value=confirmed_candidate), \
         patch.object(sm, "safe_gemini_call") as mock_llm, \
         patch.object(sm.memory, "save") as mock_save:

        mock_llm.return_value.text = "ΚΕΝΟ"
        sm._run_memory_sifter("user", "ai", "TestAgent", "telegram")

    assert mock_save.call_count == 1
