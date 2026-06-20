from unittest.mock import patch
import memory.session_memory as sm


def test_temporary_and_event_both_saved_when_event_progresses_state():
    event_candidate = {
        "memory_type": "fact",
        "fact": "[USER_FACT]: Στις 2026-06-17, πήγαμε να πάρουμε τον Αλέξανδρο από την κατασκήνωση",
        "category": "family",
        "entities": ["Αλέξανδρος"],
        "topic": "trip",
        "topic_detail": "camp",
        "state_markers": ["returned"],
        "time_scope": "2026-06-17",
        "relation_type": "follow_up",
    }
    temporary_candidate = {
        "memory_type": "fact",
        "fact": "[USER_FACT]: Στις 2026-06-17, ο Αλέξανδρος είναι στην κατασκήνωση",
        "category": "family",
        "entities": ["Αλέξανδρος"],
        "topic": "trip",
        "topic_detail": "camp",
        "state_markers": ["away"],
        "time_scope": "2026-06-17",
        "relation_type": "temporary_state",
    }

    with patch.object(sm, "_extract_event_memory_candidate", return_value=event_candidate), \
         patch.object(sm, "_extract_temporary_family_memory_candidate", return_value=temporary_candidate), \
         patch.object(sm, "_extract_confirmed_memory_candidate", return_value=None), \
         patch.object(sm, "safe_gemini_call") as mock_llm, \
         patch.object(sm.memory, "save") as mock_save:

        mock_llm.return_value.text = "ΚΕΝΟ"
        sm.run_memory_sifter_fast("user", "ai", "TestAgent", "telegram")

    assert mock_save.call_count == 2


def test_confirmed_candidate_not_saved_twice_when_same_as_temporary():
    temporary_candidate = {"memory_type": "fact", "fact": "[USER_FACT]: Στις 2026-06-17, ο Αλέξανδρος γυρνάει από την κατασκήνωση", "category": "family"}
    confirmed_candidate = {"memory_type": "fact", "fact": "[USER_FACT]: Στις 2026-06-17, ο Αλέξανδρος γυρνάει από την κατασκήνωση", "category": "family"}

    with patch.object(sm, "_extract_event_memory_candidate", return_value=None), \
         patch.object(sm, "_extract_temporary_family_memory_candidate", return_value=temporary_candidate), \
         patch.object(sm, "_extract_confirmed_memory_candidate", return_value=confirmed_candidate), \
         patch.object(sm, "safe_gemini_call") as mock_llm, \
         patch.object(sm.memory, "save") as mock_save:

        mock_llm.return_value.text = "ΚΕΝΟ"
        sm.run_memory_sifter_fast("user", "ai", "TestAgent", "telegram")

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
        sm.run_memory_sifter_fast("user", "ai", "TestAgent", "telegram")

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
        sm.run_memory_sifter_fast("user", "ai", "TestAgent", "telegram")

    assert mock_save.call_count == 1


def test_collect_deterministic_candidates_keeps_both_when_temporary_and_event_differ():
    event_candidate = {
        "memory_type": "fact",
        "fact": "[USER_FACT]: Στις 2026-06-17, πήγαμε να πάρουμε τον Αλέξανδρο από την κατασκήνωση",
        "category": "family",
        "entities": ["Αλέξανδρος"],
        "topic": "trip",
        "topic_detail": "camp",
        "time_scope": "2026-06-17",
        "state_markers": ["returned"],
        "relation_type": "follow_up",
    }
    temporary_candidate = {
        "memory_type": "fact",
        "fact": "[USER_FACT]: Στις 2026-06-17, ο Αλέξανδρος είναι στην κατασκήνωση",
        "category": "family",
        "entities": ["Αλέξανδρος"],
        "topic": "trip",
        "topic_detail": "camp",
        "time_scope": "2026-06-17",
        "state_markers": ["away"],
        "relation_type": "temporary_state",
    }

    with patch.object(sm, "_extract_event_memory_candidate", return_value=event_candidate), \
         patch.object(sm, "_extract_temporary_family_memory_candidate", return_value=temporary_candidate), \
         patch.object(sm, "_extract_confirmed_memory_candidate", return_value=None):
        selected = sm._collect_deterministic_candidates("u", "a", agent_name="x", channel="telegram")

    assert len(selected) == 2


def test_normalize_memory_candidate_builds_structured_fields():
    candidate = sm._normalize_memory_candidate({
        "memory_type": "fact",
        "fact": "[USER_FACT]: Στις 2026-06-17, ο Αλέξανδρος γύρισε σπίτι πολύ κουρασμένος από την κατασκήνωση",
        "category": "family",
        "source": "telegram",
        "agent_name": "Chat_Agent",
    })

    assert candidate["topic"] in {"trip", "health", "family"}
    assert "returned" in candidate["state_markers"]
    assert "tired" in candidate["state_markers"]
    assert candidate["time_scope"]
    assert candidate["tags"]


def test_fact_matches_any_detects_contained_fact():
    fact = "[USER_FACT]: Στις 2026-06-17, ο Αλέξανδρος γυρνάει σπίτι από την κατασκήνωση"
    seeds = ["[USER_FACT]: Στις 2026-06-17, ο Αλέξανδρος γυρνάει σπίτι"]
    assert sm._fact_matches_any(fact, seeds) is True


def test_slow_sifter_skips_seed_duplicates():
    class MockResponse:
        def __init__(self, text):
            self.text = text
            
    mock_json = '[{"fact": "[USER_FACT]: test duplicate fact", "category": "family"}]'
    
    with patch("memory.session_memory.safe_gemini_call", return_value=MockResponse(mock_json)), \
         patch("memory.session_memory.memory.save") as mock_save:
        
        seeds = ["[USER_FACT]: test duplicate fact"]
        sm.run_memory_sifter_slow("user", "ai", deterministic_seed_facts=seeds)
        
        mock_save.assert_not_called()


def test_same_identity_same_state_near_duplicate_skips_second():
    a = {
        "memory_type": "fact",
        "fact": "[USER_FACT]: Ο Αλέξανδρος είναι στην κατασκήνωση",
        "category": "family",
        "entities": ["Αλέξανδρος"],
        "topic": "trip",
        "topic_detail": "camp",
        "state_markers": ["away"],
        "time_scope": "2026-06-17",
        "relation_type": "temporary_state",
        "tags": ["alexandros", "camp", "away"],
    }
    b = {
        "memory_type": "fact",
        "fact": "[USER_FACT]: Ο Αλέξανδρος βρίσκεται στην κατασκήνωση",
        "category": "family",
        "entities": ["Αλέξανδρος"],
        "topic": "trip",
        "topic_detail": "camp",
        "state_markers": ["away"],
        "time_scope": "2026-06-17",
        "relation_type": "temporary_state",
        "tags": ["alexandros", "camp", "away"],
    }

    selected = []
    sm._append_candidate_safely(selected, a)
    sm._append_candidate_safely(selected, b)

    assert len(selected) == 1


def test_same_identity_new_state_keeps_both():
    a = {
        "memory_type": "fact",
        "fact": "[USER_FACT]: Ο Αλέξανδρος είναι στην κατασκήνωση",
        "category": "family",
        "entities": ["Αλέξανδρος"],
        "topic": "trip",
        "topic_detail": "camp",
        "state_markers": ["away"],
        "time_scope": "2026-06-17",
        "relation_type": "temporary_state",
        "tags": ["alexandros", "camp", "away"],
    }
    b = {
        "memory_type": "fact",
        "fact": "[USER_FACT]: Ο Αλέξανδρος γύρισε σπίτι από την κατασκήνωση",
        "category": "family",
        "entities": ["Αλέξανδρος"],
        "topic": "trip",
        "topic_detail": "camp",
        "state_markers": ["returned"],
        "time_scope": "2026-06-17",
        "relation_type": "state_update",
        "tags": ["alexandros", "camp", "returned"],
    }

    selected = []
    sm._append_candidate_safely(selected, a)
    sm._append_candidate_safely(selected, b)

    assert len(selected) == 2


def test_same_day_same_topic_same_state_reword_skips_duplicate():
    a = {
        "memory_type": "fact",
        "fact": "[USER_FACT]: Η Σοφία έχει ρεπό σήμερα",
        "category": "family",
        "entities": ["Σοφία"],
        "topic": "work",
        "topic_detail": "",
        "state_markers": ["confirmed"],
        "time_scope": "2026-06-18",
        "relation_type": "confirmed",
        "tags": ["sofia", "work", "confirmed"],
    }
    b = {
        "memory_type": "fact",
        "fact": "[USER_FACT]: Η Σοφία σήμερα έχει ρεπό",
        "category": "family",
        "entities": ["Σοφία"],
        "topic": "work",
        "topic_detail": "",
        "state_markers": ["confirmed"],
        "time_scope": "2026-06-18",
        "relation_type": "confirmed",
        "tags": ["sofia", "work", "confirmed"],
    }

    selected = []
    sm._append_candidate_safely(selected, a)
    sm._append_candidate_safely(selected, b)

    assert len(selected) == 1


def test_more_informative_relation_type_counts_as_new_information():
    old = {
        "fact": "[USER_FACT]: Ο Αλέξανδρος είναι στην κατασκήνωση",
        "category": "family",
        "entities": ["Αλέξανδρος"],
        "topic": "trip",
        "topic_detail": "camp",
        "state_markers": ["away"],
        "time_scope": "2026-06-17",
        "relation_type": "new_fact",
        "tags": ["alexandros", "camp"],
    }
    new = {
        "fact": "[USER_FACT]: Ο Αλέξανδρος είναι στην κατασκήνωση",
        "category": "family",
        "entities": ["Αλέξανδρος"],
        "topic": "trip",
        "topic_detail": "camp",
        "state_markers": ["away"],
        "time_scope": "2026-06-17",
        "relation_type": "temporary_state",
        "tags": ["alexandros", "camp", "away"],
    }

    assert sm._candidate_has_new_information(new, old) is True