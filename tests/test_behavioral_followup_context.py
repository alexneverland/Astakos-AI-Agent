"""Read-only coordination with the distinct follow-up queue, with no live I/O."""
from datetime import datetime, timedelta

import pytest

pytestmark = pytest.mark.usefixtures("offline_behavioral_io")

from memory import pending_followups as followups
from services.behavioral_conversation_evidence import load_followup_topic_context


def test_pending_and_recently_sent_topics_reach_initiative_without_queue_changes(tmp_path, monkeypatch):
    """An existing follow-up reserves its subject; an old sent topic does not."""
    monkeypatch.setattr(followups, "STATE_DB", str(tmp_path / "state.db"))
    now = followups._local_now()
    ids = []
    for topic, subject in (("animal_care", "rabbit"), ("gardening", "basil")):
        ids.append(followups.create_pending_followup(source_channel="matrix", source_agent="Chat_Agent",
            topic=topic, subject=subject, source_user_text="Finished caring for it",
            source_ai_text="Nice", followup_after_ts=(now+timedelta(hours=1)).isoformat(), confidence=.95))
    followups.mark_followup_sent(ids[1])
    before = followups.find_pending_followups(active_only=False)
    context = load_followup_topic_context(now)
    assert {r["subject"] for r in context} == {"rabbit", "basil"}
    assert {r["status"] for r in context} == {"pending", "sent"}
    assert followups.find_pending_followups(active_only=False) == before
    monkeypatch.setattr(followups, "ensure_pending_followups_table",
                        lambda: pytest.fail("Read-only context must not initialize tables"))
    assert load_followup_topic_context(now) == context
    assert load_followup_topic_context(now + timedelta(days=8)) == []


def test_missing_followup_store_is_read_only(tmp_path, monkeypatch):
    path = tmp_path / "missing.db"
    monkeypatch.setattr(followups, "STATE_DB", str(path))
    assert load_followup_topic_context(followups._local_now()) == []
    assert not path.exists()


def test_new_followup_during_selection_cancels_opener(tmp_path):
    """Context freshness prevents a new follow-up competing after classification."""
    from tests.test_behavioral_conversation_initiative import setup
    from services.behavioral_conversation_initiative import run_initiative
    kw, sent, _ = setup(tmp_path)
    context = {"followup_topics": []}
    kw["current_context"] = lambda: dict(context)
    def decide(payload):
        context["followup_topics"] = [{"subject": "rabbit", "status": "pending"}]
        return dict(selected_index=0, blocked=False, recently_discussed=False, message="An opener")
    kw["classify"] = decide
    assert run_initiative(**kw) == "skip"
    assert sent == []


def test_semantically_covered_followup_topic_decline_is_not_overridden(tmp_path):
    """A semantic duplicate decision stays authoritative despite a larger pool."""
    from tests.test_behavioral_conversation_initiative import setup
    from services.behavioral_conversation_initiative import run_initiative
    kw, sent, _ = setup(tmp_path)
    context = {"followup_topics": [{"subject": "beer", "status": "sent"}]}
    kw["current_context"] = lambda: context
    def decide(payload):
        assert payload["current_context"]["followup_topics"] == context["followup_topics"]
        return dict(selected_index=0, blocked=False, recently_discussed=True, message="Duplicate question")
    kw["classify"] = decide
    assert run_initiative(**kw) == "skip"
    assert sent == []
