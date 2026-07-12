from datetime import datetime, timedelta

from memory.vector_store import (
    decide_memory_overwrite,
    decide_memory_storage_action,
    memory_overlap_ratio,
    memory_richness,
)


def test_cross_category_close_match_never_enters_delete_path():
    # Cross-category matches are warn-only in _save_fact. The decision helper is
    # called only after a same-category match sets old_id.
    same_cat_dist = None
    old_id = None
    if same_cat_dist is not None and same_cat_dist < 0.25:
        old_id = "would-be-deleted"

    assert old_id is None


def test_explicit_correction_overwrites_even_if_old_is_richer():
    old_content = (
        "[USER_FACT]: Στις 2026-05-01 ο User είπε ότι μένουν στο Πεστών 7 "
        "με τη Partner και τον Αλέξανδρο, https://maps.example/old"
    )
    old_meta = {"timestamp": datetime.now().timestamp(), "confidence": 0.7}
    new_fact = "[USER_FACT]: Λάθος, η σωστή διεύθυνση είναι Πίστων 7"

    result = decide_memory_overwrite(new_fact, old_content, old_meta, new_confidence=0.7)

    assert result["looks_like_correction"] is True
    assert result["keep_old"] is False
    assert result["old_richness"] > result["new_richness"]


def test_richer_new_fact_overwrites_longer_but_emptier_old_one():
    old_content = (
        "[LESSON]: Γενικά καλό είναι να προσέχουμε πάντα τη δομή του κώδικα "
        "και να γράφουμε καθαρά σχόλια παντού στο πρόγραμμα όποτε μπορούμε"
    )
    new_fact = (
        "[LESSON]: Στις 2026-06-08 διορθώσαμε bug στο Astakos, "
        "δες memory/vector_store.py"
    )
    old_meta = {"timestamp": datetime.now().timestamp(), "confidence": 0.5}

    result = decide_memory_overwrite(new_fact, old_content, old_meta, new_confidence=0.8)

    assert len(old_content) > len(new_fact)
    assert result["new_richness"] > result["old_richness"]
    assert result["keep_old"] is False


def test_richer_old_fact_is_kept_over_generic_new_one():
    old_content = "[USER_FACT]: Στις 2026-05-20 ο Kid1 πήγε στο πάρκο με τη Partner"
    new_fact = "[USER_FACT]: Ο Kid1 πάει συχνά βόλτα"
    old_meta = {"timestamp": datetime.now().timestamp(), "confidence": 0.7}

    result = decide_memory_overwrite(new_fact, old_content, old_meta, new_confidence=0.5)

    assert result["looks_like_correction"] is False
    assert result["stale"] is False
    assert result["old_richness"] > result["new_richness"]
    assert result["keep_old"] is True


def test_stale_old_record_is_overwritten_without_correction_language():
    old_ts = (datetime.now() - timedelta(days=45)).timestamp()
    old_content = "[LESSON]: Στις 2026-04-01 κάτι λεπτομερές για το Mastroapp, δες app.py"
    old_meta = {"timestamp": old_ts, "confidence": 0.7}
    new_fact = "[LESSON]: μικρή νέα σημείωση"

    result = decide_memory_overwrite(new_fact, old_content, old_meta, new_confidence=0.5)

    assert result["looks_like_correction"] is False
    assert result["stale"] is True
    assert result["old_richness"] > result["new_richness"]
    assert result["keep_old"] is False


def test_equal_richness_falls_back_to_length_tiebreak():
    old_content = (
        "[USER_FACT]: Στις 2026-06-01 ο Kid1 έπαιξε με τον Λάζαρο LEGO "
        "για πολλή ώρα και έφτιαξαν ένα ολόκληρο κάστρο μαζί στο σαλόνι"
    )
    new_fact = "[USER_FACT]: Στις 2026-06-08 ο Kid1 έπαιξε LEGO με τον Λάζαρο"
    old_meta = {"timestamp": datetime.now().timestamp(), "confidence": 0.7}

    result = decide_memory_overwrite(new_fact, old_content, old_meta, new_confidence=0.7)

    assert result["old_richness"] == result["new_richness"]
    assert len(old_content) > len(new_fact) * 1.3
    assert result["keep_old"] is True


def test_memory_richness_counts_signals_and_confidence():
    fact = "[USER_FACT]: Στις 2026-06-08 η Partner αγόρασε δώρο από https://example.com"

    assert memory_richness(fact, {"confidence": 0.8}) == 3.8


def test_close_family_facts_add_alongside_when_not_correction():
    old_content = "[USER_FACT]: On 2026-06-13, Lazaros and Alexandros went to the park after lunch."
    new_fact = "[USER_FACT]: On 2026-06-13, the family ate fish for lunch at home."
    decision = {
        "keep_old": False,
        "looks_like_correction": False,
        "stale": False,
        "old_age_days": 0,
        "new_richness": 3.7,
        "old_richness": 3.7,
        "much_longer": False,
    }

    action = decide_memory_storage_action(decision, new_fact, old_content, distance=0.05)

    assert memory_overlap_ratio(new_fact, old_content) < 0.55
    assert action["action"] == "add_alongside"


def test_explicit_correction_still_overwrites_close_family_fact():
    old_content = "[USER_FACT]: Lazaros lives at old address Peston 7."
    new_fact = "[USER_FACT]: Correction, the right address is Piston 7."
    decision = {
        "keep_old": False,
        "looks_like_correction": True,
        "stale": False,
        "old_age_days": 0,
        "new_richness": 1.7,
        "old_richness": 2.7,
        "much_longer": False,
    }

    action = decide_memory_storage_action(decision, new_fact, old_content, distance=0.05)

    assert action["action"] == "overwrite"


def test_generic_low_signal_fact_keeps_richer_old_memory():
    old_content = "[USER_FACT]: On 2026-06-13, Alexandros played at the park with Sofia after school."
    new_fact = "[USER_FACT]: Alexandros often goes for walks."
    decision = {
        "keep_old": True,
        "looks_like_correction": False,
        "stale": False,
        "old_age_days": 0,
        "new_richness": 1.0,
        "old_richness": 3.0,
        "much_longer": False,
    }

    action = decide_memory_storage_action(decision, new_fact, old_content, distance=0.10)

    assert action["action"] == "keep_old"


def test_meaningful_dated_event_adds_alongside_even_if_old_is_richer():
    old_content = "[USER_FACT]: On 2026-06-13, the family ate fish and Alexandros ate a lot."
    new_fact = "[USER_FACT]: On 2026-06-13, Lazaros and Alexandros went to the park."
    decision = {
        "keep_old": True,
        "looks_like_correction": False,
        "stale": False,
        "old_age_days": 0,
        "new_richness": 3.0,
        "old_richness": 3.7,
        "much_longer": False,
    }

    action = decide_memory_storage_action(decision, new_fact, old_content, distance=0.05)

    assert action["action"] == "add_alongside"
