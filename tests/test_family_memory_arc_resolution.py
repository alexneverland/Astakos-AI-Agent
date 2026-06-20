from memory.family_arc_resolution import (
    _same_family_arc,
    _decide_family_arc_resolution,
    _pick_richer_candidate,
)


def _candidate(
    fact: str,
    *,
    entities=None,
    topic="trip",
    relation_type="temporary_state",
    category="family",
    date="2026-06-18",
    state_markers=None,
):
    return {
        "memory_type": "fact",
        "fact": fact,
        "category": category,
        "entities": entities or ["alexandros"],
        "topic": topic,
        "relation_type": relation_type,
        "date": date,
        "state_markers": state_markers or [],
    }


def test_same_family_arc_exact_duplicate_skips():
    old = _candidate("[USER_FACT]: On 2026-06-18, Alexandros returned home from camp")
    new = _candidate("[USER_FACT]: On 2026-06-18, Alexandros returned home from camp")
    assert _same_family_arc(old, new) is True
    assert _decide_family_arc_resolution(old, new) == "skip_exact_duplicate"


def test_same_family_arc_richer_same_stage_merges():
    old = _candidate("[USER_FACT]: On 2026-06-18, Alexandros is at camp")
    new = _candidate("[USER_FACT]: On 2026-06-18, Alexandros is at camp for 9 days")
    assert _same_family_arc(old, new) is True
    assert _decide_family_arc_resolution(old, new) == "merge_enrich_existing"
    assert _pick_richer_candidate(old, new) == new


def test_same_family_arc_new_stage_keeps_both():
    old = _candidate("[USER_FACT]: On 2026-06-18, Alexandros is at camp", relation_type="temporary_state")
    new = _candidate(
        "[USER_FACT]: On 2026-06-18, Alexandros returned home from camp tired",
        relation_type="follow_up",
        state_markers=["returned", "tired", "home"],
    )
    assert _same_family_arc(old, new) is True
    assert _decide_family_arc_resolution(old, new) == "add_new_memory"


def test_same_day_same_person_different_event_keeps_both():
    old = _candidate("[USER_FACT]: On 2026-06-18, Alexandros went to the park", topic="outing", relation_type="new_fact")
    new = _candidate("[USER_FACT]: On 2026-06-18, Alexandros ate fish", topic="food", relation_type="new_fact")
    assert _same_family_arc(old, new) is False
    assert _decide_family_arc_resolution(old, new) == "add_new_memory"


def test_different_family_entities_do_not_merge():
    old = _candidate("[USER_FACT]: On 2026-06-18, Alexandros is at camp", entities=["alexandros"], topic="trip")
    new = _candidate("[USER_FACT]: On 2026-06-18, Maria is at her friend's house", entities=["maria"], topic="trip")
    assert _same_family_arc(old, new) is False
    assert _decide_family_arc_resolution(old, new) == "add_new_memory"


def test_confirmed_same_fact_does_not_duplicate_temporary():
    old = _candidate("[USER_FACT]: On 2026-06-18, Alexandros returns from camp", relation_type="temporary_state")
    new = _candidate(
        "[USER_FACT]: On 2026-06-18, Alexandros returns from camp",
        relation_type="confirmed",
        state_markers=["confirmed"],
    )
    assert _same_family_arc(old, new) is True
    assert _decide_family_arc_resolution(old, new) == "skip_exact_duplicate"


def test_same_family_arc_same_topic_but_different_date_keeps_both():
    old = _candidate("[USER_FACT]: On 2026-06-18, Alexandros is at camp", date="2026-06-18")
    new = _candidate("[USER_FACT]: On 2026-06-25, Alexandros goes to camp again", date="2026-06-25")
    assert _same_family_arc(old, new) is False
    assert _decide_family_arc_resolution(old, new) == "add_new_memory"
