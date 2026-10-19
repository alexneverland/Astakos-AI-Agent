"""Offline review regressions for model-call bounds and truthful manual deferral."""
import json
from types import SimpleNamespace

import pytest

import memory.pending_followups as pf


@pytest.fixture(autouse=True)
def isolate(tmp_path, monkeypatch, offline_behavioral_io):
    """Isolate state and fail any model call not explicitly replaced by a test."""
    monkeypatch.setattr(pf, "STATE_DB", str(tmp_path / "followups.db"))
    monkeypatch.setattr("services.gemini.safe_gemini_call",
                        lambda *a, **kw: pytest.fail("Unexpected model call"))


def create(subject="Coffee outing"):
    """Create a distinct real pending item through the storage abstraction."""
    return pf.create_pending_followup(source_channel="matrix", source_agent="Chat_Agent",
        topic="appointment", subject=subject, source_user_text=subject, source_ai_text="Okay",
        followup_after_ts=pf._local_now().isoformat(), confidence=0.95, metadata={})


def read(identity):
    """Return the isolated final record."""
    return next(r for r in pf.find_pending_followups(active_only=False, limit=30) if r["id"] == identity)


def test_twenty_nonmatching_candidates_use_one_model_call(monkeypatch):
    identities = [create(f"candidate{chr(97+i)}") for i in range(20)]
    assert len(set(identities)) == 20
    calls = []
    def provider(prompt, *a, **kw):
        calls.append(prompt)
        return SimpleNamespace(text='{"updates":[]}')
    monkeypatch.setattr("services.gemini.safe_gemini_call", provider)
    assert pf.maybe_resolve_followups_from_user_message("Καλημέρα φίλε") == 0
    assert len(calls) == 1
    assert all(read(i)["status"] == "pending" for i in identities)


def test_batch_resolves_one_and_defers_another_in_real_storage(monkeypatch):
    coffee, task = create("Coffee outing"), create("Vacuum rooms")
    before = read(task)
    payload = {"updates": [
        {"id": coffee, "action": "resolve", "resolution_type": "completed", "confidence": 0.95, "reason": "They returned"},
        {"id": task, "action": "defer", "delay_minutes": 1440, "target_window": "explicit_timer", "confidence": 0.95, "reason": "Owner moved it to tomorrow"},
    ]}
    calls = []
    def provider(prompt, *a, **kw):
        calls.append(prompt)
        return SimpleNamespace(text=json.dumps(payload))
    monkeypatch.setattr("services.gemini.safe_gemini_call", provider)
    assert pf.maybe_resolve_followups_from_user_message("Γύρισαν. Το καθάρισμα αύριο.") == 1
    assert len(calls) == 1
    assert read(coffee)["status"] == "resolved"
    assert read(task)["last_decision"] == "deferred"
    assert read(task)["expires_at"] > before["expires_at"]


@pytest.mark.parametrize("failure", ["unknown", "duplicate", "bool_id", "string_confidence", "malformed", "provider"])
def test_invalid_batch_leaves_all_records_unchanged(monkeypatch, failure):
    identity = create()
    item = {"id": identity, "action": "resolve", "resolution_type": "completed", "confidence": 0.95, "reason": "Done"}
    if failure == "unknown": item["id"] = 999
    if failure == "bool_id": item["id"] = True
    if failure == "string_confidence": item["confidence"] = "0.95"
    payload = {"updates": [item, item] if failure == "duplicate" else [item]}
    def provider(*a, **kw):
        if failure == "provider": raise RuntimeError("offline failure")
        return SimpleNamespace(text='not json' if failure == "malformed" else json.dumps(payload))
    monkeypatch.setattr("services.gemini.safe_gemini_call", provider)
    assert pf.maybe_resolve_followups_from_user_message("Το έκανα") == 0
    assert read(identity)["status"] == "pending"


@pytest.mark.parametrize("sent", [False, True])
def test_manual_defer_reports_success_only_for_a_changed_pending_item(monkeypatch, sent):
    from tools import system
    identity = create()
    if sent: pf.mark_followup_sent(identity)
    before = read(identity)
    monkeypatch.setattr(system, "_looks_like_manual_followup_control", lambda _: True)
    result = system.control_pending_followup.func(subject_query="Coffee outing", action="defer",
        source_text="Ανέβαλε το follow-up", delay_minutes=60)
    after = read(identity)
    if sent:
        assert after == before
        assert "✅" not in result and "No changes made" in result
    else:
        assert "✅" in result and after["last_decision"] == "deferred"


def test_bad_member_cannot_partially_apply_an_otherwise_valid_batch(monkeypatch):
    identity = create()
    item = {"id": identity, "action": "resolve", "resolution_type": "completed", "confidence": 0.95, "reason": "Done"}
    # Add another real candidate so the response length itself is not the failure.
    create("Unrelated appointment")
    payload = {"updates": [item, {**item, "id": 999}]}
    monkeypatch.setattr("services.gemini.safe_gemini_call",
                        lambda *a, **kw: SimpleNamespace(text=json.dumps(payload)))
    assert pf.maybe_resolve_followups_from_user_message("Το έκανα") == 0
    assert read(identity)["status"] == "pending"


def test_empty_queue_never_calls_the_model():
    assert pf.maybe_resolve_followups_from_user_message("Καλημέρα") == 0


def test_manual_defer_handles_status_change_after_lookup(monkeypatch):
    from tools import system
    identity = create()
    original = pf.defer_followup
    def raced(*args, **kwargs):
        pf.mark_followup_sent(identity)
        return original(*args, **kwargs)
    monkeypatch.setattr(pf, "defer_followup", raced)
    monkeypatch.setattr(system, "_looks_like_manual_followup_control", lambda _: True)
    result = system.control_pending_followup.func(subject_query="Coffee outing", action="defer",
        source_text="Ανέβαλε το follow-up", delay_minutes=60)
    assert read(identity)["status"] == "sent"
    assert "✅" not in result and "No changes made" in result
