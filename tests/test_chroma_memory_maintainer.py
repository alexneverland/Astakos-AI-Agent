from datetime import datetime


def test_candidate_from_message_classifies_family_gift():
    from scripts.chroma_memory_maintainer import candidate_from_message

    candidate = candidate_from_message({
        "id": "m1",
        "channel": "telegram",
        "role": "user",
        "content": "Κράτα αυτό το link για δώρο στη Partner στα γενέθλια",
        "date": "2026-06-05",
        "timestamp": "2026-06-05T19:30:00",
    })

    assert candidate is not None
    assert candidate.category == "family"
    assert candidate.source == "telegram"
    assert candidate.reason == "sql_backfill"
    assert candidate.fact.startswith("[USER_FACT]: Στις 2026-06-05")
    assert "Partner" in candidate.fact


def test_candidate_from_message_classifies_project_lesson():
    from scripts.chroma_memory_maintainer import candidate_from_message

    candidate = candidate_from_message({
        "id": "m2",
        "channel": "web",
        "role": "user",
        "content": "Στο Astakos tool πρέπει να διορθώσουμε το bug με το memory loop",
        "date": "2026-06-07",
        "timestamp": "2026-06-07T18:30:00",
    })

    assert candidate is not None
    assert candidate.category == "projects"
    assert candidate.fact.startswith("[LESSON]:")


def test_candidate_from_message_ignores_message_draft_noise():
    from scripts.chroma_memory_maintainer import candidate_from_message

    candidate = candidate_from_message({
        "id": "m3",
        "channel": "telegram",
        "role": "assistant",
        "content": "Το προσχέδιο αποθηκεύτηκε. Θέλεις αλλαγές ή να το στείλω;",
        "date": "2026-06-07",
        "timestamp": "2026-06-07T12:31:00",
    })

    assert candidate is None


def test_candidate_from_message_ignores_user_message_request():
    from scripts.chroma_memory_maintainer import candidate_from_message

    candidate = candidate_from_message({
        "id": "m4",
        "channel": "telegram",
        "role": "user",
        "content": "Στείλτης κανένα ωραίο μήνυμα είναι στο σπίτι με τον Αλέξανδρο",
        "date": "2026-06-01",
        "timestamp": "2026-06-01T10:41:00",
    })

    assert candidate is None


def test_candidate_from_message_ignores_transient_home_status():
    from scripts.chroma_memory_maintainer import candidate_from_message

    candidate = candidate_from_message({
        "id": "m5",
        "channel": "telegram",
        "role": "user",
        "content": "Έχω ανάψει ήδη κλιματιστικό με το που γύρισα στο σπίτι",
        "date": "2026-06-01",
        "timestamp": "2026-06-01T16:45:00",
    })

    assert candidate is None


def test_candidate_from_message_keeps_home_maintenance():
    from scripts.chroma_memory_maintainer import candidate_from_message

    candidate = candidate_from_message({
        "id": "m6",
        "channel": "telegram",
        "role": "user",
        "content": "Καθάρισα τον αφυγραντήρα, τον έλυσα ολόκληρο και είχε πολλή σκόνη",
        "date": "2026-06-07",
        "timestamp": "2026-06-07T12:15:00",
    })

    assert candidate is not None
    assert candidate.category == "home"


def test_dedupe_candidates_removes_exact_normalized_duplicates():
    from scripts.chroma_memory_maintainer import MemoryCandidate, dedupe_candidates

    first = MemoryCandidate(
        fact="[USER_FACT]: Στις 2026-06-07, Πήγαμε πάρκο με τον Αλέξανδρο",
        category="family",
        source="telegram",
        reason="sql_backfill",
        confidence=0.78,
        message_id="1",
        timestamp=datetime(2026, 6, 7).isoformat(),
        role="user",
    )
    second = MemoryCandidate(
        fact="[USER_FACT]:   Στις 2026-06-07, Πήγαμε πάρκο με τον Αλέξανδρο",
        category="family",
        source="web",
        reason="sql_backfill",
        confidence=0.78,
        message_id="2",
        timestamp=datetime(2026, 6, 7).isoformat(),
        role="user",
    )

    assert dedupe_candidates([first, second]) == [first]
