from services.behavioral_pattern_aggregator import aggregate_behavioral_pattern_candidates


def _event(**overrides):
    event = {
        "event_type": "meal",
        "action_kind": "consume",
        "category": "food",
        "subject": "user",
        "item": "pasta",
        "status": "consumed",
        "event_date": "2026-08-01",
        "record_state": "confirmed",
    }
    event.update(overrides)
    return event


def test_aggregator_returns_evidence_after_three_distinct_dates():
    candidates = aggregate_behavioral_pattern_candidates([
        _event(event_date="2026-08-01"),
        _event(event_date="2026-08-04"),
        _event(event_date="2026-08-07"),
    ])

    assert candidates == [{
        "event_type": "meal",
        "action_kind": "consume",
        "category": "food",
        "subject": "user",
        "item": "pasta",
        "status": "consumed",
        "occurrence_count": 3,
        "first_date": "2026-08-01",
        "last_date": "2026-08-07",
    }]


def test_aggregator_requires_three_distinct_dates_not_three_events():
    candidates = aggregate_behavioral_pattern_candidates([
        _event(event_date="2026-08-01"),
        _event(event_date="2026-08-01"),
        _event(event_date="2026-08-04"),
    ])

    assert candidates == []


def test_aggregator_canonicalizes_equivalent_iso_dates_before_counting():
    candidates = aggregate_behavioral_pattern_candidates([
        _event(event_date="2026-01-01"),
        _event(event_date="20260101"),
        _event(event_date="2026-W01-4"),
        _event(event_date="2026-01-04"),
        _event(event_date="2026-01-07"),
    ])

    assert candidates == [{
        "event_type": "meal",
        "action_kind": "consume",
        "category": "food",
        "subject": "user",
        "item": "pasta",
        "status": "consumed",
        "occurrence_count": 5,
        "first_date": "2026-01-01",
        "last_date": "2026-01-07",
    }]


def test_aggregator_groups_case_variants_under_one_deterministic_signature():
    candidates = aggregate_behavioral_pattern_candidates([
        _event(item="Pasta", event_date="2026-08-01"),
        _event(item="pasta", event_date="2026-08-04"),
        _event(item="PASTA", event_date="2026-08-07"),
    ])

    assert candidates == [{
        "event_type": "meal",
        "action_kind": "consume",
        "category": "food",
        "subject": "user",
        "item": "pasta",
        "status": "consumed",
        "occurrence_count": 3,
        "first_date": "2026-08-01",
        "last_date": "2026-08-07",
    }]


def test_aggregator_groups_named_observations_despite_taxonomy_drift():
    """Repeated named observations remain visible when extractor labels evolve."""
    candidates = aggregate_behavioral_pattern_candidates([
        _event(
            event_type="consumption",
            action_kind="consume",
            category="alcohol",
            item="beer",
            status="completed",
            event_date="2026-08-01",
        ),
        _event(
            event_type="consume",
            action_kind="consume",
            category="food_and_drink",
            item="beer",
            status="completed",
            event_date="2026-08-04",
        ),
        _event(
            event_type="alcohol_consumption",
            action_kind="consume",
            category="substance_use",
            item="beer",
            status="completed",
            event_date="2026-08-07",
        ),
    ])

    assert candidates == [{
        "event_type": "alcohol_consumption",
        "action_kind": "consume",
        "category": "substance_use",
        "subject": "user",
        "item": "beer",
        "status": "completed",
        "occurrence_count": 3,
        "first_date": "2026-08-01",
        "last_date": "2026-08-07",
    }]


def test_aggregator_does_not_merge_named_observations_for_different_subjects():
    """A shared item alone is never enough to form a cross-person pattern."""
    candidates = aggregate_behavioral_pattern_candidates([
        _event(item="beer", subject="user", event_date="2026-08-01"),
        _event(item="beer", subject="partner", event_date="2026-08-04"),
        _event(item="beer", subject="user", event_date="2026-08-07"),
    ])

    assert candidates == []


def test_aggregator_does_not_merge_named_observations_with_different_action_kinds():
    """Different actions cannot inflate one named-item pattern."""
    candidates = aggregate_behavioral_pattern_candidates([
        _event(
            event_type="purchase",
            action_kind="acquire",
            category="shopping",
            item="beer",
            status="completed",
            event_date="2026-08-01",
        ),
        _event(
            event_type="acquisition",
            action_kind="acquire",
            category="errand",
            item="beer",
            status="completed",
            event_date="2026-08-04",
        ),
        _event(
            event_type="consumption",
            action_kind="consume",
            category="alcohol",
            item="beer",
            status="completed",
            event_date="2026-08-07",
        ),
    ])

    assert candidates == []


def test_aggregator_keeps_legacy_named_events_under_strict_taxonomy_grouping():
    """Events stored before action kinds existed are never semantically guessed."""
    candidates = aggregate_behavioral_pattern_candidates([
        _event(action_kind=None, event_date="2026-08-01"),
        _event(action_kind=None, event_date="2026-08-04"),
        _event(action_kind=None, event_date="2026-08-07"),
    ])

    assert candidates[0]["action_kind"] is None


def test_aggregator_does_not_merge_distinct_legacy_named_items():
    """Legacy events retain item identity when no action kind was stored."""
    candidates = aggregate_behavioral_pattern_candidates([
        _event(action_kind=None, item="pasta", event_date="2026-08-01"),
        _event(action_kind=None, item="salad", event_date="2026-08-04"),
        _event(action_kind=None, item="beer", event_date="2026-08-07"),
    ])

    assert candidates == []


def test_aggregator_excludes_candidate_and_incomplete_events():
    candidates = aggregate_behavioral_pattern_candidates([
        _event(event_date="2026-08-01"),
        _event(event_date="2026-08-04", record_state="candidate"),
        _event(event_date="2026-08-07"),
        _event(event_date="2026-08-10", event_type="", item=""),
    ])

    assert candidates == []


def test_aggregator_orders_by_evidence_then_recency():
    candidates = aggregate_behavioral_pattern_candidates([
        _event(item="pasta", event_date="2026-08-01"),
        _event(item="pasta", event_date="2026-08-04"),
        _event(item="pasta", event_date="2026-08-07"),
        _event(item="salad", event_date="2026-08-02"),
        _event(item="salad", event_date="2026-08-05"),
        _event(item="salad", event_date="2026-08-08"),
        _event(item="salad", event_date="2026-08-11"),
    ])

    assert [candidate["item"] for candidate in candidates] == ["salad", "pasta"]
