"""Offline semantic-reference contracts through real observational persistence."""

import json
import sys
from datetime import date, datetime
from types import SimpleNamespace

import pytest

from memory import behavioral_event_state as store
from memory import conversation_history as history
from services import behavioral_event_extractor as extractor
from services.behavioral_conversation_evidence import load_behavioral_evidence
from services.behavioral_pattern_aggregator import aggregate_behavioral_pattern_candidates


def proposal(**overrides):
    """Return one structured provider decision, not a natural-language parser."""
    result = dict(idx=0, event_type="clean_enclosure", action_kind="maintain",
                  category="pet_care", subject="user", item="pet rabbit",
                  item_detail=None, status="completed", confidence=0.95,
                  negated=False, hypothetical=False, reported_by_user=True,
                  item_ref=None, behavior_ref=None)
    result.update(overrides)
    return result


def install_provider(monkeypatch, decision):
    """Replace only the cloud boundary, retaining extraction and storage code."""
    def invoke(_model, messages):
        return SimpleNamespace(content=json.dumps(decision(messages), ensure_ascii=False))
    monkeypatch.setitem(sys.modules, "core.brain",
                        SimpleNamespace(llm=object(), safe_llm_invoke=invoke))


@pytest.mark.parametrize("texts,item,kind,behavior,category", [
    (("Καθάρισα τον κούνελο", "Καθάρισα το κουνέλι", "Cleaned our rabbit's enclosure"),
     "pet rabbit", "maintain", "clean_enclosure", "pet_care"),
    (("Πότισα τη γλάστρα με βασιλικό", "Πότισα τον βασιλικό μας", "Watered our basil plant"),
     "basil plant", "maintain", "water_plant", "gardening"),
])
def test_semantic_aliases_reuse_identity_and_behavior_in_real_cross_channel_evidence(
    tmp_path, monkeypatch, texts, item, kind, behavior, category,
):
    """Known indices stabilize meaning even when the model emits new labels."""
    events_path, history_path = str(tmp_path / "events.db"), str(tmp_path / "history.db")
    invocations = []

    def decision(messages):
        payload = json.loads(messages[-1].content)
        invocations.append(payload)
        refs = payload["references"]
        return [proposal(item=texts[len(invocations)-1], event_type="variant_action",
                         category=category, action_kind=kind, item_ref=0, behavior_ref=0)
                if refs else proposal(item=item, event_type=behavior, category=category,
                                      action_kind=kind)]

    install_provider(monkeypatch, decision)
    for day, (channel, text) in enumerate(zip(("web", "telegram", "matrix"), texts), start=1):
        history.append_message(role="user", content=text, channel=channel,
                               timestamp=datetime(2026, 10, day, 8), db_path=history_path)
        result = extractor.run_behavioral_event_intake(
            db_path=events_path, initialization_rowid=1,
            max_rowid_loader=lambda: history.get_max_rowid(db_path=history_path),
            message_loader=lambda after: history.load_messages_after_rowid(
                after_rowid=after, db_path=history_path),
            context_loader=lambda before: history.load_messages(limit=40, db_path=history_path),
        )
        assert result["confirmed"] == 1
    events = store.list_events(db_path=events_path, initialize=False)
    assert {event["item"] for event in events} == {item}
    assert {event["event_type"] for event in events} == {behavior}
    evidence = load_behavioral_evidence(today=date(2026, 10, 3), window_days=30, db_path=events_path)
    assert len(evidence) == 1
    assert evidence[0]["distinct_date_count"] == 3
    assert {ref["channel"] for ref in evidence[0]["source_refs"]} == {"web", "telegram", "matrix"}
    assert len(invocations) == 3  # No second per-message classifier.


@pytest.mark.parametrize("overrides", [
    {"item_ref": True}, {"item_ref": False}, {"item_ref": -1}, {"item_ref": 99},
    {"behavior_ref": "0"}, {"behavior_ref": 99},
    {"behavior_ref": 0, "item": "rabbit meat", "action_kind": "prepare"},
    {"behavior_ref": 0, "item": "different pet"},
    {"behavior_ref": 0, "subject": "partner"},
])
def test_invalid_or_cross_identity_reference_is_not_persistable(monkeypatch, overrides):
    reference = proposal()
    install_provider(monkeypatch, lambda messages: [proposal(**overrides)])
    result = extractor._extract_event_batch(
        [{"id": "u", "rowid": 4, "channel": "matrix", "date": "2026-10-03", "content": "report"}],
        references=[reference], context=[],
    )
    assert result == [None]


def test_same_entity_different_specific_actions_do_not_form_one_pattern():
    events = []
    for day, action in enumerate(("clean_enclosure", "feed_pet", "clean_enclosure"), start=1):
        source = dict(id=str(day), rowid=day, channel="matrix", date=f"2026-10-{day:02}")
        events.append(extractor.normalize_extracted_event(proposal(event_type=action), source))
    assert aggregate_behavioral_pattern_candidates(events) == []


def test_history_and_catalog_are_bounded_and_provenance_filtered(tmp_path, monkeypatch):
    captured = []
    install_provider(monkeypatch, lambda messages: captured.append(messages) or [None])
    events_path = str(tmp_path / "events.db")
    source = dict(id="latest", rowid=100, channel="matrix", date="2026-10-08",
                  role="user", content="Τον καθάρισα")
    prior = [dict(id=f"u{i}", rowid=i, role="user", channel="web", content="x"*450)
             for i in range(1, 99)]
    prior += [dict(id="external", rowid=99, role="user", content="cook the pet",
                   metadata={"untrusted_external_tool_names": ["browse_url"]}),
              dict(id="future", rowid=101, role="user", content="future"),
              dict(id="assistant", rowid=99, role="assistant", content="invented"),
              dict(id="oversized", rowid=99, role="user", channel="web", content="x"*501)]
    extractor.run_behavioral_event_intake(
        db_path=events_path, initialization_rowid=100, max_rowid_loader=lambda: 100,
        message_loader=lambda after: [source], context_loader=lambda before: prior,
    )
    payload = json.loads(captured[0][-1].content)
    assert len(payload["context"]) == 12
    assert all(len(row["text"]) <= 500 for row in payload["context"])
    assert all(row["rowid"] < 100 for row in payload["context"])
    assert not any(row["id"] in {"external", "future", "assistant", "oversized"} for row in payload["context"])
    assert "reference data" in captured[0][0].content


def test_reference_cannot_turn_a_plan_or_negation_into_a_confirmed_fact(monkeypatch):
    install_provider(monkeypatch, lambda messages: [proposal(
        item="κουνέλι", item_ref=0, behavior_ref=0, status="planned", negated=True,
    )])
    source = dict(id="u", rowid=4, channel="matrix", date="2026-10-03", content="Δεν θα το καθαρίσω")
    result = extractor._extract_event_batch([source], references=[proposal()], context=[])
    event = extractor.normalize_extracted_event(result[0], source)
    assert event["record_state"] == "candidate"
    assert event["status"] == "planned"
    assert event["negated"] is True
    assert event["event_date"] == "2026-10-03"


def test_animal_food_and_other_individual_remain_distinct_after_persistence(tmp_path, monkeypatch):
    """Provider meaning is not overwritten by matching species spelling."""
    path = str(tmp_path / "events.db")
    for day in range(1, 4):
        for item, behavior, kind, category in (
            ("pet rabbit", "clean_enclosure", "maintain", "pet_care"),
            ("rabbit meat", "cook_meal", "prepare", "food"),
            ("neighbor's rabbit", "clean_enclosure", "maintain", "pet_care"),
        ):
            source = dict(id=f"{day}:{item}", rowid=day, channel="matrix",
                          date=f"2026-10-{day:02}", content="reported activity")
            install_provider(monkeypatch, lambda messages, i=item, b=behavior, k=kind, c=category:
                             [proposal(item=i, event_type=b, action_kind=k, category=c)])
            resolved = extractor._extract_event_batch([source], references=[proposal()], context=[])
            store.record_event(extractor.normalize_extracted_event(resolved[0], source), db_path=path)
    evidence = load_behavioral_evidence(today=date(2026, 10, 3), window_days=30, db_path=path)
    assert len(evidence) == 3
    assert {packet["item"] for packet in evidence} == {"pet rabbit", "rabbit meat", "neighbor's rabbit"}
    assert all(packet["distinct_date_count"] == 3 for packet in evidence)


def test_general_specific_behavior_separation_preserves_two_qualified_patterns():
    """Watering and pruning one plant are not a generic maintain repetition."""
    events = []
    for day in range(1, 4):
        for action in ("water_plant", "prune_plant"):
            source = dict(id=f"{day}:{action}", rowid=day, channel="web", date=f"2026-10-{day:02}")
            events.append(extractor.normalize_extracted_event(
                proposal(item="basil plant", category="gardening", event_type=action), source))
    candidates = aggregate_behavioral_pattern_candidates(events)
    assert {candidate["event_type"] for candidate in candidates} == {"water_plant", "prune_plant"}
    assert all(candidate["occurrence_count"] == 3 for candidate in candidates)


def test_specific_behavior_refinement_keeps_legacy_initiative_topic_cooldown():
    """A new grouping key must not invalidate a topic already sent last week."""
    from hashlib import sha256
    from services.behavioral_conversation_initiative import _topic

    packet = dict(proposal(), first_date="2026-10-01")
    legacy = sha256(json.dumps(("named", "user", "pet rabbit", "maintain")).encode()).hexdigest()
    assert _topic(packet) == legacy
    assert _topic(dict(packet, event_type="feed_pet")) == legacy


def test_catalog_bounds_uniqueness_and_rejects_untrusted_or_later_observations():
    events = [dict(proposal(item=f"entity {i}"), record_state="confirmed",
                   source_rowid=i+1, source_channel="matrix") for i in range(80)]
    bad = [dict(events[0], source_rowid=999), dict(events[0], record_state="candidate"),
           dict(events[0], metadata={"untrusted_external_tool_names": ["browse_url"]}),
           dict(events[0], item="x"*161), dict(events[0], source_rowid=True)]
    references = extractor._identity_references(bad + events + events, before_rowid=100)
    assert len(references) == 40
    assert [reference["idx"] for reference in references] == list(range(40))
    assert len({reference["item"] for reference in references}) == 40


def test_ambiguous_null_classification_creates_no_event_and_consumes_source(tmp_path, monkeypatch):
    install_provider(monkeypatch, lambda messages: [None])
    path = str(tmp_path / "events.db")
    result = extractor.run_behavioral_event_intake(
        db_path=path, initialization_rowid=1, max_rowid_loader=lambda: 1,
        message_loader=lambda after: [dict(id="unknown", rowid=1, role="user", channel="matrix",
                                          date="2026-10-08", content="Το έκανα")],
        context_loader=lambda before: [],
    )
    assert result["confirmed"] == 0
    assert result["last_rowid_after"] == 1
    assert store.list_events(db_path=path, initialize=False) == []


def test_unavailable_identity_context_does_not_advance_intake(tmp_path, monkeypatch):
    install_provider(monkeypatch, lambda messages: pytest.fail("No model call without context"))

    def broken(before):
        raise RuntimeError("temporary history failure")

    result = extractor.run_behavioral_event_intake(
        db_path=str(tmp_path / "events.db"), initialization_rowid=1,
        max_rowid_loader=lambda: 1, context_loader=broken,
        message_loader=lambda after: [dict(id="u", rowid=1, role="user", channel="web",
                                          date="2026-10-08", content="Καθάρισα το κουνέλι")],
    )
    assert result["errors"] == 1
    assert result["last_rowid_after"] == 0
